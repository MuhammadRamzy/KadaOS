#!/usr/bin/env python3
"""Assistant watchers + daily briefing (run every 5 min by myos-watch.timer).

  watch.py            check disk, failed services, battery, temperatures, remote devices (`board watch`) and
                      finished `board job`s; notify once per new problem and
                      leave an alert for the orb (amber ring; opening the panel lists and clears them).
                      The first run each day after 06:00 also sends the briefing.
  watch.py --briefing print today's briefing (also what /briefing shows in the chat)
"""
import json, re, shutil, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
STATE = HOME / ".cache/myos-watch.json"                 # {problem key: last notified}, "briefed": date
ALERTS = HOME / ".cache/myos-assistant-alerts.json"     # [{"t", "title", "body"}] for the orb
REPEAT = 6 * 3600                                       # re-notify a problem that is still there after 6 h
BOARD = HOME / ".local/bin/board"                       # remote devices (config/remote/board.py)
PHONE = HOME / ".local/bin/phone"
BATTERY = HOME / ".local/bin/battery-health"            # daily battery sample + "worn" warning (config/desktop/battery.py)
TIDY = HOME / ".local/bin/tidy"                         # Downloads tidy, once a day if you turned it on (config/desktop/tidy.py)
DISK = HOME / ".local/bin/disk"                         # what can be freed (config/desktop/disk.py), for the low-disk offer                       # the phone link + alerts to the phone (config/phone/phone.py)

def q(*argv, timeout=8):
    try: return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL).stdout.strip()
    except Exception: return ""

def events(days=1):
    """[(timestamp, title, calendar, all_day)] from the calendars (reuses the control center's reader); [] if unavailable."""
    import importlib.util
    for c in (HOME / ".local/share/myos/panel.py", Path(__file__).resolve().parents[1] / "desktop/panel.py"):
        if c.exists():
            try:
                s = importlib.util.spec_from_file_location("panel", str(c)); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
                return m.calendar_events(days)
            except Exception: return []
    return []

def rd(p):
    try: return Path(p).read_text().strip()
    except OSError: return ""

def battery():
    """(percent, status) of the first battery, or None."""
    for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        cap = rd(b / "capacity")
        if cap.isdigit(): return int(cap), rd(b / "status")
    return None

def failed_units():
    units = []
    for scope in ([], ["--user"]):
        for line in q("systemctl", *scope, "--failed", "--no-legend", "--plain").splitlines():
            if line.split(): units.append(line.split()[0] + (" (user)" if scope else ""))
    return units

def remote_problems(board=BOARD, phone=PHONE):
    """Device alerts (`board watch check`), finished background jobs (`board job check`) and the phone link, as {key: (title, body)}."""
    out = {}
    if Path(phone).exists():             # phone: retry queued alerts, revive the link, report it when it's down
        try: out.update({k: tuple(v) for k, v in json.loads(q(str(phone), "_tick", timeout=60) or "{}").items()})
        except ValueError: pass
    if not Path(board).exists(): return out
    try: out.update({k: tuple(v) for k, v in json.loads(q(str(board), "watch", "check", timeout=90) or "{}").items()})
    except ValueError: pass
    try: jobs = json.loads(q(str(board), "job", "check", timeout=60) or "{}")
    except ValueError: jobs = {}
    for jid, j in jobs.items():
        ok = j.get("state") == "done" and j.get("rc") == 0
        head = ("✓ Job finished" if ok else "✗ Job lost (device rebooted?)" if j.get("state") == "lost"
                else f"✗ Job failed (exit {j.get('rc')})")
        out[f"job:{jid}"] = (f"{head} on {j.get('device', '?')}", "$ " + j.get("cmd", "")[:80] + "".join("\n" + t[:100] for t in j.get("tail") or []))
    return out

