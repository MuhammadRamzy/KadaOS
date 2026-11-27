#!/usr/bin/env python3
"""Set (apply) or clear (undo) KadaOS's keys in GDM's settings keyfile (/etc/gdm3/greeter.dconf-defaults).

  greeter-settings.py FILE apply|undo

Our lines sit under a "# kadaos" marker. An existing active key of the same name is commented out as
"# kadaos-was key=…" (GKeyFile takes the last duplicate, so leaving it would defeat ours) and undo restores it.
Keys: no logo (the backdrop is the mark), the Graphite blue accent and dark style, a 12-hour time-only clock.
"""
import re, sys

KEYS = [("org/gnome/login-screen", "logo", "''"),
        ("org/gnome/desktop/interface", "accent-color", "'blue'"),
        ("org/gnome/desktop/interface", "color-scheme", "'prefer-dark'"),
        ("org/gnome/desktop/interface", "clock-show-date", "false"),       # the big clock shows just the time
        ("org/gnome/desktop/interface", "clock-format", "'12h'")]
OLD_LOGO = "logo='/usr/share/pixmaps/kadaos-login.png'"     # earlier versions set this, without a marker


def undo(t):
    t = re.sub(r"(?m)^# kadaos\n.*\n", "", t)
    t = re.sub(rf"(?m)^{re.escape(OLD_LOGO)}\n", "", t)
    return re.sub(r"(?m)^# kadaos-was ", "", t)


def apply(t):
    t = undo(t)
    for section, key, value in KEYS:
        head = f"[{section}]\n"
        if head not in t: t = t.rstrip("\n") + f"\n\n{head}"
        start = t.index(head) + len(head)
        nxt = re.search(r"(?m)^\[", t[start:])
        end = start + nxt.start() if nxt else len(t)
        body = re.sub(rf"(?m)^({re.escape(key)}\s*=.*)$", r"# kadaos-was \1", t[start:end])
        t = t[:start] + f"# kadaos\n{key}={value}\n" + body + t[end:]
    return t


def main(argv):
    path, mode = argv[1], argv[2]
    t = open(path).read()
    new = apply(t) if mode == "apply" else undo(t) if mode == "undo" else None
    if new is None: print(__doc__.strip()); return 2
    if new != t:
        with open(path, "w") as f: f.write(new)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
