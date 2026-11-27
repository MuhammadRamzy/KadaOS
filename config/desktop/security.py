#!/usr/bin/env python3
"""security-check: this laptop's security checkup, in plain words. Read-only: it never changes anything.

  security-check      every check: ✓ good · ! worth fixing · ✗ fix soon, with why and the fix
  security-check --json  the same as data (the Security panel uses it)

The fixes are shown, not run: commands that need your password are for you to run; the panel offers the safe ones as
buttons. Pentest tooling is separate (seclab, Super+H).
"""
import getpass, json, re, shutil, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
FW_CACHE = HOME / ".cache/myos-security-fw.json"     # firmware check asks the internet: at most once a day
OK, WARN, BAD, INFO = "ok", "warn", "bad", "info"
# Things that are supposed to listen on the network here (port → what it is).
EXPECTED = {1716: "KDE Connect (phone link)", 5353: "mDNS (finding devices by name)", 67: "virtual machines' DHCP (virbr0 only)",
            53: "DNS"}
ROOT_GROUPS = {"docker": "Docker", "lxd": "LXD"}


def run(*argv, timeout=15):
    try: return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e: return subprocess.CompletedProcess(argv, 124, "", str(e))


def have(c): return shutil.which(c) is not None


def check(id_, title, state, detail, why="", fix=None):
    """fix: {"cmd": "...", "root": bool, "label": "..."} — a command to run (root ones only shown)."""
    return {"id": id_, "title": title, "state": state, "detail": detail, "why": why, "fix": fix}


# ── individual checks (each pure enough to test with canned input) ──
def parse_listeners(ss_text):
    """[(proto, addr, port, process)] for sockets listening beyond this laptop (not 127.x / ::1 / scoped to lo)."""
    out = []
    for line in (ss_text or "").splitlines():
        f = line.split()
        if len(f) < 5: continue
        proto, local = f[0], f[4] if f[0] in ("tcp", "udp") else f[3]
        if f[0] not in ("tcp", "udp"): proto, local = "tcp", f[3]
        addr, _, port = local.rpartition(":")
        if not port.isdigit(): continue
        a = addr.strip("[]").split("%")[0]
        if a.startswith("127.") or a == "::1" or "%lo" in addr: continue
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        out.append((proto, addr, int(port), program(m[1], m[2]) if m else ""))
    return out


def program(name, pid):
    """The real program: for interpreters (python3, node, …) the script they run, e.g. 'wsdd --no-host'."""
    if name not in ("python3", "python", "node", "perl", "ruby", "bash", "sh"): return name
    try: args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError: return name
    script = next((a.decode(errors="replace") for a in args[1:] if a and not a.startswith(b"-")), "")
    flags = " ".join(a.decode() for a in args if a in (b"--no-host",))
    return (Path(script).name + (" " + flags if flags else "")) if script else name


def listeners_check(ss_text):
    seen, odd = set(), []
    for proto, addr, port, proc in parse_listeners(ss_text):
        if proto == "udp" and port > 10000: continue          # outgoing-connection sockets, not servers
        if (port, proc) in seen: continue
        seen.add((port, proc))
        if port in EXPECTED or (port == 53 and "192.168.122." in addr) or proc == "wsdd --no-host": continue   # Files finding
        # Windows PCs; --no-host = it never announces this laptop
        odd.append(f"{proto} {port}" + (f" ({proc})" if proc else " (a system service)"))
    if not odd:
        return check("ports", "Open to the network", OK, "Only expected services listen: " + ", ".join(sorted(set(EXPECTED.values()))[:3]) + ".",
                     "Anything listening on the network can be reached by others on the same Wi-Fi.")
    return check("ports", "Open to the network", WARN, "Listening beyond this laptop: " + "; ".join(odd[:6]) + ".",
                 "Others on the same Wi-Fi (office, café) can reach these. Stop what you don't need, or bind it to 127.0.0.1.",
                 {"cmd": "ss -tulpn", "root": False, "label": "Show details"})


def ssh_key_check(keys):
    """keys: {path: has_passphrase}"""
    if not keys:
        return check("ssh-key", "SSH key", INFO, "No SSH key yet.", "Remote devices use one (Super+R sets it up).")
    open_ = [p for p, has in keys.items() if not has]
    if open_:
        p = open_[0]
        return check("ssh-key", "SSH key has no passphrase", BAD, f"{p.replace(str(HOME), '~')} can be used by anyone who copies the file.",
                     "This key logs into your Pis and servers. With a passphrase, a stolen copy is useless; the keyring "
                     "remembers it after login, so you won't type it all the time.",
                     {"cmd": f"ssh-keygen -p -f {p}", "root": False, "label": "Add a passphrase"})
    return check("ssh-key", "SSH key", OK, "Protected by a passphrase.")


