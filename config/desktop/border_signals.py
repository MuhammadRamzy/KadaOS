#!/usr/bin/env python3
"""Border signals: the window outline as a quiet signal channel (no popups, no sounds, nothing to dismiss).

The colour says what, the motion says how urgent: a slow breath = "when you get a chance", a quick flash = "look now".
Hyprland's own border animation does the fading, so it's smooth and costs nothing.

  border-signal lookaway      violet breath ×2   you've been at the screen 20 min: look 20 ft away for 20 s
  border-signal attention     amber flash        a window asked for attention (on that window)
  border-signal done          green breath       a long task finished (scripts, agents: `…; border-signal done`)
  border-signal fail          red flash ×2       a task failed
  border-signal battery       orange breath      battery low
  border-signal test          all of the above, one after another
  border-signal daemon        watch Hyprland and input activity (the myos-border-signals user service)

Never while fullscreen or locked; one signal at a time; the border always returns to the theme colour.
Settings (optional, re-read every 30 s) in ~/.config/myos/border-signals.json:
  {"lookaway": true, "lookaway_minutes": 20, "attention": true, "battery": true, "battery_percent": 15}
"""
import fcntl, json, os, re, socket, subprocess, sys, threading, time
from pathlib import Path

HOME = Path.home()
COLORS = HOME / ".config/hypr/colors.conf"          # written by scripts/theme.py: the colours to return to
SETTINGS = HOME / ".config/myos/border-signals.json"
LOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "border-signal.lock"
PENDING = LOCK.with_name("border-signal.windows")   # windows recoloured right now (cleared on daemon start)
IDLE = HOME / ".local/share/myos/hydration-idle"    # input-only idle observer shared with Hydration
DEFAULTS = dict(lookaway=True, lookaway_minutes=20, attention=True, battery=True, battery_percent=15)

# name: (colour, motion, times)   breathe = ~1.4 s soft in/out, flash = ~0.5 s
SIGNALS = {
    "lookaway": ("rgba(b48cffff)", "breathe", 2),
    "attention": ("rgba(ffab4dff)", "flash", 1),
    "done": ("rgba(5fd38aff)", "breathe", 1),
    "fail": ("rgba(ff6b62ff)", "flash", 2),
    "battery": ("rgba(ffab4dff)", "breathe", 1),
}


def settings():
    try: return DEFAULTS | json.loads(SETTINGS.read_text())
    except (OSError, ValueError): return dict(DEFAULTS)


def hyprctl(*args):
    try: return subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=3, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.TimeoutExpired): return ""


def theme_border():
    """The active border colour the theme set (colors.conf), never whatever is on screen right now."""
    try: m = re.search(r"col\.active_border\s*=\s*(.+)", COLORS.read_text())
    except OSError: m = None
    return m[1].strip() if m else "rgba(5b9cffdd)"


def quiet_now():
    """True when a signal would be rude or invisible: a fullscreen window or the lock screen."""
    if subprocess.run(["pgrep", "-x", "hyprlock"], capture_output=True).returncode == 0: return True
    try: return bool(json.loads(hyprctl("activewindow", "-j") or "{}").get("fullscreen"))
    except ValueError: return False


def show(name, address=None, sleep=time.sleep):
    """Play one signal. With an address, only that window's border; else the focused window's border."""
    color, motion, times = SIGNALS[name]
    if quiet_now(): return False
    LOCK.touch(exist_ok=True)
    with open(LOCK) as f:
        fcntl.flock(f, fcntl.LOCK_EX)                   # one at a time: a second signal waits its turn
        on_ms, off_ms = (700, 650) if motion == "breathe" else (260, 240)
        base = theme_border()
        if address:
            with open(PENDING, "a") as p: p.write(address + "\n")
        for i in range(times):
            if address:
                for prop in ("active_border_color", "inactive_border_color"):
                    hyprctl("dispatch", "setprop", f"address:{address}", prop, color)
            else:
                hyprctl("keyword", "general:col.active_border", color)
            sleep(on_ms / 1000)
            if address:
                for prop in ("active_border_color", "inactive_border_color"):
                    hyprctl("dispatch", "setprop", f"address:{address}", prop, "unset")
            else:
                hyprctl("keyword", "general:col.active_border", base)
            sleep(off_ms / 1000)
        if address: _forget(address)
    return True


def _forget(address):
    try: left = [a for a in PENDING.read_text().split() if a != address]
    except OSError: return
    PENDING.write_text("".join(a + "\n" for a in left))


def reset_borders():
    """Back to the theme colour, globally and on any window a cut-off signal left recoloured."""
    hyprctl("keyword", "general:col.active_border", theme_border())
    try: windows = set(PENDING.read_text().split())
    except OSError: windows = set()
    for a in windows:
        for prop in ("active_border_color", "inactive_border_color"):
            hyprctl("dispatch", "setprop", f"address:{a}", prop, "unset")
    PENDING.unlink(missing_ok=True)