def problems(disk=None, bat=None, failed=None, gpu_temp=None, cpu_temp=None, evs=None, now=None, remote=None):
    """{key: (title, body)} for everything wrong right now. Arguments override live readings (tests)."""
    out = {}
    du = disk or shutil.disk_usage("/")
    free_gb, pct = du.free / 1e9, du.free / du.total * 100
    if pct < 10 or free_gb < 15:
        out["disk"] = ("Disk almost full", f"{free_gb:.0f} GB free ({pct:.0f}%) on /. Old Docker images, ~/Downloads and ollama models are the usual space.")
    bat = battery() if bat is None else bat
    if bat and bat[0] <= 15 and bat[1] == "Discharging":
        out["battery"] = ("Battery low", f"{bat[0]}% and discharging. Plug in soon.")
    failed = failed_units() if failed is None else failed
    for u in failed:
        out[f"failed:{u}"] = ("A service failed", f"{u}. Ask the assistant: “why did {u.split()[0]} fail?”")
    if gpu_temp is None:
        t = q("nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits")
        gpu_temp = int(t) if t.isdigit() else 0
    if gpu_temp >= 87: out["gpu-hot"] = ("GPU running hot", f"{gpu_temp} °C.")
    if cpu_temp is None:
        temps = [int(rd(z / "temp")) // 1000 for z in Path("/sys/class/thermal").glob("thermal_zone*") if rd(z / "temp").lstrip("-").isdigit()]
        cpu_temp = max(temps, default=0)
    if cpu_temp >= 97: out["cpu-hot"] = ("CPU running hot", f"{cpu_temp} °C.")
    now = time.time() if now is None else now
    for ts, title, cal, all_day in (events(1) if evs is None else evs):
        if not all_day and 0 <= ts - now <= 11 * 60:
            out[f"event:{ts}:{title}"] = (f"In {max(1, round((ts - now) / 60))} min: {title}", f"{time.strftime('%H:%M', time.localtime(ts))} · {cal}")
    out.update(remote_problems() if remote is None else remote)
    if remote is None and TIDY.exists(): q(str(TIDY), "_daily", timeout=60)   # does nothing unless `tidy on`; once a day
    if remote is None and BATTERY.exists():          # once a day is recorded; cheap (sysfs)
        q(str(BATTERY), "_sample", timeout=10)
        try: r = json.loads(q(str(BATTERY), "--json", timeout=10) or "null") or {}
        except ValueError: r = {}
        if r.get("health") and r["health"] < 80:
            out["battery-worn"] = (f"Battery worn: {r['health']:.0f}% of new", "It holds noticeably less charge than new. Battery page: "
                                   "myos-panel battery. A replacement restores the full runtime.")
    return out

def load(p, default):
    try: return json.loads(Path(p).read_text())
    except (OSError, ValueError): return default

def save(p, data):
    Path(p).parent.mkdir(parents=True, exist_ok=True); Path(p).write_text(json.dumps(data))

def due(found, state, now):
    """Problems to notify now: new ones, or still there after REPEAT. Updates state (resolved ones are dropped)."""
    new = {k: v for k, v in found.items() if k not in state or now - state[k] >= REPEAT}
    for k in [k for k in state if k != "briefed" and k not in found]: del state[k]
    for k in new: state[k] = now
    return new

def dirty_repos(root=HOME / "Projects"):
    out = []
    for g in sorted(root.glob("*/.git")) if root.exists() else []:
        n = len(q("git", "-C", str(g.parent), "status", "--porcelain").splitlines())
        if n: out.append(f"{g.parent.name} ({n} changed)")
    return out

def briefing():
    lines = [f"**{time.strftime('%A %d %B')}**"]
    bat = battery()
    if bat: lines.append(f"- Battery {bat[0]}% ({bat[1].lower()})")
    du = shutil.disk_usage("/"); lines.append(f"- Disk: {du.free / 1e9:.0f} GB free of {du.total / 1e9:.0f} GB")
    f = failed_units(); lines.append("- Failed services: " + (", ".join(f) if f else "none"))
    up = rd("/var/lib/update-notifier/updates-available")
    m = re.search(r"(\d+) (?:updates?|packages?) can be applied", up)
    lines.append(f"- Updates: {m.group(1)} waiting" if m else "- Updates: none reported")
    d = dirty_repos(); lines.append("- Unfinished work: " + (", ".join(d[:6]) if d else "all projects committed"))
    try:
        log = [json.loads(l) for l in (HOME / ".local/state/myos/assistant-actions.jsonl").read_text().splitlines()[-200:]]
        y = sum(1 for e in log if time.time() - e["t"] < 86400)
        if y: lines.append(f"- The assistant did {y} action(s) in the last 24 h (/log)")
    except (OSError, ValueError, KeyError): pass
    today = [e for e in events(1) if time.localtime(e[0]).tm_yday == time.localtime().tm_yday]
    lines.append("- Today: " + ("; ".join(("all day" if a else time.strftime("%H:%M", time.localtime(t))) + f" {s}" for t, s, _c, a in today[:6])
                                if today else "nothing on the calendar"))
    return "\n".join(lines)

def main():
    if "--briefing" in sys.argv: print(briefing()); return 0
    now, state = time.time(), load(STATE, {})
    new = due(problems(), state, now)
    alerts = load(ALERTS, [])
    for key, (title, body) in new.items():
        urgent = "full" in title or "low" in title or "host key" in title
        if key == "disk" and DISK.exists():          # an offer, not just a warning: how much can go, and a button to review it
            try: safe = json.loads(q(str(DISK), "--json", timeout=60) or "{}").get("safe_total", 0)
            except ValueError: safe = 0
            if safe > 1e9: body = body.split(".")[0] + f". {safe / 1e9:.1f} GB of caches and build leftovers can be freed safely."
            # notify-send -A doesn't work with this libnotify; notify-action.py is the setup's button helper
            subprocess.Popen(["sh", "-c", 'a=$(~/.config/hypr/scripts/notify-action.py -i drive-harddisk-symbolic -t 30 "$0" "$1" open=Review); '
                              '[ "$a" = open ] && exec ~/.local/bin/myos-panel storage', title, body],
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            q("notify-send", "-a", "Assistant", "-u", "critical" if urgent else "normal", title, body)
        if PHONE.exists(): q(str(PHONE), "_alert", title, body, *(["--urgent"] if urgent else []), timeout=15)
        alerts.append({"t": now, "title": title, "body": body})
    today = time.strftime("%Y-%m-%d")
    if state.get("briefed") != today and time.localtime().tm_hour >= 6:
        state["briefed"] = today
        q("notify-send", "-a", "Assistant", "Good morning", re.sub(r"\*\*", "", briefing()))
    save(STATE, state)
    if new: save(ALERTS, alerts[-20:])
    return 0

if __name__ == "__main__":
    sys.exit(main())