def groups_check(groups):
    risky = [ROOT_GROUPS[g] for g in groups if g in ROOT_GROUPS]
    if not risky: return check("groups", "Admin without a password", OK, "No group gives root without your password.")
    return check("groups", "Admin without a password", WARN, f"You're in the {' and '.join(risky)} group{'s' if len(risky) > 1 else ''}: "
                 "anything running as you can become root without a password.",
                 "Common for developers (docker without sudo). The risk: a malicious script or package you run gets full control. "
                 "Keep it if you use Docker daily; otherwise remove it.",
                 {"cmd": " && ".join(f"sudo gpasswd -d {getpass.getuser()} {g}" for g in groups if g in ROOT_GROUPS), "root": True,
                  "label": "Remove (then log out and in)"})


def failed_logins_check(journal_text):
    lines = [l for l in (journal_text or "").splitlines() if l.strip()]
    if not lines: return check("logins", "Failed logins (7 days)", OK, "None.")
    return check("logins", "Failed logins (7 days)", WARN if len(lines) >= 5 else INFO, f"{len(lines)} failed attempt(s); latest: {lines[-1][:90]}",
                 "A few are usually your own typos (sudo, the lock screen). Many in a row, or over SSH, are worth a look.",
                 {"cmd": "journalctl --since -7d -g 'authentication failure|Failed password'", "root": False, "label": "Show them"})


def updates_check(apt_text, unattended):
    m = re.search(r"(\d+) updates? can be applied immediately", apt_text or "")
    sec = re.search(r"(\d+) of these updates? (?:is a|are) (?:standard )?security", apt_text or "")
    n, s = (int(m[1]) if m else None), (int(sec[1]) if sec else 0)
    auto = "Security updates install automatically." if unattended else "Automatic security updates are OFF."
    if n is None: return check("updates", "Updates", INFO, "Couldn't read the update status. " + auto)
    if s: return check("updates", "Updates", BAD, f"{s} security update(s) waiting. " + auto, "Security updates close holes attackers already know about.",
                       {"cmd": "sudo apt update && sudo apt upgrade", "root": True, "label": "Update now"})
    if not unattended:
        return check("updates", "Updates", WARN, f"{n} update(s) waiting. " + auto, "Without them, fixes wait until you remember.",
                     {"cmd": "sudo dpkg-reconfigure -plow unattended-upgrades", "root": True, "label": "Turn on automatic updates"})
    return check("updates", "Updates", OK, (f"{n} non-security update(s) waiting. " if n else "Up to date. ") + auto)


def firmware_check(fw_json, checked_at):
    when = time.strftime("%d %b", time.localtime(checked_at)) if checked_at else "never"
    try: devs = json.loads(fw_json)["Devices"] if fw_json else None       # no answer is "unknown", never "all good"
    except (ValueError, KeyError, TypeError): devs = None
    if devs is None: return check("firmware", "Firmware (BIOS, SSD…)", INFO, f"Couldn't check (last try: {when}).")
    if devs:
        names = ", ".join(d.get("Name", "device") for d in devs[:3])
        return check("firmware", "Firmware (BIOS, SSD…)", WARN, f"Updates for: {names}.", "Firmware updates fix security and stability bugs below the OS.",
                     {"cmd": "fwupdmgr update", "root": False, "label": "Install firmware updates"})
    return check("firmware", "Firmware (BIOS, SSD…)", OK, f"No updates (checked {when}).")


# ── live readings ──
def ssh_keys():
    out = {}
    for k in sorted((HOME / ".ssh").glob("id_*")):
        if k.suffix == ".pub" or not k.is_file(): continue
        out[str(k)] = run("ssh-keygen", "-y", "-P", "", "-f", str(k), timeout=5).returncode != 0    # opens with no passphrase → none
    return out


def firmware():
    try:
        c = json.loads(FW_CACHE.read_text())
        if time.time() - c["t"] < 86400: return c["out"], c["t"]
    except (OSError, ValueError, KeyError): pass
    if not have("fwupdmgr"): return "", 0
    r = run("fwupdmgr", "get-updates", "--json", "--no-unreported-check", timeout=40)
    out = r.stdout if r.stdout.strip().startswith("{") else '{"Devices": []}' if "No updatable devices" in r.stdout + r.stderr or "No updates" in r.stdout + r.stderr else ""
    if out:
        FW_CACHE.parent.mkdir(parents=True, exist_ok=True); FW_CACHE.write_text(json.dumps({"t": time.time(), "out": out}))
    return out, time.time() if out else 0


