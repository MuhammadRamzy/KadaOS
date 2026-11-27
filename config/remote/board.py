#!/usr/bin/env python3
"""board — your devices over SSH: Raspberry Pis, Jetsons, boards, servers, VMs.

  board                         pick a device, then an action
  board add [NAME] [HOST]       add a device (copies your key, learns what it is)
  board ls | info | doctor      what's there, details, what's wrong and how to fix it
  board ssh NAME                terminal on the device (inside tmux, survives Wi-Fi drops)
  board code | files | mount    VS Code on the device · Files (sftp) · mount at ~/Remote/NAME
  board push | pull | sync      copy files · mirror a project on every save (--run CMD)
  board run NAME|@tag -- CMD    run in the device's project folder (or on every device with a tag)
  board ports | share           open device ports here · share a laptop port with the device
  board serial                  serial console (logged, auto-reconnect)
  board scan                    find devices on your networks
  board net [info | ports HOST] every IP on your network, names, vendors, open ports · your IPs, router, DNS
  board usb | link | hotspot    field connections: one USB cable · direct Ethernet · laptop hotspot
  board flash | bootstrap       write an SD card ready to use · set a fresh device up
  board help                    every command

Devices live in ~/.config/myos/devices.toml; the SSH config is generated from it, so the same name works in
ssh, scp, rsync, git, VS Code Remote-SSH and Files. Stdlib only.
"""
import argparse, concurrent.futures as cf, datetime as dt, hashlib, ipaddress, json, os, re, secrets, selectors
import shlex, shutil, signal, socket, subprocess, sys, threading, time, tomllib
from pathlib import Path

HOME = Path.home()
CFG_DIR = HOME / ".config/myos"
REG = CFG_DIR / "devices.toml"
SSH = HOME / ".ssh"
GEN = SSH / "config.d/10-devices"
STATE = HOME / ".local/state/myos/remote.json"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
CACHE = RUNTIME / "myos-remote.json"
LOGS = HOME / "Embedded/logs"
IMAGES = HOME / "Embedded/images"
MOUNTS = HOME / "Remote"
VSCODE_SETTINGS = HOME / ".config/Code/User/settings.json"
BOOKMARKS = HOME / ".config/gtk-3.0/bookmarks"
SELF = Path(__file__).resolve()
# Tests point ssh at a private config (ssh reads ~/.ssh from the passwd home, not $HOME).
SSH_CMD = ["ssh"] + (["-F", os.environ["BOARD_SSH_CONFIG"]] if os.environ.get("BOARD_SSH_CONFIG") else [])

KINDS = ("pi", "jetson", "linux", "server", "router", "mcu", "vm", "macos", "windows")
SETTINGS_KEY = "defaults"
DEFAULT_SETTINGS = {"user": "", "baud": 115200, "tmux_session": "main", "hotspot_ssid": "", "eth_iface": "",
                    "wifi_iface": "", "country": "", "terminal": ""}
FIELDS = {  # name: (type, help)
    "host": (str, "hostname or IP (default NAME.local)"), "user": (str, "login user"), "port": (int, "ssh port"),
    "kind": (str, "|".join(KINDS)), "project": (str, "remote project folder"), "local": (str, "local project folder"),
    "tags": (list, "groups, for `board run @tag`"), "mac": (str, "network MAC (wake-on-LAN, finding it)"),
    "usb_mac": (str, "USB-cable MAC (set by `board usb enable`)"), "serial": (str, "serial port (/dev/serial/by-id/…)"),
    "baud": (int, "serial speed"), "forward": (list, "ports for `board ports` (8080 or 8080:80)"),
    "jump": (str, "ProxyJump host(s)"), "agent": (bool, "forward your ssh agent (git on the device)"),
    "identity": (str, "key file for this device"), "shell": (str, "tmux | plain"), "options": (list, "extra ssh_config lines"),
    "notes": (str, "free text"), "alerts": (bool, "notify when it goes offline, runs hot, loses power or fills its disk"), "proxy": (bool, "smart path selection (Wi-Fi / USB / cable); default on"),
    "arch": (str, ""), "model": (str, ""), "os": (str, ""), "home": (str, ""), "mem_mb": (int, ""), "flashed_at": (str, ""),
}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")
HOST_RE = re.compile(r"^[A-Za-z0-9._:%\[\]-]{1,253}$")
USER_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._@\\-]{0,63}$")
MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
USB_PREFIX_HOST, USB_PREFIX_DEV = "02:b0", "02:b1"     # locally administered MACs for USB-cable mode
USB_NET, ETH_NET = "10.55.0.1/24", "10.42.0.1/24"
NM_USB, NM_ETH, NM_HOTSPOT = "Board USB (shared)", "Board Ethernet (shared)", "Board hotspot"

# exit codes the panel and scripts rely on
OK, USAGE, OFFLINE, AUTH, HOSTKEY, FAIL = 0, 2, 3, 4, 5, 1


class Fail(Exception):
    def __init__(self, msg, code=FAIL): super().__init__(msg); self.code = code


# ───────────────────────────── small helpers ─────────────────────────────
def tty(): return sys.stdin.isatty() and sys.stdout.isatty()
def color(s, c): return f"\033[{c}m{s}\033[0m" if sys.stdout.isatty() else s
def dim(s): return color(s, "2")
def good(s): return color(s, "32")
def warn(s): return color(s, "33")
def bad(s): return color(s, "31")
def bold(s): return color(s, "1")
def say(*a): print(*a, flush=True)
def err(*a): print(*a, file=sys.stderr, flush=True)
def have(cmd): return shutil.which(cmd) is not None
def sh(*a, timeout=None, input=None):
    try: return subprocess.run(a, capture_output=True, text=True, timeout=timeout, input=input)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return subprocess.CompletedProcess(a, 124 if isinstance(e, subprocess.TimeoutExpired) else 127, "", str(e))


def ask(q, default=""):
    if not tty(): return default
    try: a = input(f"{q}{f' [{default}]' if default else ''}: ").strip()
    except EOFError: return default
    return a or default


