#!/usr/bin/env python3
"""KadaOS Hydration session service and control client. All data stays on this laptop."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime

from hydration_engine import Engine, settings

NAME = "org.myos.Hydration"
OBJECT = "/org/myos/Hydration"
CONFIG = Path.home() / ".config/myos/hydration.json"
DIRECTORY = Path.home() / ".local/state/myos/hydration"
STATE = DIRECTORY / "state.json"
HERE = Path(__file__).resolve().parent
# hypridle suspends after 20 idle minutes, so "away" must trigger before that (helper uses the same value).
AWAY = 900


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def gi_modules():
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    return Gio, GLib


def request(payload):
    Gio, GLib = gi_modules()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    result = bus.call_sync(NAME, OBJECT, NAME, "Request",
                           GLib.Variant("(s)", (json.dumps(payload),)),
                           GLib.VariantType.new("(s)"), Gio.DBusCallFlags.NO_AUTO_START,
                           8000 if payload.get("action") == "startup" else 3000, None)
    result = json.loads(result.unpack()[0])
    if "error" in result:
        raise ValueError(result["error"])
    return result


def fullscreen():
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    instance = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    path = f"{runtime}/hypr/{instance}/.socket.sock"
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(0.5)
        sock.connect(path)
        sock.sendall(b"j/activewindow")
        data = b""
        while True:
            part = sock.recv(65536)
            if not part:
                break
            data += part
            if len(data) > 1024 * 1024:
                raise ValueError("Unexpected compositor response")
    return bool(json.loads(data).get("fullscreen", 0))


def lock_process():
    # Hyprlock may not publish logind's LockedHint on every launch route.
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if entry.stat().st_uid == os.getuid() and (entry / "comm").read_text().strip() == "hyprlock":
                    return True
            except (OSError, ProcessLookupError):
                continue
    return False


class Service:
    def __init__(self):
        self.Gio, self.GLib = gi_modules()
        self.bus = self.Gio.bus_get_sync(self.Gio.BusType.SESSION, None)
        self.system = self.Gio.bus_get_sync(self.Gio.BusType.SYSTEM, None)
        self.loop = self.GLib.MainLoop()
        self.fatal = ""
        try:
            cfg = settings(read_json(CONFIG, {}))
            self.engine = Engine(cfg, read_json(STATE, None))
        except (ValueError, TypeError, KeyError) as error:
            # Preserve malformed user files. Require repair rather than losing drink history.
            self.engine = Engine()
            self.fatal = f"Settings/state need repair: {error}"
        self.ctx = dict(idle=True, away=False, active_session=False, locked=True,
                        dnd=True, fullscreen=False, call=False, error="Starting desktop checks")
        self.idle_ready = False
        self.idle_process = None
        self.idle_channel = None
        self.idle_source = None
        self.idle_retry = 0
        self.idle_failures = 0
        self.notice = 0
        self.notice_token = None
        self.last_tick = time.monotonic()
        self.last_save = 0
        self.saved_state = None
        self.last_context = 0
        self.call_warning = ""
        self.session = ""
        self.boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        self.signals = []
        self.slept = None

    def call(self, bus, dest, path, interface, method, args=None):
        return bus.call_sync(dest, path, interface, method, args, None,
                             self.Gio.DBusCallFlags.NONE, 1500, None).unpack()

    def props(self, path):
        return self.call(self.system, "org.freedesktop.login1", path,
                         "org.freedesktop.DBus.Properties", "GetAll",
                         self.GLib.Variant("(s)", ("org.freedesktop.login1.Session",)))[0]

    def refresh_context(self):
        errors = []
        try:
            sessions = self.call(self.system, "org.freedesktop.login1", "/org/freedesktop/login1",
                                 "org.freedesktop.login1.Manager", "ListSessions")[0]
            candidates = [s for s in sessions if s[1] == os.getuid() and s[3]]
            if not candidates:
                raise ValueError("No graphical login session")
            # Prefer the active local Wayland session; never select the user manager session.
            props = [self.props(s[4]) | {"session_id": s[0]} for s in candidates]
            props = [p for p in props if p.get("Type") == "wayland" and not p.get("Remote")]
            p = next((p for p in props if p.get("Active")), props[0] if props else {})
            if "LockedHint" not in p or "Active" not in p:
                raise ValueError("Session state unavailable")
            self.ctx.update(active_session=p["Active"], locked=p["LockedHint"] or lock_process())
            self.session = p["session_id"]
        except Exception:
            errors.append("login session unavailable")
        try:
            self.ctx["dnd"] = self.call(self.bus, "org.erikreider.swaync",
                "/org/erikreider/swaync/cc", "org.erikreider.swaync.cc", "GetDnd")[0]
        except Exception:
            errors.append("notification state unavailable")
        try:
            self.ctx["fullscreen"] = fullscreen()
        except (OSError, ValueError):
            errors.append("compositor unavailable")
        if not self.idle_ready:
            errors.append("activity observer unavailable")
        self.ctx["error"] = self.fatal or "; ".join(errors)
        if self.ctx["error"]:
            print(self.ctx["error"], file=sys.stderr, flush=True)

    def start_idle(self):
        if self.idle_source:
            self.GLib.source_remove(self.idle_source)
            self.idle_source = None
        # The pipe has one owner: Python's file object. GLib's channel.shutdown() closed the same fd a second
        # time when the old Popen was garbage-collected, by then the *new* helper's pipe reused that number,
        # so every restart died with "Bad file descriptor" and reminders stayed paused.
        self.idle_channel = None
        if self.idle_process:
            self.idle_process.stdout.close()
            self.idle_process.terminate()
            try:
                self.idle_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.idle_process.kill()
        self.idle_ready = False
        self.ctx.update(idle=True, away=False)
        try:
            self.idle_process = subprocess.Popen([str(HERE / "hydration-idle"), str(self.engine.cfg["idle"])],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as error:
            # Missing helper: stay up and report it instead of crash-looping into the start limit.
            # Status shows "activity observer unavailable"; manual logging keeps working.
            self.idle_process = None
            print(f"Activity helper failed to start: {error}; reinstall Hydration", file=sys.stderr, flush=True)
            return
        self.idle_channel = self.GLib.IOChannel.unix_new(self.idle_process.stdout.fileno())
        self.idle_channel.set_encoding("utf-8")
        self.idle_source = self.GLib.io_add_watch(self.idle_channel,
            self.GLib.IOCondition.IN | self.GLib.IOCondition.HUP, self.idle_event)

    def idle_event(self, channel, condition):
        if condition & self.GLib.IOCondition.IN:
            result, line, _, _ = channel.read_line()
            if line:
                event = line.strip()
                self.tick()  # finish accounting before changing activity state
                if event == "ready":
                    self.idle_ready = True
                    self.idle_failures = 0
                    self.ctx["idle"] = False
                elif event == "idle":
                    self.ctx["idle"] = True
                elif event == "away":
                    self.ctx["away"] = True
                elif event == "active":
                    if self.ctx["away"]:
                        self.engine.reset()
                    self.ctx.update(idle=False, away=False)
                self.last_context = 0
                return True
        if condition & self.GLib.IOCondition.HUP:
            self.idle_ready = False
            self.idle_source = None
            self.idle_failures += 1
            self.idle_retry = time.monotonic() + min(300, 15 * 2 ** min(self.idle_failures, 4))
            self.last_context = 0
            return False
        return True

    def microphone(self):
        """Called in a worker; only a boolean survives the metadata query."""
        try:
            result = subprocess.run(["pw-dump", "-N"], capture_output=True, text=True, timeout=3, check=True)
            nodes = json.loads(result.stdout)
            active = any(n.get("info", {}).get("state") == "running"
                         and n.get("info", {}).get("props", {}).get("media.class") == "Stream/Input/Audio"
                         and n.get("info", {}).get("props", {}).get("stream.capture.sink") not in (True, "true")
                         for n in nodes)
            warning = ""
        except (OSError, ValueError, subprocess.SubprocessError):
            active, warning = False, "Call detection unavailable"
        self.GLib.idle_add(self.update_microphone, active, warning)

    def update_microphone(self, active, warning):
        self.ctx["call"] = active
        self.call_warning = warning
        return False

    def close_notice(self):
        nid, self.notice = self.notice, 0
        self.notice_token = None
        if nid:
            try:
                self.call(self.bus, "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                          "org.freedesktop.Notifications", "CloseNotification",
                          self.GLib.Variant("(u)", (nid,)))
            except Exception:
                pass

    def notify(self):
        self.close_notice()
        token = self.engine.s["generation"]
        body = ("A moment for a drink? Your last reminder was left unconfirmed."
                if self.engine.s["attempts"] > 1 else
                f"About {self.engine.cfg['interval']} minutes of active screen time. Take a moment for a drink.")
        hints = {"suppress-sound": self.GLib.Variant("b", True),
                 "transient": self.GLib.Variant("b", True),
                 "desktop-entry": self.GLib.Variant("s", "org.myos.Hydration"),
                 "urgency": self.GLib.Variant("y", 1)}
        self.notice = self.call(self.bus, "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
            "org.freedesktop.Notifications", "Notify",
            self.GLib.Variant("(susssasa{sv}i)", ("Hydration", 0, "weather-showers-symbolic",
                "Time for a water break", body,
                ["drank", "Drank water", "snooze", "Snooze 10 min", "pause", "Pause today"], hints, 20000)))[0]
        self.notice_token = token

    def notification_signal(self, bus, sender, path, interface, name, parameters, data):
        values = parameters.unpack()
        if not self.notice or values[0] != self.notice:
            return
        if name == "ActionInvoked" and values[1] in ("drank", "snooze", "pause"):
            self.engine.action(values[1], datetime.now(), self.notice_token)
            self.close_notice()
            self.persist()
            self.tick()
        elif name == "NotificationClosed":
            self.notice = 0
            self.notice_token = None
            self.engine.s["notice"] = False

    def persist(self):
        encoded = json.dumps(self.engine.s, sort_keys=True)
        if not self.fatal and encoded != self.saved_state:
            save_json(STATE, self.engine.s)
            self.saved_state = encoded

    def tick(self):
        now = time.monotonic()
        elapsed, self.last_tick = now - self.last_tick, now
        if (self.idle_process and self.idle_process.poll() is not None
                and now >= self.idle_retry):
            try:
                fullscreen()
            except (OSError, ValueError):
                # Compositor ended: stop cleanly so the next login starts with fresh env.
                self.loop.quit()
                return False
            self.start_idle()
        if now - self.last_context >= 15 or self.engine.s["remaining"] <= 10 or self.notice:
            self.refresh_context()
            self.last_context = now
        deliver = self.engine.tick(elapsed, datetime.now(), self.ctx, self.boot + ":" + self.session)
        if self.notice and not self.engine.s["notice"]:
            self.close_notice()
        if deliver:
            # Persist intent first: a crash must not deliver the same reminder twice.
            self.persist()
            try:
                self.notify()
            except Exception as error:
                self.engine.s["notice"] = False
                print(f"Notification failed: {error}", file=sys.stderr, flush=True)
        if now - self.last_save >= 60:
            self.persist()
            self.last_save = now
        return True

    def context_signal(self, bus, sender, path, interface, name, parameters, data):
        self.last_context = 0
        if name == "PrepareForSleep":
            self.engine.s["grace"] = 120
            self.last_tick = time.monotonic()
            self.close_notice()
            # BOOTTIME keeps counting during suspend and ignores wall-clock changes.
            if parameters.unpack()[0]:
                self.slept = time.clock_gettime(time.CLOCK_BOOTTIME)
            else:
                if self.slept and time.clock_gettime(time.CLOCK_BOOTTIME) - self.slept >= AWAY:
                    self.engine.reset()  # lid closed a while = a real break; start fresh, log nothing
                self.slept = None
                self.start_idle()
        self.tick()

    def api(self, bus, sender, path, interface, method, parameters, invocation):
        try:
            payload = json.loads(parameters.unpack()[0])
            action = payload.get("action", "status")
            self.tick()
            if action == "startup":
                if type(payload.get("enabled")) is not bool:
                    raise ValueError("Startup setting must be boolean")
                subprocess.run(["systemctl", "--user", "enable" if payload["enabled"] else "disable",
                                "myos-hydration.service"], check=True, capture_output=True, timeout=5)
            elif action == "settings":
                if self.fatal:
                    raise ValueError(self.fatal)
                cfg = settings(payload["settings"])
                changed_idle = cfg["idle"] != self.engine.cfg["idle"]
                save_json(CONFIG, cfg)
                self.engine.cfg = cfg
                self.engine.undo = None
                self.engine.reset()
                if changed_idle:
                    self.start_idle()
            elif action != "status":
                if self.fatal:
                    raise ValueError(self.fatal)
                self.engine.action(action, datetime.now())
            if action != "status":
                self.close_notice()
                self.persist()
                self.tick()
            result = self.engine.status(datetime.now()) | {"warning": self.call_warning,
                "service": True, "observer": self.idle_ready}
            if action == "startup":
                result["autostart"] = payload["enabled"]
        except Exception as error:
            result = {"error": str(error)}
        invocation.return_value(self.GLib.Variant("(s)", (json.dumps(result),)))

    def run(self):
        interface = self.Gio.DBusNodeInfo.new_for_xml(
            f'<node><interface name="{NAME}"><method name="Request">'
            '<arg type="s" direction="in"/><arg type="s" direction="out"/>'
            '</method></interface></node>').interfaces[0]
        acquired = self.call(self.bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "RequestName", self.GLib.Variant("(su)", (NAME, 4)))[0]
        if acquired != 1:
            raise RuntimeError("Hydration is already running")
        self.registration = self.bus.register_object(OBJECT, interface, self.api, None, None)
        for name in ("ActionInvoked", "NotificationClosed"):
            self.signals.append(self.bus.signal_subscribe("org.freedesktop.Notifications",
                "org.freedesktop.Notifications", name, "/org/freedesktop/Notifications", None,
                self.Gio.DBusSignalFlags.NONE, self.notification_signal, None))
        self.signals.append(self.bus.signal_subscribe("org.erikreider.swaync",
            "org.erikreider.swaync.cc", "SubscribeV2", "/org/erikreider/swaync/cc", None,
            self.Gio.DBusSignalFlags.NONE, self.context_signal, None))
        for interface, name in (("org.freedesktop.login1.Manager", "PrepareForSleep"),
                                ("org.freedesktop.DBus.Properties", "PropertiesChanged")):
            self.signals.append(self.system.signal_subscribe("org.freedesktop.login1",
                interface, name, None, None, self.Gio.DBusSignalFlags.NONE, self.context_signal, None))
        self.start_idle()
        self.GLib.timeout_add_seconds(5, self.tick)
        def mic_tick():
            # Mic state only matters near delivery; skip pw-dump the rest of the time (battery).
            if self.engine.cfg["calls"] and self.engine.s["remaining"] <= 60:
                import threading
                threading.Thread(target=self.microphone, daemon=True).start()
            else:
                self.ctx["call"] = False
            return True
        mic_tick()
        self.GLib.timeout_add_seconds(30, mic_tick)
        def stop(*args):
            self.loop.quit()
            return False
        self.GLib.unix_signal_add(self.GLib.PRIORITY_DEFAULT, signal.SIGTERM, stop)
        self.GLib.unix_signal_add(self.GLib.PRIORITY_DEFAULT, signal.SIGINT, stop)
        try:
            self.tick()
            self.loop.run()
        finally:
            self.persist()
            self.close_notice()
            if self.idle_process:
                self.idle_process.terminate()
                self.idle_process.wait(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="panel",
                        choices=["daemon", "panel", "status", "drank", "snooze", "pause", "resume", "undo", "clear"])
    args = parser.parse_args()
    if args.command == "daemon":
        Service().run()
    elif args.command == "panel":
        from hydration_panel import run
        run()
    else:
        try:
            print(json.dumps(request({"action": args.command}), indent=2))
        except Exception as error:
            print(f"Hydration unavailable: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
