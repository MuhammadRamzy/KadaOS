#!/usr/bin/env python3
"""system-adapt — makes the laptop react to context (runs as a systemd user service in Hyprland).

* Power:      unplugged → power-saver + 60 Hz;  plugged in → balanced (configurable) + 165 Hz.
              Only acts on plug/unplug, so a manual Super+Shift+P choice sticks until the next change.
* Quiet:      true fullscreen, a call (camera, or mic used by a browser/meeting app) or screen recording → Do-not-disturb on;
              when it ends → back off (only if we set it) and one digest of what arrived meanwhile.
* Secretary:  every notification is recorded and sorted (needs you / people / system / low) for the "What needs me"
              panel and the bar inbox (secretary.py). Passive D-Bus monitor; nothing leaves the laptop.
* Health:     every 10 min: disk space, failed services, CPU temperature, low memory, backup age → notification
              (each warning at most once every 6 h).
Config: ~/.config/local-ai/config.json → "adapt": {...}
"""
import importlib.util, json, os, re, socket, subprocess, sys, threading, time
from pathlib import Path

HOME = Path.home()
CFG = {"ac_profile": "balanced", "battery_profile": "power-saver", "ac_hz": 165, "battery_hz": 60,
       "dnd_on_fullscreen": True, "quiet_on_call": True, "disk_warn_pct": 90, "temp_warn_c": 95, "backup_warn_days": 7}
try: CFG.update(json.loads((HOME / ".config/local-ai/config.json").read_text()).get("adapt", {}))
except Exception: pass
def _find_hypr():
    """systemd may not have Hyprland's env; locate the live instance ourselves."""
    rt = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    os.environ.setdefault("XDG_RUNTIME_DIR", str(rt))
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig and (rt / "hypr" / sig).exists(): return
    dirs = sorted((d for d in (rt / "hypr").glob("*") if (d / ".socket.sock").exists()), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs:                     # newest instance that actually answers (dead/nested leftovers keep their folders)
        try:
            s = socket.socket(socket.AF_UNIX); s.settimeout(1); s.connect(str(d / ".socket.sock")); s.close()
            os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = d.name; break
        except OSError:
            continue
    os.environ.setdefault("WAYLAND_DISPLAY", "wayland-1")
_find_hypr()
STATE = HOME / ".local/state/setup/adapt.json"; STATE.parent.mkdir(parents=True, exist_ok=True)

def sh(*a, **k): return subprocess.run(a, capture_output=True, text=True, **k)
def notify(title, body, key=None, every=6 * 3600, urgency="normal"):
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    if key and time.time() - st.get(key, 0) < every: return
    sh("notify-send", "-u", urgency, "-a", "KadaOS", title, body)
    if key: st[key] = time.time(); STATE.write_text(json.dumps(st))

# ── power ──
_energy = []   # (time, energy_now) samples for the firmware-bug check
def _rd(p, d=""):
    try: return Path(p).read_text().strip()
    except Exception: return d
def on_ac():
    """True when on the charger. HP firmware sometimes reports the adapter offline and the battery 'Discharging'
    at 0 W while actually on AC — so also judge by what the battery really does."""
    ps = Path("/sys/class/power_supply")
    for p in ps.glob("*"):
        if _rd(p / "type") in ("Mains", "USB") and _rd(p / "online") == "1": return True
    bat = next((p for p in ps.glob("BAT*")), None)
    if not bat: return True
    st = _rd(bat / "status")
    if st in ("Charging", "Full", "Not charging"): return True
    watts = int(_rd(bat / "power_now", "0") or 0) / 1e6
    e = int(_rd(bat / "energy_now", "0") or 0); now = time.time()
    _energy.append((now, e)); _energy[:] = [x for x in _energy if now - x[0] < 600]
    if watts > 0.5: return False                         # really drawing from the battery
    old = [x for x in _energy if now - x[0] >= 90]
    if old: return e >= old[0][1]                         # 0 W and not draining for 90 s+ → on AC (firmware bug)
    return int(_rd(bat / "capacity", "0") or 0) >= 98    # too early to tell: full battery at 0 W → assume AC
def panel():
    try:
        mons = json.loads(sh("hyprctl", "monitors", "-j").stdout)
        return next((m for m in mons if m["name"].startswith("eDP")), None)
    except Exception: return None
def best_hz(modes, width, height, ac):
    """The refresh rate to use: the panel's fastest at its resolution on AC, 60 Hz (or its slowest above it) on battery."""
    rates = sorted({round(float(x.split("@")[1].rstrip("Hz"))) for x in modes or [] if x.startswith(f"{width}x{height}@")})
    if not rates: return CFG["ac_hz"] if ac else CFG["battery_hz"]
    if ac: return rates[-1]
    return next((r for r in rates if r >= CFG["battery_hz"]), rates[0])

def set_hz(ac):
    m = panel()
    hz = best_hz(m.get("availableModes"), m["width"], m["height"], ac) if m else (CFG["ac_hz"] if ac else CFG["battery_hz"])
    if m and round(m["refreshRate"]) != hz:
        sh("hyprctl", "keyword", "monitor", f"{m['name']},{m['width']}x{m['height']}@{hz},{m['x']}x{m['y']},{m['scale']}")
    return hz
def apply_power(ac, announce=True):
    prof = CFG["ac_profile"] if ac else CFG["battery_profile"]
    sh("powerprofilesctl", "set", prof)
    hz = set_hz(ac)
    sh("pkill", "-RTMIN+9", "waybar")
    if announce:
        notify("Plugged in" if ac else "On battery", f"Power mode: {prof} · Screen: {hz} Hz", urgency="low")
def manual_profile():
    """A work profile the user chose (profile ai/battery/present) wins over automatic power switching."""
    try: return json.loads((HOME / ".local/state/myos/profile.json").read_text()).get("name", "auto") != "auto"
    except (OSError, ValueError): return False

def power_loop():
    last = on_ac()
    if not manual_profile(): apply_power(last, announce=False)
    while True:
        time.sleep(4)
        now = on_ac()
        if now != last:
            if manual_profile(): notify("Plugged in" if now else "On battery", "Keeping your profile (Super+Ctrl+P to change)", urgency="low")
            else: apply_power(now)
            last = now

# ── fullscreen → do not disturb ──
def events_loop():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if not sig: return
    path = f"{rt}/hypr/{sig}/.socket2.sock"
    while True:
        try:
            s = socket.socket(socket.AF_UNIX); s.connect(path); buf = b""
            while True:
                chunk = s.recv(4096)
                if not chunk: break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1); line = line.decode(errors="replace")
                    if line.startswith("monitoradded>>") or line.startswith("monitorremoved>>"):
                        time.sleep(0.5); (HOME / ".local/bin/monitors").exists() and sh(str(HOME / ".local/bin/monitors"), "apply")   # saved layout for this set of displays
                    if line.startswith("configreloaded>>") or line.startswith("monitoradded>>") or line.startswith("monitorremoved>>"):
                        time.sleep(0.5); set_hz(on_ac())          # a reload resets the rate to the config value
                    if line.startswith("configreloaded>>"):       # …and drops the Ubuntu mouse/touchpad/keyboard settings
                        sh(str(HOME / ".config/hypr/scripts/gnome-sync.sh"), "apply")
                    if line.startswith("fullscreen>>"):
                        # true fullscreen only (2); Super+M "maximize" (1) also fires this event
                        try: QUIET["fullscreen"] = json.loads(sh("hyprctl", "activewindow", "-j").stdout or "{}").get("fullscreen", 0) == 2
                        except ValueError: QUIET["fullscreen"] = line.endswith("1")
                        reconcile()
        except Exception:
            time.sleep(3)

