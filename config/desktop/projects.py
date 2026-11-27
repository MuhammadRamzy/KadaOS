#!/usr/bin/env python3
"""projects: every git repo you work on, at a glance.

  projects               branch, uncommitted changes, ahead/behind, last commit (newest first)
  projects --gh          also CI status and open pull requests (GitHub, cached 10 minutes)
  projects --json        the same as data (the Projects panel uses it; add --gh for GitHub)
  projects open PATH     VS Code + a terminal in that folder, on an empty workspace

Repos: each folder in ~/Projects that has .git, plus this setup's repo. More roots: PROJECTS_ROOTS=dir1:dir2.
Read-only: it runs git status/log/rev-list and `gh pr list` / `gh run list`, nothing that changes a repo.
"""
import json, os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOME = Path.home()
ROOTS = [Path(p).expanduser() for p in (os.environ.get("PROJECTS_ROOTS") or str(HOME / "Projects")).split(":") if p]
EXTRA = [HOME / "KadaOS"]
CACHE = HOME / ".cache/myos/projects-gh.json"
GH_TTL = 600


def run(args, cwd=None, timeout=10):
    try: return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e: return subprocess.CompletedProcess(args, 124, "", str(e))


def repos():
    seen, out = set(), []
    for d in [c for r in ROOTS if r.is_dir() for c in sorted(r.iterdir())] + EXTRA:
        if (d / ".git").exists() and d.resolve() not in seen:
            seen.add(d.resolve()); out.append(d)
    return out


def parse_counts(text):
    """`git rev-list --left-right --count @{u}...HEAD` → (ahead, behind); (None, None) with no upstream."""
    parts = text.split()
    return (int(parts[1]), int(parts[0])) if len(parts) == 2 and all(p.isdigit() for p in parts) else (None, None)


def info(path):
    g = lambda *a: run(["git", *a], cwd=path)
    branch = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "?"
    changed = len([l for l in g("status", "--porcelain").stdout.splitlines() if l.strip()])
    ahead, behind = parse_counts(g("rev-list", "--left-right", "--count", "@{u}...HEAD").stdout)
    last = g("log", "-1", "--format=%ct%x09%s").stdout.strip().split("\t", 1)
    url = g("remote", "get-url", "origin").stdout.strip()
    return {"name": path.name, "path": str(path), "branch": branch, "changed": changed, "ahead": ahead, "behind": behind,
            "last_time": int(last[0]) if last[0].isdigit() else 0, "last_msg": last[1] if len(last) > 1 else "",
            "github": "github.com" in url}


def gh_info(path):
    if not shutil.which("gh"): return {}
    prs = run(["gh", "pr", "list", "--limit", "10", "--json", "number,title,isDraft,reviewDecision"], cwd=path, timeout=15)
    ci = run(["gh", "run", "list", "--limit", "1", "--json", "status,conclusion,workflowName,headBranch"], cwd=path, timeout=15)
    try: p = json.loads(prs.stdout) if prs.returncode == 0 else None
    except ValueError: p = None
    try: c = (json.loads(ci.stdout) or [None])[0] if ci.returncode == 0 else None
    except ValueError: c = None
    return {"prs": p, "ci": ci_state(c)}


def ci_state(run_):
    """'pass' / 'fail' / 'running' / None from the latest workflow run."""
    if not run_: return None
    if run_.get("status") != "completed": return "running"
    return "pass" if run_.get("conclusion") == "success" else ("fail" if run_.get("conclusion") in ("failure", "timed_out", "startup_failure") else None)


def with_gh(items, now=None):
    now = now or time.time()
    try: cache = json.loads(CACHE.read_text())
    except (OSError, ValueError): cache = {}
    todo = [i for i in items if i["github"] and now - cache.get(i["path"], {}).get("t", 0) > GH_TTL]
    with ThreadPoolExecutor(6) as ex:
        for i, g in zip(todo, ex.map(lambda i: gh_info(i["path"]), todo)): cache[i["path"]] = {"t": now, **g}
    if todo:
        CACHE.parent.mkdir(parents=True, exist_ok=True); CACHE.write_text(json.dumps(cache))
    for i in items:
        c = cache.get(i["path"], {}); i["prs"], i["ci"] = c.get("prs"), c.get("ci")
    return items


def scan(gh=False):
    with ThreadPoolExecutor(8) as ex: items = list(ex.map(info, repos()))
    items.sort(key=lambda i: -i["last_time"])
    if gh: with_gh(items)
    for i in items: i["summary"] = summary(i)
    return items


def ago(t, now=None):
    s = (now or time.time()) - t
    if not t: return "no commits"
    for n, u in ((86400 * 30, "mo"), (86400 * 7, "w"), (86400, "d"), (3600, "h"), (60, "min")):
        if s >= n: return f"{int(s // n)} {u} ago"
    return "just now"


def summary(i, now=None):
    """One line: what needs attention first, then branch and age."""
    bits = [i["branch"]]
    if i["changed"]: bits.append(f"{i['changed']} changed")
    if i.get("ahead"): bits.append(f"↑{i['ahead']} to push")
    if i.get("behind"): bits.append(f"↓{i['behind']} to pull")
    if i.get("ci") == "fail": bits.append("CI failing")
    elif i.get("ci") == "running": bits.append("CI running")
    if i.get("prs"): bits.append(f"{len(i['prs'])} PR" + ("s" if len(i["prs"]) > 1 else ""))
    bits.append(ago(i["last_time"], now))
    return " · ".join(bits)


def open_project(path):
    p = Path(path).expanduser()
    if not p.is_dir(): print(f"Not a folder: {p}"); return 1
    def h(*a): run(["hyprctl", "dispatch", *a])
    h("workspace", "empty")
    if shutil.which("code"): h("exec", f"code --new-window '{p}'")
    if shutil.which("ptyxis"): h("exec", f"ptyxis --new-window -d '{p}'")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"]): print(__doc__.strip()); return 0
    if argv[:1] == ["open"]: return open_project(argv[1]) if len(argv) > 1 and "'" not in argv[1] else 2
    items = scan(gh="--gh" in argv)
    if "--json" in argv: print(json.dumps(items)); return 0
    if not items: print(f"No git repos found in {', '.join(map(str, ROOTS))}."); return 1
    w = max(len(i["name"]) for i in items)
    for i in items: print(f"{i['name']:<{w}}  {summary(i)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
