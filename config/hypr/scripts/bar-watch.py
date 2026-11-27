#!/usr/bin/env python3
"""Top bar auto mode: show waybar when the cursor rests at the top edge, hide it when the cursor moves away.

Asks Hyprland for the cursor position straight over its request socket: no process is spawned per poll
(the old shell loop ran pgrep + hyprctl + cut + tr 12 times a second, ~40% of a core).
Shows after the cursor rests ~150 ms at the edge (like macOS), so reaching for browser tabs doesn't pop it open.
Started by `bar.sh watch`; waybar toggles on SIGUSR1.
"""
import os, signal, socket, sys, time
from pathlib import Path

POLL, DWELL, EDGE, AWAY = 0.08, 2, 2, 60      # seconds between polls, polls at the edge, px, px


def hypr_socket():
    rt, sig = os.environ.get("XDG_RUNTIME_DIR", "/tmp"), os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    return f"{rt}/hypr/{sig}/.socket.sock"


def cursor_y(path):
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(0.5); s.connect(path); s.sendall(b"cursorpos")
            return int(s.recv(64).decode().split(",")[1])
    except (OSError, ValueError, IndexError):
        return None


def waybar_pid():
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                if (p / "comm").read_text().strip() == "waybar": return int(p.name)
            except OSError: pass
    return None


def step(state, y):
    """Pure decision: returns (new_state, toggle?). state = (shown, dwell)."""
    shown, dwell = state
    if not shown:
        dwell = dwell + 1 if y is not None and y <= EDGE else 0
        return ((True, 0), True) if dwell >= DWELL else ((False, dwell), False)
    if y is not None and y > AWAY: return (False, 0), True
    return (True, 0), False


def main():
    path, pid, state = hypr_socket(), None, (False, 0)
    while True:
        if pid is None or not Path(f"/proc/{pid}").exists():
            pid, state = waybar_pid(), (False, 0)
            time.sleep(1)                                # (re)started hidden; SIGUSR1 before it's ready would kill it
            continue
        state, toggle = step(state, cursor_y(path))
        if toggle:
            try: os.kill(pid, signal.SIGUSR1)
            except OSError: pid = None
        time.sleep(POLL)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        s = (False, 0)
        s, t = step(s, 1); assert not t, "one poll at the edge is not enough"
        s, t = step(s, 1); assert t and s == (True, 0), "two polls (~150 ms) show it"
        s, t = step(s, 30); assert not t, "still near the bar"
        s, t = step(s, 200); assert t and s == (False, 0), "moved away: hide"
        s, t = step(s, 1); s, t = step(s, 400); s, t = step(s, 1); assert not t, "a flick to the edge doesn't count"
        print("ok"); sys.exit(0)
    main()