# ── quiet mode + digest ──
QUIET = {"fullscreen": False, "call": False}
_quiet = {"ours": False, "since": 0.0, "overridden": False}
_qlock = threading.Lock()
CALL_APPS = re.compile(r"chrom|firefox|teams|zoom|discord|slack|skype|meet|webex|telegram|signal|whatsapp|obs", re.I)

def _secretary():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import secretary; return secretary

def _probe():
    """The bar's privacy probe (mic / camera / recorder), loaded once."""
    if not hasattr(_probe, "m"):
        p = HOME / ".config/hypr/scripts/bar-status.py"
        spec = importlib.util.spec_from_file_location("bar_status", p); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        _probe.m = m
    return _probe.m

_slow = {}
PRIVACY = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "myos-privacy.json"   # shared with the bar

def in_call():
    """One mic/camera/recorder scan; also saved for the bar's privacy dot so it doesn't scan again."""
    m = _probe()
    mic = m._mic_apps()                                   # cheap: kernel flag; PipeWire only while recording
    if time.time() - _slow.get("t", 0) > 30:              # camera/recorder/screen-share scans: every 30 s (calls also use the mic, seen in 5 s)
        _slow.update(t=time.time(), cam=m._camera_apps(), rec=m._recorders() + m._screen_apps())
    cam, rec = _slow["cam"], _slow["rec"]
    try:
        tmp = PRIVACY.with_suffix(".tmp"); tmp.write_text(json.dumps({"t": time.time(), "mic": mic, "cam": cam, "rec": rec})); os.replace(tmp, PRIVACY)
    except OSError: pass
    return bool(cam or rec or [a for a in mic if CALL_APPS.search(a)])

