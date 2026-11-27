#!/usr/bin/env python3
"""trust: how much to trust the network you're on: Home, Work or Public. Remembered per network.

  trust                      the current network and its level
  trust home|work|public     set the level for the current network (or: trust public "Cafe Wi-Fi")
  trust menu                 pick one (Super + Ctrl + W)
  trust --json               the same as `trust`, as data

  Home     as configured: devices on the network can find you (phone link, file sharing)
  Work     a per-network random MAC address, encrypted DNS when the server supports it
  Public   a new random MAC every time, encrypted DNS when possible, no mDNS/LLMNR (the laptop doesn't announce itself),
           and the firewall blocks everything coming in on that network (phone link, file sharing, dev servers)

Open Wi-Fi you haven't marked counts as Public. Levels are stored on the network's own NetworkManager profile
(connection.zone), so no password is needed to change them; MAC and DNS changes apply when you reconnect.
The firewall part needs a small root hook: bash scripts/phase15-network-trust.sh (installs this file as a
NetworkManager dispatcher script; it then runs as `90-myos-trust IFACE ACTION`).
"""
import json, os, subprocess, sys
from pathlib import Path

LEVELS = {
    "home":   {"label": "Home", "icon": "user-home-symbolic", "mac": "preserve", "dot": "default", "mdns": "default", "llmnr": "default",
               "desc": "devices here can find you (phone link, sharing)"},
    "work":   {"label": "Work", "icon": "network-workgroup-symbolic", "mac": "stable", "dot": "opportunistic", "mdns": "default", "llmnr": "no",
               "desc": "random MAC per network, encrypted DNS when possible"},
    "public": {"label": "Public", "icon": "security-high-symbolic", "mac": "random", "dot": "opportunistic", "mdns": "no", "llmnr": "no",
               "desc": "new random MAC, encrypted DNS, nothing can connect in"},
}
RULE_COMMENT = "myos-trust public"


