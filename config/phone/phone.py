#!/usr/bin/env python3
"""phone: your Android phone and this laptop, one tool.

  phone                  status: connected?, battery, alerts
  phone setup            once, with the phone on a USB cable: apps, battery settings, clipboard, pairing, alerts
  phone send FILE|URL…   to the phone (Wi-Fi via KDE Connect, else the USB cable)   ·   phone send -t "text"
  phone clip             laptop clipboard → phone now (normally automatic)
  phone find             ring the phone (even on silent)
  phone mirror           phone screen in a window (USB cable; clipboard syncs both ways)
  phone get [N]          newest N files from the phone's Download folder (USB cable)
  phone doctor           what's wrong and the fix
  phone push "message"   alert to the phone anywhere (ntfy)
  phone set push away|always|off · phone set detail short|private|full

Three channels that cover for each other: KDE Connect (home Wi-Fi), the USB cable (adb, always works) and ntfy
(alerts anywhere; also tells you when the KDE Connect link died). Stdlib only.
"""
import json, os, re, shutil, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

HOME = Path.home()
CFG = HOME / ".config/myos/phone.json"
STATE = HOME / ".local/state/myos/phone.json"
DOWNLOADS = HOME / "Downloads"
DEFAULTS = {"server": "https://ntfy.sh", "topic": "", "push": "away", "detail": "short", "kde_id": "", "adb_serial": ""}
KDE_PKG, NTFY_PKG = "org.kde.kdeconnect_tp", "io.heckel.ntfy"
LINK_DOWN_AFTER = 15 * 60          # phone unreachable this long on the network it was last seen on → alert
QUEUE_MAX, QUEUE_AGE = 50, 24 * 3600
OK, FAIL, USAGE = 0, 1, 2


class Fail(Exception):
    def __init__(self, msg, code=FAIL): super().__init__(msg); self.code = code


def _c(code): return (lambda s: f"\033[{code}m{s}\033[0m") if sys.stdout.isatty() else (lambda s: s)
good, bad, warn, dim, bold = _c("32"), _c("31"), _c("33"), _c("2"), _c("1")
def say(*a): print(*a, flush=True)
def have(cmd): return shutil.which(cmd) is not None


def run(*argv, timeout=15, input=None):
    try: return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=input,
                               stdin=None if input is not None else subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(argv, 124, "", str(e))


def load(path, default):
    try: return {**default, **json.loads(Path(path).read_text())}
    except (OSError, ValueError): return dict(default)


def save(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps(data, indent=1)); os.chmod(tmp, 0o600); os.replace(tmp, path)


def config(): return load(CFG, DEFAULTS)
def state(): return load(STATE, {"seen": 0, "seen_net": "", "queue": [], "last_push": {}})


# ───────────────────────── ntfy (alerts anywhere) ─────────────────────────
TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def ntfy_message(title, body, detail):
    """What leaves the laptop. ntfy.sh topics are public: by default only the short title, never output or addresses."""
    if detail == "private": return "KadaOS: a new alert. Open the laptop to see it."
    if detail == "full" and body: return f"{title}\n{body}"[:1000]
    return title[:200]


