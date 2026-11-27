#!/usr/bin/env python3
"""Private D-Bus integration fixture. Never run on the real session bus."""
import json
import os
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "config/desktop"))
from hydration import Service, gi_modules

assert os.environ.get("MYOS_HYDRATION_TEST") == "1", "Private test session required"
Gio, GLib = gi_modules()


if sys.argv[1] == "notifications":
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
        "RequestName", GLib.Variant("(su)", ("org.freedesktop.Notifications", 4)), None,
        Gio.DBusCallFlags.NONE, 3000, None)
    info = Gio.DBusNodeInfo.new_for_xml('''<node><interface name="org.freedesktop.Notifications">
      <method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/>
      <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/>
      <arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/>
      <arg type="u" direction="out"/></method>
      <method name="CloseNotification"><arg type="u" direction="in"/></method>
      <method name="Invoke"><arg type="u" direction="in"/><arg type="s" direction="in"/></method>
      <method name="Dismiss"><arg type="u" direction="in"/></method>
      <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
      <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
    </interface></node>''').interfaces[0]
    counter = [0]
    def call(bus, sender, path, interface, method, params, invocation):
        if method == "Notify":
            counter[0] += 1
            Path(os.environ["HOME"], "notification.json").write_text(json.dumps(
                dict(id=counter[0], arguments=params.unpack())))
            invocation.return_value(GLib.Variant("(u)", (counter[0],)))
        elif method == "CloseNotification":
            bus.emit_signal(None, path, interface, "NotificationClosed", GLib.Variant("(uu)", (params.unpack()[0], 3)))
            invocation.return_value(None)
        elif method == "Dismiss":  # the user clicking the popup's X (reason 2)
            bus.emit_signal(None, path, interface, "NotificationClosed", GLib.Variant("(uu)", (params.unpack()[0], 2)))
            invocation.return_value(None)
        elif method == "Invoke":
            bus.emit_signal(None, path, interface, "ActionInvoked", params)
            invocation.return_value(None)
    registration = bus.register_object("/org/freedesktop/Notifications", info, call, None, None)
    GLib.MainLoop().run()
else:
    class TestService(Service):
        def start_idle(self):
            self.idle_ready = True
            self.ctx.update(idle=False, away=False)

        def refresh_context(self):
            self.ctx.update(idle=False, away=False, active_session=True, locked=False,
                            dnd=False, fullscreen=False, call=False, error="")
            self.session = "test"

        def microphone(self):
            pass

        def api(self, bus, sender, path, interface, method, parameters, invocation):
            payload = json.loads(parameters.unpack()[0])
            if payload.get("action") == "test-due":
                self.tick()
                self.engine.s.update(remaining=0, grace=0, due_wait=300)
                self.tick()
                invocation.return_value(GLib.Variant("(s)", (json.dumps({"id": self.notice}),)))
                return
            if payload.get("action") == "test-warning":
                self.call_warning = payload["text"]
                invocation.return_value(GLib.Variant("(s)", (json.dumps({}),)))
                return
            super().api(bus, sender, path, interface, method, parameters, invocation)
    service = TestService()
    service.engine.cfg.update(start="00:00", end="23:59")
    service.run()
