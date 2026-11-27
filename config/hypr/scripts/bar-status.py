#!/usr/bin/env python3
"""Smart top-bar items (waybar custom modules, JSON out). Each stays empty until it has something to say.

  bar-status.py system    CPU / memory / temperature / disk, shown only when one of them is high
  bar-status.py privacy   orange dot while the microphone, camera or a screen recorder is in use
  bar-status.py next      next calendar event in the coming 90 minutes ("Standup in 12 min")
  bar-status.py attention (long-running) what needs you: agents waiting/finished, windows asking for attention
  bar-status.py goto      jump to the most important of those (bar click)
"""
import glob, json, os, subprocess, sys, time
from pathlib import Path

EMPTY = {"text": "", "class": "none", "tooltip": ""}
CPU_HI, MEM_HI, TEMP_HI, DISK_HI = 85, 90, 88, 92   # percent / °C at which an item appears


def out(d): print(json.dumps(d, ensure_ascii=False)); sys.stdout.flush()


def _battery_alert():
    """Warn on fast drain or little time left — only while unplugged."""
    b = Path("/sys/class/power_supply/BAT0")
    try:
        if (b / "status").read_text().strip() != "Discharging":
            return []
        watts = int((b / "power_now").read_text()) / 1e6
        left = int((b / "energy_now").read_text()) / 1e6 / watts * 60 if watts else 999
    except (OSError, ValueError):
        return []
    if left <= 25: return [("\U000F0083", f"{left:.0f} min", f"Battery: about {left:.0f} minutes left. Plug in soon")]
    if watts >= 35: return [("\U000F140B", f"{watts:.0f} W", f"Battery draining fast ({watts:.0f} W). Try power saver (Super+Shift+P)")]
    return []


def _gpu_alert():
    # never wake a sleeping dGPU just to read its temperature (that would drain the battery)
    for dev in glob.glob("/sys/bus/pci/devices/*"):
        try:
            if open(f"{dev}/vendor").read().strip() == "0x10de" and open(f"{dev}/class").read().startswith("0x03") \
                    and open(f"{dev}/power/runtime_status").read().strip() != "active":
                return []
        except OSError:
            pass
    try:
        t = int(subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=2).stdout.split()[0])
    except Exception:
        return []   # no NVIDIA GPU, driver asleep, or nvidia-smi missing
    return [("\U000F08AE", f"{t}°", f"GPU hot: {t} °C")] if t >= TEMP_HI else []


def _failed_services():
    try:
        r = subprocess.run(["systemctl", "--user", "--failed", "--plain", "--no-legend"], capture_output=True, text=True, timeout=2)
    except Exception:
        return []
    units = [l.split()[0] for l in r.stdout.splitlines() if l.strip()]
    return [("\U000F0026", str(len(units)), "Failed background services: " + ", ".join(units) +
             "\n(see: systemctl --user --failed)")] if units else []


def system():
    import psutil
    cpu = psutil.cpu_percent(interval=0.4)
    mem = psutil.virtual_memory().percent
    temps = [t.current for ts in psutil.sensors_temperatures().values() for t in ts if t.current]
    temp = max(temps, default=0)
    disk = psutil.disk_usage(str(Path.home())).percent
    alerts = []
    if cpu >= CPU_HI: alerts.append(("\U000F0EE0", f"{cpu:.0f}%", f"CPU busy: {cpu:.0f}%"))
    if mem >= MEM_HI: alerts.append(("\U000F035B", f"{mem:.0f}%", f"Memory almost full: {mem:.0f}%"))
    if temp >= TEMP_HI: alerts.append(("\U000F050F", f"{temp:.0f}°", f"Running hot: {temp:.0f} °C"))
    if disk >= DISK_HI: alerts.append(("\U000F02CA", f"{disk:.0f}%", f"Disk almost full: {disk:.0f}% used"))
    swap = psutil.swap_memory()
    if swap.total and swap.percent >= 50: alerts.append(("\U000F04B2", f"{swap.percent:.0f}%", f"Swapping heavily ({swap.percent:.0f}% swap used): things will feel slow"))
    alerts += _battery_alert() + _gpu_alert() + _failed_services()
    if not alerts:
        return EMPTY
    return {"text": "  ".join(f"{i} {v}" for i, v, _ in alerts), "class": "alert",
            "tooltip": "\n".join(t for *_, t in alerts) + "\nClick: system monitor"}


