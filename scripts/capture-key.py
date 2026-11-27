#!/usr/bin/env python3
"""Print key codes from all keyboards for 8 seconds (needs sudo). Used to map HP Omen Fn keys."""
import glob, os, select, struct, time
FMT = "llHHi"; SZ = struct.calcsize(FMT)
names = {}
for d in glob.glob("/sys/class/input/event*"):
    try: names["/dev/input/" + os.path.basename(d)] = open(d + "/device/name").read().strip()
    except OSError: pass
fds = {}
for dev, n in names.items():
    if any(k in n.lower() for k in ("keyboard", "wmi", "hotkey", "button")):
        try: fds[os.open(dev, os.O_RDONLY | os.O_NONBLOCK)] = n
        except OSError: pass
prof = lambda: open("/sys/firmware/acpi/platform_profile").read().strip()
print("platform_profile before:", prof()); print(">>> Press Fn+P now (8 seconds)…", flush=True)
end = time.time() + 8
while time.time() < end:
    r, _, _ = select.select(list(fds), [], [], 0.5)
    for fd in r:
        data = os.read(fd, SZ * 64)
        for i in range(0, len(data), SZ):
            _, _, typ, code, val = struct.unpack(FMT, data[i:i + SZ])
            if typ == 1 and val == 1: print(f"KEY code={code}  device='{fds[fd]}'")
            if typ == 4 and code == 4: print(f"MSC scancode=0x{val:x}  device='{fds[fd]}'")
print("platform_profile after:", prof())
