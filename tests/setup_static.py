#!/usr/bin/env python3
"""Whole-repo static and cross-reference checks for the laptop setup (no live changes).

Syntax: every Python file, shell script, JSON/TOML file, the Hyprland config, systemd units and
desktop entries. Wiring: every shortcut, bar module, notification-centre button, launcher action
and actions-menu entry points at something that exists; no two shortcuts share a key; theme
outputs match a fresh regen; docs links resolve.
"""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
RESULTS = []
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "graphify-out"}


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'} {name}{'' if ok else '  -> ' + str(detail)[:900]}", flush=True)


def section(title):
    print(f"\n{title}", flush=True)


def files(*patterns, under=("config", "scripts", "tests")):
    out = []
    for top in under:
        for pattern in patterns:
            out += [p for p in (ROOT / top).rglob(pattern) if p.is_file() and not SKIP_DIRS & set(p.parts)]
    return sorted(set(out))


def shell_scripts():
    found = set(files("*.sh", "*.zsh"))
    for p in files("*"):
        if p.suffix == "" and os.access(p, os.X_OK):
            head = p.open("rb").read(64)
            if head.startswith(b"#!") and (b"bash" in head or b"/sh" in head):
                found.add(p)
    return sorted(found)


def rel(p):
    return str(Path(p).relative_to(ROOT))


# ── where an installed path comes from in this repo ──
MAPS = [(HOME / ".config/hypr", ROOT / "config/hypr"), (HOME / ".config/waybar", ROOT / "config/waybar"),
        (HOME / ".config/swaync", ROOT / "config/swaync"), (HOME / ".config/rofi", ROOT / "config/rofi"),
        (HOME / ".local/share/myos", ROOT / "config/desktop"), (HOME / ".local/share/local-ai", ROOT / "config/ai")]
BIN_DIRS = [ROOT / "config/bin", ROOT / "config/desktop/bin", ROOT / "config/ai/bin", ROOT / "config/agents",
            ROOT / "config/terminal", ROOT / "config/security", ROOT / "config/backup"]


BUILTINS = {"command", "test", "[", "true", "false", "echo", "printf", "cd", "export", "read", "for", "while",
            "do", "done", "if", "then", "else", "fi", "case", "esac", "sleep", "kill", "wait", "type", "source", "."}


def resolves(command):
    """True if the first word of a shell command exists in the repo (as installed) or on the system."""
    command = command.strip()
    for prefix in ("sh -c ", "bash -c "):
        if command.startswith(prefix):
            inner = shlex.split(command)[2] if len(shlex.split(command)) > 2 else ""
            parts = [p.strip() for p in re.split(r"\s*(?:;|&&|\|\|)\s*", inner) if p.strip()]
            # `command -v X >/dev/null && X`: X is optional (installed by a later phase), so it isn't required here
            optional = {m[1] for p in parts for m in [re.match(r"command -v (\S+)", p)] if m}
            return all(resolves(p) for p in parts
                       if not p.startswith(("[", "test ", "!", "if ", "then", "fi", "else", "command -v "))
                       and re.sub(r"^exec\s+", "", p).split()[0] not in optional)
    words = command.split()
    while words and (re.fullmatch(r"\w+=\S*", words[0]) or words[0] in ("env", "exec", "setsid", "-f", "nohup", "uwsm", "app", "--")):
        words.pop(0)
    if not words:
        return True
    first = words[0].strip("'\"")
    if first in BUILTINS or first.startswith("$"):  # a shell variable can't be checked statically
        return True
    path = Path(os.path.expanduser(first.replace("$HOME", str(HOME))))
    if "/" in first:
        for live, repo in MAPS:
            if str(path).startswith(str(live)):
                return (repo / path.relative_to(live)).exists() or path.exists()
        if str(path).startswith(str(HOME / ".local/bin")):
            return any((d / path.name).exists() for d in BIN_DIRS) or path.exists()
        return path.exists()
    return bool(shutil.which(first)) or any((d / first).exists() for d in BIN_DIRS)


# ─────────────────────────────────────────────────────────────────────────────
section("Syntax: every file in the repo")
py = files("*.py")
bad = []
for p in py:
    try:
        compile(p.read_text(), str(p), "exec")
    except (SyntaxError, UnicodeDecodeError) as error:
        bad.append(f"{rel(p)}: {error}")
check(f"all {len(py)} Python files compile", not bad, bad)

sh = shell_scripts()
bad = []
for p in sh:
    shell = "zsh" if p.suffix == ".zsh" else "bash"
    if shutil.which(shell) and subprocess.run([shell, "-n", str(p)], capture_output=True).returncode:
        bad.append(rel(p))
check(f"all {len(sh)} shell scripts parse", not bad, bad)
if shutil.which("shellcheck"):
    bash_only = [str(p) for p in sh if p.suffix != ".zsh"]
    r = subprocess.run(["shellcheck", "-S", "error", "-f", "gcc", *bash_only], capture_output=True, text=True)
    errors = [l.replace(str(ROOT) + "/", "") for l in r.stdout.splitlines()]
    check("shellcheck: no errors in any shell script", not errors, errors[:10])