def _capture_open():
    """Kernel says a microphone is capturing (PipeWire closes idle devices). A file read: practically free."""
    for f in glob.glob("/proc/asound/card*/pcm*c/sub*/status"):
        try:
            if not open(f).read().startswith("closed"): return True
        except OSError:
            pass
    return False


def _pw_streams():
    """-> (apps capturing audio, apps capturing video: camera via PipeWire or screen sharing). [] if PipeWire is unavailable."""
    try:
        objs = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=3).stdout or "[]")
    except Exception:
        return None, None
    audio, video = set(), set()
    for o in objs:
        info = o.get("info") or {}; p = info.get("props") or {}
        mc = p.get("media.class", "")
        name = p.get("application.name") or p.get("application.process.binary") or "an app"
        if "peak" in p.get("media.name", "").lower() or p.get("stream.monitor") or name.lower() in ("pavucontrol", "pulseaudio volume control"):
            continue   # volume meters, not real recording
        if mc == "Stream/Input/Audio": audio.add(name)
        elif mc == "Stream/Input/Video": video.add(name)
    return sorted(audio), sorted(video)


def _mic_apps():
    if not _capture_open():
        return []
    audio, _ = _pw_streams()
    return audio if audio is not None else ["an app"]   # PipeWire unreadable but the mic is open: still in use


def _screen_apps():
    _, video = _pw_streams()
    return video or []


def _camera_apps():
    apps = set()
    for fd in glob.glob("/proc/[0-9]*/fd/*"):
        try:
            if os.readlink(fd).startswith("/dev/video"):
                apps.add(Path(fd).parents[1].joinpath("comm").read_text().strip())
        except OSError:
            pass
    return sorted(apps)


def _recorders():
    names = {"wf-recorder", "wl-screenrec", "obs", "gpu-screen-recorder", "kooha"}
    found = set()
    for c in glob.glob("/proc/[0-9]*/comm"):
        try:
            n = Path(c).read_text().strip()
        except OSError:
            continue
        if n in names: found.add(n)
    # our own recorder (record.sh) has its own timer + stop button in the bar; don't show it twice
    if Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "myos-record.pid").exists(): found.discard("wf-recorder")
    return sorted(found)


def privacy():
    # system-adapt scans every 5 s and saves the result; scan ourselves only if that is missing or stale
    try:
        d = json.loads((Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "myos-privacy.json").read_text())
        if time.time() - d["t"] > 20: raise ValueError("stale")
        mic, cam, rec = d["mic"], d["cam"], d["rec"]
    except (OSError, ValueError, KeyError):
        mic, cam, rec = _mic_apps(), _camera_apps(), _recorders() + _screen_apps()
    if not (mic or cam or rec):
        return EMPTY
    icons, tips = [], []
    if cam: icons.append("\U000F0567"); tips.append("Camera: " + ", ".join(cam))
    if mic: icons.append("\U000F036C"); tips.append("Microphone: " + ", ".join(mic))
    if rec: icons.append("\U000F044A"); tips.append("Screen recording or sharing: " + ", ".join(rec))
    return {"text": " ".join(icons), "class": "camera" if cam or rec else "mic", "tooltip": "\n".join(tips)}


def next_event_text(events, now, horizon=90 * 60):
    """Pick the event to show: one that started up to 10 minutes ago, else the next within the horizon."""
    for ts, title, cal, all_day in events:
        if all_day:
            continue
        mins = round((ts - now) / 60)
        if -10 <= mins <= 0:
            return {"text": f"\U000F00ED  {title} · now", "class": "now", "tooltip": f"{title}\n{cal} · started {time.strftime('%I:%M %p', time.localtime(ts))}"}
        if 0 < ts - now <= horizon:
            when = f"in {mins} min" if mins < 60 else time.strftime("at %I:%M %p", time.localtime(ts)).replace(" 0", " ")
            return {"text": f"\U000F00ED  {title} · {when}", "class": "soon" if mins <= 10 else "later",
                    "tooltip": f"{title}\n{cal} · {time.strftime('%I:%M %p', time.localtime(ts))}\nClick: calendar"}
    return EMPTY


