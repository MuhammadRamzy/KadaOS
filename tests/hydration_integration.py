#!/usr/bin/env python3
"""Run with dbus-run-session -- python3 tests/hydration_integration.py.

Uses temporary HOME, a private bus, and a fake notification server. No live alerts.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

assert os.environ.get("DBUS_SESSION_BUS_ADDRESS", "").startswith("unix:"), "Use dbus-run-session"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "config/desktop"))


def wait_for(function):
    for _ in range(50):
        try:
            result = function()
            if result:
                return result
        except Exception:
            pass
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for private session")


with tempfile.TemporaryDirectory(prefix="hydration-integration-") as home:
    os.environ.update(HOME=home, MYOS_HYDRATION_TEST="1")
    from hydration import request, gi_modules
    Gio, GLib = gi_modules()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    for name in ("org.myos.Hydration", "org.freedesktop.Notifications"):
        owned = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "NameHasOwner", GLib.Variant("(s)", (name,)), None,
            Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        assert not owned, "Tests require a fresh private bus; refusing to touch an existing session"
    fixture = str(ROOT / "tests/hydration_session.py")
    notification = subprocess.Popen([sys.executable, fixture, "notifications"])
    daemon = None
    try:
        time.sleep(0.3)
        daemon = subprocess.Popen([sys.executable, fixture, "service"])
        status = wait_for(lambda: request({"action": "status"}))
        assert status["observer"] and status["today"] == 0
        assert request({"action": "drank"})["today"] == 1
        assert request({"action": "undo"})["today"] == 0
        assert request({"action": "pause"})["paused"]
        assert not request({"action": "resume"})["paused"]
        assert request({"action": "snooze"})["title"] == "Snoozed"
        def invoke(nid, action):
            Gio.bus_get_sync(Gio.BusType.SESSION, None).call_sync(
                "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                "org.freedesktop.Notifications", "Invoke", GLib.Variant("(us)", (nid, action)),
                None, Gio.DBusCallFlags.NONE, 3000, None)
        nid = request({"action": "test-due"})["id"]
        assert nid
        notice = json.loads(Path(home, "notification.json").read_text())
        assert notice["arguments"][6]["suppress-sound"] is True
        assert len(notice["arguments"][5]) == 6
        invoke(nid, "drank")
        wait_for(lambda: request({"action": "status"})["today"] == 1)
        invoke(nid, "drank")
        time.sleep(0.1)
        assert request({"action": "status"})["today"] == 1
        nid = request({"action": "test-due"})["id"]
        invoke(nid, "snooze")
        wait_for(lambda: request({"action": "status"})["title"] == "Snoozed")
        nid = request({"action": "test-due"})["id"]
        invoke(nid, "pause")
        wait_for(lambda: request({"action": "status"})["paused"])
        cfg = status["settings"] | {"interval": 60}
        assert request({"action": "settings", "settings": cfg})["settings"]["interval"] == 60
        try:
            request({"action": "settings", "settings": cfg | {"start": "bad"}})
            raise AssertionError("Invalid settings accepted")
        except ValueError:
            pass
        daemon.terminate()
        daemon.wait(timeout=5)
        daemon = subprocess.Popen([sys.executable, fixture, "service"])
        restored = wait_for(lambda: request({"action": "status"}))
        assert restored["today"] == 1 and restored["paused"]
        state = Path(home, ".local/state/myos/hydration/state.json")
        assert state.stat().st_mode & 0o777 == 0o600
        assert request({"action": "clear"})["today"] == 0
        print("PASS: private D-Bus controls, three notification actions, duplicate protection, settings validation, restart persistence, permissions, clear history")
    finally:
        for child in (daemon, notification):
            if child is not None:
                child.terminate()
                child.wait(timeout=5)