bad = []
for p in files("*.json", "*.jsonc"):
    try:
        json.loads(p.read_text())
    except ValueError as error:
        bad.append(f"{rel(p)}: {error}")
check("all JSON configs parse", not bad, bad)
bad = []
for p in files("*.toml"):
    try:
        tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError as error:
        bad.append(f"{rel(p)}: {error}")
check("all TOML configs parse", not bad, bad)

with tempfile.TemporaryDirectory() as t:
    shutil.copytree(ROOT / "config/hypr", Path(t) / "hypr", ignore=shutil.ignore_patterns("__pycache__"))
    r = subprocess.run(["Hyprland", "--verify-config", "-c", str(Path(t) / "hypr/hyprland.conf")], capture_output=True, text=True)
    check("Hyprland config verifies (repo copy)", "config ok" in r.stdout + r.stderr, (r.stdout + r.stderr)[-500:])

units = files("*.service", "*.timer", under=("config",))
bad = []
for u in units:
    r = subprocess.run(["systemd-analyze", "--user", "verify", str(u)], capture_output=True, text=True)
    lines = [l for l in (r.stdout + r.stderr).splitlines() if u.name in l or u.stem in l]
    lines = [l for l in lines if "is not executable" not in l or not Path(os.path.expanduser(l.split("'")[1] if "'" in l else "")).exists()]
    if lines:
        bad.append(f"{rel(u)}: {lines[0]}")
check(f"all {len(units)} systemd units verify", not bad, bad)

desktops = files("*.desktop", under=("config",))
bad = []
for d in desktops:
    text = d.read_text()
    if "%h" in text:  # template: the installer substitutes $HOME (install-ai.sh), validate the result
        tmp = Path(tempfile.mkdtemp()) / d.name
        tmp.write_text(text.replace("%h", str(HOME)))
        d = tmp
    r = subprocess.run(["desktop-file-validate", str(d)], capture_output=True, text=True)
    if r.returncode or r.stdout.strip():
        bad.append(f"{d.name}: {r.stdout.strip()[:150]}")
check(f"all {len(desktops)} desktop entries validate", not bad, bad)

# ─────────────────────────────────────────────────────────────────────────────
section("Wiring: everything you can press points at something real")
conf = (ROOT / "config/hypr/hyprland.conf").read_text()
variables = dict(re.findall(r"^\$(\w+)\s*=\s*(.+?)\s*(?:#.*)?$", conf, re.M))


def expand(text):
    return re.sub(r"\$(\w+)", lambda m: variables.get(m.group(1), m.group(0)), text)


binds, missing, keys = [], [], {}
for line in conf.splitlines():
    m = re.match(r"^(bind[a-z]*)\s*=\s*(.*)$", line.strip())
    if not m:
        continue
    flags, body = m.group(1)[4:], expand(m.group(2))
    parts = [p.strip() for p in body.split(",", 4 if "d" in flags else 3)]
    mods, key = parts[0], parts[1]
    rest = parts[3:] if "d" in flags else parts[2:]
    dispatcher, arg = (rest + ["", ""])[:2]
    binds.append(line)
    combo = (" ".join(sorted(mods.upper().replace("+", " ").split())), key.lower(), flags.replace("d", ""))
    if dispatcher != "bringactivetotop":  # paired with cyclenext on Alt+Tab on purpose (raise after cycling)
        keys.setdefault(combo, []).append(line.strip()[:90])
    if dispatcher == "exec" and not resolves(arg.split("#")[0]):
        missing.append(arg[:80])
for line in re.findall(r"^exec(?:-once)?\s*=\s*(.+)$", conf, re.M):
    if not resolves(expand(line).split("   #")[0].split("  #")[0]):
        missing.append(line[:80])
check(f"every shortcut and startup command exists ({len(binds)} binds)", not missing, missing)
# a comma inside a bindd description shifts the fields and Hyprland reads part of the text as the dispatcher
baddisp = [l.strip()[:90] for l in binds if not re.fullmatch(r"[a-z]+", ([p.strip() for p in expand(l.split("=", 1)[1]).split(",", 4 if "d" in l.split("=")[0][4:] else 3)][3 if "d" in l.split("=")[0][4:] else 2:] + [""])[0])]
check("every shortcut names a real dispatcher (no comma in a description)", not baddisp, baddisp)
dupes = {k: v for k, v in keys.items() if len(v) > 1}
check("no two shortcuts share the same keys", not dupes, list(dupes.values())[:5])
undocumented = [b for b in binds if b.strip().startswith("bind") and "d" not in b.split("=")[0][4:]
                and "Lock" not in b and "mouse:" not in b and "bringactivetotop" not in b]
check("every shortcut has a description (shows in the cheatsheet)", not undocumented, [u[:80] for u in undocumented[:6]])