def reconcile():
    reasons = [r for r, on in (("fullscreen", QUIET["fullscreen"] and CFG["dnd_on_fullscreen"]), ("call", QUIET["call"] and CFG["quiet_on_call"])) if on]
    with _qlock:
        if not reasons and not _quiet["ours"]:
            _quiet["overridden"] = False; return         # the common case: nothing to do, no subprocesses
        dnd = sh("swaync-client", "-D").stdout.strip() == "true"
        if not reasons: _quiet["overridden"] = False      # situation over: next time we may act again
        if reasons and not dnd and not _quiet["ours"] and not _quiet["overridden"]:
            sh("swaync-client", "-dn"); _quiet.update(ours=True, since=time.time()); sh("pkill", "-RTMIN+13", "waybar")
        elif _quiet["ours"] and not dnd:
            _quiet.update(ours=False, overridden=True)   # you turned it off yourself: leave it off until this ends
        elif _quiet["ours"] and not reasons:
            sh("swaync-client", "-df"); _quiet["ours"] = False
            try:
                sec = _secretary(); since = _quiet["since"]
                d = sec.digest(sec.notifications(since), max(1, round((time.time() - since) / 60)))
                if d: sh("notify-send", "-a", "KadaOS", "-i", "view-list-symbolic", d[0], d[1] + "\nOpen: Super+Y")
            except Exception as e: print("digest:", e, flush=True)

def quiet_loop():
    while True:
        try:
            QUIET["call"] = in_call()                    # scan always: the bar's privacy dot reads the result
            reconcile()
        except Exception as e: print("quiet:", e, flush=True)
        time.sleep(5)

# ── secretary: record every notification ──
def notif_loop():
    """Passive monitor of org.freedesktop.Notifications.Notify on the session bus -> secretary log."""
    import gi; gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    sec = _secretary()
    addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
    conn = Gio.DBusConnection.new_for_address_sync(addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
                                                   Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus.Monitoring", "BecomeMonitor",
                   GLib.Variant("(asu)", (["type='method_call',interface='org.freedesktop.Notifications',member='Notify'"], 0)),
                   None, Gio.DBusCallFlags.NONE, -1, None)
    def on_msg(_c, msg, _incoming):
        try:
            if msg.get_member() == "Notify" and msg.get_body() is not None:
                app, _rid, _icon, summary, body, _acts, hints, _t = msg.get_body().unpack()
                if app != "KadaOS":                         # our own popups (agents, digest, warnings) live elsewhere
                    sec.record(app, summary, body, int(hints.get("urgency", 1)))
                    subprocess.Popen(["pkill", "-RTMIN+13", "waybar"])
        except Exception as e: print("notif:", e, flush=True)
        return None
    conn.add_filter(on_msg)
    loop = GLib.MainLoop()
    conn.connect("closed", lambda *_: loop.quit())   # bus dropped: return, and supervised() reconnects
    loop.run()

def supervised(fn):
    """Restart a loop that crashed (a bus hiccup must not kill the secretary for the whole session)."""
    def run():
        while True:
            try: fn()
            except Exception as e: print(f"{fn.__name__}:", e, flush=True)
            time.sleep(5)
    return run

# ── health ──
def health_loop():
    time.sleep(90)
    while True:
        try:
            st = os.statvfs("/"); used = 100 - st.f_bavail * 100 / st.f_blocks
            if used > CFG["disk_warn_pct"]:
                notify("Disk almost full", f"/ is {used:.0f}% used. Try: docker system prune, or clean ~/Downloads.", "disk", urgency="critical")
            failed = (sh("systemctl", "--failed", "--no-legend", "--plain").stdout + sh("systemctl", "--user", "--failed", "--no-legend", "--plain").stdout).split("\n")
            failed = [l.split()[0] for l in failed if l.strip()]
            if failed: notify("Service failed", ", ".join(failed[:4]) + "\nCheck: systemctl status " + failed[0], "failed:" + ",".join(failed))
            temps = []
            for z in Path("/sys/class/thermal").glob("thermal_zone*"):
                try:
                    if (z / "type").read_text().strip() in ("x86_pkg_temp", "TCPU", "acpitz"): temps.append(int((z / "temp").read_text()) / 1000)
                except Exception: pass
            if temps and max(temps) >= CFG["temp_warn_c"]:
                notify("Running hot", f"CPU at {max(temps):.0f}°C. Check vents / switch to balanced (Super+Shift+P).", "temp", every=1800, urgency="critical")
            mi = dict(l.split(":")[0:2] for l in Path("/proc/meminfo").read_text().splitlines())
            avail = int(mi["MemAvailable"].split()[0]) / int(mi["MemTotal"].split()[0])
            if avail < 0.07: notify("Memory nearly full", f"Only {avail * 100:.0f}% RAM free. Close heavy apps (btop: Ctrl+Shift+Esc).", "mem", every=1800)
            marker = HOME / ".local/state/setup/last-backup"
            if marker.exists():
                days = (time.time() - marker.stat().st_mtime) / 86400
                if days > CFG["backup_warn_days"]: notify("Backup overdue", f"Last backup {days:.0f} days ago. Plug in the HDD and run ~/Scripts/backup.sh", "backup", every=24 * 3600)
        except Exception as e:
            print("health:", e, flush=True)
        time.sleep(600)

if __name__ == "__main__":
    for f in (power_loop, events_loop, health_loop, quiet_loop, notif_loop):
        threading.Thread(target=supervised(f), daemon=True, name=f.__name__).start()
    while True: time.sleep(3600)
