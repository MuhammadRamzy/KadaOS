#!/usr/bin/env python3
"""notify-action.py [-i ICON] [-t SECONDS] TITLE BODY key=Label [key=Label ...]
Shows a notification with buttons and prints the key that was clicked (nothing if dismissed/timed out).
Talks to org.freedesktop.Notifications directly (libnotify 0.8.8's notify-send -A fails on this system)."""
import argparse
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

ap = argparse.ArgumentParser()
ap.add_argument("-i", "--icon", default="")
ap.add_argument("-t", "--timeout", type=int, default=20)
ap.add_argument("title"); ap.add_argument("body"); ap.add_argument("actions", nargs="*")
a = ap.parse_args()
acts = []
for x in a.actions:
    k, _, v = x.partition("="); acts += [k, v or k]
hints = {"image-path": GLib.Variant("s", a.icon)} if a.icon else {}
bus = Gio.bus_get_sync(Gio.BusType.SESSION)
nid = bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications", "Notify",
                    GLib.Variant("(susssasa{sv}i)", ("KadaOS", 0, a.icon, a.title, a.body, acts, hints, a.timeout * 1000)),
                    GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, -1, None).unpack()[0]
loop = GLib.MainLoop(); result = []
def on_sig(_c, _s, _p, _i, name, params, _u):
    args = params.unpack()
    if args[0] != nid: return
    if name == "ActionInvoked": result.append(args[1])
    loop.quit()
for sig in ("ActionInvoked", "NotificationClosed"):
    bus.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications", sig,
                         "/org/freedesktop/Notifications", None, Gio.DBusSignalFlags.NONE, on_sig, None)
GLib.timeout_add_seconds(a.timeout + 2, loop.quit)
loop.run()
if result: print(result[0])