def next_event():
    for d in (Path.home() / ".local/share/myos", Path(__file__).resolve().parents[3] / "config/desktop"):
        if (d / "panel.py").exists():
            sys.path.insert(0, str(d)); break
    # the calendar service is slow to load (~1 s CPU): fetch at most every 10 min, recompute "in N min" every run
    cache = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "bar-events.json"
    try:
        fetched, events = json.loads(cache.read_text())
    except (OSError, ValueError):
        fetched, events = 0, []
    if time.time() - fetched > 600:
        try:
            from panel import calendar_events
            events = calendar_events(days=1, limit=60)
            cache.write_text(json.dumps([time.time(), events]))
        except Exception:
            pass
    return next_event_text([tuple(e) for e in events], time.time())


AGENT_STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "myos-agents.json"   # written by agent-notify
AGENT_NAMES = {"claude": "Claude", "codex": "Codex", "agy": "Antigravity", "gemini": "Gemini"}
REMIND_AFTER = 300   # seconds an agent may wait on you before one reminder


def attention_items(urgent, clients, agents):
    """Everything asking for you, most important first: agents that need you, windows asking for attention,
    agents that finished. -> [(kind, label, workspace, address, detail)]"""
    info = {c["address"]: c for c in clients}
    app = lambda c: (c.get("class") or c.get("title") or "A window").split(".")[-1].replace("-", " ").title()
    agent_addrs = {e.get("address") for e in agents.values()}
    items = []
    for kind in ("needs", "urgent", "done"):
        if kind == "urgent":
            items += [("urgent", f"{app(info[a])} wants attention", info[a]["workspace"]["name"], a, info[a].get("title", "")[:60])
                      for a in reversed(urgent) if a in info and a not in agent_addrs]
            continue
        for e in sorted(agents.values(), key=lambda e: -e.get("since", 0)):
            if e.get("state") != kind: continue
            name = AGENT_NAMES.get(e.get("agent"), str(e.get("agent", "Agent")).title())
            verb = "needs you" if kind == "needs" else "finished"
            items.append((kind, f"{name} {verb} · {e.get('proj', '')}", e.get("ws", "?"), e.get("address", ""), e.get("summary", "")))
    return items


def attention_text(urgent, clients, agents=None):
    items = attention_items(urgent, clients, agents or {})
    if not items:
        return EMPTY
    icon = {"needs": "\U000F0026", "urgent": "\U000F0028", "done": "\U000F012C"}
    kind, label, ws, _, _ = items[0]
    text = f"{icon[kind]}  {label} · {ws}" if len(items) == 1 else f"{icon[kind]}  {label} · {ws}  +{len(items) - 1}"
    tip = "\n".join(f"{icon[k]}  {l} · workspace {w}" + (f"\n      {d}" if d else "") for k, l, w, _, d in items)
    return {"text": text, "class": kind, "tooltip": tip + "\nClick: go to the first one"}


def _agents_rw(fn):
    """Locked update of the agent state shared with agent-notify; fn(dict) -> bool (changed)."""
    import fcntl
    try:
        with open(str(AGENT_STATE) + ".lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try: d = json.load(open(AGENT_STATE))
            except (OSError, ValueError): d = {}
            if fn(d):
                tmp = str(AGENT_STATE) + ".tmp"; json.dump(d, open(tmp, "w")); os.replace(tmp, AGENT_STATE)
            return d
    except OSError:
        return {}


def goto():
    """Bar click: jump to the most important thing asking for you."""
    clients = json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True).stdout or "[]")
    agents = _agents_rw(lambda d: False)
    for kind, _, _, addr, _ in attention_items([], clients, agents):
        if addr and any(c["address"] == addr for c in clients):
            subprocess.run(["hyprctl", "dispatch", "focuswindow", f"address:{addr}"]); return
    subprocess.run(["hyprctl", "dispatch", "focusurgentorlast"])