def run(*a, timeout=15):
    try: return subprocess.run(a, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e: return subprocess.CompletedProcess(a, 124, "", str(e))


def level_of(zone, key_mgmt, wireless):
    """The effective level: what you chose, else Public for open Wi-Fi, else None (unmarked: left as it is)."""
    if zone in LEVELS: return zone
    if wireless and not key_mgmt: return "public"
    return None


def nm_settings(level):
    """nmcli `connection modify` arguments for a level (wireless ones only for Wi-Fi)."""
    L = LEVELS[level]
    return {"connection.zone": level, "connection.dns-over-tls": L["dot"], "connection.mdns": L["mdns"],
            "connection.llmnr": L["llmnr"], "802-11-wireless.cloned-mac-address": L["mac"]}


def firewall_plan(level, iface, action, have_rule):
    """ufw commands for the dispatcher: block incoming on a Public network's interface; lift it otherwise."""
    if not iface or iface == "lo": return []
    if action in ("down", "pre-down"): want = False
    elif action in ("up", "reapply", "dhcp4-change", "dhcp6-change", "connectivity-change"): want = level == "public"
    else: return []
    if want and not have_rule: return [["ufw", "prepend", "deny", "in", "on", iface, "comment", RULE_COMMENT]]
    if not want and have_rule: return [["ufw", "delete", "deny", "in", "on", iface]]
    return []


def has_rule(status_text, iface):
    return any(f"on {iface}" in l and RULE_COMMENT in l for l in status_text.splitlines())


def active():
    """(name, uuid, type, device) of the connection carrying the default route, or None."""
    for line in run("nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active").stdout.splitlines():
        parts = line.replace("\\:", "\0").split(":")
        if len(parts) == 4 and parts[2] in ("802-11-wireless", "802-3-ethernet"):
            return tuple(p.replace("\0", ":") for p in parts)
    return None


def props(conn):
    out = run("nmcli", "-g", "connection.zone,802-11-wireless-security.key-mgmt", "connection", "show", conn).stdout.splitlines()
    return (out + ["", ""])[0].strip(), (out + ["", ""])[1].strip()


def current():
    a = active()
    if not a: return None
    name, uuid, typ, dev = a
    zone, km = props(uuid)
    lvl = level_of(zone, km, typ == "802-11-wireless")
    return {"name": name, "uuid": uuid, "device": dev, "wireless": typ == "802-11-wireless", "level": lvl, "chosen": zone in LEVELS,
            "open": typ == "802-11-wireless" and not km, "firewall_hook": Path("/etc/NetworkManager/dispatcher.d/90-myos-trust").exists()}


def set_level(level, conn=None):
    c = current() if conn is None else {"uuid": conn, "name": conn, "wireless": True}
    if not c: print("Not connected."); return 1
    s = nm_settings(level)
    if not c["wireless"]: s.pop("802-11-wireless.cloned-mac-address")
    args = [x for kv in s.items() for x in kv]
    r = run("nmcli", "connection", "modify", c["uuid"], *args)
    if r.returncode: print((r.stderr or r.stdout).strip()); return 1
    print(f"{c['name']}: {LEVELS[level]['label']} ({LEVELS[level]['desc']}). MAC and DNS changes apply when you reconnect.")
    if level == "public" and not Path("/etc/NetworkManager/dispatcher.d/90-myos-trust").exists():
        print("Firewall part not installed yet: bash scripts/phase15-network-trust.sh")
    return 0


def dispatch(iface, action):
    """Runs as root from NetworkManager: firewall only (the rest lives on the connection profile)."""
    uuid = os.environ.get("CONNECTION_UUID", "")
    if not uuid or not Path("/usr/sbin/ufw").exists(): return 0
    zone, km = props(uuid)
    wireless = os.environ.get("DEVICE_IFACE", iface).startswith("wl")
    lvl = level_of(zone, km, wireless)
    for cmd in firewall_plan(lvl, iface, action, has_rule(run("ufw", "status").stdout, iface)): run(*cmd)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if Path(sys.argv[0]).name == "90-myos-trust" or argv[:1] == ["_dispatch"]:
        a = argv[1:] if argv[:1] == ["_dispatch"] else argv
        return dispatch(*(a + ["", ""])[:2])
    cmd = argv[0] if argv else "show"
    if cmd in ("-h", "--help"): print(__doc__.strip()); return 0
    if cmd == "menu":
        c = current(); now = LEVELS[c["level"]]["label"] if c and c["level"] else "not set"
        lines = "\n".join(f"{L['label']}\t{L['icon']}\t{L['desc']}" for L in LEVELS.values())
        r = subprocess.run([str(Path.home() / ".config/hypr/scripts/menu.sh"), f"{c['name'] if c else 'Network'} (now: {now})"],
                           input=lines, capture_output=True, text=True)
        pick = next((k for k, L in LEVELS.items() if r.stdout.strip().startswith(L["label"])), None)
        if not pick: return 0
        rc = set_level(pick)
        subprocess.run(["notify-send", "-a", "Network", f"{c['name'] if c else 'Network'}: {LEVELS[pick]['label']}",
                        "Reconnect to apply the new MAC address and DNS."], capture_output=True)
        return rc
    if cmd in LEVELS: return set_level(cmd, argv[1] if len(argv) > 1 else None)
    c = current()
    if cmd == "--json": print(json.dumps(c)); return 0
    if not c: print("Not connected."); return 0
    lvl = c["level"]
    print(f"{c['name']} ({c['device']}): " + (f"{LEVELS[lvl]['label']}" + ("" if c["chosen"] else " (open Wi-Fi)") + f" · {LEVELS[lvl]['desc']}"
                                              if lvl else "not set: trust home | work | public"))
    if not c["firewall_hook"]: print("Firewall hook: not installed (bash scripts/phase15-network-trust.sh)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