def ntfy_send(cfg, message, priority=3, tags=(), timeout=8):
    """POST JSON (UTF-8 safe, unlike headers). Raises OSError on network failure."""
    data = json.dumps({"topic": cfg["topic"], "message": message, "priority": priority, "tags": list(tags)}).encode()
    req = urllib.request.Request(cfg["server"].rstrip("/"), data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status >= 300: raise OSError(f"ntfy answered {r.status}")


def push(message, priority=3, tags=(), cfg=None, now=None):
    """Send now, or queue for the next try (no internet). Returns 'sent' | 'queued' | 'off'."""
    cfg = cfg or config(); now = time.time() if now is None else now
    if not cfg.get("topic"): return "off"
    st = state()
    try:
        ntfy_send(cfg, message, priority, tags); st["last_push"] = {"t": now, "ok": True}; result = "sent"
    except (OSError, urllib.error.URLError) as e:
        st["queue"] = (st["queue"] + [{"t": now, "m": message, "p": priority, "tags": list(tags)}])[-QUEUE_MAX:]
        st["last_push"] = {"t": now, "ok": False, "error": str(e)[:120]}; result = "queued"
    save(STATE, st)
    return result


def flush(cfg=None, now=None):
    """Retry queued alerts, oldest first; drop ones older than a day. Returns how many were sent."""
    cfg = cfg or config(); now = time.time() if now is None else now
    st = state(); q = [m for m in st["queue"] if now - m["t"] < QUEUE_AGE]; sent = 0
    while q and cfg.get("topic"):
        try: ntfy_send(cfg, q[0]["m"], q[0].get("p", 3), q[0].get("tags", ()))
        except (OSError, urllib.error.URLError): break
        q.pop(0); sent += 1
    st["queue"] = q; save(STATE, st)
    return sent


def away():
    """You're away from the laptop when its screen is locked."""
    return run("pgrep", "-x", "hyprlock", timeout=3).returncode == 0


def alert(title, body="", urgent=False, cfg=None, is_away=None):
    """A watcher problem → the phone, following the user's rule (push = away | always | off)."""
    cfg = cfg or config()
    rule = cfg.get("push", "away")
    if rule == "off" or not cfg.get("topic"): return "off"
    if rule == "away" and not urgent and not (away() if is_away is None else is_away): return "here"
    return push(ntfy_message(title, body, cfg.get("detail", "short")), 4 if urgent else 3, ["warning"] if urgent else [], cfg)


# ───────────────────────── KDE Connect (home Wi-Fi) ─────────────────────────
LIST_RE = re.compile(r"^- (.+): (\S+) \((.+)\)$")


def kde(*args, timeout=15): return run("kdeconnect-cli", *args, timeout=timeout)


def parse_kde_list(text):
    """`kdeconnect-cli -l` lines '- Name: id (paired and reachable)' → [{id, name, paired, reachable}]."""
    out = []
    for line in (text or "").splitlines():
        m = LIST_RE.match(line.strip())
        if m: out.append({"name": m[1], "id": m[2], "paired": "paired" in m[3] and "unpaired" not in m[3],
                          "reachable": "reachable" in m[3] and "unreachable" not in m[3]})
    return out


def kde_devices():
    """Known devices (starts the daemon through D-Bus if it isn't running). [] if KDE Connect isn't installed."""
    if not have("kdeconnect-cli"): return []
    return parse_kde_list(kde("-l").stdout)


def kde_phone(cfg=None, devs=None):
    """The paired phone: the chosen one, else the only paired device."""
    cfg = cfg or config(); devs = kde_devices() if devs is None else devs
    paired = [d for d in devs if d["paired"]]
    return next((d for d in paired if d["id"] == cfg.get("kde_id")), paired[0] if len(paired) == 1 else None)


def kde_battery(dev_id):
    """(percent, charging) from KDE Connect's battery plugin over D-Bus, or (None, None)."""
    r = run("gdbus", "call", "--session", "--dest", "org.kde.kdeconnect", "--object-path",
            f"/modules/kdeconnect/devices/{dev_id}/battery", "--method", "org.freedesktop.DBus.Properties.GetAll",
            "org.kde.kdeconnect.device.battery", timeout=4)
    m, c = re.search(r"'charge': <(-?\d+)>", r.stdout), re.search(r"'isCharging': <(true|false)>", r.stdout)
    if r.returncode or not m or int(m[1]) < 0: return None, None
    return int(m[1]), (c[1] == "true") if c else None


def parse_peer(ss_text, mine=()):
    """The phone's address from kdeconnectd's established TCP connection (`ss -tnpH`); None if there's none."""
    for line in (ss_text or "").splitlines():
        if "kdeconnect" not in line: continue
        f = line.split()
        if len(f) < 5: continue
        for addr in (f[4], f[3]):                         # peer column first
            ip = addr.rsplit(":", 1)[0].strip("[]").removeprefix("::ffff:")
            if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip) and ip not in mine and not ip.startswith("127."): return ip
    return None


