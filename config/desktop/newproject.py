#!/usr/bin/env python3
"""new-project: start a project folder that sets itself up when you cd into it.

  new-project NAME [--lang python|node|go|rust|none] [--ros] [--dir ~/Projects] [--open]

Creates ~/Projects/NAME with:
  git (main branch) · .gitignore · README.md
  AGENTS.md (the agents' rules) + CLAUDE.md / GEMINI.md pointing at it · docs/HANDOFF.md · docs/decisions/
  .envrc (direnv): loads .env, the language environment (python: a uv .venv) and mise tools when mise is installed
  mise.toml: the language version for this project (used once mise is installed)
  --ros: ROS 2 Lyrical sourced in .envrc, plus distrobox.ini for a ROS Jazzy box (`distrobox assemble create`)
  --open: VS Code + a terminal there afterwards (same as clicking it in Projects)

Never overwrites: it stops if the folder already exists and isn't empty.
"""
import argparse, os, re, shutil, subprocess, sys
from pathlib import Path

HOME = Path.home()
LANGS = {
    "python": {"mise": 'python = "3.13"', "ignore": [".venv/", "__pycache__/", "*.pyc", ".pytest_cache/"],
               "envrc": ['[ -d .venv ] || uv venv -q .venv 2>/dev/null || python3 -m venv .venv', "source .venv/bin/activate"]},
    "node": {"mise": 'node = "lts"', "ignore": ["node_modules/", "dist/", ".next/"], "envrc": ["PATH_add node_modules/.bin"]},
    "go": {"mise": 'go = "latest"', "ignore": ["bin/"], "envrc": []},
    "rust": {"mise": 'rust = "stable"', "ignore": ["target/"], "envrc": []},
    "none": {"mise": "", "ignore": [], "envrc": []},
}
ROS_ENVRC = ["# ROS 2 Lyrical (native)", "[ -f /opt/ros/lyrical/setup.bash ] && source /opt/ros/lyrical/setup.bash",
             '[ -f install/setup.bash ] && source install/setup.bash']
DISTROBOX = """# ROS 2 Jazzy in a container, for packages that aren't built for this Ubuntu yet.
# Create it: distrobox assemble create   ·   enter: distrobox enter {name}-ros
[{name}-ros]
image=docker.io/osrf/ros:jazzy-desktop
pull=true
init=false
additional_packages="python3-colcon-common-extensions"
"""


def files(name, lang, ros):
    L = LANGS[lang]
    envrc = ["# direnv: runs when you cd here (approve changes with `direnv allow`)", "dotenv_if_exists .env",
             'if has mise; then eval "$(mise env -s bash)"; fi'] + L["envrc"] + (ROS_ENVRC if ros else [])
    out = {
        ".gitignore": "\n".join([".env", ".env.*", "!.env.example", ".direnv/", "*.log", ".DS_Store"] + L["ignore"]
                                + (["build/", "install/", "log/"] if ros else [])) + "\n",
        ".envrc": "\n".join(envrc) + "\n",
        "README.md": f"# {name}\n\nWhat it is, how to run it.\n",
        "AGENTS.md": f"""# {name}: rules for coding agents

Source of truth for every agent (Claude reads it through CLAUDE.md, Antigravity through GEMINI.md).

## Before you start
- Read docs/HANDOFF.md: another agent may have been here. Check `git status` and don't overwrite uncommitted work.

## Working rules
- Inspect before editing; small, reversible changes. Don't invent APIs or requirements.
- Run the tests/linters for what you touched before saying "done", and report failures honestly.
- Never commit secrets or .env files.
- Durable decisions go in docs/decisions/NNNN-title.md.

## Before you stop
- Add an entry at the top of docs/HANDOFF.md: agent, date, what you did, what's next.
""",
        "CLAUDE.md": "Read AGENTS.md and follow it.\n",
        "GEMINI.md": "Read AGENTS.md and follow it.\n",
        "docs/HANDOFF.md": "# Handoff\n\nNewest entry first: agent · date · what was done · what's next.\n",
        "docs/decisions/.gitkeep": "",
    }
    if L["mise"]: out["mise.toml"] = f"[tools]\n{L['mise']}\n"
    if ros: out["distrobox.ini"] = DISTROBOX.format(name=name)
    return out


def create(name, lang="none", ros=False, base=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name): raise ValueError("Use letters, digits, - _ . for the name.")
    d = Path(base or HOME / "Projects").expanduser() / name
    if d.exists() and any(d.iterdir()): raise ValueError(f"{d} already exists and isn't empty.")
    for rel, text in files(name, lang, ros).items():
        p = d / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
    q = lambda *a: subprocess.run(a, cwd=d, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    q("git", "init", "-q", "-b", "main")
    if shutil.which("direnv"): q("direnv", "allow", ".")
    q("git", "add", "-A"); q("git", "commit", "-qm", "Start the project")
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(prog="new-project", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name"); ap.add_argument("--lang", choices=list(LANGS), default="none")
    ap.add_argument("--ros", action="store_true"); ap.add_argument("--dir"); ap.add_argument("--open", action="store_true")
    a = ap.parse_args(argv)
    try: d = create(a.name, a.lang, a.ros, a.dir)
    except (ValueError, OSError) as e: print(f"new-project: {e}", file=sys.stderr); return 1
    print(f"Created {d}")
    if not shutil.which("mise") and a.lang not in ("none", "python"):
        print("  (mise isn't installed yet, so the system's own toolchain is used: see docs/ENVIRONMENTS.md)")
    if a.open and shutil.which("projects"): subprocess.Popen(["projects", "open", str(d)], start_new_session=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
