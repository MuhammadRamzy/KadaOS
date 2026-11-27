#!/usr/bin/env python3
"""battery-health: how your battery is aging, from a daily sample.

  battery-health            health (capacity now vs new), cycles, charge, power draw, trend and projection
  battery-health --json     the same as data (the Battery panel uses it)
  battery-health _sample    record today's reading (the assistant's watcher calls this; once a day is kept)

History: ~/.local/state/myos/battery.jsonl (one line per day, local only).
"""
import json, os, sys, time
from pathlib import Path

HOME = Path.home()
LOG = Path(os.environ.get("BATTERY_LOG") or HOME / ".local/state/myos/battery.jsonl")
SYS = Path(os.environ.get("BATTERY_SYS") or "/sys/class/power_supply")
WORN = 80          # % of design capacity where a battery counts as worn (the usual warranty line)


def rd(p):
    try: return Path(p).read_text().strip()
    except OSError: return ""


def num(p):
    v = rd(p); return int(v) if v.lstrip("-").isdigit() else None


def battery_dir():
    return next((b for b in sorted(SYS.glob("BAT*")) if rd(b / "type") == "Battery"), None)


def read(b=None):
    """Live reading in Wh / W (handles energy_* in µWh and charge_* in µAh × voltage)."""
    b = b or battery_dir()
    if not b: return None
    full, design = num(b / "energy_full"), num(b / "energy_full_design")
    now, power = num(b / "energy_now"), num(b / "power_now")
    if full is None:                                       # charge-based batteries: µAh × µV
        v = num(b / "voltage_min_design") or num(b / "voltage_now") or 0
        cf, cd, cn, cur = num(b / "charge_full"), num(b / "charge_full_design"), num(b / "charge_now"), num(b / "current_now")
        full, design = (cf * v // 10**6 if cf else None), (cd * v // 10**6 if cd else None)
        now, power = (cn * v // 10**6 if cn else None), (cur * (num(b / "voltage_now") or v) // 10**6 if cur else None)
    if not full or not design: return None
    return {"full_wh": full / 1e6, "design_wh": design / 1e6, "now_wh": (now or 0) / 1e6, "power_w": abs(power or 0) / 1e6,
            "health": round(full / design * 100, 1), "cycles": num(b / "cycle_count"), "percent": num(b / "capacity"),
            "status": rd(b / "status"), "maker": rd(b / "manufacturer"), "tech": rd(b / "technology")}


def history():
    try: return [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
    except (OSError, ValueError): return []


def sample(now=None, r=None):
    """Append today's health/cycles once per day. Returns True if a line was written."""
    r = r or read()
    if not r: return False
    day = time.strftime("%Y-%m-%d", time.localtime(now or time.time()))
    h = history()
    if h and h[-1].get("day") == day: return False
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f: f.write(json.dumps({"day": day, "health": r["health"], "cycles": r["cycles"], "full_wh": r["full_wh"]}) + "\n")
    return True


def trend(h):
    """Health lost per 100 cycles and per year, from the first and last samples; None until there's enough data."""
    if len(h) < 2: return None
    a, b = h[0], h[-1]
    days = (time.mktime(time.strptime(b["day"], "%Y-%m-%d")) - time.mktime(time.strptime(a["day"], "%Y-%m-%d"))) / 86400
    lost = a["health"] - b["health"]
    cyc = (b.get("cycles") or 0) - (a.get("cycles") or 0)
    if days < 30 or lost <= 0: return {"per_year": 0.0, "per_100_cycles": 0.0, "days": int(days)}
    return {"per_year": round(lost / days * 365, 1), "per_100_cycles": round(lost / cyc * 100, 1) if cyc > 0 else None, "days": int(days)}


def projection(health, t):
    """Years until WORN at the current pace, or None if it isn't aging measurably."""
    if not t or not t.get("per_year") or health <= WORN: return None
    return round((health - WORN) / t["per_year"], 1)


def verdict(health):
    if health >= 95: return "Like new"
    if health >= 85: return "Good"
    if health >= WORN: return "Aging normally"
    return "Worn: it holds noticeably less than new"


def report():
    r = read()
    if not r: return None
    h = history(); t = trend(h)
    hours = (r["now_wh"] / r["power_w"]) if r["power_w"] > 0.5 and r["status"] == "Discharging" else None
    return {**r, "verdict": verdict(r["health"]), "trend": t, "years_to_worn": projection(r["health"], t),
            "hours_left": round(hours, 1) if hours else None, "history": h[-180:]}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"]): print(__doc__.strip()); return 0
    if argv[:1] == ["_sample"]: sample(); return 0
    r = report()
    if "--json" in argv: print(json.dumps(r)); return 0
    if not r: print("No battery found."); return 1
    print(f"Health {r['health']:.0f}% · {r['verdict']}  ({r['full_wh']:.1f} of {r['design_wh']:.1f} Wh when new)")
    print(f"Cycles {r['cycles'] if r['cycles'] is not None else '?'} · now {r['percent']}% ({r['status'].lower()})"
          + (f" · {r['power_w']:.1f} W" if r["power_w"] else "") + (f" · about {r['hours_left']} h left" if r["hours_left"] else ""))
    t = r["trend"]
    if not t: print("Trend: building up (one sample a day)")
    else:
        print(f"Trend over {t['days']} days: " + (f"−{t['per_year']}% a year" if t["per_year"] else "no measurable loss")
              + (f" · about {r['years_to_worn']} years to {WORN}%" if r["years_to_worn"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
