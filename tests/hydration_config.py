#!/usr/bin/env python3
"""Theme, desktop-integration and installer checks for Hydration, all in sandbox HOMEs.

Never touches the live desktop: systemctl, swaync-client and update-desktop-database are stubbed.
"""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REAL_HOME = Path.home()
RESULTS = []
CLI = {"daemon", "panel", "status", "drank", "snooze", "pause", "resume", "undo", "clear"}


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'} {name}{'' if ok else '  -> ' + str(detail)}", flush=True)


def section(title):
    print(f"\n{title}", flush=True)


def is_hydration_button(action):
    return "myos-hydration" in action.get("command", "")


section("Theme (generated from scripts/theme.py)")
with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    home = t / "home"
    (home / ".local/share").mkdir(parents=True)
    (t / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/theme.py", t / "scripts")
    shutil.copytree(ROOT / "config", t / "config", ignore=shutil.ignore_patterns("__pycache__"))
    if (REAL_HOME / ".local/share/fonts").exists():
        (home / ".local/share/fonts").symlink_to(REAL_HOME / ".local/share/fonts")
    if (REAL_HOME / ".face").exists():
        (home / ".face").symlink_to(REAL_HOME / ".face")
    r = subprocess.run([sys.executable, str(t / "scripts/theme.py")], env=os.environ | {"HOME": str(home)},
                       capture_output=True, text=True, timeout=120)
    check("theme.py runs", r.returncode == 0, r.stderr[-300:])
    drift = []
    for path in (t / "config").rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            repo = ROOT / path.relative_to(t)
            try:
                generated = path.read_text().replace(str(home), str(REAL_HOME))
                if not repo.exists() or generated != repo.read_text():
                    drift.append(str(path.relative_to(t)))
            except UnicodeDecodeError:
                pass
    check("committed configs match a fresh theme regen (no drift)", not drift, drift)

swaync = json.loads((ROOT / "config/swaync/config.json").read_text())
actions = swaync["widget-config"]["buttons-grid"]["actions"]
buttons = [a for a in actions if is_hydration_button(a)]
check("notification centre has exactly one Hydration button", len(buttons) == 1, buttons)
if buttons:
    b = buttons[0]
    check("Hydration button opens the panel and closes the centre first",
          "swaync-client -cp" in b["command"] and "myos-hydration panel" in b["command"], b)
    check("Hydration button uses a Nerd Font glyph + label like its neighbours",
          re.fullmatch(r"[\U000F0000-\U000FFFFF] {3}Hydration", b["label"]), repr(b["label"]))
    labels = [a["label"].split()[-1] for a in actions]
    check("Hydration sits before Settings and Power", labels.index("Hydration") < labels.index("Settings") < labels.index("Power"), labels)
theme_src = (ROOT / "scripts/theme.py").read_text()
check("theme.py defines the Hydration button (survives regen)", 'btn("\\U000F058C", "Hydration", "~/.local/bin/myos-hydration panel")' in theme_src)
check("Hydration panel follows the dark Graphite scheme", "PREFER_DARK" in (ROOT / "config/desktop/hydration_panel.py").read_text())
check("panel shows times on a 12-hour clock", "%I:%M %p" in (ROOT / "config/desktop/hydration_panel.py").read_text())

section("Launcher, desktop entry, Hyprland startup")
run_src = (ROOT / "config/desktop/run.py").read_text()
entries = re.findall(r'\("Hydration: ([^"]+)", f"\{HOME\}/\.local/bin/myos-hydration (\w+)", "([\w-]+)"\)', run_src)
check("Super+Space has 4 Hydration actions", len(entries) == 4, entries)
check("every launcher action is a real CLI command", all(cmd in CLI for _, cmd, _ in entries), entries)
check("launcher hides Hydration actions when not installed", 'name.startswith("Hydration:") and not (HOME / ".local/bin/myos-hydration").exists()' in run_src)
ast.parse(run_src)
desktop = (ROOT / "config/desktop/org.myos.Hydration.desktop").read_text()
r = subprocess.run(["desktop-file-validate", str(ROOT / "config/desktop/org.myos.Hydration.desktop")], capture_output=True, text=True)
check("desktop entry validates", r.returncode == 0 and not r.stdout.strip(), r.stdout + r.stderr)
execs = re.findall(r"^Exec=myos-hydration (\w+)$", desktop, re.M)
check("desktop entry: main + 4 right-click actions map to CLI commands",
      execs == ["panel", "drank", "snooze", "pause", "resume"], execs)
check("desktop entry searchable by water/drink/break", all(k in desktop for k in ("water", "drink", "break")))
hypr = (ROOT / "config/hypr/hyprland.conf").read_text().splitlines()
lines = [l for l in hypr if l.startswith("exec-once") and "myos-hydration" in l]
check("Hyprland restarts the service at login (fresh Wayland env), only if enabled",
      len(lines) == 1 and "import-environment WAYLAND_DISPLAY" in lines[0] and "is-enabled --quiet myos-hydration.service && systemctl --user restart" in lines[0], lines)
unit = (ROOT / "config/systemd/myos-hydration.service").read_text()
check("unit: dbus type, restart on failure, private umask, doc link exists",
      all(s in unit for s in ("Type=dbus", "BusName=org.myos.Hydration", "Restart=on-failure", "UMask=0077"))
      and (ROOT / "docs/HYDRATION.md").exists())
helper = (ROOT / "config/desktop/hydration_idle.c").read_text()
away = re.search(r"^AWAY = (\d+)", (ROOT / "config/desktop/hydration.py").read_text(), re.M)
idle_conf = (ROOT / "config/hypr/hypridle.conf").read_text()
suspend = max(int(x) for x in re.findall(r"timeout = (\d+)\s*\n\s*on-timeout = systemctl suspend", idle_conf))
check("long-break threshold fires before hypridle suspends", away and int(away.group(1)) < suspend, (away and away.group(1), suspend))
check("idle helper uses the same long-break threshold", away and f"{int(away.group(1)) * 1000}, seat" in helper)

section("Installer (sandbox HOME, stubbed systemctl)")
with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    home, stub = t / "home", t / "stub"
    stub.mkdir()
    (stub / "systemctl").write_text(f"""#!/bin/sh
echo "$*" >> "{stub}/calls"
case "$*" in
  *is-active*) exit 1 ;;
  *is-enabled*) [ -f "{stub}/enabled" ]; exit $? ;;
  *disable*) rm -f "{stub}/enabled" ;;
  *" enable "*) touch "{stub}/enabled" ;;
esac
exit 0
""")
    for name in ("swaync-client", "update-desktop-database"):
        (stub / name).write_text("#!/bin/sh\nexit 0\n")
    for f in stub.iterdir():
        f.chmod(0o755)
    (home / ".config/hypr").mkdir(parents=True)
    (home / ".config/hypr/hyprland.conf").write_text(
        "\n".join(l for l in hypr if l not in lines) + "\n")
    (home / ".config/swaync").mkdir()
    old = json.loads(json.dumps(swaync))
    old["widget-config"]["buttons-grid"]["actions"] = [a for a in actions if not is_hydration_button(a)]
    (home / ".config/swaync/config.json").write_text(json.dumps(old, indent=2, ensure_ascii=False) + "\n")
    (home / ".local/share/myos").mkdir(parents=True)
    (home / ".local/share/myos/run.py").write_text("# older launcher\n")
    (home / ".config/myos").mkdir()
    (home / ".config/myos/hydration.json").write_text('{"interval": 60}')
    env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")}
    env |= {"HOME": str(home), "PATH": f"{stub}:{os.environ['PATH']}"}

    def install(*args):
        (stub / "calls").write_text("")
        return subprocess.run(["bash", str(ROOT / "scripts/install-hydration.sh"), *args], env=env,
                              capture_output=True, text=True, timeout=180)

    def backups():
        d = home / ".local/state/myos/hydration-backups"
        return sorted(d.iterdir()) if d.exists() else []

    targets = {home / ".local/share/myos/hydration.py": 0o644, home / ".local/share/myos/hydration_engine.py": 0o644,
               home / ".local/share/myos/hydration_panel.py": 0o644, home / ".local/share/myos/hydration-idle": 0o755,
               home / ".local/bin/myos-hydration": 0o755, home / ".config/systemd/user/myos-hydration.service": 0o644,
               home / ".local/share/applications/org.myos.Hydration.desktop": 0o644}
    r = install()
    check("first install succeeds", r.returncode == 0, r.stderr[-400:])
    check("all files installed with correct permissions",
          all(p.exists() and p.stat().st_mode & 0o777 == m for p, m in targets.items()),
          {str(p): oct(p.stat().st_mode & 0o777) if p.exists() else "missing" for p in targets})
    calls = (stub / "calls").read_text()
    check("first install enables and starts the service", "--user enable myos-hydration.service" in calls and "--user restart myos-hydration.service" in calls, calls)
    h = subprocess.run([str(home / ".local/share/myos/hydration-idle"), "5"], env=env)
    check("built helper rejects an out-of-range idle time", h.returncode == 2, h.returncode)
    h = subprocess.run([str(home / ".local/share/myos/hydration-idle"), "180"], env=env | {"WAYLAND_DISPLAY": "nonexistent-test"})
    check("built helper exits cleanly without a compositor", h.returncode == 3, h.returncode)
    live_hypr = (home / ".config/hypr/hyprland.conf").read_text()
    check("Hyprland startup line added once", live_hypr.count("myos-hydration.service") == lines[0].count("myos-hydration.service"))
    live_sw = json.loads((home / ".config/swaync/config.json").read_text())["widget-config"]["buttons-grid"]["actions"]
    check("notification-centre button added once", sum(map(is_hydration_button, live_sw)) == 1)
    check("launcher updated with Hydration actions", (home / ".local/share/myos/run.py").read_text() == run_src)
    check("existing settings preserved", json.loads((home / ".config/myos/hydration.json").read_text()) == {"interval": 60})
    first = backups()
    check("previous files backed up", first and any(first[0].rglob("hyprland.conf")))

    r = install()
    check("reinstall succeeds", r.returncode == 0, r.stderr[-400:])
    check("reinstall is idempotent (no changes, no new backups)", backups() == first, backups())
    check("reinstall keeps one startup line and one button",
          (home / ".config/hypr/hyprland.conf").read_text() == live_hypr
          and sum(map(is_hydration_button, json.loads((home / ".config/swaync/config.json").read_text())["widget-config"]["buttons-grid"]["actions"])) == 1)

    (stub / "enabled").unlink()  # user turned off "Start after login"
    r = install()
    calls = (stub / "calls").read_text()
    check("reinstall respects disabled autostart (no enable, no restart)",
          r.returncode == 0 and " enable " not in f" {calls} " and "restart" not in calls, calls)

    r = install("--bogus")
    check("unknown option rejected with usage", r.returncode != 0 and "Usage" in (r.stderr + r.stdout))

    r = install("--uninstall")
    calls = (stub / "calls").read_text()
    check("uninstall succeeds and stops/disables the service", r.returncode == 0 and "disable --now myos-hydration.service" in calls, r.stderr + calls)
    check("uninstall removes every installed file", not any(p.exists() for p in targets), [str(p) for p in targets if p.exists()])
    check("uninstall removes the Hyprland line", "myos-hydration" not in (home / ".config/hypr/hyprland.conf").read_text())
    check("uninstall removes the notification-centre button",
          not any(map(is_hydration_button, json.loads((home / ".config/swaync/config.json").read_text())["widget-config"]["buttons-grid"]["actions"])))
    check("uninstall keeps settings and backups", (home / ".config/myos/hydration.json").exists() and backups())

print(f"\nConfig/installer suite: {sum(RESULTS)}/{len(RESULTS)} passed.")
sys.exit(0 if all(RESULTS) else 1)