def attention():
    """Long-running: follow Hyprland's events plus the agent state; one line of waybar JSON per change."""
    import select, socket
    sock = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "hypr" / os.environ["HYPRLAND_INSTANCE_SIGNATURE"] / ".socket2.sock"
    clients = lambda: json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True).stdout or "[]")
    urgent, last, mtime = [], None, 0
    parent = os.getppid()   # waybar; if it goes away we must too (else every bar restart leaks a listener)
    s = socket.socket(socket.AF_UNIX); s.connect(str(sock)); buf = b""
    while os.getppid() == parent:
        changed_addr = None
        if select.select([s], [], [], 1.0)[0]:
            chunk = s.recv(65536)
            if not chunk: return   # Hyprland went away; waybar restarts us
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                ev, _, data = line.decode("utf-8", "replace").partition(">>")
                addr = "0x" + data.split(",")[0].removeprefix("0x")
                if ev == "urgent":
                    urgent = [a for a in urgent if a != addr] + [addr]
                elif ev in ("activewindowv2", "closewindow"):
                    if addr in urgent: urgent.remove(addr)
                    changed_addr = (ev, addr)
        now = time.time()

        def update(d):
            ch = False
            for k, e in list(d.items()):
                if changed_addr and e.get("address") == changed_addr[1]:
                    if changed_addr[0] == "closewindow":
                        del d[k]; ch = True; continue
                    if e.get("state") in ("needs", "done"):
                        e["state"] = "seen"; ch = True   # you looked at it
                if e.get("state") == "needs" and not e.get("reminded") and now - e.get("since", now) > REMIND_AFTER:
                    e["reminded"] = True; ch = True
                    name = AGENT_NAMES.get(e.get("agent"), "An agent")
                    subprocess.Popen(["notify-send", "-u", "critical", "-a", "KadaOS", "-i", "dialog-question-symbolic",
                                      f"Still waiting · {name} · {e.get('proj', '')}",
                                      f"{e.get('summary', '')}\nWaiting {int((now - e['since']) // 60)} min · workspace {e.get('ws', '?')}"])
                if e.get("state") in ("seen", "working") and now - e.get("since", now) > 86400:
                    del d[k]; ch = True   # forget day-old sessions
            return ch
        try: m = AGENT_STATE.stat().st_mtime
        except OSError: m = 0
        if changed_addr or m != mtime or now - (last or (0, 0))[1] > 30:
            mtime = m
            agents = _agents_rw(update)
            o = attention_text(urgent, clients(), agents)
            if not last or o != last[0]:
                out(o)
            last = (o, now)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "test":
        now = 1_000_000
        assert next_event_text([], now) == EMPTY
        assert next_event_text([(now + 600, "Standup", "Work", False)], now)["class"] == "soon"
        assert "in 30 min" in next_event_text([(now + 1800, "Sync", "Work", False)], now)["text"]
        assert next_event_text([(now - 120, "Call", "Work", False)], now)["class"] == "now"
        assert next_event_text([(now + 600, "Holiday", "Work", True)], now) == EMPTY
        assert next_event_text([(now + 4 * 3600, "Later", "Work", False)], now) == EMPTY
        c = [{"address": "0xa", "class": "google-chrome", "title": "Meet", "workspace": {"name": "3"}},
             {"address": "0xb", "class": "org.gnome.Nautilus", "title": "Files", "workspace": {"name": "2"}}]
        assert attention_text([], c) == EMPTY and attention_text(["0xdead"], c) == EMPTY
        assert attention_text(["0xa"], c)["text"].endswith("Google Chrome wants attention · 3")
        assert "+1" in attention_text(["0xa", "0xb"], c)["text"]
        ag = {"s1": {"agent": "claude", "proj": "KadaOS", "state": "done", "ws": "3", "address": "0xc", "summary": "Fixed the clock.", "since": 5},
              "s2": {"agent": "codex", "proj": "lab", "state": "needs", "ws": "2", "address": "0xd", "summary": "Run tests?", "since": 1},
              "s3": {"agent": "claude", "proj": "x", "state": "seen", "ws": "1", "address": "0xe", "since": 9}}
        t = attention_text(["0xa"], c, ag)
        assert t["class"] == "needs" and t["text"].endswith("Codex needs you · lab · 2  +2"), t
        assert [k for k, *_ in attention_items(["0xa"], c, ag)] == ["needs", "urgent", "done"]
        assert attention_text([], c, {"s3": ag["s3"]}) == EMPTY
        assert attention_text([], c, {"s1": ag["s1"]})["text"].endswith("Claude finished · KadaOS · 3")
        print("ok"); sys.exit(0)
    if cmd == "attention":
        attention(); sys.exit(0)
    if cmd == "goto":
        goto(); sys.exit(0)
    fn = {"system": system, "privacy": privacy, "next": next_event}.get(cmd)
    if not fn:
        print(__doc__); sys.exit(2)
    try:
        out(fn())
    except Exception as e:   # a broken probe must never break the bar
        out(dict(EMPTY, tooltip=str(e)))
