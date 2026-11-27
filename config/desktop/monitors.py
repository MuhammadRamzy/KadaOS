#!/usr/bin/env python3
"""monitors: remember a screen layout for each set of displays and put it back when they're plugged in again.

  monitors            show the connected displays and whether this set has a saved layout
  monitors save       remember the current layout for this set (arrange it first, e.g. with nwg-displays)
  monitors apply      put back the saved layout for this set (system-adapt runs this on plug / unplug)
  monitors forget     delete the saved layout for this set
  monitors --json     the same as `monitors`, as data

Displays are matched by their make/model/serial (not the port), so a monitor is recognised on any cable.
Saved layouts: ~/.config/myos/monitor-profiles.json. With no saved layout Hyprland's default applies
(an external display goes to the right of the laptop). On unplug Hyprland moves its workspaces to the laptop.
"""
import json, os, subprocess, sys
from pathlib import Path

STORE = Path(os.environ.get("MONITOR_PROFILES") or Path.home() / ".config/myos/monitor-profiles.json")


def hypr(*a):
    try: return subprocess.run(["hyprctl", *a], capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.TimeoutExpired): return ""


def current():
    try: return json.loads(hypr("monitors", "all", "-j") or "[]")
    except ValueError: return []


def ident(m):
    return m.get("description") or m["name"]


def key(mons):
    """The set of displays, independent of port and order."""
    return " + ".join(sorted(ident(m) for m in mons))


def snapshot(mons):
    return {ident(m): ({"disabled": True} if m.get("disabled") else
                       {"mode": f"{m['width']}x{m['height']}@{m['refreshRate']:.2f}", "pos": f"{m['x']}x{m['y']}",
                        "scale": round(m["scale"], 2), "transform": m.get("transform", 0)}) for m in mons}


def rules(layout):
    """hyprctl `keyword monitor` values for a saved layout, matched by description."""
    out = []
    for desc, s in sorted(layout.items()):
        if s.get("disabled"): out.append(f"desc:{desc},disable"); continue
        r = f"desc:{desc},{s['mode']},{s['pos']},{s['scale']:g}"
        if s.get("transform"): r += f",transform,{s['transform']}"
        out.append(r)
    return out


def load():
    try: return json.loads(STORE.read_text())
    except (OSError, ValueError): return {}


def store(d):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, indent=2) + "\n")


def apply(mons=None, profiles=None):
    """Apply the saved layout for the connected set. Returns the rules applied ([] if none saved)."""
    mons = current() if mons is None else mons
    layout = (load() if profiles is None else profiles).get(key(mons))
    if not layout: return []
    rs = rules(layout)
    for r in rs: hypr("keyword", "monitor", r)
    return rs


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "show"
    if cmd in ("-h", "--help"): print(__doc__.strip()); return 0
    mons = current()
    if not mons: print("Hyprland isn't answering (run this inside the desktop)."); return 1
    k, saved = key(mons), load()
    if cmd == "save":
        saved[k] = snapshot(mons); store(saved); print(f"Saved the layout for: {k}"); return 0
    if cmd == "forget":
        print("Forgot it." if saved.pop(k, None) else "Nothing saved for this set."); store(saved); return 0
    if cmd == "apply":
        rs = apply(mons, saved); print("\n".join(rs) if rs else "No saved layout for this set."); return 0
    if cmd in ("show", "--json"):
        if cmd == "--json": print(json.dumps({"set": k, "saved": k in saved, "monitors": snapshot(mons)})); return 0
        for d, s in snapshot(mons).items(): print(f"{d}: " + ("off" if s.get("disabled") else f"{s['mode']} at {s['pos']} ×{s['scale']:g}"))
        print("Saved layout: " + ("yes (applied on plug-in)" if k in saved else "no (arrange, then `monitors save`)")); return 0
    print(__doc__.strip()); return 2


if __name__ == "__main__":
    sys.exit(main())
