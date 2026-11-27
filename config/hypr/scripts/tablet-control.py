#!/usr/bin/env python3
"""Control the Android tablet with the laptop's mouse and keyboard (software KVM, no screen mirroring).

  tablet-control.py start | stop | toggle | status | json | selftest

Push the pointer into the laptop's right edge and it continues on the Pad (a real Android mouse
pointer); the keyboard types on the Pad too. Press Super on its own to come back.
How: scrcpy simulates a physical HID mouse + keyboard over adb (USB debugging, cable or wireless
debugging) with video off. Its input window is a thin strip on the right edge (Hyprland rules
match the title below); when the pointer reaches it, a Super tap tells scrcpy to capture.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

TITLE = "Pad control"          # must match the windowrules in hyprland.conf
STRIP = 3                      # px; same as the windowrule size
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
PIDFILE = RUNTIME / "tablet-control.pid"
LOG = RUNTIME / "tablet-control.log"
HERE = Path(__file__).resolve().parent


def notify(text):
    print(text)
    subprocess.run(["notify-send", "-i", "input-mouse", "Pad control", text], check=False)


def hypr(command):
    path = RUNTIME / "hypr" / os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "") / ".socket.sock"
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(0.5)
        sock.connect(str(path))
        sock.sendall(command.encode())
        data = b""
        while part := sock.recv(65536):
            data += part
    return json.loads(data)


def edge_step(x, right, title, armed):
    """One watcher tick → (enter_pad, armed).

    Enter only when the pointer sits on the right-edge strip and the strip has focus.
    After entering (or after coming back with Super), stay disarmed until the pointer
    leaves the strip, so returning never bounces straight back to the Pad.
    """
    if x < right - STRIP:
        return False, True
    if armed and title == TITLE:
        return True, False
    return False, armed


def running_pid():
    try:
        pid = int(PIDFILE.read_text())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def run():
    PIDFILE.write_text(str(os.getpid()))
    env = os.environ | {"SDL_VIDEODRIVER": "wayland"}   # native pointer lock on Hyprland
    with LOG.open("w") as log:
        scrcpy = subprocess.Popen(["scrcpy", "--no-video", "--no-audio", "--mouse=uhid", "--keyboard=uhid",
                                   "--window-title", TITLE, "--window-borderless"],
                                  env=env, stdout=log, stderr=log)
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    armed = False   # the pointer may already be at the edge when we start
    try:
        while not stop and scrcpy.poll() is None:
            time.sleep(0.05)
            try:
                right = max(m["x"] + m["width"] for m in hypr("j/monitors"))
                x = hypr("j/cursorpos")["x"]
                title = hypr("j/activewindow").get("title", "") if x >= right - STRIP else ""
            except (OSError, ValueError):
                continue
            enter, armed = edge_step(x, right, title, armed)
            if enter:
                # scrcpy toggles mouse capture on a lone Super tap; focus was just verified.
                subprocess.run(["wtype", "-k", "Super_L"], check=False)
    finally:
        if scrcpy.poll() is None:
            scrcpy.terminate()
            try:
                scrcpy.wait(timeout=3)
            except subprocess.TimeoutExpired:
                scrcpy.kill()
        elif not stop:
            notify("Pad disconnected; control stopped. Details: " + str(LOG))
        PIDFILE.unlink(missing_ok=True)


def start():
    if running_pid():
        return notify("Already on. Push the pointer into the right edge to use the Pad.")
    for tool in ("scrcpy", "adb", "wtype"):
        if not subprocess.run(["sh", "-c", f"command -v {tool}"], capture_output=True).returncode == 0:
            return notify(f"{tool} is not installed.")
    state = subprocess.run(["adb", "get-state"], capture_output=True, text=True, timeout=10)
    if state.stdout.strip() != "device":
        notify("Pad not found. Plug it in with USB debugging on (or pair Wireless debugging) and accept the prompt on the Pad.")
        return 1
    # The extended-screen mode would put another screen on the right edge; one mode at a time.
    if subprocess.run([str(HERE / "tablet-display.sh"), "status"], capture_output=True, text=True).stdout.strip() != "off":
        subprocess.run([str(HERE / "tablet-display.sh"), "stop"], capture_output=True)
    subprocess.Popen([sys.executable, __file__, "run"], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    notify("On. Push the pointer into the right edge to control the Pad; press Super to come back.")
    return 0


def stop():
    pid = running_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        notify("Off.")
    else:
        print("Already off.")


def selftest():
    right = 1920
    assert edge_step(100, right, "", True) == (False, True), "away from the edge: armed, no entry"
    assert edge_step(1919, right, "kitty", True) == (False, True), "edge but strip not focused yet: wait"
    assert edge_step(1919, right, TITLE, True) == (True, False), "edge + strip focused: enter once"
    assert edge_step(1919, right, TITLE, False) == (False, False), "still on the strip: no bounce back"
    assert edge_step(1916, right, TITLE, False) == (False, True), "left the strip: re-armed"
    assert edge_step(1917, right, TITLE, True) == (True, False), "strip is 3 px wide"
    print("tablet-control selftest: ok")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    if command == "run":
        run()
    elif command == "start":
        return start()
    elif command == "stop":
        stop()
    elif command == "toggle":
        return stop() if running_pid() else start()
    elif command == "status":
        print("on" if running_pid() else "off")
    elif command == "json":
        on = bool(running_pid())
        print(json.dumps({"text": "\U000F04F6", "class": "on" if on else "off",
                          "tooltip": "Pad control ON: push the pointer into the right edge; Super returns. Click to stop."
                          if on else "Control the Pad with this mouse/keyboard (Super+F12). Right-click: Pad as a second screen."}, ensure_ascii=False))
    elif command == "selftest":
        selftest()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