class LookAway:
    """Continuous activity → a reminder every N minutes. A minute away (idle) resets it."""
    def __init__(self, minutes, now=time.monotonic):
        self.period, self.now, self.since = minutes * 60, now, None

    def active(self):
        if self.since is None: self.since = self.now()

    def idle(self):
        self.since = None

    def due(self):
        return self.since is not None and self.now() - self.since >= self.period

    def shown(self):
        self.since = self.now()


class Battery:
    """Once per discharge, when the level crosses the threshold."""
    def __init__(self, percent):
        self.percent, self.warned = percent, False

    def check(self, level, discharging):
        if not discharging or level > self.percent + 2:
            self.warned = False                          # plugged in, or charged back up: arm again
            return False
        if level <= self.percent and not self.warned:
            self.warned = True
            return True
        return False


def read_battery():
    for b in Path("/sys/class/power_supply").glob("BAT*"):
        try: return int((b / "capacity").read_text()), (b / "status").read_text().strip() == "Discharging"
        except (OSError, ValueError): pass
    return None


def watch_idle(look):
    """Feed the look-away timer from the input-only idle observer (idle after 60 s without input)."""
    while True:
        try:
            p = subprocess.Popen([str(IDLE), "60"], stdout=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
            for line in p.stdout:
                ev = line.strip()
                if ev in ("ready", "active"): look.active()
                elif ev in ("idle", "away"): look.idle()
        except OSError:
            pass
        look.active()                                    # observer gone: fall back to plain time-at-screen
        time.sleep(30)


def attention_wanted(addr, opened, now, last, focused):
    """Flash for urgent>>addr? Not for a window that is just appearing (GTK marks new windows urgent ~20 ms
    before they open), not for the focused one, and at most once a minute per window."""
    if addr == focused or now - opened.get(addr, -1e9) < 2 or now - last.get(addr, -1e9) < 60: return False
    last[addr] = now
    return True


def watch_hyprland():
    """urgent>>ADDR from Hyprland's event socket → an amber flash on that window."""
    opened, last, pending = {}, {}, set()
    def later(addr):
        try:
            time.sleep(0.5)                              # let an opening window open (and take focus) first
            focused = json.loads(hyprctl("activewindow", "-j") or "{}").get("address")
            if attention_wanted(addr, opened, time.monotonic(), last, focused): show("attention", addr)
        except ValueError:
            pass
        finally:
            pending.discard(addr)
    while True:
        try:
            sig = os.environ["HYPRLAND_INSTANCE_SIGNATURE"]
            path = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "hypr" / sig / ".socket2.sock"
            with socket.socket(socket.AF_UNIX) as s:
                s.connect(str(path))
                for line in s.makefile():
                    ev, _, data = line.strip().partition(">>")
                    if ev == "openwindow": opened["0x" + data.split(",")[0]] = time.monotonic()
                    elif ev == "closewindow": opened.pop("0x" + data, None); last.pop("0x" + data, None)
                    elif ev == "urgent" and settings()["attention"]:
                        addr = "0x" + data                # at most one waiting check per window, and only if due
                        if addr in pending or time.monotonic() - last.get(addr, -1e9) < 60: continue
                        pending.add(addr)
                        threading.Thread(target=later, args=(addr,), daemon=True).start()
        except (OSError, KeyError, ValueError):
            pass
        time.sleep(5)                                    # Hyprland restarting: try again


def daemon():
    reset_borders()                                      # in case a signal was ever cut off mid-way
    cfg = settings()
    look, batt = LookAway(cfg["lookaway_minutes"]), Battery(cfg["battery_percent"])
    threading.Thread(target=watch_idle, args=(look,), daemon=True).start()
    threading.Thread(target=watch_hyprland, daemon=True).start()
    while True:
        time.sleep(30)
        cfg = settings()                                 # edits to the settings file apply within 30 s
        look.period, batt.percent = cfg["lookaway_minutes"] * 60, cfg["battery_percent"]
        if cfg["lookaway"] and look.due() and show("lookaway"): look.shown()   # quiet now: try again in 30 s
        b = read_battery() if cfg["battery"] else None
        if b and batt.check(*b) and not show("battery"): batt.warned = False   # quiet now (fullscreen/locked): retry


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "-h"
    if cmd == "daemon": daemon()
    elif cmd == "test":
        for name in SIGNALS: print(name); show(name); time.sleep(0.6)
    elif cmd in SIGNALS: return 0 if show(cmd) else 1
    else: print(__doc__.strip()); return 0 if cmd in ("-h", "--help", "help") else 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