def confirm(q, default=False, yes=False):
    if yes: return True
    if not tty(): return default
    try: a = input(f"{q} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    except EOFError: return default
    return default if not a else a in ("y", "yes")


def notify(title, body="", urgency="normal"):
    sh("notify-send", "-a", "Remote", "-u", urgency, "-i", "network-server-symbolic", title, body, timeout=5)


def human_bytes(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB": return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def human_secs(s):
    s = int(s)
    if s < 90: return f"{s} s"
    if s < 5400: return f"{s // 60} min"
    if s < 172800: return f"{s // 3600} h"
    return f"{s // 86400} d"


def atomic_write(path, text, mode=0o600):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f: f.write(text)
    os.replace(tmp, path)


def board_cmd():
    """How the installed CLI is invoked (used in generated ssh config and VS Code tasks)."""
    p = shutil.which("board")
    return p if p else f"{sys.executable} {SELF}"


# ───────────────────────────── registry (TOML) ─────────────────────────────
def _tval(v):
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, int): return str(v)
    if isinstance(v, list): return "[" + ", ".join(_tval(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)     # JSON string escapes are valid TOML basic strings


def dump_registry(reg):
    out = ["# Devices for `board`. Edit with `board edit` (validated) or by hand, then run `board gen`.",
           "# Fields: " + ", ".join(k for k, (_, h) in FIELDS.items() if h), ""]
    settings = reg.get(SETTINGS_KEY)
    for name in ([SETTINGS_KEY] if settings else []) + sorted(k for k in reg if k != SETTINGS_KEY):
        out.append(f"[{name}]")
        for k, v in reg[name].items():
            if v is None or v == "" or v == []: continue
            out.append(f"{k} = {_tval(v)}")
        out.append("")
    return "\n".join(out)


def load_registry(path=None):
    path = Path(path or REG)
    if not path.exists(): return {}
    try: reg = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e: raise Fail(f"{path} has a syntax error: {e}. Fix it with `board edit`.")
    return reg


def devices(reg=None):
    reg = load_registry() if reg is None else reg
    return {k: v for k, v in reg.items() if k != SETTINGS_KEY and isinstance(v, dict)}


def settings(reg=None):
    reg = load_registry() if reg is None else reg
    s = dict(DEFAULT_SETTINGS); s.update(reg.get(SETTINGS_KEY, {})); return s


def validate_device(name, d):
    """Return a list of problems (empty = fine). Everything here ends up in ssh_config, so be strict."""
    p = []
    if not NAME_RE.match(name) or name == SETTINGS_KEY:
        p.append(f"name '{name}': use letters, digits, - and _ (no dots or spaces)")
    for k, v in d.items():
        if k not in FIELDS: p.append(f"{name}: unknown field '{k}'"); continue
        t = FIELDS[k][0]
        if t is int and (not isinstance(v, int) or isinstance(v, bool)): p.append(f"{name}.{k}: must be a number")
        elif t is bool and not isinstance(v, bool): p.append(f"{name}.{k}: must be true or false")
        elif t is list and not (isinstance(v, list) and all(isinstance(x, str) for x in v)): p.append(f"{name}.{k}: must be a list of text")
        elif t is str and not isinstance(v, str): p.append(f"{name}.{k}: must be text")
    for k in d:
        v = d[k]
        if isinstance(v, str) and any(c in v for c in "\n\r\0"): p.append(f"{name}.{k}: no line breaks")
        if isinstance(v, list) and any(any(c in x for c in "\n\r\0") for x in v): p.append(f"{name}.{k}: no line breaks")
    if d.get("host") and not HOST_RE.match(d["host"]): p.append(f"{name}.host: '{d['host']}' is not a hostname or IP")
    if d.get("user") and not USER_RE.match(d["user"]): p.append(f"{name}.user: '{d['user']}' has characters ssh can't use")
    if "port" in d and isinstance(d["port"], int) and not 0 < d["port"] < 65536: p.append(f"{name}.port: 1–65535")
    if d.get("kind") and d["kind"] not in KINDS: p.append(f"{name}.kind: one of {', '.join(KINDS)}")
    if d.get("shell") and d["shell"] not in ("tmux", "plain"): p.append(f"{name}.shell: tmux or plain")
    for k in ("mac", "usb_mac"):
        if d.get(k) and not MAC_RE.match(d[k].lower()): p.append(f"{name}.{k}: like aa:bb:cc:dd:ee:ff")
    if d.get("jump") and re.search(r"\s", d["jump"]): p.append(f"{name}.jump: no spaces (use commas for several)")
    for spec in d.get("forward", []) if isinstance(d.get("forward"), list) else []:
        try: parse_port_spec(spec)
        except Fail as e: p.append(f"{name}.forward: {e}")
    for o in d.get("options", []) if isinstance(d.get("options"), list) else []:
        if not re.match(r"^[A-Za-z]+\s+\S", o): p.append(f"{name}.options: '{o}' should look like 'Compression yes'")
    return p


def save_registry(reg):
    problems = [x for n, d in devices(reg).items() for x in validate_device(n, d)]
    if problems: raise Fail("Not saved:\n  " + "\n  ".join(problems), USAGE)
    if REG.exists():
        bk = CFG_DIR / "backups"; bk.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REG, bk / f"devices-{dt.datetime.now():%Y%m%d-%H%M%S}.toml")
        for old in sorted(bk.glob("devices-*.toml"))[:-20]: old.unlink()     # keep the last 20
    atomic_write(REG, dump_registry(reg))
    gen_ssh_config(reg)


def get_device(name, reg=None):
    devs = devices(reg)
    if name in devs: return devs[name]
    close = [n for n in devs if n.lower().startswith(name.lower())]
    if len(close) == 1: return devs[close[0]] | {"_name": close[0]}
    hint = f" Did you mean: {', '.join(close)}?" if close else (f" Known: {', '.join(devs)}." if devs else " Add one with `board add`.")
    raise Fail(f"No device called '{name}'.{hint}", USAGE)


def resolve_name(name, reg=None):
    if name is None: return pick_device(reg)
    d = get_device(name, reg)
    return d.get("_name", name)


def dev_host(name, d): return d.get("host") or f"{name}.local"
def dev_home(d): return d.get("home") or (f"/home/{d['user']}" if d.get("user") else "~")


def remote_path(d, p=None):
    """Absolute remote path; '~/x' expanded with the device's home when we know it."""
    p = p or d.get("project") or "~"
    if p == "~": return dev_home(d)
    if p.startswith("~/"): return dev_home(d).rstrip("/") + p[1:]
    return p


# ───────────────────────────── ssh config ─────────────────────────────
def render_ssh_config(reg):
    lines = ["# Generated by `board` from ~/.config/myos/devices.toml. Do not edit: use `board edit` / `board set`.", ""]
    cmd = board_cmd()
    for name, d in sorted(devices(reg).items()):
        if d.get("kind") == "mcu" and not d.get("host"): continue     # serial-only board
        lines.append(f"Host {name}")
        lines.append(f"  HostName {dev_host(name, d)}")
        if d.get("user"): lines.append(f"  User {d['user']}")
        if d.get("port"): lines.append(f"  Port {d['port']}")
        lines.append(f"  HostKeyAlias {name}")       # one host key per device, whichever path (Wi-Fi/USB/IP) is used
        if d.get("jump"): lines.append(f"  ProxyJump {d['jump']}")
        elif d.get("proxy", True): lines.append(f"  ProxyCommand {cmd} _proxy {name} %p")
        if d.get("identity"): lines.append(f"  IdentityFile {d['identity']}")
        if d.get("agent"): lines.append("  ForwardAgent yes")
        if d.get("kind") == "windows": lines.append("  RequestTTY auto")
        for o in d.get("options", []): lines.append(f"  {o}")
        lines.append("")
    return "\n".join(lines)


def gen_ssh_config(reg=None):
    reg = load_registry() if reg is None else reg
    ensure_ssh_layout()
    atomic_write(GEN, render_ssh_config(reg))


def ensure_ssh_layout():
    """~/.ssh/config gets one Include line at the top (backup first); defaults live in config.d/99-defaults."""
    SSH.mkdir(mode=0o700, exist_ok=True); os.chmod(SSH, 0o700)
    (SSH / "config.d").mkdir(mode=0o700, exist_ok=True)
    (SSH / "sockets").mkdir(mode=0o700, exist_ok=True)
    cfg = SSH / "config"
    inc = "Include ~/.ssh/config.d/*"
    text = cfg.read_text() if cfg.exists() else ""
    if inc not in text:
        if text:
            shutil.copy2(cfg, SSH / f"config.backup-{dt.datetime.now():%Y%m%d-%H%M%S}")
        atomic_write(cfg, f"{inc}\n\n{text}" if text else
                     f"{inc}\n\n# Your own hosts can go below or in ~/.ssh/config.d/20-personal.\n"
                     "# Device hosts come from `board` (config.d/10-devices); defaults in config.d/99-defaults.\n")


# ───────────────────────────── state + paths ─────────────────────────────
def load_state():
    try: return json.loads(STATE.read_text())
    except Exception: return {}


def save_state(update):
    st = load_state()
    for k, v in update.items(): st.setdefault(k, {}).update(v)
    try: atomic_write(STATE, json.dumps(st, indent=1))
    except OSError: pass


def ip_neigh():
    """{mac: [ips]} from the kernel neighbour table."""
    out = {}
    r = sh("ip", "-j", "neigh", timeout=3)
    try:
        for n in json.loads(r.stdout or "[]"):
            if n.get("lladdr") and n.get("dst") and ":" not in n["dst"]:
                out.setdefault(n["lladdr"].lower(), []).append(n["dst"])
    except ValueError: pass
    return out


def local_nets():
    """[(iface, IPv4Interface)] for real interfaces (no docker/bridges/vpn-less loopback)."""
    out = []
    r = sh("ip", "-j", "-4", "addr", timeout=3)
    try:
        for i in json.loads(r.stdout or "[]"):
            n = i.get("ifname", "")
            if n == "lo" or n.startswith(("docker", "br-", "virbr", "veth", "lxc", "vnet")): continue
            if "UP" not in i.get("flags", []): continue
            for a in i.get("addr_info", []):
                if a.get("family") == "inet":
                    out.append((n, ipaddress.ip_interface(f"{a['local']}/{a['prefixlen']}")))
    except (ValueError, KeyError): pass
    return out


def scan_nets(nets=None):
    """Networks worth scanning: each interface's own /24 (a /16 would take minutes)."""
    out = []
    for iface, ipi in (nets if nets is not None else local_nets()):
        net = ipi.network if ipi.network.prefixlen >= 24 else ipaddress.ip_network(f"{ipi.ip}/24", strict=False)
        if net.num_addresses > 1: out.append((iface, net))
    return out


def iface_kind(iface):
    """'USB cable' | 'Ethernet' | 'Wi-Fi' | 'VPN' | iface."""
    if not iface: return "?"
    if iface.startswith("enx" + USB_PREFIX_HOST.replace(":", "")) or iface.startswith("usb"): return "USB cable"
    drv = ""
    try: drv = os.path.basename(os.readlink(f"/sys/class/net/{iface}/device/driver"))
    except OSError: pass
    if drv in ("cdc_ether", "rndis_host", "cdc_ncm"): return "USB cable"
    if iface.startswith(("wl", "wlan")): return "Wi-Fi"
    if iface.startswith(("en", "eth")): return "Ethernet"
    if iface.startswith(("tun", "tap", "wg", "ppp")): return "VPN"
    if iface == "lo": return "this laptop"
    return iface


def route_iface(ip):
    r = sh("ip", "-j", "route", "get", ip, timeout=2)
    try: return json.loads(r.stdout)[0].get("dev", "")
    except (ValueError, IndexError): return ""


def via_label(ip):
    try: ipaddress.ip_address(ip)
    except ValueError:
        try: ip = socket.gethostbyname(ip)
        except OSError: return "?"
    return iface_kind(route_iface(ip))


def _connect(host, port, timeout):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        return s
    except OSError:
        return None


def race(candidates, port, grace=0.8, timeout=5.0):
    """Connect to all candidates at once; prefer earlier ones, but don't wait more than `grace` s for them
    once a later one has answered. Returns (host, socket) or (None, None)."""
    candidates = list(dict.fromkeys(c for c in candidates if c))
    if not candidates: return None, None
    ex = cf.ThreadPoolExecutor(max_workers=len(candidates))
    futs = [ex.submit(_connect, h, port, timeout) for h in candidates]
    t0, win = time.monotonic(), None
    try:
        while time.monotonic() - t0 < timeout + 0.5 and win is None:
            waiting = False
            for i, f in enumerate(futs):
                if not f.done():
                    if time.monotonic() - t0 < grace: waiting = True; break
                    continue
                if f.result() is not None: win = i; break
            if win is None and (all(f.done() for f in futs) and not waiting): break
            if win is None: time.sleep(0.02)
    finally:
        for i, f in enumerate(futs):
            if i != win: f.add_done_callback(lambda f: f.result() and f.result().close())
        ex.shutdown(wait=False)
    return (candidates[win], futs[win].result()) if win is not None else (None, None)


def sweep(net, port=22, timeout=0.4, limit=254):
    """Hosts in a small subnet with `port` open (used on USB/cable links where no lease file is readable)."""
    hosts = [str(h) for h in list(net.hosts())[:limit]]
    with cf.ThreadPoolExecutor(64) as ex:
        res = list(ex.map(lambda h: (h, _connect(h, port, timeout)), hosts))
    found = []
    for h, s in res:
        if s: s.close(); found.append(h)
    return found


def candidates_for(name, d, state=None):
    """Where might this device be, best guess first."""
    state = load_state() if state is None else state
    host = dev_host(name, d)
    c = [host]
    if not host.endswith(".local") and d.get("kind") not in ("windows", "router"): c.append(f"{name}.local")
    if state.get(name, {}).get("ip"): c.append(state[name]["ip"])
    neigh = ip_neigh()
    for k in ("usb_mac", "mac"):
        if d.get(k): c += neigh.get(d[k].lower(), [])
    return list(dict.fromkeys(c))


def cable_candidates(name, d):
    """Last resort: sweep the USB-cable / direct-Ethernet subnets for an open ssh port."""
    port = d.get("port", 22)
    out = []
    for iface, ipi in local_nets():
        if iface_kind(iface) in ("USB cable",) or str(ipi.network) in (str(ipaddress.ip_interface(USB_NET).network),
                                                                       str(ipaddress.ip_interface(ETH_NET).network)):
            out += [h for h in sweep(ipi.network, port) if h != str(ipi.ip)]
    return out


def find_path(name, d, timeout=5.0):
    """(host, socket, via) for the best reachable path, or raises Fail(OFFLINE)."""
    port = d.get("port", 22)
    cands = candidates_for(name, d)
    host, s = race(cands, port, timeout=timeout)
    if not s:
        extra = [h for h in cable_candidates(name, d) if h not in cands]
        if len(extra) == 1 or d.get("usb_mac"):
            host, s = race(extra, port, timeout=2)
        cands += extra
    if not s:
        raise Fail(f"{name} is not reachable (tried {', '.join(cands) or 'nothing'}). Is it powered, and on the same "
                   f"network or cable? `board doctor {name}` checks every path.", OFFLINE)
    ip = s.getpeername()[0]
    via = iface_kind(route_iface(ip))
    save_state({name: {"ip": ip, "via": via, "seen": time.time()}})
    return host, s, via


def cmd_proxy(a):
    """ProxyCommand: pick a path, then relay bytes between ssh (stdin/stdout) and the device."""
    reg = load_registry()
    d = devices(reg).get(a.name)
    if d is None:
        s = _connect(a.name, int(a.port), 10)
        if not s: err(f"board: unknown device {a.name}"); return 255
    else:
        d = dict(d); d["port"] = int(a.port)
        try: _, s, _ = find_path(a.name, d)
        except Fail as e:
            err(f"board: {e}")
            # ssh drops a ProxyCommand's stderr when ControlPersist is on, so leave the reason where we can find it
            try: atomic_write(proxy_err_file(a.name), str(e))
            except OSError: pass
            return 255
    s.settimeout(None)
    relay(s)
    return 0


def proxy_err_file(name): return RUNTIME / f"board-proxy-{name}.err"


def proxy_error(name, max_age=120):
    f = proxy_err_file(name)
    try:
        if time.time() - f.stat().st_mtime < max_age: return f.read_text().strip()
    except OSError: pass
    return ""


def relay(s):
    sel = selectors.DefaultSelector()
    sel.register(0, selectors.EVENT_READ, "in"); sel.register(s, selectors.EVENT_READ, "net")
    open_in = True
    try:
        while True:
            for key, _ in sel.select():
                if key.data == "in":
                    data = os.read(0, 65536)
                    if not data:
                        sel.unregister(0); open_in = False
                        try: s.shutdown(socket.SHUT_WR)
                        except OSError: pass
                    else: s.sendall(data)
                else:
                    data = s.recv(65536)
                    if not data: return
                    v = memoryview(data)
                    while v: v = v[os.write(1, v):]
            if not open_in and not sel.get_map(): return
    except (BrokenPipeError, ConnectionResetError, OSError):
        return
    finally:
        s.close()


# ───────────────────────────── running ssh ─────────────────────────────
def ssh_base(batch=False, extra=()):
    a = list(SSH_CMD)
    if batch: a += ["-o", "BatchMode=yes", "-o", "ConnectTimeout=6"]
    return a + list(extra)


def ssh_env():
    env = dict(os.environ)
    if env.get("TERM", "").startswith("xterm-kitty") or env.get("TERM") in ("xterm-ghostty", "alacritty", "foot"):
        env["TERM"] = "xterm-256color"           # a bare Pi has no terminfo for these
    return env


def classify_ssh_error(stderr, code):
    s = stderr or ""
    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in s or "POSSIBLE DNS SPOOFING" in s: return "hostkey-changed"
    if "Host key verification failed" in s: return "hostkey-unknown"
    if "Permission denied" in s or "Too many authentication failures" in s: return "auth"
    if code == 255 and re.search(r"not reachable|timed out|refused|No route|Could not resolve|unknown device|"
                                 r"Connection closed by UNKNOWN|kex_exchange_identification|Network is unreachable", s):
        return "offline"
    if code == 255: return "ssh"
    return "ok" if code == 0 else "remote"


def master_alive(name):
    return sh(*SSH_CMD, "-O", "check", name, timeout=3).returncode == 0


def ssh_check(name, timeout=10):
    """(state, stderr): ok | hostkey-changed | hostkey-unknown | auth | offline | ssh. Opens a master connection."""
    r = sh(*ssh_base(batch=True), name, "true", timeout=timeout)
    if r.returncode == 124: return "offline", "timed out"
    st = classify_ssh_error(r.stderr, r.returncode)
    return ("ok" if st == "remote" else st), r.stderr


def new_fingerprint(stderr):
    m = re.search(r"(SHA256:[A-Za-z0-9+/=]+)", stderr or "")
    return m.group(1) if m else "unknown"


def forget_hostkeys(name, d=None):
    kh = SSH / "known_hosts"
    if not kh.exists(): return
    d = d or devices().get(name, {})
    st = load_state().get(name, {})
    for h in {name, dev_host(name, d), st.get("ip", "")} - {""}:
        for target in (h, f"[{h}]:{d.get('port', 22)}"):
            sh("ssh-keygen", "-R", target, "-f", str(kh), timeout=5)


def handle_hostkey_change(name, d, stderr, yes=False):
    when = d.get("flashed_at")
    say(warn(f"\n{name} is offering a different host key than before."))
    say(f"  New key: {new_fingerprint(stderr)}")
    if when: say(f"  That's expected: you flashed it on {when}.")
    else: say("  Expected if you reflashed or reinstalled it. If you didn't, someone could be intercepting the connection.")
    if confirm("Trust the new key?", default=bool(when), yes=yes):
        forget_hostkeys(name, d)
        r = sh(*ssh_base(batch=True, extra=["-o", "StrictHostKeyChecking=accept-new"]), name, "true", timeout=15)
        return classify_ssh_error(r.stderr, r.returncode) in ("ok", "remote", "auth")
    return False


def ensure_connected(name, d, interactive=True, yes=False):
    """Open (or reuse) a master connection, fixing what can be fixed. Returns 'ok' or raises Fail."""
    if master_alive(name): return "ok"
    st, stderr = ssh_check(name)
    if st == "hostkey-changed":
        if interactive and handle_hostkey_change(name, d, stderr, yes): st, stderr = ssh_check(name)
        else: raise Fail(f"{name}'s host key changed. Run `board forget {name}` if you reflashed it.", HOSTKEY)
    if st == "hostkey-unknown":
        if interactive:
            r = sh(*ssh_base(batch=True, extra=["-o", "StrictHostKeyChecking=accept-new"]), name, "true", timeout=15)
            st = classify_ssh_error(r.stderr, r.returncode); st = "ok" if st == "remote" else st
            if st == "ok": say(dim(f"Trusted {name}'s host key on first use."))
        else: raise Fail(f"{name}: new host key, not trusted yet. Connect once with `board ssh {name}`.", HOSTKEY)
    if st == "offline":
        lines = stderr.strip().splitlines()
        ours = [l for l in lines if l.startswith("board: ")] or [proxy_error(name)] * bool(proxy_error(name))
        raise Fail((ours or lines or [f"{name} is offline."])[-1].replace("board: ", ""), OFFLINE)
    if st == "auth":
        if interactive and (tty() or os.environ.get("SSH_ASKPASS_REQUIRE") == "force"):
            return "auth"       # caller decides: interactive ssh / copy-id (a terminal, or the panel's password helper)
        raise Fail(f"{name} refused your key. Run `board copy-id {name}` (asks the device password once).", AUTH)
    if st == "ssh":
        raise Fail(f"ssh to {name} failed: {stderr.strip()[-300:]}")
    return "ok"


def run_remote(name, script, timeout=30, input=None, tty_=False):
    args = ssh_base(batch=not tty_) + (["-t"] if tty_ else []) + [name, script]
    if tty_: return subprocess.run(args, env=ssh_env()).returncode
    return sh(*args, timeout=timeout, input=input)


def execvp(args, env=None):
    sys.stdout.flush(); sys.stderr.flush()
    try: os.execvpe(args[0], args, env or os.environ)
    except FileNotFoundError: raise Fail(f"{args[0]} is not installed. `board doctor` lists what to install.")


def set_title(t):
    if sys.stdout.isatty(): sys.stdout.write(f"\033]0;{t}\007"); sys.stdout.flush()


# ───────────────────────────── facts / status ─────────────────────────────
PROBE = r"""
m=$(tr -d '\0' </proc/device-tree/model 2>/dev/null)
[ -z "$m" ] && m=$(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null)
echo "model=$m"
echo "arch=$(uname -m)"
echo "kernel=$(uname -r)"
. /etc/os-release 2>/dev/null; echo "os=$PRETTY_NAME"
echo "home=$HOME"
echo "temp=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)"
echo "load=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null)"
echo "uptime=$(cut -d' ' -f1 /proc/uptime 2>/dev/null)"
echo "disk_free=$(df -Pk / 2>/dev/null | awk 'NR==2{print $4}')"
echo "disk_total=$(df -Pk / 2>/dev/null | awk 'NR==2{print $2}')"
echo "mem_total=$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null)"
echo "mem_avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null)"
echo "cpus=$(nproc 2>/dev/null)"
echo "throttled=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)"
echo "ips=$(hostname -I 2>/dev/null)"
echo "tmux=$(command -v tmux >/dev/null && echo yes || echo no)"
echo "sudo=$(sudo -n true 2>/dev/null && echo yes || echo no)"
echo "hostname=$(hostname 2>/dev/null)"
"""

THROTTLE_BITS = {0: "under-voltage now", 1: "CPU speed capped now", 2: "throttled now", 3: "hot (soft limit) now",
                 16: "under-voltage since boot", 17: "speed capped since boot", 18: "throttled since boot",
                 19: "hot since boot"}


def decode_throttled(v):
    try: n = int(v, 16) if isinstance(v, str) else int(v)
    except (TypeError, ValueError): return []
    return [t for b, t in THROTTLE_BITS.items() if n & (1 << b)]


def parse_probe(text):
    f = {}
    for line in (text or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1); f[k.strip()] = v.strip()
    out = {k: f.get(k, "") for k in ("model", "arch", "kernel", "os", "home", "ips", "hostname")}
    def num(k, scale=1.0):
        try: return float(f.get(k, "")) * scale
        except ValueError: return None
    t = num("temp")
    out["temp_c"] = round(t / 1000, 1) if t and t > 200 else t
    out["load"] = num("load"); out["uptime_s"] = num("uptime"); out["cpus"] = num("cpus")
    out["disk_free_kb"] = num("disk_free"); out["disk_total_kb"] = num("disk_total")
    out["mem_total_kb"] = num("mem_total"); out["mem_avail_kb"] = num("mem_avail")
    out["throttled"] = decode_throttled(f.get("throttled", ""))
    out["tmux"] = f.get("tmux") == "yes"; out["sudo"] = f.get("sudo") == "yes"
    return out


def probe(name, timeout=8):
    """Live facts over the (multiplexed) connection. Returns dict with 'state'."""
    t0 = time.monotonic()
    r = sh(*ssh_base(batch=True), name, "sh -s", timeout=timeout, input=PROBE)
    ms = round((time.monotonic() - t0) * 1000)
    st = classify_ssh_error(r.stderr, r.returncode) if r.returncode != 124 else "offline"
    if st in ("ok", "remote"):
        f = parse_probe(r.stdout); f["state"] = "online"; f["ms"] = ms
        return f
    return {"state": {"auth": "auth", "hostkey-changed": "hostkey", "hostkey-unknown": "hostkey"}.get(st, "offline"),
            "error": (r.stderr or "").strip().splitlines()[-1:] or [""]}


def learn_facts(name, f, reg=None):
    """Store what doesn't change (arch, model, os, home, memory) in the registry."""
    reg = load_registry() if reg is None else reg
    d = reg.get(name)
    if not d or f.get("state") != "online": return
    upd = {"arch": f.get("arch"), "model": f.get("model"), "os": f.get("os"), "home": f.get("home")}
    if f.get("mem_total_kb"): upd["mem_mb"] = int(f["mem_total_kb"] / 1024)
    changed = False
    for k, v in upd.items():
        if v and d.get(k) != v: d[k] = v; changed = True
    if not d.get("kind"):
        m = (f.get("model") or "").lower()
        d["kind"] = "pi" if "raspberry" in m else "jetson" if ("jetson" in m or "orin" in m) else "linux"
        changed = True
    if changed: save_registry(reg)


def status_all(reg=None, timeout=8):
    reg = load_registry() if reg is None else reg
    devs = {n: d for n, d in devices(reg).items() if d.get("host") or d.get("kind") != "mcu"}
    st = load_state()
    with cf.ThreadPoolExecutor(max(1, min(16, len(devs)))) as ex:
        res = dict(zip(devs, ex.map(lambda n: probe(n, timeout), devs)))
    out = {}
    for n, f in res.items():
        f["via"] = load_state().get(n, {}).get("via", "") if f["state"] == "online" else ""
        f["seen"] = time.time() if f["state"] == "online" else st.get(n, {}).get("seen")
        f["session"] = master_alive(n) if f["state"] == "online" else False
        out[n] = f
    for n, d in devices(reg).items():
        if n not in out: out[n] = {"state": "serial", "serial_present": bool(d.get("serial") and Path(d["serial"]).exists())}
    try: atomic_write(CACHE, json.dumps({"t": time.time(), "devices": out}))
    except OSError: pass
    return out


def fast_status(devs):
    """No network: connected (master socket) / serial / unknown, for instant listings."""
    out = {}
    for n, d in devs.items():
        if d.get("kind") == "mcu" and not d.get("host"):
            out[n] = {"state": "serial", "serial_present": bool(d.get("serial") and Path(d["serial"]).exists())}
        else:
            out[n] = {"state": "online" if master_alive(n) else "unknown", "via": load_state().get(n, {}).get("via", "")}
    return out


# ───────────────────────────── picker ─────────────────────────────
def pick(items, prompt="device", preview=None):
    """items: [(value, label)]. fzf when available, numbered list otherwise."""
    if not items: return None
    if len(items) == 1: return items[0][0]
    if not tty(): raise Fail(f"Choose a {prompt} (no terminal to ask in).", USAGE)
    if have("fzf"):
        args = ["fzf", "--height=~50%", "--reverse", "--ansi", "--with-nth=2..", "--delimiter=\t",
                f"--prompt={prompt} › ", "--info=inline-right", "--border=rounded", "--no-multi"]
        if preview: args += ["--preview", preview, "--preview-window=right,50%,wrap"]
        r = subprocess.run(args, input="\n".join(f"{v}\t{l}" for v, l in items), text=True, stdout=subprocess.PIPE)
        if r.returncode != 0 or not r.stdout.strip(): raise Fail("Cancelled.", USAGE)
        return r.stdout.split("\t", 1)[0].strip()
    for i, (_, l) in enumerate(items, 1): say(f"  {i:>2}  {l}")
    a = ask(f"{prompt} number")
    if not a.isdigit() or not 1 <= int(a) <= len(items): raise Fail("Cancelled.", USAGE)
    return items[int(a) - 1][0]


def pick_device(reg=None, want=None):
    devs = devices(reg)
    if not devs: raise Fail("No devices yet. Find some with `board scan`, or `board add NAME HOST`.", USAGE)
    st = load_state()
    order = sorted(devs, key=lambda n: -(st.get(n, {}).get("used", 0)))
    items = []
    for n in order:
        d = devs[n]
        if want == "net" and d.get("kind") == "mcu" and not d.get("host"): continue
        if want == "serial" and not d.get("serial"): continue
        live = "●" if master_alive(n) else "○"
        seen = st.get(n, {}).get("seen")
        items.append((n, f"{live} {n:<14} {dim((d.get('model') or d.get('kind') or '')[:34]):<44} "
                         f"{dim('seen ' + human_secs(time.time() - seen) + ' ago') if seen else ''}"))
    v = pick(items)
    save_state({v: {"used": time.time()}})
    return v


# ───────────────────────────── commands: devices ─────────────────────────────
def key_path():
    for k in ("id_ed25519", "id_ed25519_sk", "id_ecdsa", "id_rsa"):
        if (SSH / k).exists() and (SSH / f"{k}.pub").exists(): return SSH / k
    return None


def cmd_add(a):
    reg = load_registry()
    s = settings(reg)
    host = a.host
    name = a.name
    if not name and not host:
        if not tty(): raise Fail("Usage: board add NAME [HOST] [--user U]", USAGE)
        host = ask("Host or IP (empty = NAME.local)")
        name = ask("Name", (host.split(".")[0] if host and not re.match(r"^\d", host) else ""))
    if name and not host and re.match(r"^\d+\.\d+\.\d+\.\d+$|.+\..+", name) and not NAME_RE.match(name):
        host, name = name, name.split(".")[0]                       # `board add 192.168.1.5` or `board add pi.local`
    if not name: name = host.split(".")[0] if host and not re.match(r"^\d", host) else ask("Name")
    if not NAME_RE.match(name or ""): raise Fail(f"'{name}' isn't a usable name: letters, digits, - and _.", USAGE)
    exists = name in reg
    if exists and not a.update and not confirm(f"{name} exists. Update it?", True):
        raise Fail("Nothing changed.", USAGE)
    d = dict(reg.get(name, {}))
    if host: d["host"] = host
    elif "host" not in d and a.kind != "mcu": d["host"] = f"{name}.local"
    user = a.user or d.get("user") or s.get("user") or ask("User on the device", os.environ.get("USER", ""))
    if user: d["user"] = user
    for k in ("port", "kind", "project", "local", "jump", "identity", "serial", "mac", "notes"):
        v = getattr(a, k, None)
        if v not in (None, ""): d[k] = v
    if a.local == ".": d["local"] = os.getcwd()
    if a.tag: d["tags"] = sorted(set(d.get("tags", []) + a.tag))
    if a.no_proxy: d["proxy"] = False
    if a.agent: d["agent"] = True
    problems = validate_device(name, d)
    if problems: raise Fail("\n".join(problems), USAGE)
    reg[name] = d
    save_registry(reg)
    say(good(f"✓ {name} saved") + dim(f"  ({d.get('user', '?')}@{d.get('host', 'serial only')})"))
    if d.get("kind") == "mcu" and not d.get("host"):
        return OK
    if a.offline:
        say(dim("Not connecting now (--offline)."));
        return OK
    return connect_and_learn(name, d, copy_id=not a.no_copy_id, yes=a.yes)


def connect_and_learn(name, d, copy_id=True, yes=False):
    if not key_path():
        say(warn("You have no SSH key yet. Run `board setup` first (it makes one), then `board copy-id " + name + "`."))
        return AUTH
    try: st = ensure_connected(name, d, interactive=True, yes=yes)
    except Fail as e:
        say(warn(str(e)) + dim("  (saved anyway; it will work once the device is reachable)"))
        return e.code
    if st == "auth":
        if not copy_id: say(warn(f"{name} refused the key. `board copy-id {name}` sends it.")); return AUTH
        say(f"Sending your key to {name}. It will ask for the device's password once.")
        if do_copy_id(name) != 0: return AUTH
    f = probe(name)
    if f["state"] == "online":
        learn_facts(name, f)
        d = devices()[name]
        add_bookmark(name, d)
        update_vscode_platforms()
        say(good(f"✓ connected via {load_state().get(name, {}).get('via', '?')}") +
            f"  {f.get('model') or '?'} · {f.get('os') or '?'} · {f.get('arch')}")
        if not f.get("tmux"): say(dim(f"  tip: `board bootstrap {name}` installs tmux and friends"))
        say(dim(f"  next: board ssh {name} · board code {name} · board files {name}"))
        return OK
    say(warn(f"Saved, but couldn't read device facts ({f['state']})."))
    return FAIL


def do_copy_id(name):
    k = key_path()
    if not k: raise Fail("No SSH key. Run `board setup` first.", AUTH)
    r = subprocess.run(["ssh-copy-id", "-i", f"{k}.pub", *SSH_CMD[1:], "-o", "ControlPath=none", name])
    if r.returncode == 0:
        sh(*SSH_CMD, "-O", "exit", name, timeout=3)
        say(good(f"✓ key installed on {name}; no more passwords."))
    else:
        say(bad(f"Couldn't install the key on {name}."))
    return r.returncode


def cmd_copy_id(a): return do_copy_id(resolve_name(a.name))


def cmd_rm(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    if not confirm(f"Remove {name} from your devices? (Nothing on the device changes.)", False, a.yes): return USAGE
    d = reg.pop(name)
    save_registry(reg)
    if a.forget: forget_hostkeys(name, d)
    remove_bookmark(name)
    say(good(f"✓ removed {name}"))
    return OK


def cmd_set(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = dict(reg[name])
    for kv in a.pairs:
        if "=" not in kv: raise Fail(f"'{kv}': use key=value (empty value removes the key)", USAGE)
        k, v = kv.split("=", 1)
        if k not in FIELDS: raise Fail(f"Unknown field '{k}'. Fields: {', '.join(FIELDS)}", USAGE)
        if v == "": d.pop(k, None); continue
        t = FIELDS[k][0]
        if t is int:
            if not v.isdigit(): raise Fail(f"{k} must be a number", USAGE)
            d[k] = int(v)
        elif t is bool: d[k] = v.lower() in ("1", "true", "yes", "on")
        elif t is list: d[k] = [x.strip() for x in v.split(",") if x.strip()]
        else: d[k] = v
    reg[name] = d
    save_registry(reg)
    say(good(f"✓ {name} updated"))
    return OK


def cmd_edit(a):
    if not REG.exists(): atomic_write(REG, dump_registry({}))
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("nano" if have("nano") else "vi")
    before = REG.read_text()
    tmp = REG.with_name(".devices.edit.toml"); tmp.write_text(before)
    while True:
        subprocess.run(shlex.split(editor) + [str(tmp)])
        try:
            reg = tomllib.loads(tmp.read_text())
            problems = [x for n, d in devices(reg).items() for x in validate_device(n, d)]
            if problems: raise ValueError("\n  ".join(problems))
        except (tomllib.TOMLDecodeError, ValueError) as e:
            say(bad(f"Not saved:\n  {e}"))
            if confirm("Edit again?", True): continue
            tmp.unlink(); return USAGE
        break
    tmp.unlink()
    if tomllib.loads(before or "") != reg: save_registry(reg); say(good("✓ saved"))
    else: say(dim("No changes."))
    return OK


def cmd_gen(a):
    gen_ssh_config(); update_vscode_platforms(); sync_bookmarks()
    say(good(f"✓ wrote {GEN}")); return OK


def cmd_ls(a):
    reg = load_registry()
    devs = devices(reg)
    if a.tag: devs = {n: d for n, d in devs.items() if a.tag in d.get("tags", [])}
    if not devs:
        say("No devices yet. `board scan` finds them on your network; `board add NAME HOST` adds one.")
        return OK
    stat = fast_status(devs) if a.fast else status_all({SETTINGS_KEY: reg.get(SETTINGS_KEY, {}), **devs})
    if a.json:
        print(json.dumps({n: {**devs[n], **({"status": stat.get(n)} if stat else {})} for n in devs}, indent=1)); return OK
    st = load_state()
    rows = []
    for n, d in sorted(devs.items()):
        f = stat.get(n, {})
        state = f.get("state", "?")
        dot = {"online": good("●"), "offline": dim("○"), "auth": warn("●"), "hostkey": warn("●"),
               "serial": color("◌", "36"), "unknown": dim("·")}.get(state, "?")
        info = d.get("model") or d.get("kind") or ""
        if state == "online" and "ms" not in f: detail = good("connected") + dim(f" {f.get('via', '')}")
        elif state == "unknown": detail = dim(dev_host(n, d))
        elif state == "online":
            bits = [f.get("via", ""), f"{f.get('ms')} ms"]
            if f.get("temp_c"): bits.append(f"{f['temp_c']:.0f}°C")
            if f.get("load") is not None: bits.append(f"load {f['load']:.2f}")
            if f.get("disk_free_kb"): bits.append(f"{human_bytes(f['disk_free_kb'] * 1024)} free")
            if f.get("uptime_s"): bits.append(f"up {human_secs(f['uptime_s'])}")
            if f.get("throttled"): bits.append(warn("⚠ " + f["throttled"][0]))
            detail = " · ".join(b for b in bits if b)
        elif state == "auth": detail = warn(f"key refused → board copy-id {n}")
        elif state == "hostkey": detail = warn(f"host key changed → board forget {n}")
        elif state == "serial": detail = "serial " + ("connected" if f.get("serial_present") else "not plugged in")
        else:
            seen = st.get(n, {}).get("seen")
            detail = dim(f"offline · seen {human_secs(time.time() - seen)} ago" if seen else "offline")
        rows.append(f" {dot} {bold(n):<24} {dim(info[:30]):<40} {detail}")
    say("\n".join(rows))
    return OK


def cmd_info(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    if a.json:
        print(json.dumps({"device": d, "status": probe(name)}, indent=1)); return OK
    try: ensure_connected(name, d, interactive=tty())
    except Fail as e: say(warn(str(e)))
    f = probe(name)
    say(bold(name) + dim(f"  {d.get('user', '')}@{dev_host(name, d)}"))
    if f["state"] != "online":
        say(warn(f"  {f['state']}: {f.get('error', [''])[0]}")); return OFFLINE
    learn_facts(name, f, reg)
    st = load_state().get(name, {})
    rows = [("Model", f.get("model")), ("OS", f.get("os")), ("Kernel", f"{f.get('kernel')} ({f.get('arch')})"),
            ("Path", f"{st.get('via', '?')} → {st.get('ip', '?')} · {f.get('ms')} ms"),
            ("IPs", f.get("ips")), ("Uptime", human_secs(f["uptime_s"]) if f.get("uptime_s") else ""),
            ("CPU", f"{int(f['cpus'] or 0)} cores · load {f.get('load')}" + (f" · {f['temp_c']:.1f}°C" if f.get("temp_c") else "")),
            ("Memory", f"{human_bytes((f.get('mem_avail_kb') or 0) * 1024)} free of {human_bytes((f.get('mem_total_kb') or 0) * 1024)}"),
            ("Disk /", f"{human_bytes((f.get('disk_free_kb') or 0) * 1024)} free of {human_bytes((f.get('disk_total_kb') or 0) * 1024)}"),
            ("Power", (warn(", ".join(f["throttled"])) + dim("  (use a proper 5V/3A–5A supply)")) if f.get("throttled") else good("OK") if f.get("throttled") == [] and "pi" in (d.get("kind") or "") else ""),
            ("tmux", "yes" if f.get("tmux") else warn(f"no (board bootstrap {name})")),
            ("sudo", "passwordless" if f.get("sudo") else "asks for password"),
            ("Project", remote_path(d) if d.get("project") else dim("not set (board set NAME project=~/code)")),
            ("Tags", ", ".join(d.get("tags", []))), ("Notes", d.get("notes"))]
    for k, v in rows:
        if v: say(f"  {dim(k + ':'):<20} {v}")
    return OK


# ───────────────────────────── commands: connect ─────────────────────────────
def cmd_ssh(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    save_state({name: {"used": time.time()}})
    try: st = ensure_connected(name, d, interactive=True, yes=a.yes)
    except Fail as e:
        if e.code == OFFLINE: raise
        st = "auth"
    plain = a.plain or d.get("shell") == "plain" or d.get("kind") in ("windows", "router", "macos")
    session = a.session or settings(reg)["tmux_session"]
    set_title(f"⇄ {name}")
    args = list(SSH_CMD) + (["-t"] if not plain or a.cmd else []) + [name]
    if a.cmd: args += [" ".join(a.cmd)]
    elif not plain:
        q = shlex.quote(session)
        args += [f"if command -v tmux >/dev/null 2>&1; then exec tmux new-session -A -s {q}; "
                 f"else echo '(no tmux on this device: board bootstrap {name} installs it)'; exec \"$SHELL\" -l; fi"]
    if st == "auth": say(dim("Key not accepted yet: ssh will ask for a passphrase or password."))
    execvp(args, ssh_env())


def cmd_mosh(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    if not have("mosh"): raise Fail("mosh isn't installed: run `bash scripts/phase12-embedded.sh` (see `board doctor`).")
    d = devices(reg)[name]
    ensure_connected(name, d)
    set_title(f"⇄ {name} (mosh)")
    session = settings(reg)["tmux_session"]
    execvp(["mosh", f"--ssh=ssh", name, "--", "sh", "-c", f"tmux new-session -A -s {shlex.quote(session)} || exec $SHELL -l"], ssh_env())


def needs_sshfs_mode(d):
    arch = (d.get("arch") or "").lower()
    return arch.startswith(("armv6", "armv5", "mips", "riscv32")) or (d.get("mem_mb") or 4096) < 900 or \
        d.get("kind") in ("router",)


def cmd_code(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    if not have("code"): raise Fail("VS Code (`code`) isn't installed.")
    st = ensure_connected(name, d, interactive=True)
    if st == "auth": raise Fail(f"{name} refused your key. `board copy-id {name}` first (VS Code can't ask for passwords nicely).", AUTH)
    if not d.get("arch"): learn_facts(name, probe(name), reg); d = devices()[name]
    path = remote_path(d, a.path)
    save_state({name: {"used": time.time()}})
    if a.mount or (needs_sshfs_mode(d) and not a.remote):
        why = "" if a.mount else f" ({d.get('arch')}, {d.get('mem_mb')} MB: too small for the VS Code server)"
        say(f"Opening {name} through a mount{why}. The terminal inside VS Code runs on the device.")
        mp = do_mount(name, d, path)
        write_mount_workspace(mp, name)
        execvp(["code", str(mp)])
    if not extension_installed("ms-vscode-remote.remote-ssh"):
        say("Installing VS Code Remote-SSH…")
        sh("code", "--install-extension", "ms-vscode-remote.remote-ssh", timeout=180)
    update_vscode_platforms()
    r = subprocess.run(["code", "--remote", f"ssh-remote+{name}", path])
    return r.returncode


def write_mount_workspace(mp, name):
    """In mount mode, make VS Code's terminal open on the device."""
    vs = Path(mp) / ".vscode"
    s = vs / "settings.json"
    if s.exists(): return
    try:
        vs.mkdir(exist_ok=True)
        s.write_text(json.dumps({
            "terminal.integrated.profiles.linux": {name: {"path": "ssh", "args": ["-t", name]}},
            "terminal.integrated.defaultProfile.linux": name, "files.watcherExclude": {"**": True},
            "search.followSymlinks": False}, indent=2) + "\n")
    except OSError: pass


def extension_installed(ext):
    r = sh("code", "--list-extensions", timeout=30)
    return ext.lower() in r.stdout.lower()


def read_vscode_settings():
    if not VSCODE_SETTINGS.exists(): return {}
    text = VSCODE_SETTINGS.read_text()
    try: return json.loads(text) if text.strip() else {}
    except ValueError: return None      # comments (JSONC): leave the file alone


def update_vscode_platforms(extra=None):
    """remote.SSH.remotePlatform for every device, so VS Code never asks 'Linux, Windows or macOS?'."""
    s = read_vscode_settings()
    if s is None: return False
    plat = dict(s.get("remote.SSH.remotePlatform", {}))
    for n, d in devices().items():
        if d.get("kind") == "mcu" and not d.get("host"): continue
        plat[n] = {"windows": "windows", "macos": "macOS"}.get(d.get("kind"), "linux")
    new = dict(s); new["remote.SSH.remotePlatform"] = plat
    for k, v in (extra or {}).items(): new.setdefault(k, v)
    if new != s:
        bk = VSCODE_SETTINGS.with_name("settings.json.board-backup")
        if VSCODE_SETTINGS.exists() and not bk.exists(): shutil.copy2(VSCODE_SETTINGS, bk)
        atomic_write(VSCODE_SETTINGS, json.dumps(new, indent=4) + "\n", 0o644)
    return True


VSCODE_DEFAULTS = {
    "remote.SSH.configFile": str(SSH / "config"),
    "remote.SSH.useLocalServer": True,
    "remote.SSH.localServerDownload": "always",     # the laptop downloads the server: devices need no internet
    "remote.SSH.connectTimeout": 30,
    "remote.SSH.showLoginTerminal": False,
    "remote.SSH.enableDynamicForwarding": True,
    "remote.SSH.defaultExtensions": ["ms-python.python", "ms-vscode.cpptools"],
    "remote.autoForwardPortsSource": "process",
}


# ── files ──
def cmd_files(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    st = ensure_connected(name, d, interactive=True)
    if st == "auth": raise Fail(f"{name} refused your key: `board copy-id {name}` first.", AUTH)
    if not d.get("home"): learn_facts(name, probe(name), reg); d = devices()[name]
    path = remote_path(d, a.path)
    url = f"sftp://{name}{path if path.startswith('/') else '/' + path}"
    add_bookmark(name, d)
    if a.print: print(url); return OK
    subprocess.Popen(["gio", "open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    say(f"Opening {url}")
    return OK


def read_bookmarks():
    try: return BOOKMARKS.read_text().splitlines()
    except OSError: return []


def add_bookmark(name, d):
    if d.get("kind") == "mcu" and not d.get("host"): return
    path = remote_path(d)
    if not path.startswith("/"): return
    url = f"sftp://{name}{path}"
    label = f"{name} · {Path(path).name or '/'}"
    lines = [l for l in read_bookmarks() if not l.startswith(f"sftp://{name}/") and l != f"sftp://{name}"]
    lines.append(f"{url} {label}")
    try: atomic_write(BOOKMARKS, "\n".join(lines) + "\n", 0o644)
    except OSError: pass


def remove_bookmark(name):
    lines = [l for l in read_bookmarks() if not l.startswith(f"sftp://{name}/")]
    try: atomic_write(BOOKMARKS, "\n".join(lines) + ("\n" if lines else ""), 0o644)
    except OSError: pass


def sync_bookmarks():
    devs = devices()
    keep = [l for l in read_bookmarks() if not (l.startswith("sftp://") and l[7:].split("/")[0] not in devs
                                                  and " · " in l)]
    try: atomic_write(BOOKMARKS, "\n".join(keep) + ("\n" if keep else ""), 0o644)
    except OSError: pass
    for n, d in devs.items(): add_bookmark(n, d)


def sshfs_mounts():
    out = {}
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            src, mp, fs = line.split()[:3]
            if fs == "fuse.sshfs": out[mp.replace("\\040", " ")] = src
    except OSError: pass
    return out


def do_mount(name, d, path=None):
    if not have("sshfs"): raise Fail("sshfs isn't installed: run `bash scripts/phase12-embedded.sh`.")
    mp = MOUNTS / name
    if str(mp) in sshfs_mounts(): return mp
    mp.mkdir(parents=True, exist_ok=True)
    if any(mp.iterdir()): raise Fail(f"{mp} isn't empty; not mounting over your files.")
    src = f"{name}:{path or remote_path(d)}"
    r = sh("sshfs", src, str(mp), *SSH_CMD[1:], "-o", "reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,idmap=user,"
           "follow_symlinks,auto_cache,noatime", timeout=30)
    if r.returncode != 0: raise Fail(f"Mount failed: {r.stderr.strip()}")
    return mp


def cmd_mount(a):
    if not a.name and not tty():
        for mp, src in sshfs_mounts().items(): print(f"{src}\t{mp}")
        return OK
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    ensure_connected(name, d)
    if not d.get("home"): learn_facts(name, probe(name), reg); d = devices()[name]
    mp = do_mount(name, d, remote_path(d, a.path))
    say(good(f"✓ {name} mounted at {mp}") + dim(f"   unmount: board umount {name}"))
    if a.open: subprocess.Popen(["gio", "open", str(mp)], start_new_session=True)
    return OK


def cmd_umount(a):
    mounts = sshfs_mounts()
    targets = [str(MOUNTS / a.name)] if a.name else [m for m in mounts if m.startswith(str(MOUNTS))]
    if not targets: say("Nothing mounted."); return OK
    rc = OK
    for mp in targets:
        if mp not in mounts: say(dim(f"{mp} isn't mounted")); continue
        r = sh("fusermount3", "-u", mp) if have("fusermount3") else sh("fusermount", "-u", mp)
        if r.returncode != 0:
            r = sh("fusermount3", "-uz", mp)     # busy or device gone: lazy unmount
        if r.returncode == 0:
            say(good(f"✓ unmounted {mp}"))
            try: Path(mp).rmdir()
            except OSError: pass
        else: say(bad(f"Couldn't unmount {mp}: {r.stderr.strip()}")); rc = FAIL
    return rc


# ── copy / sync ──
DEFAULT_IGNORES = [".git/", ".venv/", "venv/", "__pycache__/", "node_modules/", "build/", ".pio/", ".cache/",
                   "*.pyc", ".DS_Store", ".vscode-server/", "*.img", "*.img.xz", "*.img.zst"]


def rsync_filters(src):
    f = []
    src = Path(src)
    if src.is_dir():
        if (src / ".gitignore").exists(): f.append("--filter=:- .gitignore")
        if (src / ".boardignore").exists(): f += [f"--exclude-from={src / '.boardignore'}"]
        else: f += [f"--exclude={x}" for x in DEFAULT_IGNORES]
    return f


def rsync(args, quiet=False):
    base = ["rsync", "-az", "--mkpath", "--partial", "--human-readable"] + (["-e", " ".join(SSH_CMD)] if len(SSH_CMD) > 1 else [])
    if not quiet: base += ["--info=progress2,stats0" if tty() else "--info=stats1"]
    t0 = time.time()
    r = subprocess.run(base + args)
    return r.returncode, time.time() - t0


def cmd_push(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    ensure_connected(name, d, interactive=tty())
    dst = remote_path(d, a.to) if a.to else remote_path(d)
    srcs = a.src or ["."]
    rc_all = OK
    for src in srcs:
        p = Path(src).expanduser()
        if not p.exists(): say(bad(f"{src}: no such file")); rc_all = FAIL; continue
        s = str(p) + ("/" if p.is_dir() and a.contents else "")
        target = f"{name}:{dst.rstrip('/')}/"
        rc, secs = rsync((["--delete"] if a.delete else []) + rsync_filters(p) + [s, target])
        if rc == 0: say(good(f"✓ {p.name or src} → {name}:{dst}"))
        else: say(bad(f"✗ copying {src} failed (rsync exit {rc})")); rc_all = FAIL
        if secs > 15 and not tty(): notify(f"Copied to {name}", f"{p.name} → {dst}")
    return rc_all


def cmd_pull(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    ensure_connected(name, d, interactive=tty())
    dest = Path(a.to or ".").expanduser()
    rc_all = OK
    for src in a.src:
        rp = src if src.startswith("/") else remote_path(d, src) if src.startswith("~") else \
            (remote_path(d) if d.get("project") else dev_home(d)).rstrip("/") + "/" + src
        rc, secs = rsync([f"{name}:{rp}", str(dest) + "/"])
        if rc == 0: say(good(f"✓ {name}:{rp} → {dest}"))
        else: say(bad(f"✗ {rp}: rsync exit {rc}")); rc_all = FAIL
        if secs > 15: notify(f"Copied from {name}", f"{rp} → {dest}")
    return rc_all


def snapshot(root, ignores):
    """{relpath: (mtime_ns, size)} skipping ignored dirs. Polling keeps this dependency-free.
    ponytail: polling every 0.4 s; switch to inotify (inotifywait) if a project grows past ~50k files."""
    out = {}
    skip_dirs = {x.rstrip("/") for x in ignores if x.endswith("/")}
    root = Path(root)
    for dp, dns, fns in os.walk(root):
        dns[:] = [n for n in dns if n not in skip_dirs and not n.startswith(".git")]
        for fn in fns:
            if fn.endswith((".swp", ".swx", "~", ".pyc")) or fn.startswith(".#"): continue
            p = os.path.join(dp, fn)
            try: st = os.stat(p); out[os.path.relpath(p, root)] = (st.st_mtime_ns, st.st_size)
            except OSError: pass
    return out


def cmd_sync(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    local = Path(a.local or d.get("local") or ".").expanduser().resolve()
    if not local.is_dir(): raise Fail(f"{local} isn't a folder.")
    remote = remote_path(d, a.remote) if a.remote else (remote_path(d) if d.get("project") else
                                                        dev_home(d).rstrip("/") + "/" + local.name)
    ensure_connected(name, d, interactive=tty())
    if not d.get("project") and not a.remote and confirm(f"Remember {remote} as {name}'s project folder?", True):
        reg[name]["project"] = remote.replace(dev_home(d), "~", 1) if remote.startswith(dev_home(d)) else remote
        reg[name].setdefault("local", str(local)); save_registry(reg)
    ign = DEFAULT_IGNORES if not (local / ".boardignore").exists() else \
        [l.strip() for l in (local / ".boardignore").read_text().splitlines() if l.strip() and not l.startswith("#")]
    flt = rsync_filters(local)
    run_proc = [None]

    def push_once(first=False):
        rc, secs = rsync((["--delete"] if a.delete else []) + flt + [f"{local}/", f"{name}:{remote}/"], quiet=not first)
        stamp = dt.datetime.now().strftime("%I:%M:%S %p").lstrip("0")
        say((good("✓") if rc == 0 else bad("✗")) + dim(f" {stamp} synced {local.name} → {name}:{remote}  ({secs:.1f} s)"))
        return rc

    def restart_run():
        if not a.run: return
        if run_proc[0] and run_proc[0].poll() is None:
            run_proc[0].terminate()
            try: run_proc[0].wait(3)
            except subprocess.TimeoutExpired: run_proc[0].kill()
        say(dim(f"▶ {a.run}"))
        run_proc[0] = subprocess.Popen([*SSH_CMD, "-tt", name, f"cd {shlex.quote(remote)} && {a.run}"], env=ssh_env(),
                                       stdin=subprocess.DEVNULL)

    if push_once(first=True) != 0: return FAIL
    if a.once:
        if a.run: return subprocess.run([*SSH_CMD, "-t", name, f"cd {shlex.quote(remote)} && {a.run}"], env=ssh_env()).returncode
        return OK
    restart_run()
    say(dim(f"Watching {local} — save a file to sync{' and re-run' if a.run else ''}. Ctrl+C to stop."))
    set_title(f"⇄ sync {name}")
    snap = snapshot(local, ign)
    try:
        while True:
            time.sleep(0.4)
            new = snapshot(local, ign)
            if new != snap:
                time.sleep(0.3)                       # let editors finish writing (atomic saves, formatters)
                snap = snapshot(local, ign)
                if push_once() == 0: restart_run()
    except KeyboardInterrupt:
        if run_proc[0] and run_proc[0].poll() is None: run_proc[0].terminate()
        say(dim("\nstopped"))
    return OK


# ── run ──
def cmd_run(a):
    reg = load_registry()
    if not a.cmd: raise Fail("Usage: board run NAME -- COMMAND", USAGE)
    target = a.target
    cmd = " ".join(a.cmd) if len(a.cmd) > 1 else a.cmd[0]
    if target and target.startswith("@"):
        tag = target[1:]
        names = [n for n, d in devices(reg).items() if tag in d.get("tags", []) or tag == "all"]
        if not names: raise Fail(f"No devices tagged '{tag}'.", USAGE)
        return fan_out(names, cmd, reg, a.here)
    name = resolve_name(target, reg)
    d = devices(reg)[name]
    ensure_connected(name, d, interactive=tty())
    full = cmd if a.here or not d.get("project") else f"cd {shlex.quote(remote_path(d))} 2>/dev/null; {cmd}"
    args = list(SSH_CMD) + (["-t"] if tty() else []) + [name, full]
    return subprocess.run(args, env=ssh_env()).returncode


def fan_out(names, cmd, reg, here=False):
    width = max(len(n) for n in names)
    palette = ["36", "35", "33", "34", "32", "31"]
    lock = threading.Lock()
    results = {}

    def one(i, n):
        d = devices(reg)[n]
        full = cmd if here or not d.get("project") else f"cd {shlex.quote(remote_path(d))} 2>/dev/null; {cmd}"
        p = subprocess.Popen(ssh_base(batch=True) + [n, full], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            with lock: print(color(f"{n:<{width}} │", palette[i % len(palette)]), line.rstrip(), flush=True)
        results[n] = p.wait()

    ts = [threading.Thread(target=one, args=(i, n)) for i, n in enumerate(names)]
    for t in ts: t.start()
    for t in ts: t.join()
    failed = [n for n, rc in results.items() if rc != 0]
    say(dim("─" * 40)); say(good(f"✓ {len(names) - len(failed)} ok") + (bad(f"  ✗ failed: {', '.join(failed)}") if failed else ""))
    return FAIL if failed else OK


# ── background jobs: keep running on the device after the laptop disconnects; the watcher notifies when done ──
JOB_DIR = "$HOME/.board-jobs"
JOB_RE = re.compile(r"^\d{4}-\d{6}-[0-9a-f]{4}$")


def job_start_script(jid, cmd, cd=""):
    """Shell for the device: run cmd detached (own session, survives ssh exit), log to ID.log, exit code to ID.rc."""
    j = f"{JOB_DIR}/{jid}"
    inner = f"sh -c {shlex.quote(cmd)}; echo $? > \"{j}.rc\""
    pre = f"cd {shlex.quote(cd)} 2>/dev/null; " if cd else ""
    return (f"mkdir -p {JOB_DIR} && {pre}printf '%s\\n' {shlex.quote(cmd)} > \"{j}.cmd\" && "
            f"S=$(command -v setsid || true); nohup $S sh -c {shlex.quote(inner)} > \"{j}.log\" 2>&1 < /dev/null & "
            f"echo $! > \"{j}.pid\"; echo started")


def job_status_script(ids, tail=3):
    """Prints `ID done RC` (+ `ID | line` log tail), `ID running`, `ID stopped` (board job kill) or `ID lost`
    (died without an exit code: the device rebooted)."""
    ids = " ".join(i for i in ids if JOB_RE.match(i))
    return (f"for id in {ids}; do J={JOB_DIR}/$id; if [ -f \"$J.rc\" ]; then echo \"$id done $(cat \"$J.rc\")\"; "
            f"tail -n {tail} \"$J.log\" 2>/dev/null | sed \"s/^/$id | /\"; "
            "elif [ -f \"$J.stopped\" ]; then echo \"$id stopped\"; "
            "elif [ -f \"$J.pid\" ] && kill -0 \"$(cat \"$J.pid\")\" 2>/dev/null; then echo \"$id running\"; "
            "else echo \"$id lost\"; fi; done")


def parse_job_status(text):
    """{id: {"state": done|running|lost, "rc": int|None, "tail": [lines]}}"""
    out = {}
    for line in (text or "").splitlines():
        if " | " in line:
            jid, rest = line.split(" | ", 1)
            if jid in out: out[jid]["tail"].append(rest)
            continue
        p = line.split()
        if len(p) >= 2 and JOB_RE.match(p[0]) and p[1] in ("done", "running", "lost", "stopped"):
            rc = int(p[2]) if p[1] == "done" and len(p) > 2 and p[2].lstrip("-").isdigit() else None
            out[p[0]] = {"state": p[1], "rc": rc, "tail": []}
    return out


def jobs_state(): return load_state().get("_jobs", {})


def jobs_refresh(only_pending=True):
    """Ask each device (one ssh each, in parallel) about its unfinished jobs; store results. Offline devices are skipped."""
    jobs = jobs_state()
    by_dev = {}
    for jid, j in jobs.items():
        if not only_pending or j.get("state", "running") == "running": by_dev.setdefault(j["device"], []).append(jid)
    def ask(item):
        dev, ids = item
        r = run_remote(dev, job_status_script(ids), timeout=20)
        return parse_job_status(r.stdout) if r.returncode == 0 else {}
    with cf.ThreadPoolExecutor(max(1, min(8, len(by_dev)))) as ex:
        for res in ex.map(ask, by_dev.items()):
            for jid, s in res.items():
                jobs[jid].update(state=s["state"], rc=s["rc"], tail=s["tail"][-3:])
                if s["state"] != "running": jobs[jid].setdefault("ended", time.time())
    save_state({"_jobs": jobs})
    return jobs


JOB_ACTIONS = ("ls", "log", "kill", "forget", "check")


def parse_job_args(rest):
    """`NAME [--here] [--json] [--] CMD…` (start) or `ACTION [ID] [-f] [-n N] [--json]`. Returns a Namespace."""
    rest = list(rest)
    a = argparse.Namespace(action="ls", target=None, cmd=[], here=False, json=False, follow=False, lines=100)
    if not rest: return a
    if rest[0] in JOB_ACTIONS:
        q = argparse.ArgumentParser(prog="board job", add_help=False)
        q.add_argument("target", nargs="?"); q.add_argument("-f", "--follow", action="store_true")
        q.add_argument("-n", "--lines", type=int, default=100); q.add_argument("--json", action="store_true")
        q.parse_args(rest[1:], namespace=a); a.action = rest[0]; return a
    a.action, a.target = "start", rest.pop(0)
    while rest and rest[0] in ("--here", "--json"): setattr(a, rest.pop(0)[2:], True)
    if rest[:1] == ["--"]: rest.pop(0)
    a.cmd = rest
    return a


def cmd_job(a):
    a = parse_job_args(getattr(a, "rest", []))
    act = a.action
    if act == "start":
        name_ = a.target
        if not a.cmd: raise Fail("Usage: board job NAME -- COMMAND", USAGE)
        reg = load_registry(); name = resolve_name(name_, reg); d = devices(reg)[name]
        ensure_connected(name, d, interactive=tty())
        cmd = " ".join(a.cmd) if len(a.cmd) > 1 else a.cmd[0]
        jid = time.strftime("%m%d-%H%M%S-") + os.urandom(2).hex()
        cd = "" if a.here or not d.get("project") else remote_path(d)
        r = run_remote(name, job_start_script(jid, cmd, cd), timeout=20)
        if r.returncode or "started" not in r.stdout: raise Fail(f"Couldn't start the job on {name}: {(r.stderr or r.stdout).strip()[-200:]}")
        save_state({"_jobs": {jid: {"device": name, "cmd": cmd, "started": time.time(), "state": "running"}}})
        if a.json: print(json.dumps({"id": jid, "device": name})); return OK
        say(good(f"✓ job {jid} running on {name}") + dim(f"\n  board job log {jid} -f   ·   board job kill {jid}   ·   you get a notification when it ends"))
        return OK
    if act == "ls":
        jobs = jobs_refresh()
        rows = sorted(jobs.items(), key=lambda kv: kv[1].get("started", 0), reverse=True)[:20]
        if a.json: print(json.dumps(dict(rows), indent=1)); return OK
        if not rows: say("No jobs. Start one: board job NAME -- COMMAND"); return OK
        for jid, j in rows:
            st = j.get("state", "?")
            mark = {"running": warn("● running"), "lost": bad("✗ lost"), "stopped": dim("■ stopped")}.get(st) or (good("✓ done") if j.get("rc") == 0 else bad(f"✗ exit {j.get('rc')}"))
            say(f"{jid}  {mark:<20} {j['device']:<10} {dim(human_secs(time.time() - j.get('started', time.time())) + ' ago')}  {j['cmd'][:60]}")
        return OK
    jid = a.target
    jobs = jobs_state()
    if act in ("log", "kill", "forget"):
        if not jid: raise Fail(f"Usage: board job {act} ID   (board job ls)", USAGE)
        match = [k for k in jobs if k == jid or k.endswith(jid)]
        if len(match) != 1: raise Fail(f"No single job matches '{jid}'. See `board job ls`.", USAGE)
        jid = match[0]; dev = jobs[jid]["device"]; j = f"{JOB_DIR}/{jid}"
        if act == "forget":
            run_remote(dev, f"rm -f \"{j}\".cmd \"{j}\".log \"{j}\".rc \"{j}\".pid \"{j}\".stopped", timeout=15)
            st = load_state(); st.get("_jobs", {}).pop(jid, None); atomic_write(STATE, json.dumps(st, indent=1)); return OK
        ensure_connected(dev, devices()[dev], interactive=tty())
        if act == "log":
            if a.follow and tty(): return run_remote(dev, f"tail -n 200 -F \"{j}.log\"", tty_=True)
            r = run_remote(dev, f"tail -n {a.lines} \"{j}.log\"", timeout=20); print(r.stdout, end=""); return r.returncode
        r = run_remote(dev, f"[ ! -f \"{j}.rc\" ] && P=$(cat \"{j}.pid\") && touch \"{j}.stopped\" && "
                            f"{{ kill -TERM -$P 2>/dev/null || kill -TERM $P; }}", timeout=15)   # -PGID: dash has no `kill --`
        if r.returncode: raise Fail(f"Couldn't stop {jid} (already finished?)")
        say(good(f"✓ stopped {jid}")); return OK
    if act == "check":                       # the watcher: finished jobs not reported yet, then mark them reported
        jobs = jobs_refresh()
        ended = [k for k, j in jobs.items() if j.get("state") in ("done", "lost", "stopped") and not j.get("notified")]
        fresh = {k: jobs[k] for k in ended if jobs[k]["state"] != "stopped"}      # you stopped it: no notification
        for k in ended: jobs[k]["notified"] = time.time()
        if len(jobs) > 60:                   # keep the newest 60
            jobs = dict(sorted(jobs.items(), key=lambda kv: kv[1].get("started", 0))[-60:])
        st = load_state(); st["_jobs"] = jobs; atomic_write(STATE, json.dumps(st, indent=1))
        print(json.dumps(fresh, indent=1)); return OK
    raise Fail("board job NAME -- CMD | ls | log ID [-f] | kill ID | forget ID", USAGE)


# ── watching: device health + new devices on chosen networks, for the assistant's 5-minute watcher ──
OFFLINE_AFTER = 10 * 60


def device_problems(name, f, last_seen, now):
    """{key: (title, body)} for one device's live status."""
    out = {}
    s = f.get("state")
    if s == "offline":
        if last_seen and now - last_seen >= OFFLINE_AFTER:
            out[f"dev-offline:{name}"] = (f"{name} is offline", f"Not reachable for {human_secs(now - last_seen)}. `board doctor {name}` checks every path.")
        return out
    if s == "hostkey":
        out[f"dev-hostkey:{name}"] = (f"{name}: host key changed", "Expected after a reflash; otherwise something is impersonating it. "
                                                                    f"Check the fingerprint: board trust {name}")
    elif s == "auth":
        out[f"dev-auth:{name}"] = (f"{name} refused your key", f"board copy-id {name}")
    if s != "online": return out
    now_bits = [t for t in f.get("throttled") or [] if t.endswith(" now")]
    if now_bits: out[f"dev-power:{name}"] = (f"{name}: {', '.join(now_bits)}", "Usually the power supply or cable. Use a proper 5V 3–5A supply.")
    if (f.get("temp_c") or 0) >= 80: out[f"dev-hot:{name}"] = (f"{name} running hot", f"{f['temp_c']:.0f} °C.")
    free, total = f.get("disk_free_kb") or 0, f.get("disk_total_kb") or 0
    if total and free / total < 0.1:
        out[f"dev-disk:{name}"] = (f"{name}: disk almost full", f"{human_bytes(free * 1024)} free of {human_bytes(total * 1024)}.")
    return out


def current_net_id():
    """'gateway MAC' of the first default route: identifies a network better than its name."""
    neigh = neigh_states()
    for _, gw in sorted(gateways().items()):
        if gw in neigh: return neigh[gw][0]
        ping(gw); neigh = neigh_states()
        if gw in neigh: return neigh[gw][0]
    return ""


def watch_problems(now=None):
    now = time.time() if now is None else now
    reg = load_registry(); devs = {n: d for n, d in devices(reg).items() if d.get("alerts")}
    out = {}
    if devs:
        st = load_state()
        with cf.ThreadPoolExecutor(max(1, min(8, len(devs)))) as ex:
            res = dict(zip(devs, ex.map(lambda n: probe(n, 10), devs)))
        for n, f in res.items():
            if f["state"] == "online": save_state({n: {"seen": now}})
            out.update(device_problems(n, f, st.get(n, {}).get("seen"), now))
    watched = watch_nets(reg)
    nid = current_net_id() if watched else ""
    if nid in watched:
        for h in net_hosts(ports=False):
            if h["new"]:
                who = " · ".join(x for x in (h["name"], h["vendor"]) if x) or "unknown device"
                out[f"net-new:{h['mac'] or h['ip']}"] = (f"New device on {watched[nid]}", f"{h['ip']}  {who}  {h['mac']}")
    return out


def watch_nets(reg):
    """{router MAC: label}; stored as ["MAC label", …] because the registry is flat TOML."""
    return dict((x.split(" ", 1) + ["this network"])[:2] for x in settings(reg).get("watch_nets") or [] if x.strip())


def cmd_watch(a):
    reg = load_registry(); s = reg.setdefault(SETTINGS_KEY, {})
    if a.action == "check": print(json.dumps(watch_problems(), indent=1)); return OK
    if a.action in ("on", "off"):
        if a.target:
            name = resolve_name(a.target, reg)
            if a.action == "on": reg[name]["alerts"] = True
            else: reg[name].pop("alerts", None)
            save_registry(reg); say(good(f"✓ alerts {a.action} for {name}")); return OK
        nid = current_net_id()
        if not nid: raise Fail("No router found: connect to the network first.", OFFLINE)
        w = watch_nets(reg)
        if a.action == "on":
            w[nid] = " ".join((a.label or wifi_name() or "this network").split()); net_hosts(ports=False)   # learn who's here now
        else: w.pop(nid, None)
        s["watch_nets"] = [f"{k} {v}" for k, v in w.items()]; save_registry(reg)
        say(good(f"✓ {'watching' if a.action == 'on' else 'stopped watching'} {w.get(nid, 'this network')} for new devices")); return OK
    devs = [n for n, d in devices(reg).items() if d.get("alerts")]
    say(f"Device alerts: {', '.join(devs) or dim('none (board watch on NAME)')}")
    say(f"Networks watched for new devices: {', '.join(watch_nets(reg).values()) or dim('none (board watch on, while connected)')}")
    return OK


def wifi_name():
    for line in sh("nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi", timeout=5).stdout.splitlines():
        if line.startswith("yes:"): return line[4:].replace("\\:", ":")
    return ""


# ── ports ──
def parse_port_spec(spec):
    """'8080' → (8080, 'localhost', 8080);  '9000:80' → (9000, 'localhost', 80);  '5432:db:5432' → (5432,'db',5432)."""
    parts = str(spec).split(":")
    try:
        if len(parts) == 1: lp = rp = int(parts[0]); rh = "localhost"
        elif len(parts) == 2: lp, rp, rh = int(parts[0]), int(parts[1]), "localhost"
        elif len(parts) == 3: lp, rh, rp = int(parts[0]), parts[1], int(parts[2])
        else: raise ValueError
    except ValueError:
        raise Fail(f"'{spec}' isn't a port spec (8080, 9000:80 or 5432:host:5432)", USAGE)
    if not (0 < lp < 65536 and 0 < rp < 65536) or not HOST_RE.match(rh): raise Fail(f"'{spec}': bad port or host", USAGE)
    return lp, rh, rp


def tunnels():
    st = load_state()
    out = {}
    for n, v in st.items():
        for t in v.get("tunnels", []):
            try: os.kill(t["pid"], 0); out.setdefault(n, []).append(t)
            except (OSError, KeyError): pass
    return out


def _save_tunnels(name, items):
    st = load_state()
    st.setdefault(name, {})["tunnels"] = items
    atomic_write(STATE, json.dumps(st, indent=1))


def open_tunnel(name, flag, specs, reverse=False):
    alive = tunnels().get(name, [])
    new = []
    for spec in specs:
        lp, rh, rp = parse_port_spec(spec)
        if any(t["spec"] == f"{flag}{spec}" for t in alive): say(dim(f"{spec} already open")); continue
        fwd = f"{lp}:localhost:{rp}" if reverse else f"{lp}:{rh}:{rp}"    # reverse: device's lp → laptop's rp
        p = subprocess.Popen([*SSH_CMD, "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ControlMaster=no",
                              "-o", "ControlPath=none", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=15",
                              flag, fwd, name], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True,
                             text=True)
        time.sleep(1.2)
        if p.poll() is not None:
            e = p.stderr.read().strip().splitlines()
            raise Fail(f"Couldn't open {spec}: {e[-1] if e else 'ssh exited'}")
        new.append({"pid": p.pid, "spec": f"{flag}{spec}", "local": lp, "remote": rp, "host": rh})
    _save_tunnels(name, alive + new)
    return new


def cmd_ports(a):
    reg = load_registry()
    if a.list or (not a.name and not tty()):
        for n, ts in tunnels().items():
            for t in ts: say(f"{n:<14} {'←' if t['spec'].startswith('-R') else '→'} {t['spec'][2:]}  (pid {t['pid']})")
        return OK
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    if a.close:
        for t in tunnels().get(name, []):
            try: os.kill(t["pid"], signal.SIGTERM)
            except OSError: pass
        _save_tunnels(name, []); say(good(f"✓ closed {name}'s tunnels")); return OK
    specs = a.specs or d.get("forward", [])
    if not specs:
        raise Fail(f"Which ports? e.g. `board ports {name} 8080 5000:5000`, or save defaults: "
                   f"`board set {name} forward=8080,5000`", USAGE)
    ensure_connected(name, d, interactive=tty())
    for t in open_tunnel(name, "-L", specs):
        say(good(f"✓ http://localhost:{t['local']}") + dim(f"  → {name}:{t['remote']}"))
        if a.open: subprocess.Popen(["xdg-open", f"http://localhost:{t['local']}"], start_new_session=True,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    say(dim(f"Close with: board ports {name} --close"))
    return OK


def cmd_share(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    ensure_connected(name, d, interactive=tty())
    specs = [f"{a.as_port or p}:{p}" for p in a.ports]
    for t in open_tunnel(name, "-R", specs, reverse=True):
        say(good(f"✓ {name} can reach your laptop's port {t['remote']} at localhost:{t['local']}"))
    if "11434" in a.ports: say(dim(f"  e.g. on {name}: curl localhost:11434/api/tags   (your local AI model)"))
    say(dim(f"Close with: board ports {name} --close"))
    return OK


# ── logs, top, power ──
def cmd_logs(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    ensure_connected(name, d, interactive=tty())
    unit = f"-u {shlex.quote(a.unit)}" if a.unit else ""
    if a.why:
        r = run_remote(name, f"journalctl -b -n 300 -p warning --no-pager -o short-iso {unit} 2>/dev/null || "
                             f"tail -n 300 /var/log/syslog 2>/dev/null || dmesg | tail -n 200", timeout=30)
        text = r.stdout.strip()
        if not text: say("No warnings or errors this boot."); return OK
        if not have("fai"): say(text); return OK
        tmp = RUNTIME / f"board-logs-{name}.txt"; tmp.write_text(text)
        q = (f"These are the warnings and errors from the device '{name}' ({d.get('model') or d.get('kind') or 'Linux'}). "
             "In plain words: what is wrong, how serious, and the exact fix. Ignore harmless noise.")
        return subprocess.run(["fai", "ask", "--text-file", str(tmp), q]).returncode
    follow = "" if a.no_follow else "-f"
    cmd = (f"journalctl {follow} -n {a.lines} -o short-iso --no-hostname {unit} 2>/dev/null || "
           f"tail -n {a.lines} {follow and '-F'} /var/log/syslog")
    set_title(f"⇄ logs {name}")
    return subprocess.run([*SSH_CMD, "-t", name, cmd], env=ssh_env()).returncode


def cmd_top(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    ensure_connected(name, devices(reg)[name])
    execvp([*SSH_CMD, "-t", name, "command -v btop >/dev/null && exec btop || command -v htop >/dev/null && exec htop || exec top"], ssh_env())


def wait_state(name, d, want_up, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        host, s = race(candidates_for(name, d), d.get("port", 22), timeout=2)
        if s: s.close()
        if bool(s) == want_up: return time.time() - t0
        time.sleep(2)
    return None


def cmd_power(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    action = a.action
    if not confirm(f"{action.capitalize()} {name}?", False, a.yes): return USAGE
    ensure_connected(name, d, interactive=tty())
    cmd = f"sudo -n systemctl {action} 2>/dev/null || sudo -n {action} 2>/dev/null || sudo systemctl {action}"
    subprocess.run([*SSH_CMD, "-t", name, cmd], env=ssh_env(), stderr=subprocess.DEVNULL)
    sh(*SSH_CMD, "-O", "exit", name, timeout=3)
    say(dim(f"Waiting for {name} to go down…"))
    down = wait_state(name, d, False, 90)
    if action == "poweroff":
        say(good(f"✓ {name} is off") if down is not None else warn(f"{name} still answers")); return OK
    say(dim("…and come back"))
    up = wait_state(name, d, True, 300)
    if up is None: say(warn(f"{name} hasn't come back in 5 min. `board serial {name}` shows its console.")); return OFFLINE
    say(good(f"✓ {name} is back online") + dim(f" after {human_secs((down or 0) + up)}"))
    notify(f"{name} is back online")
    return OK


def cmd_wake(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    mac = devices(reg)[name].get("mac", "").lower()
    if not MAC_RE.match(mac): raise Fail(f"Set {name}'s MAC first: board set {name} mac=aa:bb:cc:dd:ee:ff", USAGE)
    packet = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16
    targets = {"255.255.255.255"} | {str(n.broadcast_address) for _, n in scan_nets()}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for t in targets:
            for port in (9, 7):
                try: s.sendto(packet, (t, port))
                except OSError: pass
    say(good(f"✓ wake-up sent to {name} ({mac})"))
    return OK


def cmd_forget(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    forget_hostkeys(name, devices(reg)[name])
    sh(*SSH_CMD, "-O", "exit", name, timeout=3)
    say(good(f"✓ forgot {name}'s host key; the next connection trusts the new one (and tells you)."))
    return OK


def cmd_mv(a):
    """Rename a device. Its trusted host key moves with it, so no new 'trust this key?' question."""
    reg = load_registry()
    old = resolve_name(a.old, reg)
    new = a.new
    if not NAME_RE.match(new or ""): raise Fail(f"'{new}' isn't a usable name: letters, digits, - and _.", USAGE)
    if new in reg: raise Fail(f"There's already a device called {new}.", USAGE)
    d = reg.pop(old); reg[new] = d
    save_registry(reg)
    kh = SSH / "known_hosts"
    if kh.exists():
        lines = kh.read_text().splitlines()
        extra = []
        for l in lines:
            f = l.split(None, 1)
            if len(f) == 2 and old in f[0].split(","): extra.append(f"{new} {f[1]}")
        if extra: atomic_write(kh, "\n".join(lines + extra) + "\n", 0o600)
    st = load_state()
    if old in st:
        st[new] = st.pop(old)
        try: atomic_write(STATE, json.dumps(st, indent=1))
        except OSError: pass
    sh(*SSH_CMD, "-O", "exit", old, timeout=3)
    remove_bookmark(old); add_bookmark(new, d); update_vscode_platforms()
    say(good(f"✓ {old} is now {new}"))
    return OK


def scan_fingerprint(name, d):
    """SHA256 fingerprints the device offers right now (ssh-keyscan through our path finder)."""
    host, s, _ = find_path(name, d, timeout=5)
    ip = s.getpeername()[0]; s.close()
    r = sh("ssh-keyscan", "-T", "5", "-p", str(d.get("port", 22)), "-t", "ed25519,ecdsa,rsa", ip, timeout=10)
    out = sh("ssh-keygen", "-lf", "-", input=r.stdout, timeout=5).stdout if r.stdout else ""
    return [line.split()[1] + " (" + line.split()[-1].strip("()") + ")" for line in out.splitlines() if len(line.split()) >= 2]


def cmd_trust(a):
    """After a reflash: show the new host key, then (unless --check) trust it."""
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    fps = scan_fingerprint(name, d)
    if a.check:
        print(json.dumps({"name": name, "fingerprints": fps, "flashed_at": d.get("flashed_at", "")})); return OK
    if not fps: raise Fail(f"{name} didn't offer a host key. Is SSH running on it?", OFFLINE)
    say("New host key: " + ", ".join(fps))
    if not confirm(f"Trust it for {name}?", bool(d.get("flashed_at")), a.yes): return USAGE
    forget_hostkeys(name, d)
    sh(*SSH_CMD, "-O", "exit", name, timeout=3)
    r = sh(*ssh_base(batch=True, extra=["-o", "StrictHostKeyChecking=accept-new"]), name, "true", timeout=20)
    st = classify_ssh_error(r.stderr, r.returncode)
    if st in ("ok", "remote"): say(good(f"✓ {name}'s new key is trusted")); return OK
    if st == "auth": say(warn(f"Key trusted, but {name} refused your login key. Send it again: board copy-id {name}")); return AUTH
    raise Fail(f"Couldn't connect after trusting: {r.stderr.strip()[-200:]}", OFFLINE)


# ───────────────────────────── serial ─────────────────────────────
USB_IDS = {  # vid:pid → friendly
    "2e8a:0003": "Raspberry Pi Pico (BOOTSEL: ready to flash)", "2e8a:0005": "Raspberry Pi Pico (MicroPython)",
    "2e8a:000a": "Raspberry Pi Pico (C/C++ SDK)", "2e8a:000c": "Raspberry Pi Debug Probe", "2e8a:000f": "Raspberry Pi Pico 2 (BOOTSEL)",
    "303a:1001": "ESP32 (USB-JTAG/serial)", "303a:0002": "ESP32-S2", "10c4:ea60": "CP210x USB-serial (often ESP32)",
    "1a86:7523": "CH340 USB-serial", "1a86:55d4": "CH9102 USB-serial (often ESP32)", "0403:6001": "FTDI FT232 USB-serial",
    "0403:6010": "FTDI FT2232 (JTAG/serial)", "0403:6014": "FTDI FT232H", "067b:2303": "PL2303 USB-serial",
    "0483:3748": "ST-Link/V2", "0483:374b": "ST-Link/V2-1 (Nucleo)", "0483:374e": "ST-Link/V3", "0483:3752": "ST-Link/V2-1",
    "0d28:0204": "CMSIS-DAP (DAPLink)", "1366:0101": "SEGGER J-Link", "1366:1015": "SEGGER J-Link",
    "2341:0043": "Arduino Uno", "2341:0042": "Arduino Mega", "2341:8036": "Arduino Leonardo", "2341:0070": "Arduino Nano ESP32",
    "239a:8029": "Adafruit Feather", "1d50:6018": "Black Magic Probe", "0525:a4a7": "Linux USB gadget serial",
    "0525:a4a2": "Linux USB gadget Ethernet", "1d6b:0104": "Linux USB gadget (composite)",
}


def usb_props(dev):
    """vid, pid, product, serial for a tty, from sysfs."""
    p = Path("/sys/class/tty") / Path(os.path.realpath(dev)).name / "device"
    for up in [p] + list(p.resolve().parents)[:5]:
        if (up / "idVendor").exists():
            r = lambda f: (up / f).read_text().strip() if (up / f).exists() else ""
            return {"vid": r("idVendor"), "pid": r("idProduct"), "product": r("product"), "manufacturer": r("manufacturer"),
                    "serial": r("serial")}
    return {}


def serial_ports(reg=None):
    """[{path, by_id, dev, label, device}] — stable /dev/serial/by-id paths first."""
    devs = devices(reg)
    by_serial = {os.path.realpath(d["serial"]): n for n, d in devs.items() if d.get("serial")}
    seen, out = set(), []
    byid = Path("/dev/serial/by-id")
    paths = sorted(byid.glob("*")) if byid.exists() else []
    import glob as _g
    for p in [str(x) for x in paths] + sorted(_g.glob("/dev/ttyUSB*") + _g.glob("/dev/ttyACM*")):
        real = os.path.realpath(p)
        if real in seen: continue
        seen.add(real)
        u = usb_props(real)
        key = f"{u.get('vid', '')}:{u.get('pid', '')}"
        label = USB_IDS.get(key) or " ".join(x for x in (u.get("manufacturer"), u.get("product")) if x) or \
            re.sub(r"^usb-|-if\d+.*$|_", " ", Path(p).name).strip()
        out.append({"path": p, "dev": real, "label": label, "usb": key, "device": by_serial.get(real, ""),
                    "access": os.access(real, os.R_OK | os.W_OK)})
    return out


def cmd_serial(a):
    reg = load_registry()
    s = settings(reg)
    ports = serial_ports(reg)
    if a.list:
        for p in ports: print(f"{p['path']}\t{p['label']}\t{p['device']}")
        return OK
    target, baud, label = a.target, a.baud, None
    if target and (target.startswith("/dev/") or Path(target).exists()):
        dev = target
    elif target:
        name = resolve_name(target, reg)
        d = devices(reg)[name]
        dev = d.get("serial")
        if not dev:
            if len(ports) == 1 and confirm(f"Use {ports[0]['label']} as {name}'s console (saved)?", True):
                reg[name]["serial"] = ports[0]["path"]; save_registry(reg); dev = ports[0]["path"]
            else: raise Fail(f"{name} has no serial port set: board set {name} serial=/dev/serial/by-id/…", USAGE)
        baud = baud or d.get("baud"); label = name
    else:
        if not ports:
            raise Fail("No serial device plugged in. Connect a USB-serial adapter (TX→RX, RX→TX, GND→GND) "
                       "or a board's USB port.", OFFLINE)
        items = [(p["path"], f"{p['label']:<44} {dim(p['device'] or Path(p['dev']).name)}") for p in ports]
        dev = pick(items, "serial port")
    if not Path(dev).exists(): raise Fail(f"{dev} isn't plugged in.", OFFLINE)
    if not label:
        label = next((p["device"] for p in ports if os.path.realpath(p["path"]) == os.path.realpath(dev) and p["device"]), "") \
            or Path(os.path.realpath(dev)).name
        if not baud: baud = next((d.get("baud") for n, d in devices(reg).items() if n == label), None)
    baud = int(baud or s["baud"])
    if not os.access(os.path.realpath(dev), os.R_OK | os.W_OK):
        raise Fail(f"No permission for {dev}. Add yourself to the dialout group once, then log out and back in:\n"
                   f"  ! sudo usermod -aG dialout $USER", AUTH)
    logdir = LOGS / label; logdir.mkdir(parents=True, exist_ok=True)
    log = logdir / f"{dt.datetime.now():%Y-%m-%d_%H%M%S}.log"
    set_title(f"⌁ {label} · {baud}")
    if have("tio"):
        say(dim(f"⌁ {label} at {baud} baud · log: {log}\n  Ctrl+T Q quit · Ctrl+T B send break · Ctrl+T ? help"))
        args = ["tio", "-b", str(baud), "--timestamp", "--log", "--log-file", str(log)]
        if a.hex: args += ["--input-mode", "hex", "--output-mode", "hex"]
        execvp(args + [dev])
    if have("picocom"):
        say(dim(f"⌁ {label} at {baud} baud · log: {log}\n  Ctrl+A Ctrl+X quit"))
        execvp(["picocom", "-b", str(baud), "--logfile", str(log), "-q", dev])
    if have("screen"):
        say(dim(f"⌁ {label} at {baud} baud (screen; install tio for logs and auto-reconnect)\n  Ctrl+A K quit"))
        execvp(["screen", dev, str(baud)])
    raise Fail("No serial program found: run `bash scripts/phase12-embedded.sh` (installs tio).")


def cmd_serial_last(a):
    logs = sorted(LOGS.glob("*/*.log"), key=lambda p: p.stat().st_mtime)
    if not logs: raise Fail("No serial logs yet.")
    execvp(["less", "+G", "-R", str(logs[-1])])


# ───────────────────────────── scan ─────────────────────────────
_OUI = None
OUI_FALLBACK = {"B827EB": "Raspberry Pi", "DCA632": "Raspberry Pi", "E45F01": "Raspberry Pi", "D83ADD": "Raspberry Pi",
                "2CCF67": "Raspberry Pi", "28CDC1": "Raspberry Pi", "88A29E": "Raspberry Pi", "48B02D": "NVIDIA (Jetson)",
                "00044B": "NVIDIA (Jetson)", "240AC4": "Espressif (ESP32)", "30AEA4": "Espressif (ESP32)",
                "A4CF12": "Espressif (ESP32)", "246F28": "Espressif (ESP32)", "7C9EBD": "Espressif (ESP32)"}


def vendor(mac):
    global _OUI
    if not mac: return ""
    if _OUI is None:
        _OUI = dict(OUI_FALLBACK)
        p = Path("/usr/share/nmap/nmap-mac-prefixes")
        if p.exists():
            for line in p.read_text(errors="ignore").splitlines():
                if len(line) > 7 and not line.startswith("#"): _OUI.setdefault(line[:6].upper(), line[7:].strip())
    pre = mac.replace(":", "").upper()
    if pre.startswith(USB_PREFIX_DEV.replace(":", "").upper()): return "board USB cable"
    if int(pre[1], 16) & 2: return "random MAC (phone/laptop privacy)"
    return _OUI.get(pre[:6], "")


def guess_kind(vend, services):
    v = (vend or "").lower()
    if "raspberry" in v: return "pi"
    if "nvidia" in v: return "jetson"
    if "espressif" in v or any("esphome" in s or "arduino" in s for s in services): return "mcu"
    return "linux"


def avahi_hosts(timeout=6):
    out = {}
    if not have("avahi-browse"): return out
    r = sh("avahi-browse", "-aprt", "--no-db-lookup", timeout=timeout + 2)
    for line in r.stdout.splitlines():
        f = line.split(";")
        if len(f) >= 9 and f[0] == "=" and f[2] == "IPv4":
            h = out.setdefault(f[7], {"name": f[6], "services": set()})
            h["services"].add(f[4]); h["name"] = f[6]
    return out


def nmap_ssh(net, port=22):
    if not have("nmap"): return [h for h in sweep(net, port, 0.5, 1024)]
    r = sh("nmap", "-Pn", "-n", "-sT", f"-p{port}", "--open", "-T4", "--max-retries", "1", "--host-timeout", "4s",
           "-oG", "-", str(net), timeout=180)
    return re.findall(r"Host: (\S+) .*Ports: \d+/open", r.stdout)


def do_scan(nets=None, port=22):
    nets = nets or scan_nets()
    with cf.ThreadPoolExecutor(8) as ex:
        fav = ex.submit(avahi_hosts)
        fssh = {str(n): ex.submit(nmap_ssh, n, port) for _, n in nets}
        av = fav.result()
        ssh_open = {ip for f in fssh.values() for ip in f.result()}
    mine = {str(i.ip) for _, i in local_nets()}
    neigh = {ip: mac for mac, ips in ip_neigh().items() for ip in ips}
    reg = devices()
    st = load_state()
    known = {}
    for n, d in reg.items():
        for v in (d.get("host"), st.get(n, {}).get("ip"), f"{n}.local"): known[v] = n
        for k in ("mac", "usb_mac"):
            if d.get(k): known[d[k].lower()] = n
    found = []
    for ip in sorted(ssh_open | set(av), key=lambda x: tuple(int(p) for p in x.split(".")) if re.match(r"^[\d.]+$", x) else (999,)):
        if ip in mine or not re.match(r"^\d+\.\d+\.\d+\.\d+$", ip): continue
        mac = neigh.get(ip, "")
        a = av.get(ip, {})
        name = a.get("name", "")
        services = sorted(s.replace("._tcp", "").lstrip("_") for s in a.get("services", []))
        v = vendor(mac)
        found.append({"ip": ip, "name": name, "mac": mac, "vendor": v, "ssh": ip in ssh_open,
                      "services": services, "kind": guess_kind(v, services), "via": via_label(ip),
                      "known": known.get(ip) or known.get(name) or known.get(mac, "")})
    return found


def cmd_scan(a):
    nets = scan_nets()
    if a.net:
        try: nets = [("custom", ipaddress.ip_network(a.net, strict=False))]
        except ValueError: raise Fail(f"'{a.net}' isn't a network (like 192.168.1.0/24)", USAGE)
        if nets[0][1].num_addresses > 4096 and not confirm(f"{a.net} has {nets[0][1].num_addresses} addresses; "
                                                            "this can take minutes. Continue?", False, a.yes): return USAGE
    if not a.json: say(dim(f"Scanning {', '.join(f'{n} ({iface_kind(i)})' for i, n in nets)} …"))
    found = do_scan(nets, a.port)
    if a.json: print(json.dumps(found, indent=1)); return OK
    if not found: say("Nothing with SSH or mDNS found. Is the device on the same network? Try `board usb` or `board link`."); return OK
    items = []
    for f in found:
        tag = good(f"✓ {f['known']}") if f["known"] else (good("ssh") if f["ssh"] else dim("no ssh"))
        label = f"{f['ip']:<15} {(f['name'] or '?')[:26]:<26} {dim((f['vendor'] or '')[:24]):<34} {f['via']:<10} {tag}"
        items.append((f["ip"], label))
        if not tty() or a.list: say(label)
    if a.list or not tty(): return OK
    choice = pick(items, "add which (Esc = none)")
    f = next(x for x in found if x["ip"] == choice)
    if f["known"]: say(f"Already added as {f['known']}."); return OK
    suggested = (f["name"].replace(".local", "") or f"dev-{f['ip'].split('.')[-1]}")
    suggested = re.sub(r"[^A-Za-z0-9_-]", "-", suggested)
    name = ask("Name", suggested)
    host = f["name"] if f["name"].endswith(".local") else f["ip"]
    ns = argparse.Namespace(name=name, host=host, user=None, port=None, kind=f["kind"] if f["kind"] != "mcu" else None,
                            project=None, local=None, jump=None, identity=None, serial=None,
                            mac=f["mac"] if f["mac"] and not vendor(f["mac"]).startswith("random") else None,
                            notes=None, tag=None, no_proxy=False, agent=False, update=False, offline=False,
                            no_copy_id=False, yes=False)
    return cmd_add(ns)


# ───────────────────────────── network: who's here, what's open ─────────────────────────────
COMMON_PORTS = {21: "ftp", 22: "ssh", 23: "telnet", 53: "dns", 80: "http", 139: "netbios", 443: "https", 445: "smb",
                548: "afp", 554: "rtsp camera", 631: "printer (ipp)", 1883: "mqtt", 1900: "upnp", 3000: "dev server",
                3389: "rdp", 5000: "dev server", 5353: "mdns", 5900: "vnc", 8000: "http-alt", 8008: "chromecast",
                8080: "http-alt", 8123: "home assistant", 8443: "https-alt", 8883: "mqtt (tls)", 9100: "printer",
                11434: "ollama", 32400: "plex", 62078: "iphone sync"}


def gateways():
    """{iface: gateway ip} from the default routes."""
    try: return {r["dev"]: r["gateway"] for r in json.loads(sh("ip", "-j", "-4", "route", "show", "default", timeout=3).stdout or "[]")
                 if r.get("gateway") and r.get("dev")}
    except ValueError: return {}


def neigh_states():
    """{ip: (mac, [states])} for IPv4 neighbours that have a MAC."""
    out = {}
    try:
        for n in json.loads(sh("ip", "-j", "-4", "neigh", timeout=3).stdout or "[]"):
            if n.get("lladdr") and n.get("dst"): out[n["dst"]] = (n["lladdr"].lower(), n.get("state", []))
    except ValueError: pass
    return out


def ping(ip, wait=1):
    return sh("ping", "-c1", "-n", "-q", f"-W{wait}", ip, timeout=wait + 2).returncode == 0


def probe_ports(ip, ports, timeout=0.4):
    """Open TCP ports on one host (plain connect, nothing sent)."""
    if not ports: return []
    def one(p):
        try:
            with socket.create_connection((ip, p), timeout=timeout): return p
        except OSError: return None
    with cf.ThreadPoolExecutor(min(64, len(ports))) as ex:
        return sorted(p for p in ex.map(one, ports) if p)


def rdns(ip):
    try: return socket.gethostbyaddr(ip)[0]
    except OSError: return ""


MAX_TARGETS = 4096   # a /20; bigger networks need --net with a smaller range


def live_hosts(nets, wide=True):
    """Every host that answers ping OR ARP on these networks. Pinging fills the ARP table, so devices that drop
    ping (phones, Windows, most IoT) still show up as REACHABLE neighbours. wide=False (a custom --net): nothing
    outside `nets` is added."""
    total = sum(n.num_addresses for _, n in nets)
    if total > MAX_TARGETS:
        raise Fail(f"That's {total} addresses; the limit is {MAX_TARGETS}. Use --net with a smaller range (like a /24).", USAGE)
    targets = list(dict.fromkeys(str(h) for _, n in nets for h in n.hosts()))
    with cf.ThreadPoolExecutor(128) as ex: answered = {ip for ip, ok in zip(targets, ex.map(ping, targets)) if ok}
    time.sleep(0.5)                                           # let the last ARP replies land
    # the interfaces' real subnets too (a /16 Wi-Fi's router is often outside our /24): only hosts we already talk to
    scope = [n for _, n in nets] + ([ipi.network for _, ipi in local_nets()] if wide else [])
    inside = lambda ip: any(ipaddress.ip_address(ip) in n for n in scope)
    neigh = neigh_states()
    arp = {ip for ip, (_, st) in neigh.items() if inside(ip) and set(st) & {"REACHABLE", "DELAY", "PROBE"}}   # PERMANENT = a static entry, not proof it's on
    return answered | arp, neigh


def net_hosts(nets=None, ports=True):
    wide = nets is None
    if nets is None: nets = scan_nets()
    alive, neigh = live_hosts(nets, wide)
    mine = {str(i.ip) for _, i in local_nets()}
    gws = {g for i, g in gateways().items() if wide and any(i == iface for iface, _ in nets)
           or any(ipaddress.ip_address(g) in n for _, n in nets)}   # only routers of the networks being looked at
    alive |= {ip for ip in mine if any(ipaddress.ip_address(ip) in n for _, n in nets)} | gws
    with cf.ThreadPoolExecutor(32) as ex:
        fav = ex.submit(avahi_hosts)
        names = dict(zip(alive, ex.map(rdns, alive)))
        open_ = dict(zip(alive, ex.map(lambda ip: probe_ports(ip, list(COMMON_PORTS)), alive))) if ports else {}
        av = fav.result()
    reg, st = devices(), load_state()
    known = {}
    for n, d in reg.items():
        for v in (d.get("host"), st.get(n, {}).get("ip")): known[v] = n
        for k in ("mac", "usb_mac"):
            if d.get(k): known[d[k].lower()] = n
    seen = st.get("_net_seen", {})
    first_run, now, out = not seen, time.time(), []
    for ip in sorted(alive, key=lambda x: tuple(int(p) for p in x.split("."))):
        mac = neigh.get(ip, ("", []))[0]
        name = av.get(ip, {}).get("name") or names.get(ip, "")
        v = vendor(mac)
        role = "this laptop" if ip in mine else "router" if ip in gws else ""
        key = mac or ip
        out.append({"ip": ip, "name": name, "mac": mac, "vendor": v, "role": role,
                    "ports": open_.get(ip, []), "known": known.get(ip) or known.get(mac, ""),
                    "new": not first_run and key not in seen and ip not in mine, "via": via_label(ip)})
        seen.setdefault(key, now)
    save_state({"_net_seen": seen})
    return out


def port_label(p):
    if p in COMMON_PORTS: return COMMON_PORTS[p]
    try: return socket.getservbyport(p)
    except OSError: return ""


def cmd_net(a):
    if a.action == "info": return net_info(a)
    if a.action == "ports": return net_ports(a)
    nets = scan_nets()
    if a.net:
        try: nets = [("custom", ipaddress.ip_network(a.net, strict=False))]
        except ValueError: raise Fail(f"'{a.net}' isn't a network (like 192.168.1.0/24)", USAGE)
        if not local_net_ok(nets[0][1]): raise Fail(f"{a.net} isn't a network this laptop is on. `board net` only looks at your own networks.", USAGE)
        if nets[0][1].num_addresses > 1024 and not confirm(f"{a.net} has {nets[0][1].num_addresses} addresses; this takes a while. Continue?", False, a.yes): return USAGE
    if not nets: raise Fail("Not connected to any network.", OFFLINE)
    if not a.json: say(dim(f"Looking at {', '.join(f'{n} ({iface_kind(i)})' for i, n in nets)} …"))
    hosts = net_hosts(None if not a.net else nets, ports=not a.fast)
    if a.json: print(json.dumps(hosts, indent=1)); return OK
    say(bold(f"{'IP':<15} {'NAME':<28} {'VENDOR':<26} OPEN"))
    for h in hosts:
        tag = " ".join(x for x in (good(f"✓ {h['known']}") if h["known"] else "", warn("new") if h["new"] else "",
                                   dim(h["role"]) if h["role"] else "") if x)
        ports = ",".join(str(p) for p in h["ports"]) or dim("–")
        say(f"{h['ip']:<15} {(h['name'] or '?')[:28]:<28} {(h['vendor'] or dim('unknown'))[:26]:<26} {ports}  {tag}")
    new = sum(h["new"] for h in hosts)
    if all(h["role"] for h in hosts):
        say(dim("Only this laptop and the router answered. Office, campus and guest Wi-Fi usually hide devices from each "
                "other (client isolation); at home or on `board hotspot` you'll see everything."))
    say(dim(f"\n{len(hosts)} devices" + (f", {new} new since last time" if new else "") +
            ". Ports: `board net ports IP` · add an SSH one: `board scan`"))
    return OK


def local_net_ok(target):
    """Only our own networks (lab rule: no scanning beyond them)."""
    nets = [n for _, n in scan_nets()] + [ipi.network for _, ipi in local_nets()]
    if isinstance(target, ipaddress.IPv4Network): return any(target.subnet_of(n) for n in nets if n.version == 4)
    return any(target in n for n in nets) or target.is_loopback


def parse_ports(spec):
    """'22,80,8000-8100' -> sorted unique ports; validates before expanding (no huge or reversed ranges)."""
    out = set()
    for part in spec.split(","):
        lo, dash, hi = part.strip().partition("-")
        if not lo.isdigit() or (dash and not hi.isdigit()): raise Fail(f"Bad port list '{spec}' (like 22,80,8000-8100)", USAGE)
        a, b = int(lo), int(hi) if dash else int(lo)
        if not 1 <= a <= b <= 65535: raise Fail(f"'{part.strip()}': ports go from 1 to 65535, low-high.", USAGE)
        out.update(range(a, b + 1))
    return sorted(out)


def net_ports(a):
    if not a.target: raise Fail("Usage: board net ports HOST [--ports 1-1024]", USAGE)
    host = devices().get(a.target, {}).get("host") or a.target
    try: ip = ipaddress.ip_address(socket.gethostbyname(host))
    except OSError: raise Fail(f"Can't resolve {host}.", OFFLINE)
    if not local_net_ok(ip): raise Fail(f"{ip} isn't on a network this laptop is on. `board net ports` only checks your own LAN.", USAGE)
    ports = list(COMMON_PORTS)
    if a.ports:
        ports = parse_ports(a.ports)
    if not a.json: say(dim(f"Checking {len(ports)} TCP ports on {ip} …"))
    found = probe_ports(str(ip), ports, timeout=0.6)
    if a.json: print(json.dumps([{"port": p, "service": port_label(p)} for p in found])); return OK
    if not found: say("No open TCP ports (or a firewall drops them)."); return OK
    for p in found: say(f"  {p:>5}  {port_label(p)}")
    return OK


def net_info(a):
    info = {"interfaces": [], "gateways": gateways(), "dns": [], "wifi": {}}
    for iface, ipi in local_nets():
        info["interfaces"].append({"iface": iface, "kind": iface_kind(iface), "ip": str(ipi)})
    def is_ip(w):
        try: return bool(ipaddress.ip_address(w.split("#")[0]))
        except ValueError: return False
    r = sh("resolvectl", "dns", timeout=3)
    info["dns"] = list(dict.fromkeys(w.split("#")[0] for line in r.stdout.splitlines() for w in line.split(":", 1)[-1].split() if is_ip(w)))
    if not info["dns"]:
        try: info["dns"] = re.findall(r"^nameserver\s+(\S+)", Path("/etc/resolv.conf").read_text(), re.M)
        except OSError: pass
    for line in sh("nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,CHAN,RATE,SECURITY", "dev", "wifi", timeout=5).stdout.splitlines():
        f = re.split(r"(?<!\\):", line)
        if f[0] == "yes" and len(f) >= 6:
            info["wifi"] = {"ssid": f[1].replace("\\:", ":"), "signal": f[2], "channel": f[3], "rate": f[4], "security": f[5]}
    if a.public:                                             # opt-in: asks an outside service, sends nothing about you
        import urllib.request
        try: info["public_ip"] = urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode().strip()
        except OSError as e: info["public_ip"] = f"unknown ({e})"
    if a.json: print(json.dumps(info, indent=1)); return OK
    for i in info["interfaces"]:
        gw = info["gateways"].get(i["iface"])
        say(f"{bold(i['kind'].ljust(10))} {i['iface']:<16} {i['ip']:<20} {dim('router ' + gw) if gw else ''}")
    if info["wifi"]:
        w = info["wifi"]; say(f"Wi-Fi  {w['ssid']} · signal {w['signal']}% · channel {w['channel']} · {w['rate']} · {w['security'] or 'open'}")
    if info["dns"]: say(f"DNS    {', '.join(info['dns'])}")
    if "public_ip" in info: say(f"Public {info['public_ip']}")
    return OK


# ───────────────────────────── field connections ─────────────────────────────
def usb_macs(name):
    h = hashlib.sha1(name.encode()).hexdigest()[:8]
    tail = ":".join(h[i:i + 2] for i in range(0, 8, 2))
    return f"{USB_PREFIX_HOST}:{tail}", f"{USB_PREFIX_DEV}:{tail}"


def nm_has(con): return sh("nmcli", "-t", "-f", "NAME", "con", "show", timeout=5).stdout.splitlines().count(con) > 0


def nm_active(con): return con in sh("nmcli", "-t", "-f", "NAME", "con", "show", "--active", timeout=5).stdout.splitlines()


def ensure_nm_usb():
    """Laptop side of USB-cable mode: any board gadget (MAC 02:b0:…) gets 10.55.0.1 and DHCP from NetworkManager."""
    if nm_has(NM_USB): return True
    r = sh("nmcli", "con", "add", "type", "ethernet", "con-name", NM_USB, "ifname", "*",
           "match.interface-name", "enx" + USB_PREFIX_HOST.replace(":", "") + "*",
           "ipv4.method", "shared", "ipv4.addresses", USB_NET, "ipv6.method", "link-local",
           "connection.autoconnect", "yes", "connection.autoconnect-priority", "50", timeout=15)
    if r.returncode != 0: raise Fail(f"Couldn't create the USB network profile: {r.stderr.strip()}")
    return True


def gadget_script(host_mac, dev_mac, enable=True):
    if not enable:
        return r"""set -e
B=/boot/firmware; [ -f $B/config.txt ] || B=/boot
sudo sed -i '/^dtoverlay=dwc2/d' $B/config.txt
sudo sed -i 's/ modules-load=dwc2,g_ether[^ ]*//; s/ g_ether.host_addr=[^ ]*//; s/ g_ether.dev_addr=[^ ]*//' $B/cmdline.txt
command -v nmcli >/dev/null && sudo nmcli con delete board-usb >/dev/null 2>&1 || true
echo done"""
    return rf"""set -e
B=/boot/firmware; [ -f $B/config.txt ] || B=/boot
[ -f $B/cmdline.txt ] || {{ echo "NOPI: no $B/cmdline.txt (not Raspberry Pi OS?)"; exit 3; }}
grep -q '^dtoverlay=dwc2' $B/config.txt || printf '\n[all]\ndtoverlay=dwc2,dr_mode=peripheral\n' | sudo tee -a $B/config.txt >/dev/null
if ! grep -q 'modules-load=dwc2,g_ether' $B/cmdline.txt; then
  sudo sed -i 's/ g_ether.host_addr=[^ ]*//; s/ g_ether.dev_addr=[^ ]*//' $B/cmdline.txt
  sudo sed -i '1 s/$/ modules-load=dwc2,g_ether g_ether.host_addr={host_mac} g_ether.dev_addr={dev_mac}/' $B/cmdline.txt
fi
if command -v nmcli >/dev/null; then
  sudo nmcli con show board-usb >/dev/null 2>&1 || sudo nmcli con add type ethernet ifname usb0 con-name board-usb \
    ipv4.method auto ipv4.may-fail yes ipv6.method link-local connection.autoconnect yes >/dev/null
fi
echo done"""


def cmd_usb(a):
    reg = load_registry()
    if a.action == "status":
        rows = [(i, str(n)) for i, n in local_nets() if iface_kind(i) == "USB cable"]
        say(f"Laptop profile '{NM_USB}': " + (good("ready") if nm_has(NM_USB) else warn("missing (board usb setup)")))
        if not rows: say(dim("No device on a USB cable right now.")); return OK
        for i, n in rows:
            hits = [h for h in sweep(ipaddress.ip_interface(n).network, 22) if h != n.split("/")[0]]
            say(f"  {i}: {n}  devices: {', '.join(hits) or dim('none answering on ssh yet (booting?)')}")
        return OK
    if a.action == "setup":
        ensure_nm_usb(); say(good(f"✓ laptop ready: any board on a USB cable gets an address (10.55.0.x).")); return OK
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    host_mac, dev_mac = usb_macs(name)
    ensure_connected(name, d, interactive=tty())
    model = d.get("model", "")
    if a.action == "enable" and re.search(r"Pi (3|2|1) |Pi Model B(?! Rev)|Pi 3 Model|Pi 2 Model", model):
        raise Fail(f"{model} has no USB device (OTG) port; USB-cable mode needs a Pi Zero, Zero 2, 4, 5 or CM. "
                   f"Use a direct Ethernet cable instead: `board link on`.")
    r = run_remote(name, gadget_script(host_mac, dev_mac, a.action == "enable"), timeout=60)
    if r.returncode != 0 or "done" not in r.stdout:
        raise Fail(("Not Raspberry Pi OS: " if "NOPI" in r.stdout else "Failed: ") + (r.stderr or r.stdout).strip()[-300:])
    if a.action == "enable":
        ensure_nm_usb()
        reg[name]["usb_mac"] = dev_mac; save_registry(reg)
        say(good(f"✓ USB-cable mode is set up on {name}."))
        say("  Reboot it, then plug a data USB cable into its USB-C/OTG port (Pi Zero: the inner 'USB' port).")
        say(dim(f"  The laptop gives it 10.55.0.x; `board ssh {name}` finds it on the cable by itself."))
        if confirm(f"Reboot {name} now?", False): subprocess.run([*SSH_CMD, name, "sudo reboot"], stderr=subprocess.DEVNULL)
    else:
        reg[name].pop("usb_mac", None); save_registry(reg)
        say(good(f"✓ USB-cable mode removed from {name} (applies after a reboot)."))
    return OK


def default_iface(kind):
    r = sh("nmcli", "-t", "-f", "DEVICE,TYPE", "dev", timeout=5)
    for line in r.stdout.splitlines():
        dev, _, typ = line.rpartition(":")
        if typ == kind and not dev.startswith(("docker", "veth", "br-", "virbr", "p2p")): return dev
    return ""


def cmd_link(a):
    reg = load_registry()
    iface = settings(reg)["eth_iface"] or default_iface("ethernet")
    if not iface: raise Fail("No Ethernet port found on this laptop (USB-Ethernet adapters work too).")
    if not nm_has(NM_ETH):
        r = sh("nmcli", "con", "add", "type", "ethernet", "con-name", NM_ETH, "ifname", iface, "ipv4.method", "shared",
               "ipv4.addresses", ETH_NET, "ipv6.method", "link-local", "connection.autoconnect", "no", timeout=15)
        if r.returncode != 0: raise Fail(f"Couldn't create the Ethernet profile: {r.stderr.strip()}")
    if a.action == "on":
        r = sh("nmcli", "con", "up", NM_ETH, timeout=30)
        if r.returncode != 0:
            raise Fail(f"Couldn't start it: {r.stderr.strip()}\nIs a cable plugged into {iface}?")
        say(good(f"✓ direct Ethernet on {iface}: devices on the cable get 10.42.0.x, and your Wi-Fi internet is shared."))
        say(dim("  Plug the device in and power it; then `board scan` or `board ssh NAME`. Turn off: board link off"))
    elif a.action == "off":
        sh("nmcli", "con", "down", NM_ETH, timeout=15); say(good("✓ direct Ethernet off (normal wired networking back)"))
    else:
        on = nm_active(NM_ETH)
        say(f"Direct Ethernet ({iface}): " + (good("on") if on else dim("off")))
        if on:
            hits = sweep(ipaddress.ip_network("10.42.0.0/24"), 22)
            say(f"  devices with ssh: {', '.join(h for h in hits if h != '10.42.0.1') or dim('none yet')}")
    return OK


def cmd_hotspot(a):
    reg = load_registry()
    s = settings(reg)
    iface = s["wifi_iface"] or default_iface("wifi")
    ssid = s["hotspot_ssid"] or f"{socket.gethostname()}-lab"
    if a.action == "on":
        if not confirm("Your Wi-Fi internet drops while the hotspot is on (one radio). Start it?", True, a.yes): return USAGE
        if nm_has(NM_HOTSPOT): r = sh("nmcli", "con", "up", NM_HOTSPOT, timeout=30)
        else:
            pw = secrets.token_urlsafe(9)
            r = sh("nmcli", "dev", "wifi", "hotspot", "ifname", iface, "con-name", NM_HOTSPOT, "ssid", ssid,
                   "password", pw, timeout=30)
            if r.returncode == 0: sh("nmcli", "con", "modify", NM_HOTSPOT, "connection.autoconnect", "no", timeout=10)
        if r.returncode != 0: raise Fail(f"Couldn't start the hotspot: {r.stderr.strip()}")
        say(good(f"✓ hotspot '{ssid}' is on.") + f"  password: {hotspot_password()}")
        say(dim("  Boards flashed with `board flash` join it by themselves. Off: board hotspot off"))
    elif a.action == "off":
        sh("nmcli", "con", "down", NM_HOTSPOT, timeout=15); say(good("✓ hotspot off; Wi-Fi reconnects by itself"))
    else:
        on = nm_active(NM_HOTSPOT)
        say(f"Hotspot '{ssid}': " + (good("on") if on else dim("off")) + (f"  password: {hotspot_password()}" if nm_has(NM_HOTSPOT) else ""))
        if on:
            hits = sweep(ipaddress.ip_network("10.42.0.0/24"), 22)
            say(f"  devices with ssh: {', '.join(h for h in hits if h != '10.42.0.1') or dim('none yet')}")
    return OK


def carrier(iface):
    try: return Path(f"/sys/class/net/{iface}/carrier").read_text().strip() == "1"
    except OSError: return False


def links_state():
    """Everything the Remote panel needs to guide setup: key, tools, groups, and each field connection."""
    reg = load_registry(); s = settings(reg)
    eth = s["eth_iface"] or default_iface("ethernet") or ""
    wifi = s["wifi_iface"] or default_iface("wifi") or ""
    usb_ifaces = [i for i in os.listdir("/sys/class/net") if i.startswith(("enx" + USB_PREFIX_HOST.replace(":", ""), "usb"))]
    return {
        "key": bool(key_path()), "key_path": str(key_path() or ""),
        "missing": [t for t in TOOLS if not have(t) and t != "code"], "dialout": in_group("dialout"),
        "eth": {"iface": eth, "cable": carrier(eth) if eth else False, "on": nm_active(NM_ETH)},
        "usb": {"ready": nm_has(NM_USB), "connected": usb_ifaces},
        "hotspot": {"iface": wifi, "on": nm_active(NM_HOTSPOT), "ssid": s["hotspot_ssid"] or f"{socket.gethostname()}-lab",
                    "password": hotspot_password() if nm_has(NM_HOTSPOT) else ""},
    }


def hotspot_password():
    r = sh("nmcli", "-s", "-g", "802-11-wireless-security.psk", "con", "show", NM_HOTSPOT, timeout=10)
    return r.stdout.strip() or "?"


# ───────────────────────────── setup / doctor ─────────────────────────────
TOOLS = {"tio": "serial console", "picocom": "serial console (fallback)", "sshfs": "mount devices",
         "mosh": "roaming terminal", "avahi-browse": "find .local devices (avahi-utils)", "waypipe": "device GUI apps here",
         "nmap": "network scan", "fzf": "pickers", "rsync": "copy/sync", "zstd": "SD backups", "code": "VS Code"}


def in_group(g):
    try:
        import grp
        return g in [grp.getgrgid(x).gr_name for x in os.getgroups()]
    except Exception: return False


def group_configured(g):
    try:
        import grp
        return os.environ.get("USER", "") in grp.getgrnam(g).gr_mem
    except Exception: return False


def cmd_setup(a):
    ensure_ssh_layout()
    k = key_path()
    if not k:
        say(bold("Making your SSH key") + dim(" (ed25519). Pick a passphrase: the keyring remembers it after login."))
        r = subprocess.run(["ssh-keygen", "-t", "ed25519", "-a", "64", "-C", f"{os.environ.get('USER', 'me')}@{socket.gethostname()}",
                            "-f", str(SSH / "id_ed25519")])
        if r.returncode != 0: raise Fail("Key not created.")
        k = SSH / "id_ed25519"
    say(good(f"✓ key {k}.pub"))
    if sh("ssh-add", "-l", timeout=5).returncode != 0:
        subprocess.run(["ssh-add", str(k)]) if tty() else None
    say(good("✓ ssh-agent has your key") if sh("ssh-add", "-l", timeout=5).returncode == 0 else
        warn("! agent doesn't hold the key yet (it'll ask once per login)"))
    gen_ssh_config()
    say(good(f"✓ ssh config: ~/.ssh/config → config.d/ (devices, defaults, yours)"))
    if have("code"):
        if not extension_installed("ms-vscode-remote.remote-ssh"):
            sh("code", "--install-extension", "ms-vscode-remote.remote-ssh", timeout=240)
            sh("code", "--install-extension", "ms-vscode.remote-explorer", timeout=240)
        ok = update_vscode_platforms(VSCODE_DEFAULTS)
        say(good("✓ VS Code Remote-SSH ready (works on devices with no internet)") if ok else
            warn("! VS Code settings.json has comments; add the remote.SSH settings by hand (see docs/REMOTE.md)"))
    for d in (LOGS, IMAGES, MOUNTS): d.mkdir(parents=True, exist_ok=True)
    if a.github:
        if not have("gh"): say(warn("gh isn't installed")); return FAIL
        r = sh("gh", "ssh-key", "add", f"{k}.pub", "--title", f"{socket.gethostname()} (board)", timeout=30)
        say(good("✓ key added to GitHub") if r.returncode == 0 or "already" in r.stderr else
            warn(f"! GitHub: {r.stderr.strip()}  (try: gh auth refresh -h github.com -s admin:public_key)"))
    if a.signing:
        email = sh("git", "config", "--global", "user.email").stdout.strip()
        allowed = SSH / "allowed_signers"
        line = f"{email} {(Path(str(k) + '.pub')).read_text().strip()}"
        if line not in (allowed.read_text() if allowed.exists() else ""):
            with open(allowed, "a") as f: f.write(line + "\n")
        for kv in (("gpg.format", "ssh"), ("user.signingkey", f"{k}.pub"), ("commit.gpgsign", "true"),
                   ("tag.gpgsign", "true"), ("gpg.ssh.allowedSignersFile", str(allowed))):
            sh("git", "config", "--global", *kv)
        if have("gh"): sh("gh", "ssh-key", "add", f"{k}.pub", "--type", "signing", "--title", f"{socket.gethostname()} signing", timeout=30)
        say(good("✓ commits are now signed with your SSH key (GitHub shows 'Verified')"))
    missing = [t for t in TOOLS if not have(t)]
    if missing or not group_configured("dialout"):
        say(warn("\nTo finish (needs your password once):") + "\n  ! bash ~/KadaOS/scripts/phase12-embedded.sh")
    say(dim("\nNext: board scan  ·  board add NAME HOST  ·  board doctor"))
    return OK


def check(ok, text, fix=""):
    say(f"  {good('✓') if ok else bad('✗')} {text}" + ("" if ok or not fix else dim(f"\n      → {fix}")))
    return ok


def cmd_doctor(a):
    if a.name: return doctor_device(resolve_name(a.name))
    say(bold("This laptop"))
    k = key_path()
    check(bool(k), f"SSH key {k}" if k else "SSH key", "board setup")
    check(sh("ssh-add", "-l", timeout=5).returncode == 0, "key unlocked in the agent", "ssh-add  (asks the passphrase once per login)")
    cfg = (SSH / "config").read_text() if (SSH / "config").exists() else ""
    check("Include ~/.ssh/config.d/*" in cfg, "~/.ssh/config includes config.d/", "board setup")
    check((SSH / "config.d/99-defaults").exists(), "connection defaults (fast reconnects, keepalive)", "bash scripts/install-remote.sh")
    check(GEN.exists(), "device hosts generated", "board gen")
    check(oct(SSH.stat().st_mode & 0o777) == "0o700" if SSH.exists() else False, "~/.ssh permissions 700", "chmod 700 ~/.ssh")
    check(in_group("dialout"), "serial ports allowed (dialout group)",
          "log out and back in" if group_configured("dialout") else "! sudo usermod -aG dialout $USER, then log out/in")
    for t, why in TOOLS.items(): check(have(t), f"{t} ({why})", "bash scripts/phase12-embedded.sh")
    if have("code"):
        check(extension_installed("ms-vscode-remote.remote-ssh"), "VS Code Remote-SSH", "board setup")
    check(nm_has(NM_USB), "USB-cable networking profile", "board usb setup")
    reg = load_registry()
    devs = devices(reg)
    say(bold(f"\nDevices ({len(devs)})"))
    if not devs: say(dim("  none yet: board scan / board add"))
    stat = status_all(reg) if devs else {}
    for n, f in stat.items():
        if f["state"] == "online": check(True, f"{n} online via {f.get('via')}")
        elif f["state"] == "serial": check(True, f"{n} (serial only)")
        elif f["state"] == "auth": check(False, f"{n} refuses your key", f"board copy-id {n}")
        elif f["state"] == "hostkey": check(False, f"{n} host key changed", f"board forget {n}  (if you reflashed it)")
        else: check(False, f"{n} offline", f"board doctor {n}")
    return OK


def doctor_device(name):
    d = devices()[name]
    say(bold(name) + dim(f"  {d.get('user', '?')}@{dev_host(name, d)}:{d.get('port', 22)}"))
    port = d.get("port", 22)
    cands = candidates_for(name, d)
    any_ok = False
    for c in cands:
        try: ip = socket.gethostbyname(c)
        except OSError: check(False, f"{c}: name doesn't resolve", "is it on this network? mDNS needs the same LAN"); continue
        s = _connect(ip, port, 3)
        if s: s.close(); any_ok = True
        check(bool(s), f"{c} ({ip}, via {via_label(ip)}): port {port} " + ("open" if s else "not answering"),
              "powered? sshd enabled? (Pi: an empty file called 'ssh' on the boot partition)")
    if not any_ok:
        extra = cable_candidates(name, d)
        if extra: say(f"  found ssh on a cable link at {', '.join(extra)}: `board set {name} host={extra[0]}` if that's it"); any_ok = True
    if not any_ok:
        say(dim("  ideas: same Wi-Fi? `board scan` · one USB cable: `board usb` · Ethernet cable: `board link on` · "
                f"console: `board serial {name}`"))
        return OFFLINE
    st, stderr = ssh_check(name)
    if not check(st in ("ok",), {"ok": "logs in with your key", "auth": "key refused", "hostkey-changed": "host key changed",
                                 "hostkey-unknown": "host key not trusted yet"}.get(st, f"ssh: {stderr.strip()[-120:]}"),
                 {"auth": f"board copy-id {name}", "hostkey-changed": f"board forget {name}",
                  "hostkey-unknown": f"board ssh {name} (trusts it on first use)"}.get(st, "")):
        return {"auth": AUTH, "hostkey-changed": HOSTKEY}.get(st, FAIL)
    f = probe(name)
    learn_facts(name, f)
    check(f.get("tmux"), "tmux installed (sessions survive Wi-Fi drops)", f"board bootstrap {name}")
    check(f.get("sudo"), "passwordless sudo (needed for reboot, backup, USB mode from the panel)",
          "fine to skip; those commands will ask for the password")
    if f.get("throttled"): check(False, "power: " + ", ".join(f["throttled"]), "use the official power supply / a shorter cable")
    if f.get("disk_free_kb") is not None: check(f["disk_free_kb"] > 1024 * 1024, f"disk free {human_bytes(f['disk_free_kb'] * 1024)}", "free some space (journalctl --vacuum-size=100M)")
    d = devices()[name]
    check(not needs_sshfs_mode(d), f"VS Code server supported ({d.get('arch')}, {d.get('mem_mb')} MB)",
          "board code uses a mount instead; that's automatic")
    return OK


# ───────────────────────────── flash + bootstrap ─────────────────────────────
OS_IMAGES = {
    "raspios-lite": ("Raspberry Pi OS Lite 64-bit (no desktop)", "https://downloads.raspberrypi.com/raspios_lite_arm64_latest"),
    "raspios": ("Raspberry Pi OS 64-bit (desktop)", "https://downloads.raspberrypi.com/raspios_arm64_latest"),
    "raspios-lite-32": ("Raspberry Pi OS Lite 32-bit (Pi Zero / 1 / 2)", "https://downloads.raspberrypi.com/raspios_lite_armhf_latest"),
}


def removable_disks():
    """Disks that are safe to write: removable or USB/MMC, not holding / or /boot, not the system disk."""
    r = sh("lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,MODEL,TRAN,RM,TYPE,MOUNTPOINTS,HOTPLUG", timeout=10)
    try: data = json.loads(r.stdout)["blockdevices"]
    except (ValueError, KeyError): return []
    return safe_disks(data)


def safe_disks(data):
    out = []
    for d in data:
        if d.get("type") != "disk": continue
        mps = [m for c in d.get("children", []) or [] for m in (c.get("mountpoints") or []) if m] + \
              [m for m in (d.get("mountpoints") or []) if m]
        if any(m in ("/", "/boot", "/boot/efi", "/home", "[SWAP]") or m.startswith(("/usr", "/var")) for m in mps): continue
        removable = bool(d.get("rm")) or bool(d.get("hotplug")) or d.get("tran") in ("usb", "mmc") or d["name"].startswith("mmcblk")
        if not removable or d["name"].startswith(("nvme", "loop", "zram", "sr")): continue
        if not d.get("size") or int(d["size"]) < 1 << 30 or int(d["size"]) > 2 << 40: continue
        out.append({"path": d["path"], "size": int(d["size"]), "model": (d.get("model") or "").strip(),
                    "tran": d.get("tran") or "", "mounted": mps})
    return out


def download_image(key_or_url):
    IMAGES.mkdir(parents=True, exist_ok=True)
    url = OS_IMAGES.get(key_or_url, (None, key_or_url))[1]
    import urllib.request
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "board"})
    with urllib.request.urlopen(req, timeout=30) as r: final = r.geturl()
    fn = IMAGES / Path(final).name
    if fn.exists() and fn.stat().st_size > 0:
        say(dim(f"Using cached {fn.name}")); return fn
    sha = None
    try:
        with urllib.request.urlopen(final + ".sha256", timeout=30) as r: sha = r.read().decode().split()[0]
    except Exception: say(warn("No checksum published for this image; continuing without verification."))
    tmp = fn.with_suffix(fn.suffix + ".part")
    h = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(final, headers={"User-Agent": "board"}), timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0)); got = 0
        while chunk := r.read(1 << 20):
            f.write(chunk); h.update(chunk); got += len(chunk)
            if total and tty(): print(f"\r  downloading {fn.name}: {got * 100 // total}% of {human_bytes(total)}", end="", flush=True)
    print()
    if sha and h.hexdigest() != sha: tmp.unlink(); raise Fail("Download corrupted (checksum mismatch). Try again.")
    tmp.rename(fn)
    say(good(f"✓ {fn.name}" + (" (checksum verified)" if sha else "")))
    return fn


def decompressor(path):
    p = str(path)
    if p.endswith(".xz"): return ["xz", "-dc", p]
    if p.endswith(".zst"): return ["zstd", "-dc", p]
    if p.endswith(".gz"): return ["gzip", "-dc", p]
    if p.endswith(".img") or p.endswith(".iso"): return ["cat", p]
    raise Fail(f"Don't know how to read {Path(p).name} (want .img, .img.xz, .img.zst or .img.gz)")


def boot_partition(disk):
    for _ in range(20):
        r = sh("lsblk", "-J", "-o", "PATH,FSTYPE,LABEL,MOUNTPOINTS", disk, timeout=10)
        try:
            for c in json.loads(r.stdout)["blockdevices"][0].get("children", []):
                if c.get("fstype") == "vfat": return c["path"], (c.get("mountpoints") or [None])[0]
        except (ValueError, KeyError, IndexError): pass
        time.sleep(1)
    return None, None


def wifi_networks():
    """[(ssid, psk)] for the network we're on now (NetworkManager shares the secret with its owner)."""
    out = []
    r = sh("nmcli", "-t", "-f", "NAME,TYPE", "con", "show", "--active", timeout=5)
    for line in r.stdout.splitlines():
        name, _, typ = line.rpartition(":")
        if typ != "802-11-wireless" or name == NM_HOTSPOT: continue
        ssid = sh("nmcli", "-g", "802-11-wireless.ssid", "con", "show", name, timeout=5).stdout.strip()
        psk = sh("nmcli", "-s", "-g", "802-11-wireless-security.psk", "con", "show", name, timeout=10).stdout.strip()
        if ssid: out.append((ssid, psk))
    return out


def country_code(reg=None):
    c = settings(reg)["country"]
    if c: return c.upper()
    r = sh("iw", "reg", "get", timeout=3)
    m = re.search(r"country (\w\w):", r.stdout)
    if m and m.group(1) != "00": return m.group(1)
    loc = os.environ.get("LANG", "")
    m = re.match(r"\w\w_(\w\w)", loc)
    return m.group(1) if m else "US"


def cloud_init_files(hostname, user, pubkey, tz, wifi, country, extra_groups=True):
    groups = "users,adm,dialout,audio,netdev,video,plugdev,cdrom,games,input,gpio,spi,i2c,render,sudo" if extra_groups else "sudo"
    user_data = f"""#cloud-config
# written by `board flash`
hostname: {hostname}
manage_etc_hosts: true
timezone: {tz}
ssh_pwauth: false
users:
  - name: {user}
    groups: {groups}
    shell: /bin/bash
    lock_passwd: true
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - {pubkey}
enable_ssh: true
rpi:
  interfaces:
    serial: true
"""
    net = ["network:", "  version: 2"]
    if wifi:
        net += ["  wifis:", "    wlan0:", "      dhcp4: true", "      optional: true", f"      regulatory-domain: {country}",
                "      access-points:"]
        for ssid, psk in wifi:
            net.append(f"        {json.dumps(ssid)}:")
            net.append(f"          password: {json.dumps(psk)}" if psk else "          {}")
    net += ["  ethernets:", "    eth0:", "      dhcp4: true", "      optional: true"]
    return user_data, "\n".join(net) + "\n"


def customize_boot(mp, name, user, pubkey, wifi, country, uart=True, gadget=False):
    mp = Path(mp)
    done = []
    tz = sh("timedatectl", "show", "-p", "Timezone", "--value", timeout=5).stdout.strip() or "UTC"
    (mp / "ssh").touch(); done.append("SSH on")
    if (mp / "user-data").exists() or (mp / "meta-data").exists() or (mp / "network-config").exists():
        ud, nc = cloud_init_files(name, user, pubkey, tz, wifi, country)
        (mp / "user-data").write_text(ud); (mp / "network-config").write_text(nc)
        md = mp / "meta-data"
        if not md.exists() or "instance-id" not in md.read_text():
            md.write_text(f"instance-id: board-{name}-{int(time.time())}\n")
        done += [f"user {user} with your key (no password login)", f"hostname {name}", f"timezone {tz}"]
        if wifi: done.append("Wi-Fi: " + ", ".join(s for s, _ in wifi))
        legacy = False
    else:
        legacy = True
    cfg = mp / "config.txt"
    if cfg.exists():
        text = cfg.read_text()
        add = []
        if uart and "enable_uart=1" not in text: add.append("enable_uart=1")
        if gadget and "dtoverlay=dwc2" not in text: add.append("dtoverlay=dwc2,dr_mode=peripheral")
        if add: cfg.write_text(text.rstrip() + "\n\n[all]\n# added by board flash\n" + "\n".join(add) + "\n")
        if uart: done.append("serial console on GPIO14/15")
    cmd = mp / "cmdline.txt"
    if gadget and cmd.exists():
        h, dv = usb_macs(name)
        t = cmd.read_text().strip()
        if "g_ether" not in t: cmd.write_text(t + f" modules-load=dwc2,g_ether g_ether.host_addr={h} g_ether.dev_addr={dv}\n")
        done.append("USB-cable mode")
    return done, legacy


def cmd_flash(a):
    if not tty(): raise Fail("board flash is interactive: run it in a terminal.", USAGE)
    reg = load_registry()
    k = key_path()
    if not k: raise Fail("No SSH key yet: `board setup` first, so the card can be ready for key login.")
    say(bold("Flash a card for a new device") + dim("  (Ctrl+C any time; nothing is written until you type the disk name)"))
    # 1. image
    if a.image: img = Path(a.image).expanduser() if Path(a.image).expanduser().exists() else download_image(a.image)
    else:
        cached = sorted(IMAGES.glob("*.img*"), key=lambda p: -p.stat().st_mtime) if IMAGES.exists() else []
        items = [(k_, f"{v[0]}  {dim('download latest')}") for k_, v in OS_IMAGES.items()] + \
                [(str(p), f"{p.name}  {dim('cached · ' + human_bytes(p.stat().st_size))}") for p in cached if not p.name.endswith(".part")]
        choice = pick(items, "image")
        img = Path(choice) if Path(choice).exists() else download_image(choice)
    decompressor(img)
    # 2. disk
    disks = removable_disks()
    if a.disk: disks = [x for x in disks if x["path"] == a.disk] or []
    if not disks: raise Fail("No SD card or USB drive found (the system disk is never offered). Insert one and retry.")
    disk = pick([(x["path"], f"{x['path']:<12} {human_bytes(x['size']):>9}  {x['model']} {dim(x['tran'])}"
                  + (warn('  mounted') if x["mounted"] else "")) for x in disks], "disk")
    info = next(x for x in disks if x["path"] == disk)
    # 3. who it will be
    name = a.name or ask("Device name (hostname)", "pi")
    if not NAME_RE.match(name): raise Fail("Name: letters, digits, - and _.", USAGE)
    user = a.user or ask("User to create", settings(reg)["user"] or os.environ.get("USER", "pi"))
    if not USER_RE.match(user) or user == "root": raise Fail("Pick a normal user name.", USAGE)
    wifi = [] if a.no_wifi else wifi_networks()
    if wifi and not confirm(f"Join Wi-Fi '{wifi[0][0]}' on first boot?", True): wifi = []
    if not wifi and not a.no_wifi:
        ssid = ask("Wi-Fi name to join (empty = none)")
        if ssid: wifi = [(ssid, ask("Wi-Fi password"))]
    if nm_has(NM_HOTSPOT): wifi.append((settings(reg)["hotspot_ssid"] or f"{socket.gethostname()}-lab", hotspot_password()))
    gadget = a.gadget if a.gadget is not None else confirm("Is it a Pi Zero / Zero 2 / 4 / 5? (enables one-USB-cable mode)", True)
    country = country_code(reg)
    # 4. write
    say(warn(f"\nThis ERASES {disk} ({human_bytes(info['size'])} {info['model']})."))
    if ask(f"Type {Path(disk).name} to continue") != Path(disk).name: raise Fail("Not confirmed; nothing written.", USAGE)
    for part in sh("lsblk", "-ln", "-o", "PATH", disk).stdout.split()[1:]:
        sh("udisksctl", "unmount", "-b", part, "--no-user-interaction", timeout=20)
    say(dim("Writing (sudo asks for your password)…"))
    src = subprocess.Popen(decompressor(img), stdout=subprocess.PIPE)
    dd = subprocess.run(["sudo", "dd", f"of={disk}", "bs=4M", "conv=fsync", "oflag=direct", "status=progress"], stdin=src.stdout)
    src.stdout.close(); src.wait()
    if dd.returncode != 0 or src.returncode != 0: raise Fail("Writing failed; the card is not usable yet. Try again or another card.")
    say(good("✓ written"))
    # 5. customise
    sh("partprobe", disk, timeout=10)
    part, mp = boot_partition(disk)
    if part and not mp:
        r = sh("udisksctl", "mount", "-b", part, "--no-user-interaction", timeout=20)
        m = re.search(r" at (\S+)", r.stdout); mp = m.group(1).rstrip(".") if m else None
    if not mp: raise Fail("Couldn't open the card's boot partition to set it up. Re-insert the card and run `board flash` again.")
    pub = Path(f"{k}.pub").read_text().strip()
    done, legacy = customize_boot(mp, name, user, pub, wifi, country, uart=not a.no_uart, gadget=gadget)
    sh("sync"); sh("udisksctl", "unmount", "-b", part, "--no-user-interaction", timeout=20)
    sh("udisksctl", "power-off", "-b", disk, "--no-user-interaction", timeout=20)
    for x in done: say(good(f"  ✓ {x}"))
    if legacy:
        say(warn("  This image doesn't support cloud-init setup (older Raspberry Pi OS). SSH is on, but set the user,\n"
                 "  key and Wi-Fi with Raspberry Pi Imager's settings, or connect a screen once."))
    # 6. register
    d = dict(reg.get(name, {})); d.update({"host": f"{name}.local", "user": user, "kind": "pi",
                                           "flashed_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")})
    if gadget: d["usb_mac"] = usb_macs(name)[1]
    reg[name] = d; save_registry(reg); forget_hostkeys(name, d)
    if gadget: ensure_nm_usb()
    say(good(f"\n✓ Card ready. Put it in the device and power it on.") + dim(" First boot takes 1–3 minutes."))
    if confirm("Wait here until it's online?", True):
        t = wait_state(name, d, True, 420)
        if t is None: say(warn(f"Not online after 7 min. Try `board scan`, `board usb status`, or `board serial`.")); return OFFLINE
        say(good(f"✓ {name} is up after {human_secs(t)}"))
        time.sleep(5)
        connect_and_learn(name, devices()[name], copy_id=False, yes=True)
        if confirm(f"Set it up now (tmux, updates, your timezone)? → board bootstrap {name}", True):
            return cmd_bootstrap(argparse.Namespace(name=name, packages=[], interfaces="", no_harden=False, swap=0,
                                                    no_upgrade=False, yes=True))
    return OK


BOOTSTRAP_PACKAGES = ["tmux", "rsync", "git", "htop", "btop", "python3-venv", "python3-pip", "i2c-tools", "gdbserver", "curl"]
TMUX_CONF = """# from board bootstrap
set -g mouse on
set -g history-limit 50000
set -g default-terminal "tmux-256color"
set -g status-style "bg=#1e2024,fg=#c9ccd3"
set -g status-left " #[bold]#H#[nobold] · "
set -g status-right "#(cut -d' ' -f1 /proc/loadavg) · %I:%M %p "
set -g set-titles on
set -g set-titles-string "#H: #W"
"""


def cmd_bootstrap(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    st = ensure_connected(name, d, interactive=True, yes=a.yes)
    if st == "auth" and do_copy_id(name) != 0: return AUTH
    say(bold(f"Setting up {name}") + dim("  (safe to run again)"))

    def step(title, script, timeout=900, ok_rc=(0,)):
        say(f"  · {title}…")
        r = subprocess.run([*SSH_CMD, "-t", name, script], env=ssh_env()) if tty() else sh(*SSH_CMD, name, script, timeout=timeout)
        rc = r.returncode
        say(("    " + good("✓ done")) if rc in ok_rc else ("    " + warn(f"! exit {rc}")))
        return rc in ok_rc

    # 1. key login proven on a fresh connection before turning off passwords
    r = sh(*SSH_CMD, "-o", "BatchMode=yes", "-o", "ControlMaster=no", "-o", "ControlPath=none", name, "true", timeout=20)
    key_ok = r.returncode == 0
    tz = sh("timedatectl", "show", "-p", "Timezone", "--value", timeout=5).stdout.strip() or "UTC"
    step(f"timezone {tz}", f"sudo timedatectl set-timezone {shlex.quote(tz)} 2>/dev/null || true")
    pk = " ".join(shlex.quote(p) for p in BOOTSTRAP_PACKAGES + list(a.packages or []))
    upgrade = "" if a.no_upgrade else "sudo DEBIAN_FRONTEND=noninteractive apt-get -y upgrade -o Dpkg::Options::=--force-confold; "
    step("packages (tmux, rsync, git, btop, python venv, i2c-tools, gdbserver)" + ("" if a.no_upgrade else " + updates"),
         "command -v apt-get >/dev/null || { echo 'not apt-based; skipping'; exit 0; }; "
         f"sudo apt-get update -q && {upgrade}for p in {pk}; do "
         "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q \"$p\" >/dev/null 2>&1 || echo \"  (skipped $p)\"; done")
    step("tmux config", f"[ -f ~/.tmux.conf ] || printf %s {shlex.quote(TMUX_CONF)} > ~/.tmux.conf")
    if a.interfaces:
        cmds = {"i2c": "do_i2c", "spi": "do_spi", "serial": "do_serial_hw", "camera": "do_camera", "onewire": "do_onewire",
                "vnc": "do_vnc"}
        parts = [f"sudo raspi-config nonint {cmds[i]} 0" for i in a.interfaces.split(",") if i in cmds]
        if parts: step(f"enable {a.interfaces}", "command -v raspi-config >/dev/null || { echo 'no raspi-config'; exit 0; }; " + " && ".join(parts))
    if a.swap:
        step(f"swap {a.swap} MB", f"if [ -f /etc/dphys-swapfile ]; then sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE={int(a.swap)}/' "
                                  "/etc/dphys-swapfile && sudo systemctl restart dphys-swapfile; else echo 'no dphys-swapfile'; fi")
    if not a.no_harden:
        if key_ok:
            step("SSH: keys only (password login off)",
                 "printf 'PasswordAuthentication no\\nKbdInteractiveAuthentication no\\nPermitRootLogin no\\n' | "
                 "sudo tee /etc/ssh/sshd_config.d/10-board.conf >/dev/null && sudo sshd -t && "
                 "(sudo systemctl reload ssh 2>/dev/null || sudo systemctl reload sshd)")
        else:
            say(warn("  · skipped turning off password login: key login isn't proven yet (board copy-id first)"))
    f = probe(name); learn_facts(name, f)
    say(good(f"✓ {name} is set up.") + dim(f"  board ssh {name} · board code {name} · board info {name}"))
    return OK


# ───────────────────────────── backup, ferry, gui, cam ─────────────────────────────
def cmd_backup(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    ensure_connected(name, d, interactive=tty())
    r = run_remote(name, "src=$(findmnt -no SOURCE /); pk=$(lsblk -no PKNAME \"$src\" | head -1); "
                         "echo \"/dev/${pk:-$(basename $src)}\"; lsblk -bdno SIZE \"/dev/${pk:-$(basename $src)}\"; "
                         "sudo -n true 2>/dev/null && echo SUDO", timeout=20)
    lines = r.stdout.split()
    if len(lines) < 2: raise Fail(f"Couldn't find {name}'s system disk: {r.stderr.strip()}")
    disk, size = lines[0], int(lines[1])
    if "SUDO" not in lines: raise Fail(f"Backup needs passwordless sudo on {name} (Raspberry Pi OS has it by default).")
    dest = Path(a.to or HOME / "Embedded/backups").expanduser(); dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{name}-{dt.datetime.now():%Y%m%d-%H%M}.img.zst"
    free = shutil.disk_usage(dest).free
    if free < size * 0.6 and not a.yes: raise Fail(f"Only {human_bytes(free)} free in {dest}; the image could need up to {human_bytes(size)}.")
    if not have("zstd"): raise Fail("zstd isn't installed.")
    if not confirm(f"Back up {name}:{disk} ({human_bytes(size)}) to {out}? The device keeps running; quiet moments give the cleanest copy.", True, a.yes): return USAGE
    run_remote(name, "sync", timeout=30)
    src = subprocess.Popen([*SSH_CMD, name, f"sudo -n dd if={disk} bs=4M status=none"], stdout=subprocess.PIPE)
    z = subprocess.Popen(["zstd", "-T0", "-3", "-q", "-o", str(out)], stdin=subprocess.PIPE)
    got, t0 = 0, time.time()
    try:
        while chunk := src.stdout.read(1 << 20):
            z.stdin.write(chunk); got += len(chunk)
            if tty():
                rate = got / max(0.1, time.time() - t0)
                print(f"\r  {got * 100 // size:>3}%  {human_bytes(got)} of {human_bytes(size)} · {human_bytes(rate)}/s · "
                      f"{human_secs((size - got) / max(rate, 1))} left   ", end="", flush=True)
    except KeyboardInterrupt:
        src.kill(); z.kill(); out.unlink(missing_ok=True); raise Fail("Cancelled; partial image removed.")
    z.stdin.close(); z.wait(); src.wait()
    print()
    if src.returncode != 0 or z.returncode != 0 or got < size:
        out.unlink(missing_ok=True); raise Fail("Backup incomplete (connection dropped?). Partial image removed.")
    say(good(f"✓ {out} ({human_bytes(out.stat().st_size)})") + dim(f"\n  restore to a card: board flash --image {out}"))
    notify(f"Backup of {name} finished", str(out))
    return OK


def cmd_ferry(a):
    """Carry packages to a device with no internet: .deb files are installed, wheels go into the project venv."""
    reg = load_registry()
    name = resolve_name(a.name, reg)
    d = devices(reg)[name]
    src = Path(a.dir).expanduser()
    if not src.is_dir(): raise Fail(f"{src} isn't a folder of .deb / .whl files.")
    ensure_connected(name, d, interactive=tty())
    dst = f"{dev_home(d)}/ferry/{src.name}"
    rc, _ = rsync([f"{src}/", f"{name}:{dst}/"])
    if rc: return FAIL
    debs, whls = list(src.glob("*.deb")), list(src.glob("*.whl"))
    if debs:
        subprocess.run([*SSH_CMD, "-t", name, f"sudo apt-get install -y {shlex.quote(dst)}/*.deb"], env=ssh_env())
    if whls:
        venv = f"{remote_path(d)}/.venv" if d.get("project") else ""
        pip = f"{venv}/bin/pip" if venv else "python3 -m pip"
        subprocess.run([*SSH_CMD, "-t", name, f"[ -x {venv}/bin/pip ] || python3 -m venv {venv or '~/.venv'}; "
                                           f"{pip if venv else '~/.venv/bin/pip'} install --no-index --find-links {shlex.quote(dst)} "
                                           + " ".join(shlex.quote(w.name.split('-')[0]) for w in whls)], env=ssh_env())
    say(good(f"✓ ferried {len(debs)} .deb and {len(whls)} wheels to {name}"))
    return OK


def cmd_gui(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    if not have("waypipe"): raise Fail("waypipe isn't installed here (bash scripts/phase12-embedded.sh); the device needs it too (sudo apt install waypipe).")
    ensure_connected(name, devices(reg)[name])
    execvp(["waypipe", "ssh", name] + a.app)


def cmd_cam(a):
    reg = load_registry()
    name = resolve_name(a.name, reg)
    ensure_connected(name, devices(reg)[name])
    w, h = (a.size or "1280x720").split("x")
    remote = (f"(command -v rpicam-vid >/dev/null && exec rpicam-vid -t 0 -n --inline --codec h264 --width {w} --height {h} "
              f"--framerate {a.fps} -o - ) || (command -v libcamera-vid >/dev/null && exec libcamera-vid -t 0 -n --inline "
              f"--width {w} --height {h} --framerate {a.fps} -o - ) || exec ffmpeg -loglevel error -f v4l2 -video_size {a.size or '1280x720'} "
              f"-i /dev/video0 -c:v libx264 -preset ultrafast -tune zerolatency -f h264 -")
    player = (["mpv", "--no-cache", "--untimed", "--profile=low-latency", "--demuxer-lavf-format=h264",
               f"--title={name} camera", "-"] if have("mpv") else
              ["ffplay", "-loglevel", "error", "-fflags", "nobuffer", "-flags", "low_delay", "-framedrop", "-f", "h264",
               "-window_title", f"{name} camera", "-i", "-"])
    say(dim(f"Live camera from {name}. Close the window or Ctrl+C to stop."))
    src = subprocess.Popen([*SSH_CMD, name, remote], stdout=subprocess.PIPE)
    if a.record:
        tee = subprocess.Popen(["tee", a.record], stdin=src.stdout, stdout=subprocess.PIPE)
        p = subprocess.run(player, stdin=tee.stdout)
    else:
        p = subprocess.run(player, stdin=src.stdout)
    src.terminate()
    return p.returncode


# ───────────────────────────── VS Code project templates ─────────────────────────────
def task(label, command, group=None, background=False, reveal="always"):
    t = {"label": label, "type": "shell", "command": command, "problemMatcher": [],
         "presentation": {"reveal": reveal, "panel": "dedicated" if background else "shared", "clear": True}}
    if group: t["group"] = group
    if background:
        t["isBackground"] = True
        t["problemMatcher"] = {"pattern": {"regexp": "^__never__$"},
                               "background": {"activesBegin": ".", "beginsPattern": ".", "endsPattern": "(✓|listening|Listening|ready)"}}
    return t


def project_templates(kind, devs, default, entry, remote):
    b = board_cmd() if " " not in board_cmd() else "board"
    dev = "${input:device}"
    inputs = [{"id": "device", "type": "pickString", "description": "Device", "options": devs, "default": default}]
    tasks = [
        task("Deploy to device", f"{b} sync {dev} --once", None),
        task("Deploy + run", f"{b} sync {dev} --once --run {shlex.quote(entry['run'])}", {"kind": "build", "isDefault": True}),
        task("Sync + re-run on save", f"{b} sync {dev} --run {shlex.quote(entry['run'])}", None, background=True),
        task("Device terminal", f"{b} ssh {dev}", None),
        task("Device logs", f"{b} logs {dev}", None, background=True),
        task("Device info", f"{b} info {dev}", None),
    ]
    launch = {"version": "0.2.0", "configurations": []}
    if kind == "python":
        tasks.append(task("Debug: start on device",
                          f"{b} ports {dev} 5678 && {b} run {dev} -- python3 -m debugpy --listen 127.0.0.1:5678 --wait-for-client {entry['file']}",
                          None, background=True))
        launch["configurations"].append({
            "name": "Python: debug on device", "type": "debugpy", "request": "attach", "preLaunchTask": "Debug: start on device",
            "connect": {"host": "localhost", "port": 5678},
            "pathMappings": [{"localRoot": "${workspaceFolder}", "remoteRoot": remote}], "justMyCode": False})
    elif kind == "c":
        tasks.insert(0, task("Cross-build (aarch64)", "cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=cmake/aarch64.cmake "
                                                     "-DCMAKE_BUILD_TYPE=Debug && cmake --build build -j", None))
        tasks.append(task("Debug: gdbserver on device",
                          f"{b} sync {dev} --once && {b} ports {dev} 2345 && {b} run {dev} -- gdbserver :2345 build/{entry['bin']}",
                          None, background=True))
        launch["configurations"].append({
            "name": "C/C++: debug on device", "type": "cppdbg", "request": "launch", "program": "${workspaceFolder}/build/" + entry["bin"],
            "cwd": "${workspaceFolder}", "MIMode": "gdb", "miDebuggerPath": "gdb-multiarch",
            "miDebuggerServerAddress": "localhost:2345", "preLaunchTask": "Debug: gdbserver on device",
            "setupCommands": [{"text": "-enable-pretty-printing", "ignoreFailures": True}]})
    elif kind == "mcu":
        tasks = [task("Serial monitor", f"{b} serial", None)]
        launch["configurations"] += [
            {"name": "MCU: debug (OpenOCD, ST-Link)", "type": "cortex-debug", "request": "launch", "servertype": "openocd",
             "executable": "${workspaceFolder}/build/firmware.elf", "configFiles": ["interface/stlink.cfg", "target/stm32f4x.cfg"],
             "runToEntryPoint": "main"},
            {"name": "MCU: debug (probe-rs)", "type": "cortex-debug", "request": "launch", "servertype": "external",
             "gdbTarget": "localhost:1337", "executable": "${workspaceFolder}/build/firmware.elf", "runToEntryPoint": "main"},
            {"name": "Pico: debug (Debug Probe)", "type": "cortex-debug", "request": "launch", "servertype": "openocd",
             "executable": "${workspaceFolder}/build/firmware.elf", "configFiles": ["interface/cmsis-dap.cfg", "target/rp2040.cfg"],
             "openOCDLaunchCommands": ["adapter speed 5000"], "runToEntryPoint": "main"}]
        inputs = []
    elif kind == "ros2":
        tasks.insert(1, task("colcon build on device", f"{b} sync {dev} --once --run 'source /opt/ros/*/setup.bash && colcon build --symlink-install'", None))
    return {"version": "2.0.0", "tasks": tasks, "inputs": inputs}, launch


CMAKE_TOOLCHAIN = """# Cross-compile for 64-bit Raspberry Pi / Jetson (apt: gcc-aarch64-linux-gnu g++-aarch64-linux-gnu)
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
"""


def detect_kind(path):
    p = Path(path)
    if (p / "platformio.ini").exists() or (p / "pico_sdk_import.cmake").exists(): return "mcu"
    if (p / "package.xml").exists() or (p / "src").is_dir() and any((p / "src").glob("*/package.xml")): return "ros2"
    if (p / "CMakeLists.txt").exists() or any(p.glob("*.c")) or any(p.glob("*.cpp")): return "c"
    return "python"


def cmd_init_project(a):
    reg = load_registry()
    root = Path(a.path or ".").resolve()
    kind = a.kind or detect_kind(root)
    devs = [n for n, d in devices(reg).items() if d.get("host") or d.get("kind") != "mcu"]
    if kind != "mcu" and not devs: raise Fail("Add a device first (board add / board scan).", USAGE)
    default = a.device or (pick_device(reg, "net") if kind != "mcu" and len(devs) > 1 and tty() else (devs[0] if devs else ""))
    d = devices(reg).get(default, {})
    remote = remote_path(d, d.get("project") or f"~/{root.name}") if d else f"~/{root.name}"
    entry = {"file": a.entry or ("main.py" if (root / "main.py").exists() else "app.py" if (root / "app.py").exists() else "main.py"),
             "bin": root.name}
    entry["run"] = a.run or {"python": f"python3 {entry['file']}", "c": f"./build/{entry['bin']}", "ros2": "ros2 launch .",
                             "mcu": ""}.get(kind, "./run.sh")
    tasks, launch = project_templates(kind, devs or [""], default, entry, remote)
    vs = root / ".vscode"; vs.mkdir(exist_ok=True)
    written = []
    for fn, data in (("tasks.json", tasks), ("launch.json", launch)):
        if fn == "launch.json" and not data["configurations"]: continue
        p = vs / fn
        if p.exists() and not a.force:
            try:
                cur = json.loads(p.read_text())
                key = "tasks" if fn == "tasks.json" else "configurations"
                have_labels = {x.get("label") or x.get("name") for x in cur.get(key, [])}
                cur[key] = cur.get(key, []) + [x for x in data[key] if (x.get("label") or x.get("name")) not in have_labels]
                if fn == "tasks.json":
                    ids = {i["id"] for i in cur.get("inputs", [])}
                    cur["inputs"] = cur.get("inputs", []) + [i for i in data.get("inputs", []) if i["id"] not in ids]
                data = cur
            except ValueError:
                p = vs / fn.replace(".json", ".board.json")
        atomic_write(p, json.dumps(data, indent=2) + "\n", 0o644); written.append(str(p.relative_to(root)))
    if not (root / ".boardignore").exists():
        (root / ".boardignore").write_text("# not copied to the device by board sync/push\n" + "\n".join(DEFAULT_IGNORES) + "\n")
        written.append(".boardignore")
    if kind == "c" and not (root / "cmake/aarch64.cmake").exists():
        (root / "cmake").mkdir(exist_ok=True); (root / "cmake/aarch64.cmake").write_text(CMAKE_TOOLCHAIN); written.append("cmake/aarch64.cmake")
    if d and default in reg:
        reg[default].setdefault("local", str(root))
        reg[default].setdefault("project", remote.replace(dev_home(d), "~", 1) if remote.startswith(dev_home(d)) else remote)
        save_registry(reg)
    say(good(f"✓ {kind} project wired to {default or 'your boards'}: ") + ", ".join(written))
    say(dim("  In VS Code: Ctrl+Shift+B = deploy + run · F5 = debug on the device · Terminal → Run Task for the rest"))
    return OK


# ───────────────────────────── hotplug events (used by system-adapt) ─────────────────────────────
def classify_usb_event(props, reg=None):
    """udev properties of an 'add' event → (title, body, actions) or None. actions: [(id, label, argv)]."""
    sub, action = props.get("SUBSYSTEM"), props.get("ACTION")
    if action != "add": return None
    vid, pid = props.get("ID_VENDOR_ID", "").lower(), props.get("ID_MODEL_ID", "").lower()
    key = f"{vid}:{pid}"
    term = terminal_argv()
    if sub == "tty" and props.get("DEVNAME", "").startswith(("/dev/ttyUSB", "/dev/ttyACM")):
        dev = props["DEVNAME"]
        byid = next((l for l in props.get("DEVLINKS", "").split() if "/by-id/" in l), dev)
        owner = next((n for n, d in devices(reg).items() if d.get("serial") and os.path.realpath(d["serial"]) == os.path.realpath(byid)), "")
        label = USB_IDS.get(key) or props.get("ID_MODEL_FROM_DATABASE") or props.get("ID_MODEL", "USB serial").replace("_", " ")
        title = f"{owner} console connected" if owner else f"{label} connected"
        if key == "2e8a:0005":
            return (title, f"MicroPython REPL on {Path(dev).name}",
                    [("repl", "Open REPL", term + ["board", "serial", byid]),
                     ("code", "VS Code", ["code", str(HOME)])])
        return (title, f"{Path(dev).name}" + (f" · {owner}" if owner else ""),
                [("open", "Open console", term + ["board", "serial", owner or byid])])
    if sub == "usb" and props.get("DEVTYPE") == "usb_device":
        if key in ("2e8a:0003", "2e8a:000f"):
            return ("Pico ready to flash", "Drop a .uf2 on the RPI-RP2 drive, or flash the latest build.",
                    [("files", "Open drive", ["gio", "open", f"/media/{os.environ.get('USER', '')}"])])
        if key in ("0483:3748", "0483:374b", "0483:374e", "0483:3752", "0d28:0204", "1366:0101", "1366:1015", "2e8a:000c", "1d50:6018"):
            return (f"{USB_IDS[key]} connected", "Debug probe ready (OpenOCD / probe-rs / Cortex-Debug in VS Code).", [])
    if sub == "net" and props.get("INTERFACE", "").startswith("enx" + USB_PREFIX_HOST.replace(":", "")):
        mac = props.get("ID_NET_NAME_MAC", props["INTERFACE"])[3:]
        owner = next((n for n, d in devices(reg).items() if d.get("usb_mac") and usb_macs(n)[0].replace(":", "") == mac), "")
        if owner:
            return (f"{owner} on USB cable", "Connected over one cable. It takes a few seconds to get an address.",
                    [("ssh", "Terminal", term + ["board", "ssh", owner]), ("code", "VS Code", ["board", "code", owner]),
                     ("files", "Files", ["board", "files", owner])])
        return ("Board on USB cable", "A device in USB-cable mode is connected.", [("scan", "Show", term + ["board", "usb", "status"])])
    return None


def terminal_argv(title=None):
    t = settings()["terminal"]
    if t: return shlex.split(t)
    if have("ptyxis"): return ["ptyxis", "--new-window"] + (["-T", title] if title else []) + ["--"]
    if have("kitty"): return ["kitty"] + (["--title", title] if title else []) + ["--"]
    return ["x-terminal-emulator", "-e"]


def notify_with_actions(title, body, actions):
    """Show a notification; run the chosen action. Blocks until dismissed: call it from a thread."""
    if not actions: notify(title, body); return
    args = ["notify-send", "-a", "Remote", "-i", "network-server-symbolic", "--wait"] + \
           [f"--action={i}={label}" for i, label, _ in actions] + [title, body]
    r = sh(*args, timeout=600)
    chosen = r.stdout.strip()
    for i, _, argv in actions:
        if i == chosen:
            subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def watch_hotplug(stop=None):
    """Follow udev and notify (system-adapt runs this in a supervised thread)."""
    p = subprocess.Popen(["udevadm", "monitor", "--udev", "--property", "-s", "tty", "-s", "usb/usb_device", "-s", "net"],
                         stdout=subprocess.PIPE, text=True)
    props, recent = {}, {}
    for line in p.stdout:
        line = line.strip()
        if stop and stop.is_set(): p.terminate(); return
        if not line:
            if props:
                try: ev = classify_usb_event(props)
                except Exception as e: ev = None; print("remote hotplug:", e, flush=True)
                key = ev and ev[0]
                if ev and time.time() - recent.get(key, 0) > 5:          # one popup per device, not per interface
                    recent[key] = time.time()
                    threading.Thread(target=notify_with_actions, args=ev, daemon=True).start()
            props = {}
            continue
        if "=" in line: k, v = line.split("=", 1); props[k] = v
    p.wait()


# ───────────────────────────── Files (Nautilus) scripts ─────────────────────────────
def uri_to_remote(uri):
    """sftp://pi5/home/x or a path under ~/Remote/pi5 → ('pi5', '/home/x'); else None."""
    from urllib.parse import unquote, urlparse
    if uri.startswith("sftp://"):
        u = urlparse(uri); return (u.hostname or ""), unquote(u.path) or "/"
    path = unquote(uri[7:]) if uri.startswith("file://") else uri
    for mp, src in sshfs_mounts().items():
        if path == mp or path.startswith(mp + "/"):
            host, _, base = src.partition(":")
            return host, (base.rstrip("/") + path[len(mp):]) or "/"
    return None


def gui_pick(items, title):
    """items [(value, label, icon, subtitle)] → value, using the themed picker (rofi/zenity fallback)."""
    lines = "\n".join(f"{l}\t{i}\t{s}" for _, l, i, s in items)
    for cmd in (["myos-pick", "--title", title], ["rofi", "-dmenu", "-p", title], ["zenity", "--list", "--column", title]):
        if have(cmd[0]):
            r = subprocess.run(cmd, input=lines if cmd[0] == "myos-pick" else "\n".join(l for _, l, _, _ in items),
                               capture_output=True, text=True)
            if r.returncode != 0: return None
            label = r.stdout.strip().split("\t")[0]
            return next((v for v, l, _, _ in items if l == label), None)
    return None


def cmd_nautilus(a):
    uris = [u for u in os.environ.get("NAUTILUS_SCRIPT_SELECTED_URIS", "").splitlines() if u] or \
           [os.environ.get("NAUTILUS_SCRIPT_CURRENT_URI", "")]
    if a.action == "send":
        paths = [p for p in os.environ.get("NAUTILUS_SCRIPT_SELECTED_FILE_PATHS", "").splitlines() if p]
        if not paths: notify("Send to device", "Select local files or folders first."); return USAGE
        devs = devices()
        st = load_state()
        items = [(n, n, "computer-symbolic", (d.get("model") or d.get("kind") or "") + f" → {remote_path(d)}")
                 for n, d in sorted(devs.items(), key=lambda kv: -st.get(kv[0], {}).get("used", 0))
                 if d.get("host") or d.get("kind") != "mcu"]
        if not items: notify("No devices yet", "Add one with: board add NAME HOST"); return USAGE
        name = gui_pick(items, f"Send {len(paths)} item{'s' if len(paths) > 1 else ''} to")
        if not name: return USAGE
        notify(f"Sending to {name}…", ", ".join(Path(p).name for p in paths[:4]))
        r = subprocess.run([sys.executable, str(SELF), "push", name, *paths], capture_output=True, text=True)
        if r.returncode == 0: notify(f"Sent to {name}", f"{len(paths)} item(s) → {remote_path(devs[name])}")
        else: notify(f"Couldn't send to {name}", (r.stderr or r.stdout).strip()[-200:], "critical")
        return r.returncode
    targets = [x for x in (uri_to_remote(u) for u in uris) if x]
    if not targets:
        notify("Not a device folder", "Use this on a device in Files (sftp://…) or a mount in ~/Remote."); return USAGE
    if a.action == "copy":
        text = "\n".join(f"{h}:{p}" for h, p in targets)
        subprocess.run(["wl-copy"], input=text, text=True)
        notify("Copied", text)
        return OK
    if a.action == "code":
        h, p = targets[0]
        d = devices().get(h, {})
        if needs_sshfs_mode(d) or h not in devices():
            subprocess.Popen(["code", str(MOUNTS / h) if (MOUNTS / h).exists() else p], start_new_session=True)
        else:
            subprocess.Popen(["code", "--remote", f"ssh-remote+{h}", p], start_new_session=True)
        return OK
    if a.action == "terminal":
        h, p = targets[0]
        subprocess.Popen(terminal_argv(f"⇄ {h}") + [*SSH_CMD, "-t", h, f"cd {shlex.quote(p)} && exec $SHELL -l"],
                         start_new_session=True)
        return OK
    return USAGE


# ───────────────────────────── menu (bare `board`) ─────────────────────────────
ACTIONS = [("ssh", "Terminal (tmux)"), ("code", "VS Code"), ("files", "Files"), ("serial", "Serial console"),
           ("sync", "Sync this folder + run"), ("ports", "Open ports"), ("logs", "Logs"), ("info", "Info"),
           ("top", "Processes (btop)"), ("mount", "Mount at ~/Remote"), ("reboot", "Reboot"), ("doctor", "Diagnose")]


def cmd_menu(a):
    reg = load_registry()
    if not devices(reg):
        say(bold("No devices yet.") + "\n  board scan            find devices on your network"
                                      "\n  board add NAME HOST   add one by hand\n  board flash           prepare an SD card")
        return OK
    name = pick_device(reg)
    act = pick([(k, l) for k, l in ACTIONS], f"{name}")
    return main([act if act != "reboot" else "reboot", name])


# ───────────────────────────── argparse ─────────────────────────────
def build_parser():
    p = argparse.ArgumentParser(prog="board", description="Your devices over SSH.", formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd")

    def add(name, fn, help, aliases=()):
        q = sp.add_parser(name, help=help, aliases=list(aliases), description=help); q.set_defaults(fn=fn); return q

    q = add("add", cmd_add, "add or update a device")
    q.add_argument("name", nargs="?"); q.add_argument("host", nargs="?")
    q.add_argument("-u", "--user"); q.add_argument("-p", "--port", type=int); q.add_argument("--kind", choices=KINDS)
    q.add_argument("--project", help="remote folder, e.g. ~/robot"); q.add_argument("--local", help="local folder (. = here)")
    q.add_argument("--tag", action="append"); q.add_argument("--jump", help="ProxyJump host"); q.add_argument("--identity")
    q.add_argument("--serial"); q.add_argument("--mac"); q.add_argument("--notes"); q.add_argument("--agent", action="store_true")
    q.add_argument("--no-proxy", action="store_true", help="plain ssh, no smart path selection")
    q.add_argument("--no-copy-id", action="store_true"); q.add_argument("--offline", action="store_true", help="save without connecting")
    q.add_argument("--update", action="store_true"); q.add_argument("-y", "--yes", action="store_true")
    q = add("copy-id", cmd_copy_id, "install your key on a device (asks its password once)"); q.add_argument("name", nargs="?")
    q = add("rm", cmd_rm, "remove a device from the list"); q.add_argument("name", nargs="?"); q.add_argument("--forget", action="store_true"); q.add_argument("-y", "--yes", action="store_true")
    q = add("mv", cmd_mv, "rename a device (keeps its trusted host key)", ("rename",)); q.add_argument("old"); q.add_argument("new")
    q = add("trust", cmd_trust, "after a reflash: show the new host key and trust it"); q.add_argument("name", nargs="?")
    q.add_argument("--check", action="store_true", help="only show the fingerprint (JSON)"); q.add_argument("-y", "--yes", action="store_true")
    q = add("set", cmd_set, "change fields: board set pi5 project=~/robot tags=lab,robot"); q.add_argument("name"); q.add_argument("pairs", nargs="+")
    add("edit", cmd_edit, "edit devices.toml (validated)")
    add("gen", cmd_gen, "regenerate ssh config, VS Code and Files entries")
    q = add("ls", cmd_ls, "devices and their status", ("list",)); q.add_argument("--tag"); q.add_argument("--json", action="store_true"); q.add_argument("--fast", action="store_true", help="no live status")
    q = add("info", cmd_info, "details: model, OS, temperature, power, disk"); q.add_argument("name", nargs="?"); q.add_argument("--json", action="store_true")
    q = add("doctor", cmd_doctor, "explain what's wrong and how to fix it"); q.add_argument("name", nargs="?")
    q = add("setup", cmd_setup, "SSH key, ssh config, VS Code; once per laptop")
    q.add_argument("--github", action="store_true", help="add the key to GitHub (gh)"); q.add_argument("--signing", action="store_true", help="sign git commits with the key")
    q = add("ssh", cmd_ssh, "terminal on the device (tmux)", ("s",)); q.add_argument("name", nargs="?")
    q.add_argument("--plain", action="store_true", help="no tmux"); q.add_argument("--session"); q.add_argument("-y", "--yes", action="store_true")
    q.add_argument("cmd", nargs=argparse.REMAINDER)
    q = add("mosh", cmd_mosh, "terminal over mosh (flaky Wi-Fi)"); q.add_argument("name", nargs="?")
    q = add("code", cmd_code, "VS Code on the device", ("c",)); q.add_argument("name", nargs="?"); q.add_argument("path", nargs="?")
    q.add_argument("--mount", action="store_true", help="local VS Code on a mount"); q.add_argument("--remote", action="store_true", help="force Remote-SSH")
    q = add("files", cmd_files, "open the device in Files (sftp)", ("f",)); q.add_argument("name", nargs="?"); q.add_argument("path", nargs="?"); q.add_argument("--print", action="store_true")
    q = add("mount", cmd_mount, "mount at ~/Remote/NAME (sshfs)"); q.add_argument("name", nargs="?"); q.add_argument("path", nargs="?"); q.add_argument("--open", action="store_true")
    q = add("umount", cmd_umount, "unmount (all if no name)", ("unmount",)); q.add_argument("name", nargs="?")
    q = add("push", cmd_push, "copy files to the device (project folder by default)"); q.add_argument("name", nargs="?"); q.add_argument("src", nargs="*")
    q.add_argument("--to"); q.add_argument("--delete", action="store_true", help="mirror: remove files the source doesn't have")
    q.add_argument("--contents", action="store_true", help="copy a folder's contents, not the folder")
    q = add("pull", cmd_pull, "copy files from the device"); q.add_argument("name"); q.add_argument("src", nargs="+"); q.add_argument("--to")
    q = add("sync", cmd_sync, "mirror a local folder to the device on every save"); q.add_argument("name", nargs="?")
    q.add_argument("--local"); q.add_argument("--remote"); q.add_argument("--run", help="command to (re)run after each sync")
    q.add_argument("--once", action="store_true"); q.add_argument("--delete", action="store_true")
    q = add("run", cmd_run, "run a command on a device (or @tag / @all)", ("x",)); q.add_argument("target", nargs="?")
    q.add_argument("--here", action="store_true", help="don't cd into the project"); q.add_argument("cmd", nargs=argparse.REMAINDER)
    q = add("ports", cmd_ports, "open device ports on this laptop"); q.add_argument("name", nargs="?"); q.add_argument("specs", nargs="*")
    q.add_argument("--close", action="store_true"); q.add_argument("--list", action="store_true"); q.add_argument("--open", action="store_true")
    q = add("share", cmd_share, "let the device reach a laptop port (e.g. 11434 local AI)"); q.add_argument("name"); q.add_argument("ports", nargs="+"); q.add_argument("--as", dest="as_port")
    q = add("logs", cmd_logs, "follow the device's logs (--why: explain them)"); q.add_argument("name", nargs="?"); q.add_argument("unit", nargs="?")
    q.add_argument("--why", action="store_true"); q.add_argument("-n", "--lines", type=int, default=100); q.add_argument("--no-follow", action="store_true")
    q = add("top", cmd_top, "processes on the device"); q.add_argument("name", nargs="?")
    for act in ("reboot", "poweroff"):
        q = add(act, cmd_power, f"{act} and report when it's back"); q.add_argument("name", nargs="?"); q.add_argument("-y", "--yes", action="store_true"); q.set_defaults(action=act)
    q = add("wake", cmd_wake, "wake-on-LAN"); q.add_argument("name", nargs="?")
    q = add("forget", cmd_forget, "forget a device's host key (after reflashing)"); q.add_argument("name", nargs="?")
    q = add("serial", cmd_serial, "serial console (device name, port, or pick)", ("console",)); q.add_argument("target", nargs="?")
    q.add_argument("-b", "--baud", type=int); q.add_argument("--hex", action="store_true"); q.add_argument("--list", action="store_true")
    add("serial-log", cmd_serial_last, "open the latest serial log")
    q = add("scan", cmd_scan, "find devices on your networks"); q.add_argument("--net"); q.add_argument("--port", type=int, default=22)
    q.add_argument("--json", action="store_true"); q.add_argument("--list", action="store_true"); q.add_argument("-y", "--yes", action="store_true")
    q = add("net", cmd_net, "everything on your network: IPs, names, vendors, open ports · info · ports HOST")
    q.add_argument("action", choices=("hosts", "info", "ports"), nargs="?", default="hosts"); q.add_argument("target", nargs="?")
    q.add_argument("--net", help="a subnet you're on, e.g. 192.168.1.0/24"); q.add_argument("--ports", help="ports for `net ports`: 22,80,8000-8100")
    q.add_argument("--fast", action="store_true", help="skip the port check"); q.add_argument("--public", action="store_true", help="also show your public IP (asks api.ipify.org)")
    q.add_argument("--json", action="store_true"); q.add_argument("-y", "--yes", action="store_true")
    q = add("usb", cmd_usb, "one-USB-cable mode: setup | status | enable NAME | disable NAME"); q.add_argument("action", choices=("setup", "status", "enable", "disable"), nargs="?", default="status"); q.add_argument("name", nargs="?")
    q = add("link", cmd_link, "direct Ethernet cable to a device: on | off | status"); q.add_argument("action", choices=("on", "off", "status"), nargs="?", default="status")
    q = add("hotspot", cmd_hotspot, "laptop Wi-Fi hotspot for devices: on | off | status"); q.add_argument("action", choices=("on", "off", "status"), nargs="?", default="status"); q.add_argument("-y", "--yes", action="store_true")
    q = add("flash", cmd_flash, "write an SD card / USB drive ready for key login"); q.add_argument("--image"); q.add_argument("--disk"); q.add_argument("--name"); q.add_argument("--user")
    q.add_argument("--no-wifi", action="store_true"); q.add_argument("--no-uart", action="store_true")
    q.add_argument("--gadget", action="store_true", default=None); q.add_argument("--no-gadget", dest="gadget", action="store_false")
    q = add("bootstrap", cmd_bootstrap, "set a fresh device up (tmux, updates, keys only)"); q.add_argument("name", nargs="?")
    q.add_argument("--packages", nargs="*", default=[]); q.add_argument("--interfaces", default="", help="i2c,spi,serial,camera,onewire,vnc")
    q.add_argument("--swap", type=int, default=0); q.add_argument("--no-harden", action="store_true"); q.add_argument("--no-upgrade", action="store_true"); q.add_argument("-y", "--yes", action="store_true")
    q = add("backup", cmd_backup, "image the device's SD card over the network"); q.add_argument("name", nargs="?"); q.add_argument("--to"); q.add_argument("-y", "--yes", action="store_true")
    q = add("ferry", cmd_ferry, "carry .deb / .whl files to an offline device and install them"); q.add_argument("name"); q.add_argument("dir")
    q = add("gui", cmd_gui, "run a device GUI app as a window here (waypipe)"); q.add_argument("name"); q.add_argument("app", nargs="+")
    q = add("cam", cmd_cam, "live camera preview from the device"); q.add_argument("name", nargs="?"); q.add_argument("--size"); q.add_argument("--fps", type=int, default=30); q.add_argument("--record")
    q = add("init-project", cmd_init_project, "VS Code deploy/run/debug tasks for this project", ("init",))
    q.add_argument("path", nargs="?"); q.add_argument("--kind", choices=("python", "c", "mcu", "ros2")); q.add_argument("--device")
    q.add_argument("--entry"); q.add_argument("--run"); q.add_argument("--force", action="store_true")
    q = add("job", cmd_job, "long command on a device that keeps running after you disconnect; notifies when done (ls | log | kill)")
    q.add_argument("rest", nargs=argparse.REMAINDER, help="NAME [--here] [--json] -- COMMAND · ls [--json] · log ID [-f] [-n N] · kill ID · forget ID")
    q = add("watch", cmd_watch, "alerts: on NAME | off NAME (device health) · on | off (new devices on this network) · status")
    q.add_argument("action", choices=("status", "on", "off", "check"), nargs="?", default="status"); q.add_argument("target", nargs="?")
    q.add_argument("--label", help="name for this network (default: Wi-Fi name)")
    q = add("json", cmd_json, "machine-readable output: names | devices | status | serial | scan | tunnels | mounts"); q.add_argument("what")
    q = sp.add_parser("_proxy"); q.add_argument("name"); q.add_argument("port"); q.set_defaults(fn=cmd_proxy)
    q = sp.add_parser("_nautilus"); q.add_argument("action", choices=("send", "copy", "code", "terminal")); q.set_defaults(fn=cmd_nautilus)
    q = sp.add_parser("_hotplug"); q.set_defaults(fn=lambda a: watch_hotplug() or 0)
    add("help", lambda a: (p.print_help(), 0)[1], "every command")
    return p


def cmd_json(a):
    w = a.what
    if w == "names": print("\n".join(sorted(devices()))); return OK
    if w == "devices": print(json.dumps(devices(), indent=1)); return OK
    if w == "status": print(json.dumps(status_all(), indent=1)); return OK
    if w == "serial": print(json.dumps(serial_ports(), indent=1)); return OK
    if w == "scan": print(json.dumps(do_scan(), indent=1)); return OK
    if w == "net": print(json.dumps(net_hosts(), indent=1)); return OK
    if w == "links": print(json.dumps(links_state(), indent=1)); return OK
    if w == "tunnels": print(json.dumps(tunnels(), indent=1)); return OK
    if w == "mounts": print(json.dumps(sshfs_mounts(), indent=1)); return OK
    if w == "jobs": print("\n".join(sorted(jobs_state(), reverse=True))); return OK      # IDs, for completion (no ssh)
    raise Fail(f"json what? names | devices | status | serial | scan | net | links | tunnels | mounts | jobs", USAGE)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    p = build_parser()
    if not argv: argv = ["_menu"]
    if argv[0] == "_menu":
        fn, a = cmd_menu, argparse.Namespace()
    else:
        a = p.parse_args(argv)
        if not getattr(a, "fn", None): p.print_help(); return USAGE
        fn = a.fn
        if getattr(a, "cmd", None) and isinstance(a.cmd, list) and a.cmd[:1] == ["--"]: a.cmd = a.cmd[1:]
    try:
        return fn(a) or OK
    except Fail as e:
        err(bad("✗ ") + str(e)); return e.code
    except KeyboardInterrupt:
        err(""); return 130


if __name__ == "__main__":
    sys.exit(main())