waybar = json.loads((ROOT / "config/waybar/config.jsonc").read_text())
bars = waybar if isinstance(waybar, list) else [waybar]
missing = []
for bar in bars:
    for name, module in bar.items():
        if isinstance(module, dict) and name.startswith("custom/"):  # built-in modules take keywords, not commands
            for k in ("exec", "on-click", "on-click-right", "on-click-middle", "on-scroll-up", "on-scroll-down"):
                if isinstance(module.get(k), str) and not resolves(module[k]):
                    missing.append(f"{name}.{k}: {module[k][:60]}")
check("every bar module's command exists", not missing, missing)
declared = {m for bar in bars for side in ("modules-left", "modules-center", "modules-right") for m in bar.get(side, [])}
undefined = [m for m in declared if not m.startswith(("custom/", "group/")) is False and m not in bars[0]]
check("every custom bar module is defined", not undefined, undefined)

sw = json.loads((ROOT / "config/swaync/config.json").read_text())
missing = []
for b in sw["widget-config"]["buttons-grid"]["actions"]:
    if not resolves(b["command"].replace("swaync-client -cp; sleep 0.3; ", "")):
        missing.append(b.get("label", "")[4:] + ": " + b["command"][:60])
check("every notification-centre button's command exists", not missing, missing)

run_src = (ROOT / "config/desktop/run.py").read_text()
block = run_src[run_src.index("ACTIONS = ["):]
block = block[:block.index("\n    ]")]
actions = re.findall(r'\("([^"]+)", f?"([^"]+)", "[\w-]+"\)', block)
missing = [f"{n}: {c}" for n, c in actions if not resolves(c.replace("{HOME}", str(HOME)).replace("{S}", str(HOME / ".config/hypr/scripts")).replace("{B}", str(HOME / ".local/bin")))]
check(f"every Super+Space action's command exists ({len(actions)})", not missing, missing)

modi = (ROOT / "config/hypr/scripts/actions-modi.sh").read_text()
entries = re.findall(r'^\s*"([^"]+)"\s+"((?:[^"\\]|\\.)*)"\s+"[\w-]+"', modi, re.M)
missing = [f"{n}: {c}" for n, c in entries if not resolves(c.replace("$S", str(HOME / ".config/hypr/scripts")))]
check(f"every actions-menu entry's command exists ({len(entries)})", not missing, missing)

scripts = sorted((ROOT / "config/hypr/scripts").glob("*"))
not_exec = [p.name for p in scripts if p.is_file() and p.suffix in (".sh", ".py") and not os.access(p, os.X_OK)
            and re.search(re.escape(p.name), conf + modi + json.dumps(waybar) + json.dumps(sw))]
check("every referenced Hyprland script is executable", not not_exec, not_exec)

# ─────────────────────────────────────────────────────────────────────────────
section("Theme and docs")
with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    home = t / "home"
    (home / ".local/share").mkdir(parents=True)
    (t / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/theme.py", t / "scripts")
    shutil.copytree(ROOT / "config", t / "config", ignore=shutil.ignore_patterns("__pycache__"))
    if (HOME / ".local/share/fonts").exists():
        (home / ".local/share/fonts").symlink_to(HOME / ".local/share/fonts")
    if (HOME / ".face").exists():
        (home / ".face").symlink_to(HOME / ".face")
    r = subprocess.run([sys.executable, str(t / "scripts/theme.py")], env=os.environ | {"HOME": str(home)},
                       capture_output=True, text=True, timeout=180)
    drift = []
    for p in (t / "config").rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            try:
                if p.read_text().replace(str(home), str(HOME)) != (ROOT / p.relative_to(t)).read_text():
                    drift.append(str(p.relative_to(t)))
            except (UnicodeDecodeError, FileNotFoundError):
                pass
    check("theme generator runs", r.returncode == 0, r.stderr[-300:])
    check("every themed config matches a fresh regen (Graphite palette in sync)", not drift, drift)
theme = (ROOT / "scripts/theme.py").read_text()
check("no navy/gold (old Odyssey palette) left in generated configs",
      not any(re.search(r"#(1b2a4a|c9a227|d4af37)", p.read_text(errors="ignore"), re.I)
              for p in files("*.css", "*.conf", "*.rasi", "*.jsonc", under=("config",))))

broken = []
for md in sorted((ROOT / "docs").rglob("*.md")) + [ROOT / "README.md", ROOT / "AGENTS.md"]:
    if not md.exists():
        continue
    prose = re.sub(r"```.*?```", "", md.read_text(), flags=re.S)          # code blocks aren't links
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", prose):
        if re.match(r"^[a-z]+:", target):
            continue
        if not (md.parent / target).exists():
            broken.append(f"{rel(md)} → {target}")
check("every link in the docs points at a file that exists", not broken, broken[:10])

print(f"\nStatic checks: {sum(RESULTS)}/{len(RESULTS)} passed.")
sys.exit(0 if all(RESULTS) else 1)