def local_ips():
    return set(re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", run("ip", "-4", "-o", "addr", timeout=3).stdout))


def laptop_ip():
    """This laptop's address on the network it uses to reach the internet (what the phone should call)."""
    m = re.search(r"src (\S+)", run("ip", "-4", "route", "get", "1.1.1.1", timeout=3).stdout)
    return m[1] if m else ""


def neigh_mac(ip):
    m = re.search(r"lladdr (\S+)", run("ip", "neigh", "show", ip, timeout=3).stdout)
    return m[1].lower() if m else ""


def ip_for_mac(mac):
    for line in run("ip", "-4", "neigh", timeout=3).stdout.splitlines():
        if f"lladdr {mac}" in line.lower(): return line.split()[0]
    return ""


def remember_peer(st, net):
    """While connected: note the phone's IP + Wi-Fi MAC for this network (to call it directly when broadcast fails)."""
    ip = parse_peer(run("ss", "-tnpH", "state", "established", timeout=3).stdout, local_ips())
    if ip and net:
        st.setdefault("peers", {})[net] = {"ip": ip, "mac": neigh_mac(ip) or st.get("peers", {}).get(net, {}).get("mac", "")}
    return ip


def set_custom_devices(ips):
    """KDE Connect's customDevices (D-Bus): addresses it announces itself to directly, for networks that drop broadcast."""
    v = "[" + ", ".join(repr(i) for i in ips) + "]" if ips else "@as []"
    return run("gdbus", "call", "--session", "--dest", "org.kde.kdeconnect", "--object-path", "/modules/kdeconnect",
               "--method", "org.freedesktop.DBus.Properties.Set", "org.kde.kdeconnect.daemon", "customDevices", f"<{v}>", timeout=5).returncode == 0


def wake(cfg=None, wait=4):
    """Try to get the phone back: call it at its last address on this network, then search. Returns the phone dict."""
    cfg = cfg or config(); st = state(); net = net_id()
    peer = st.get("peers", {}).get(net, {})
    ip = (ip_for_mac(peer["mac"]) if peer.get("mac") else "") or peer.get("ip", "")
    if ip: set_custom_devices([ip])
    kde("--refresh", timeout=10)
    for _ in range(max(1, wait)):
        ph = kde_phone(cfg)
        if not ph or ph["reachable"]: return ph
        time.sleep(1)
    return kde_phone(cfg)


# ───────────────────────── USB cable (adb) ─────────────────────────
def adb_devices():
    """[{serial, state, model}] from `adb devices -l`."""
    if not have("adb"): return []
    out = []
    for line in run("adb", "devices", "-l", timeout=8).stdout.splitlines()[1:]:
        p = line.split()
        if len(p) >= 2:
            out.append({"serial": p[0], "state": p[1], "model": next((x[6:] for x in p if x.startswith("model:")), "")})
    return out


def adb_phone(cfg=None, devs=None):
    """The phone on the cable: the chosen serial, else the only device (the Android tablet also uses adb, so pick once)."""
    cfg = cfg or config(); devs = adb_devices() if devs is None else devs
    ready = [d for d in devs if d["state"] == "device"]
    return next((d for d in ready if d["serial"] == cfg.get("adb_serial")), ready[0] if len(ready) == 1 and not cfg.get("adb_serial") else None)


def adb(serial, *args, timeout=30): return run("adb", "-s", serial, *args, timeout=timeout)


def harden_steps(packages):
    """adb shell commands that stop Android/MIUI from killing the apps, and let KDE Connect read the clipboard."""
    steps = []
    for pkg in packages:
        steps += [(f"{pkg}: never put to sleep (Doze)", f"dumpsys deviceidle whitelist +{pkg}"),
                  (f"{pkg}: may run in the background", f"cmd appops set {pkg} RUN_IN_BACKGROUND allow"),
                  (f"{pkg}: may run in the background (all)", f"cmd appops set {pkg} RUN_ANY_IN_BACKGROUND allow"),
                  (f"{pkg}: keep permissions when unused", f"cmd appops set {pkg} AUTO_REVOKE_PERMISSIONS_IF_UNUSED ignore")]
    if KDE_PKG in packages:
        steps += [("clipboard: phone → laptop automatic", f"pm grant {KDE_PKG} android.permission.READ_LOGS"),
                  ("clipboard: helper window", f"cmd appops set {KDE_PKG} SYSTEM_ALERT_WINDOW allow")]
    return steps


def installed_packages(serial):
    return set(re.findall(r"^package:(\S+)", adb(serial, "shell", "pm", "list", "packages").stdout, re.M))


# ───────────────────────── network identity (for the link watchdog) ─────────────────────────
def net_id():
    """Wi-Fi name, or the default route's interface: enough to know 'same place as last time'."""
    for line in run("nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi", timeout=5).stdout.splitlines():
        if line.startswith("yes:"): return "wifi:" + line[4:]
    m = re.search(r"dev (\S+)", run("ip", "-4", "route", "show", "default", timeout=3).stdout)
    return f"if:{m[1]}" if m else ""


def link_problem(reachable, st, net, now):
    """Update st (seen, seen_net); return a problem when the paired phone has been gone LINK_DOWN_AFTER on its network."""
    if reachable:
        st["seen"], st["seen_net"] = now, net
        return None
    if st.get("seen") and net and net == st.get("seen_net") and now - st["seen"] >= LINK_DOWN_AFTER:
        return ("Phone link is down",
                "KDE Connect can't reach the phone. Open KDE Connect on the phone once; if it keeps happening, run `phone doctor`.")
    return None


def tick(now=None):
    """Every 5 minutes (the assistant's watcher): retry queued alerts, wake the link, watch it. Returns {key: [title, body]}."""
    now = time.time() if now is None else now
    cfg, out = config(), {}
    flush(cfg, now)
    if not have("kdeconnect-cli"): return out
    devs = kde_devices()
    ph = kde_phone(cfg, devs)
    if not ph: return out
    if not ph["reachable"]: ph = wake(cfg) or ph
    st, net = state(), net_id()
    if ph["reachable"]: remember_peer(st, net)
    p = link_problem(ph["reachable"], st, net, now)
    save(STATE, st)
    if p: out[f"phone-link:{ph['id']}"] = list(p)
    return out


# ───────────────────────── commands ─────────────────────────
def status():
    cfg = config(); ph = kde_phone(cfg); cable = adb_phone(cfg); st = state()
    if ph and ph["reachable"]:
        st["seen"], st["seen_net"] = time.time(), net_id(); remember_peer(st, st["seen_net"]); save(STATE, st)
    bat, charging = kde_battery(ph["id"]) if ph and ph["reachable"] else (None, None)
    return {"kdeconnect": have("kdeconnect-cli"), "phone": ph, "battery": bat, "charging": charging,
            "cable": cable, "alerts": {"topic": cfg["topic"], "rule": cfg["push"], "detail": cfg["detail"],
                                       "queued": len(st["queue"]), "last": st["last_push"]},
            "seen": st.get("seen") or None, "laptop_ip": laptop_ip()}


def cmd_status(args):
    s = status()
    if "--json" in args: print(json.dumps(s, indent=1)); return OK
    ph = s["phone"]
    if ph and ph["reachable"]:
        say(good("● ") + bold(ph["name"]) + good("  connected over Wi-Fi") + (f"  ·  battery {s['battery']}%" + (" charging" if s["charging"] else "") if s["battery"] is not None else ""))
    elif ph:
        when = time.strftime("%H:%M %d %b", time.localtime(s["seen"])) if s["seen"] else "not yet"
        say(warn("○ ") + bold(ph["name"]) + warn("  not reachable") + dim(f"  (last seen {when})"))
    elif s["kdeconnect"]:
        say(warn("○ No phone paired yet.") + "  Run: phone setup")
    else:
        say(warn("○ KDE Connect isn't installed.") + "  Run: phone setup")
    if s["cable"]: say(good("● ") + f"USB cable: {s['cable']['model'] or s['cable']['serial']}")
    a = s["alerts"]
    if a["topic"]:
        say(f"Alerts: ntfy topic {bold(a['topic'])} · sent {dict(away='when the laptop is locked', always='always', off='never')[a['rule']]}"
            + (warn(f" · {a['queued']} waiting for internet") if a["queued"] else ""))
    else: say(dim("Alerts to the phone: off (phone setup)"))
    return OK


URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://")


def send_targets(items):
    """Files become absolute paths (must exist); URLs pass through."""
    out = [i if URL_RE.match(i) else str(Path(i).expanduser().resolve()) for i in items]
    missing = [t for t in out if not URL_RE.match(t) and not Path(t).exists()]
    if missing: raise Fail(f"Not found: {', '.join(missing)}", USAGE)
    return out


def cmd_send(args):
    text = " ".join(args[1:]).strip() if args[:1] in (["-t"], ["--text"]) else None
    if text == "" or (text is None and not args): raise Fail('Usage: phone send FILE… | URL | -t "text"', USAGE)
    targets = [] if text is not None else send_targets(args)
    cfg = config(); ph = kde_phone(cfg)
    if ph and not ph["reachable"]: ph = wake(cfg) or ph
    if ph and ph["reachable"]:
        rs = [kde("-d", ph["id"], "--share-text", text)] if text is not None else [kde("-d", ph["id"], "--share", t, timeout=60) for t in targets]
        bad_ = [r for r in rs if r.returncode]
        if not bad_: say(good(f"✓ sent to {ph['name']} over Wi-Fi")); return OK
        say(warn(f"Wi-Fi send failed ({(bad_[0].stderr or bad_[0].stdout).strip()[:120]}); trying the cable…"))
    cable = adb_phone(cfg)
    if cable and text is None:
        for t in targets:
            r = (adb(cable["serial"], "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", t) if URL_RE.match(t)
                 else adb(cable["serial"], "push", t, "/sdcard/Download/", timeout=600))
            if r.returncode: raise Fail(f"USB send failed: {(r.stderr or r.stdout).strip()[-200:]}")
        say(good("✓ sent over the USB cable") + dim(" (files are in the phone's Download folder)")); return OK
    raise Fail("The phone isn't reachable: same Wi-Fi as the laptop? KDE Connect open on the phone? "
               "Or plug in the USB cable. `phone doctor` checks everything.")


def cmd_clip(args):
    ph = kde_phone()
    if ph and not ph["reachable"]: ph = wake() or ph
    if not (ph and ph["reachable"]): raise Fail("The phone isn't connected over Wi-Fi (phone doctor).")
    r = kde("-d", ph["id"], "--send-clipboard")
    if r.returncode: raise Fail((r.stderr or r.stdout).strip() or "KDE Connect refused")
    say(good("✓ clipboard sent")); return OK


def cmd_find(args):
    ph = kde_phone()
    if ph and not ph["reachable"]: ph = wake() or ph
    if not (ph and ph["reachable"]): raise Fail("The phone isn't connected over Wi-Fi, so it can't ring (phone doctor).")
    r = kde("-d", ph["id"], "--ring")
    if r.returncode: raise Fail((r.stderr or r.stdout).strip() or "KDE Connect refused")
    say(good(f"✓ {ph['name']} is ringing")); return OK


def cmd_mirror(args):
    cable = adb_phone()
    if not cable: raise Fail("Plug the phone in with a USB cable (USB debugging on) to mirror it.")
    if not have("scrcpy"): raise Fail("scrcpy isn't installed.")
    os.execvp("scrcpy", ["scrcpy", "-s", cable["serial"], "--window-title", "Phone", "--stay-awake", "--turn-screen-off"])


def cmd_get(args):
    n = int(args[0]) if args and args[0].isdigit() else 1
    cable = adb_phone()
    if not cable: raise Fail("Plug the phone in with a USB cable. (Over Wi-Fi: Share → KDE Connect on the phone.)")
    names = [l for l in adb(cable["serial"], "shell", "ls", "-t", "/sdcard/Download/").stdout.splitlines() if l.strip()][:n]
    if not names: say("The phone's Download folder is empty."); return OK
    dst = DOWNLOADS / "Phone"; dst.mkdir(parents=True, exist_ok=True)
    for name in names:
        r = adb(cable["serial"], "pull", f"/sdcard/Download/{name}", str(dst), timeout=600)
        say((good("✓ ") if r.returncode == 0 else bad("✗ ")) + name)
    say(dim(f"in {dst}")); return OK


def cmd_push(args):
    msg = " ".join(args).strip()
    if not msg: raise Fail('Usage: phone push "message"', USAGE)
    r = push(msg[:1000])
    if r == "off": raise Fail("Alerts aren't set up: phone setup")
    say(good("✓ sent") if r == "sent" else warn("No internet: queued, it goes out when the laptop is back online.")); return OK


def cmd_alert(args):        # internal: the watcher
    if not args: return USAGE
    print(alert(args[0], args[1] if len(args) > 1 else "", "--urgent" in args)); return OK


def cmd_tick(args):         # internal: the watcher
    print(json.dumps(tick(), indent=1)); return OK


def cmd_doctor(args):
    cfg, fails = config(), 0
    def row(ok, text, fix=""):
        nonlocal fails; fails += not ok
        say((good("✓ ") if ok else bad("✗ ")) + text + (f"\n    {dim('fix:')} {fix}" if fix and not ok else ""))
    row(have("kdeconnect-cli"), "KDE Connect installed on the laptop", "! bash scripts/phase13-phone.sh   (then: phone setup)")
    if have("kdeconnect-cli"):
        devs = kde_devices(); ph = kde_phone(cfg, devs)
        row(bool(devs) or kde("-l").returncode == 0, "KDE Connect is running", "log out and in, or: kdeconnectd &")
        fw = run("systemctl", "is-active", "ufw", timeout=3).stdout.strip() == "active"
        if fw: say(dim("  · firewall is on: ports 1714–1764 must be open (phase13-phone.sh does it)"))
        row(bool(ph), "phone paired", "phone setup")
        if ph:
            row(ph["reachable"], f"{ph['name']} reachable over Wi-Fi",
                "on the phone: open KDE Connect · same Wi-Fi as the laptop? · guest/campus Wi-Fi often blocks devices "
                "from seeing each other: on the phone, KDE Connect → ⋮ → Add devices by IP → " + (laptop_ip() or "this laptop's IP")
                + " · or use the USB cable / your hotspot · keeps dying? phone setup (battery settings)")
    cable = adb_phone(cfg)
    say((good("✓ ") if cable else dim("· ")) + ("USB cable: " + (cable["model"] or cable["serial"]) if cable else "USB cable: not plugged in (optional)"))
    row(bool(cfg["topic"]), f"alerts to the phone (ntfy topic {cfg['topic'] or '—'})", "phone setup")
    if cfg["topic"]:
        try: urllib.request.urlopen(cfg["server"], timeout=6); row(True, f"{cfg['server']} reachable")
        except (OSError, urllib.error.URLError) as e: row(False, f"{cfg['server']} reachable ({e})", "check the internet connection")
        q = len(state()["queue"])
        if q: say(warn(f"  · {q} alert(s) waiting to be sent"))
    return FAIL if fails else OK


def ask(prompt, default=True):
    if not sys.stdin.isatty(): return default
    a = input(f"{prompt} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not a else a.startswith("y")


def cmd_setup(args):
    """One guided pass. Most of it runs over the USB cable, so the phone side is taps only."""
    cfg = config()
    topic = next((a.split("=", 1)[1] for a in args if a.startswith("--topic=")), "") or cfg["topic"]
    say(bold("1 · Alerts to your phone (ntfy, works anywhere)"))
    if not topic and sys.stdin.isatty(): topic = input("  ntfy topic name (letters, digits, - _): ").strip()
    if topic:
        if not TOPIC_RE.match(topic): raise Fail("Topic: letters, digits, - and _ only (max 64).", USAGE)
        cfg["topic"] = topic; save(CFG, cfg)
        say(f"  topic {bold(topic)} · only short titles are sent (no output, IPs or file names)")
    say(bold("\n2 · The phone on a USB cable (once)"))
    say("  On the phone: Settings → About phone → tap 'OS version' 7× → Additional settings → Developer options →\n"
        "  USB debugging ON (and 'USB debugging (Security settings)' ON, for the clipboard). Plug in, tap Allow.")
    cable = adb_phone(cfg)
    if not cable and sys.stdin.isatty():
        input("  Press Enter when the phone is plugged in and allowed… ")
        devs = adb_devices(); ready = [d for d in devs if d["state"] == "device"]
        if len(ready) > 1:
            for i, d in enumerate(ready, 1): say(f"   {i}. {d['model'] or d['serial']}")
            pick = input("  Which one is the phone? ").strip()
            if pick.isdigit() and 1 <= int(pick) <= len(ready): cable = ready[int(pick) - 1]
        else: cable = adb_phone(cfg, devs)
        unauth = [d for d in devs if d["state"] == "unauthorized"]
        if not cable and unauth: say(warn("  The phone is waiting: tap 'Allow' on its screen, then run phone setup again."))
    if cable:
        cfg["adb_serial"] = cable["serial"]; save(CFG, cfg)
        s = cable["serial"]; pk = installed_packages(s)
        for pkg, label in ((KDE_PKG, "KDE Connect"), (NTFY_PKG, "ntfy")):
            if pkg == NTFY_PKG and not cfg["topic"]: continue
            if pkg not in pk:
                adb(s, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"market://details?id={pkg}")
                say(f"  → the phone shows {label} in the Play Store: tap Install")
        if sys.stdin.isatty() and not {KDE_PKG, NTFY_PKG} <= pk: input("  Press Enter when installed… ")
        pk = installed_packages(s)
        for label, cmd in harden_steps([p for p in (KDE_PKG, NTFY_PKG) if p in pk]):
            r = adb(s, "shell", cmd)
            ok = r.returncode == 0 and not re.search(r"Exception|Error|not allowed|denied", r.stdout + r.stderr, re.I)
            say(("  " + good("✓ ") if ok else "  " + warn("· ")) + label + ("" if ok else dim("  (skipped: MIUI blocked it)")))
        if NTFY_PKG in pk and cfg["topic"]:
            adb(s, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", f"ntfy://{cfg['server'].split('://')[-1]}/{cfg['topic']}")
            say(f"  → the phone opens ntfy on topic {cfg['topic']}: tap Subscribe")
        adb(s, "shell", "am", "start", "-n", "com.miui.securitycenter/com.miui.permcenter.autostart.AutoStartManagementActivity")
        say("  → the phone shows Autostart: turn ON KDE Connect" + (" and ntfy" if NTFY_PKG in pk else "")
            + ".\n    Then: long-press KDE Connect → App info → Battery saver → No restrictions. (MIUI's own killer; adb can't set it.)")
        if sys.stdin.isatty(): input("  Press Enter when done… ")
    else:
        say(dim("  skipped (no cable). Run phone setup again with the phone plugged in for the battery and clipboard settings."))
    say(bold("\n3 · Pair over Wi-Fi"))
    if not have("kdeconnect-cli"):
        say(warn("  KDE Connect isn't installed on the laptop: ! bash scripts/phase13-phone.sh, then phone setup again."))
    else:
        devs = kde_devices(); ph = kde_phone(cfg, devs)
        if not ph:
            say("  On the phone open KDE Connect (same Wi-Fi as the laptop)…")
            for _ in range(20):
                devs = [d for d in kde_devices() if d["reachable"]]
                if devs: break
                kde("--refresh"); time.sleep(3)
            if devs:
                d = devs[0] if len(devs) == 1 else devs[int(input("  " + "  ".join(f"{i}. {x['name']}" for i, x in enumerate(devs, 1)) + " → ") or 1) - 1]
                kde("-d", d["id"], "--pair")
                say(f"  → tap Accept on {d['name']}")
                for _ in range(30):
                    ph = kde_phone({**cfg, "kde_id": d["id"]})
                    if ph and ph["id"] == d["id"]: break
                    time.sleep(2)
            else: say(warn("  The phone didn't show up. Same Wi-Fi? Guest/campus Wi-Fi blocks this: try at home or on your hotspot."))
        if ph:
            cfg["kde_id"] = ph["id"]; save(CFG, cfg); say(good(f"  ✓ paired with {ph['name']}"))
    if cfg["topic"]:
        r = push("KadaOS: alerts from your laptop will arrive here.", cfg=cfg)
        say(("\n" + good("✓ test alert sent: check the phone")) if r == "sent" else warn("\nTest alert queued (no internet)."))
    say(dim("\nDaily use: phone send FILE · Files → right-click → Send to phone · on the phone: Share → KDE Connect."))
    return OK


PHONE_ICON = "\U000F011C"


def bar_json(ph, bat=None, charging=None, seen=0):
    """The top-bar item: hidden until paired; dim when the phone is away; battery shown only when it's low."""
    if not ph: return {"text": "", "class": "none", "tooltip": ""}
    if not ph["reachable"]:
        when = time.strftime("%H:%M", time.localtime(seen)) if seen else "a while ago"
        return {"text": PHONE_ICON, "class": "away", "tooltip": f"{ph['name']}: not reachable (last seen {when})\nClick for the phone panel"}
    low = bat is not None and bat <= 20 and not charging
    batt = f"{bat}%" + (" charging" if charging else "") if bat is not None else "battery unknown"
    return {"text": PHONE_ICON + (f" {bat}%" if low else ""), "class": "low" if low else "on",
            "tooltip": f"{ph['name']}: connected · {batt}\nClick for the phone panel"}


def cmd_bar(args):          # internal: the top bar (every 30 s). KDE Connect only: no adb here, it's too slow for a bar
    ph = kde_phone() if have("kdeconnect-cli") else None
    if ph and ph["reachable"]:
        st = state(); st["seen"] = time.time(); st["seen_net"] = net_id(); remember_peer(st, st["seen_net"]); save(STATE, st)
    bat, charging = kde_battery(ph["id"]) if ph and ph["reachable"] else (None, None)
    print(json.dumps(bar_json(ph, bat, charging, state().get("seen", 0)), ensure_ascii=False)); return OK


def set_option(key, value):
    """Change one alert setting (the panel): push = away|always|off, detail = short|private|full."""
    allowed = {"push": ("away", "always", "off"), "detail": ("short", "private", "full")}
    if value not in allowed.get(key, ()): raise Fail(f"{key} must be one of {', '.join(allowed.get(key, ()))}", USAGE)
    cfg = config(); cfg[key] = value; save(CFG, cfg)


def cmd_set(args):
    if len(args) != 2: raise Fail("Usage: phone set push away|always|off · phone set detail short|private|full", USAGE)
    set_option(*args); say(good(f"✓ {args[0]} = {args[1]}")); return OK


COMMANDS = {"status": cmd_status, "send": cmd_send, "clip": cmd_clip, "find": cmd_find, "ring": cmd_find, "mirror": cmd_mirror,
            "get": cmd_get, "push": cmd_push, "doctor": cmd_doctor, "setup": cmd_setup, "set": cmd_set, "_alert": cmd_alert, "_tick": cmd_tick, "_bar": cmd_bar}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"], ["help"]): print(__doc__.strip()); return OK
    cmd, args = (argv[0], argv[1:]) if argv and argv[0] in COMMANDS else ("status", argv)
    try: return COMMANDS[cmd](args) or OK
    except Fail as e: print(bad("✗ ") + str(e), file=sys.stderr); return e.code
    except KeyboardInterrupt: return 130


if __name__ == "__main__":
    sys.exit(main())
