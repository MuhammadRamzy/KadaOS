#!/usr/bin/env python3
"""usb-guard: new USB devices stay blocked until you allow them (USBGuard), with a notification to decide.

  usb-guard                 devices USBGuard knows about, allowed or blocked
  usb-guard allow ID [--always]    let a blocked device in (--always: remember it)
  usb-guard block ID
  usb-guard watch           the notifier (a user service runs it): Allow once / Always allow / Keep blocked

Why: a USB stick can pretend to be a keyboard and type commands ("BadUSB"). With USBGuard only devices you know work.
The laptop's own keyboard and touchpad aren't USB, so they always work, even if every USB device were blocked.
Setup (needs your password, be at the laptop): bash scripts/phase16-usbguard.sh. Recovery: docs/USB_GUARD.md.
"""
import re, subprocess, sys
from pathlib import Path

HOME = Path.home()
NOTIFY = HOME / ".config/hypr/scripts/notify-action.py"
CLASSES = {"01": "audio", "02": "network/modem", "03": "keyboard/mouse (HID)", "06": "camera/scanner", "07": "printer",
           "08": "storage", "09": "hub", "0a": "network/modem", "0b": "smart card", "0e": "video", "e0": "wireless/Bluetooth",
           "ef": "multi-function", "fe": "firmware/debug", "ff": "vendor-specific"}


def run(*a, timeout=10):
    try: return subprocess.run(a, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e: return subprocess.CompletedProcess(a, 124, "", str(e))


def parse_rule(rule):
    """{target, vid_pid, name, kinds} from a USBGuard device rule line."""
    m = re.match(r"(?:(\d+):\s+)?(allow|block|reject)\s+id\s+([0-9a-f*]{4}:[0-9a-f*]{4})", rule)
    name = re.search(r'\bname "([^"]*)"', rule)
    ifaces = re.findall(r"\b([0-9a-f]{2}):[0-9a-f*]{2}:[0-9a-f*]{2}\b", rule.split("with-interface", 1)[1]) if "with-interface" in rule else []
    kinds = sorted({CLASSES.get(c, f"class {c}") for c in ifaces})
    return {"id": m[1] if m and m[1] else "", "target": m[2] if m else "", "vid_pid": m[3] if m else "",
            "name": name[1] if name else "", "kinds": kinds}


def describe(d):
    """A plain sentence for the notification, warning loudly when a storage-looking gadget also claims to be a keyboard."""
    k = d["kinds"]; what = ", ".join(k) or "unknown kind"
    warn = "  ⚠ It says it's a keyboard: if this is a USB stick or cable, keep it blocked." if "keyboard/mouse (HID)" in k and len(k) > 1 else ""
    return f"{d['name'] or 'Unnamed device'} ({d['vid_pid']}) · {what}.{warn}"


def events(lines):
    """Yield device dicts for 'inserted and blocked' events from `usbguard watch` output."""
    cur = {}
    for line in lines:
        line = line.rstrip("\n")
        m = re.match(r"\[device\] (\w+): id=(\d+)", line)
        if m: cur = {"event_type": m[1], "id": m[2]}; continue
        m = re.match(r"\s+(\w+)=(.*)", line)
        if not m or not cur: continue
        cur[m[1]] = m[2]
        if m[1] == "device_rule" and cur.get("event_type") == "PresenceChanged" and cur.get("event") == "Insert" and cur.get("target") == "block":
            d = parse_rule(m[2]); d["id"] = cur["id"]; yield d
            cur = {}


def notify(d):
    r = subprocess.run([sys.executable, str(NOTIFY), "-i", "drive-removable-media-symbolic", "-t", "120", "New USB device blocked",
                        describe(d), "once=Allow once", "always=Always allow", "block=Keep blocked"],
                       capture_output=True, text=True)
    choice = r.stdout.strip()
    if choice == "once": run("usbguard", "allow-device", d["id"])
    elif choice == "always": run("usbguard", "allow-device", "-p", d["id"])


def watch():
    p = subprocess.Popen(["usbguard", "watch"], stdout=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
    import threading
    for d in events(p.stdout):
        threading.Thread(target=notify, args=(d,), daemon=True).start()     # one notification per device, side by side
    return p.wait()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "list"
    if cmd in ("-h", "--help"): print(__doc__.strip()); return 0
    if not run("sh", "-c", "command -v usbguard").stdout.strip():
        print("USBGuard isn't installed: bash scripts/phase16-usbguard.sh"); return 1
    if cmd == "watch": return watch()
    if cmd in ("allow", "block") and len(argv) > 1 and argv[1].isdigit():
        r = run("usbguard", f"{cmd}-device", *(["-p"] if "--always" in argv else []), argv[1])
        print((r.stdout + r.stderr).strip() or "done"); return r.returncode
    if cmd == "list":
        r = run("usbguard", "list-devices")
        if r.returncode: print((r.stderr or r.stdout).strip() or "USBGuard isn't answering (is the service running?)"); return 1
        for line in r.stdout.splitlines():
            d = parse_rule(line)
            print(f"{d['id']:>3}  {d['target']:<6} {d['vid_pid']}  {d['name'] or '?':<34} {', '.join(d['kinds'])}")
        return 0
    print(__doc__.strip()); return 2


if __name__ == "__main__":
    sys.exit(main())