def gather():
    checks = []
    fw = run("systemctl", "is-active", "ufw").stdout.strip()
    checks.append(check("firewall", "Firewall", OK, "On: nothing can connect in unless allowed.") if fw == "active" else
                  check("firewall", "Firewall", BAD, "Off: anything listening is reachable by others on the network.",
                        "The firewall blocks incoming connections you didn't allow.", {"cmd": "sudo ufw enable", "root": True, "label": "Turn on"}))
    checks.append(listeners_check(run("ss", "-tulpnH").stdout))
    crypt = "crypt" in run("lsblk", "-o", "TYPE").stdout
    checks.append(check("encryption", "Disk encryption", OK, "Your disk is encrypted.") if crypt else
                  check("encryption", "Disk encryption", BAD, "Not encrypted: if the laptop is lost or stolen, every file can be read.",
                        "A login password doesn't protect the disk: it can be read from another computer. Full-disk encryption "
                        "is set up at install time; until then, encrypt the folders that matter (build plan item 16).",
                        {"cmd": "", "root": False, "label": "Plan: encrypted folders"}))
    sb = run("mokutil", "--sb-state").stdout if have("mokutil") else ""
    checks.append(check("secureboot", "Secure Boot", OK, "On.") if "enabled" in sb else
                  check("secureboot", "Secure Boot", WARN if sb else INFO, "Off." if sb else "Unknown (mokutil missing).",
                        "Secure Boot stops tampered bootloaders and kernels. Turning it on is a BIOS setting; the NVIDIA driver then "
                        "needs its key enrolled once (Ubuntu asks for a password at the next boot).", None))
    checks.append(updates_check(run("/usr/lib/update-notifier/apt-check", "--human-readable", timeout=30).stdout,
                                run("systemctl", "is-enabled", "unattended-upgrades").stdout.strip() == "enabled"))
    checks.append(firmware_check(*firmware()))
    checks.append(ssh_key_check(ssh_keys()))
    checks.append(groups_check(run("id", "-nG").stdout.split()))
    checks.append(failed_logins_check(run("journalctl", "-q", "--since", "-7d", "--no-pager", "-o", "short",
                                          "-g", "authentication failure|Failed password|FAILED SU", timeout=30).stdout))
    sshd = run("systemctl", "is-active", "ssh").stdout.strip() == "active"
    checks.append(check("sshd", "Remote login to this laptop (SSH server)", WARN if sshd else OK,
                        "On: others can try to log in over the network." if sshd else "Off.",
                        "Only needed if you log into this laptop from elsewhere." if sshd else "",
                        {"cmd": "sudo systemctl disable --now ssh", "root": True, "label": "Turn off"} if sshd else None))
    auto = re.search(r"^\s*AutomaticLoginEnable\s*=\s*true", Path("/etc/gdm3/custom.conf").read_text() if Path("/etc/gdm3/custom.conf").exists() else "", re.M | re.I)
    checks.append(check("autologin", "Automatic login", BAD if auto else OK, "On: anyone who opens the laptop is logged in." if auto else "Off: a password is needed.",
                        "", {"cmd": "sudo sed -i 's/^\\s*AutomaticLoginEnable.*/AutomaticLoginEnable = false/' /etc/gdm3/custom.conf", "root": True, "label": "Turn off"} if auto else None))
    lock = re.search(r"timeout\s*=\s*(\d+)\s*\n\s*on-timeout\s*=\s*loginctl lock-session", (HOME / ".config/hypr/hypridle.conf").read_text()
                     if (HOME / ".config/hypr/hypridle.conf").exists() else "")
    checks.append(check("lock", "Screen lock", OK if lock and int(lock[1]) <= 600 else WARN,
                        f"Locks after {int(lock[1]) // 60} min idle, and before sleep." if lock else "No automatic lock found.",
                        "" if lock else "An unlocked, unattended laptop is the easiest way in."))
    wifi = next((l.split(":", 2) for l in run("nmcli", "-t", "-f", "ACTIVE,SSID,SECURITY", "dev", "wifi").stdout.splitlines() if l.startswith("yes:")), None)
    if wifi:
        sec = wifi[2] if len(wifi) > 2 else ""
        checks.append(check("wifi", "This Wi-Fi", WARN if not sec.strip() or sec.strip() == "--" else OK,
                            f"{wifi[1]}: " + ("open, no encryption. Others nearby can see unencrypted traffic." if not sec.strip() or sec.strip() == "--" else f"encrypted ({sec})."),
                            "On open Wi-Fi, use a VPN or your phone's hotspot (network trust levels: build plan item 14)."
                            if not sec.strip() or sec.strip() == "--" else ""))
    return checks


def summary(checks):
    n = {s: sum(c["state"] == s for c in checks) for s in (OK, WARN, BAD, INFO)}
    return {"good": n[OK], "warn": n[WARN], "bad": n[BAD], "info": n[INFO]}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"]): print(__doc__.strip()); return 0
    checks = gather()
    order = {BAD: 0, WARN: 1, INFO: 2, OK: 3}
    checks.sort(key=lambda c: order[c["state"]])
    if "--json" in argv: print(json.dumps({"checks": checks, "summary": summary(checks), "t": time.time()})); return 0
    tty = sys.stdout.isatty()
    col = {OK: "32", WARN: "33", BAD: "31", INFO: "2"}; mark = {OK: "✓", WARN: "!", BAD: "✗", INFO: "·"}
    for c in checks:
        m = f"\033[{col[c['state']]}m{mark[c['state']]}\033[0m" if tty else mark[c["state"]]
        print(f"{m} {c['title']}: {c['detail']}")
        if c["state"] in (WARN, BAD):
            if c["why"]: print(f"    {c['why']}")
            if c["fix"] and c["fix"].get("cmd"): print(f"    fix: {'! ' if c['fix']['root'] else ''}{c['fix']['cmd']}")
    s = summary(checks)
    print(f"\n{s['good']} good · {s['warn']} worth fixing · {s['bad']} fix soon")
    return 0


if __name__ == "__main__":
    sys.exit(main())
