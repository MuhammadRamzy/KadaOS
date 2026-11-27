#!/usr/bin/env python3
"""tasks: hand a coding task to an agent; it works on its own branch while you do something else.

  tasks add REPO "what to do" [--agent claude|codex] [--start]    queue a task (REPO: a path or a name in ~/Projects)
  tasks start ID          run it: a git worktree + branch, the agent non-interactively, memory-capped (`job`)
  tasks ls [--json]       every task and where it is (queued, running, review, merged, discarded, failed)
  tasks diff ID           what it changed (against the branch it started from)
  tasks log ID [-f]       the agent's output
  tasks review ID [--by codex|claude]   a different agent reviews the diff (agent-review), saved in the worktree
  tasks merge ID          merge the branch into the repo (only into the branch it started from, with a clean tree)
  tasks discard ID        delete the worktree and branch

Nothing runs by itself: a task only starts when you say so (Start, or --start). The agents work in a separate worktree
(~/.local/share/myos/worktrees) so your checkout is never touched; Claude runs with --permission-mode auto, Codex in its
workspace-write sandbox, neither can push. Leftover uncommitted work is committed on the task branch when the agent ends.
State: ~/.local/state/myos/tasks/.
"""
import json, os, re, shlex, shutil, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
DIR = Path(os.environ.get("TASKS_DIR") or HOME / ".local/state/myos/tasks")
TREES = Path(os.environ.get("TASKS_TREES") or HOME / ".local/share/myos/worktrees")
SELF = Path(__file__).resolve()
AGENTS = ("claude", "codex")
ID_RE = re.compile(r"^t\d{6}-\d{6}$")
PROMPT = """You are working alone, non-interactively, in a git worktree of {repo} on the branch {branch}.
Nobody can answer questions: make sensible choices and note them in your final message.
Read AGENTS.md / CLAUDE.md and docs/HANDOFF.md if they exist and follow them.

Task:
{task}

When done: run the project's tests or linters for what you changed, then commit your work on this branch with a clear
message. Do not push, do not switch branches, do not touch files outside this folder. End with a short summary:
what you changed, checks run and their result, anything left to do."""


def git(*a, cwd=None, check=False):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if check and r.returncode: raise RuntimeError((r.stderr or r.stdout).strip())
    return r


def path(tid): return DIR / f"{tid}.json"
def load(tid): return json.loads(path(tid).read_text())


def save(t):
    DIR.mkdir(parents=True, exist_ok=True); p = path(t["id"]); p.write_text(json.dumps(t, indent=1)); os.chmod(p, 0o600)


def all_tasks():
    return sorted((json.loads(p.read_text()) for p in DIR.glob("t*.json")), key=lambda t: t["id"], reverse=True) if DIR.exists() else []


def resolve(prefix):
    m = [t["id"] for t in all_tasks() if t["id"] == prefix or t["id"].endswith(prefix)]
    if len(m) != 1: raise ValueError(f"no single task matches {prefix!r} (tasks ls)")
    return m[0]


def find_repo(name):
    p = Path(name).expanduser()
    if not p.is_absolute() and not p.exists(): p = HOME / "Projects" / name
    top = git("rev-parse", "--show-toplevel", cwd=p).stdout.strip() if p.is_dir() else ""
    if not top: raise ValueError(f"not a git repo: {name}")
    return Path(top)


def slug(text): return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30].strip("-") or "task"


def add(repo, task, agent="claude"):
    if agent not in AGENTS: raise ValueError(f"agent must be one of {', '.join(AGENTS)}")
    if not task.strip(): raise ValueError("say what the agent should do")
    r = find_repo(repo)
    tid = time.strftime("t%y%m%d-%H%M%S")
    while path(tid).exists(): time.sleep(1); tid = time.strftime("t%y%m%d-%H%M%S")
    base = git("rev-parse", "--abbrev-ref", "HEAD", cwd=r).stdout.strip()
    t = {"id": tid, "repo": str(r), "name": r.name, "task": task.strip(), "agent": agent, "state": "queued",
         "base": base, "branch": f"agent/{agent}-{slug(task)}-{tid[-6:]}", "tree": str(TREES / f"{r.name}-{tid}"),
         "created": time.time()}
    save(t); return t


def agent_cmd(t):
    fake = os.environ.get("TASKS_FAKE_AGENT")                     # tests
    prompt = PROMPT.format(repo=t["name"], branch=t["branch"], task=t["task"])
    if fake: return [fake, prompt]
    if t["agent"] == "claude": return ["claude", "-p", prompt, "--permission-mode", "auto", "--output-format", "text"]
    return ["codex", "exec", "-s", "workspace-write", "--skip-git-repo-check", "-C", t["tree"], prompt]


def start(tid, via_job=True):
    t = load(tid)
    if t["state"] not in ("queued", "failed"): raise ValueError(f"task is {t['state']}")
    if not os.environ.get("TASKS_FAKE_AGENT") and not shutil.which(agent_cmd(t)[0]): raise ValueError(f"{t['agent']} isn't installed")
    if not Path(t["tree"]).exists():
        Path(t["tree"]).parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-q", "-b", t["branch"], t["tree"], t["base"], cwd=t["repo"], check=True)
        t["base_commit"] = git("rev-parse", "HEAD", cwd=t["tree"]).stdout.strip()
    t.update(state="running", started=time.time()); t.pop("error", None); save(t)
    if not via_job: return run(tid)
    job = shutil.which("job") or str(HOME / ".local/bin/job")
    passthru = [f"{k}={os.environ[k]}" for k in ("TASKS_DIR", "TASKS_TREES", "TASKS_FAKE_AGENT") if os.environ.get(k)]
    cmd = shlex.join((["env", *passthru] if passthru else []) + [sys.executable, str(SELF), "_run", tid])   # the job doesn't inherit our env
    r = subprocess.run([job, "--label", f"{t['agent']}: {t['task'][:30]}", "--", cmd],
                       cwd=t["tree"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode:
        t.update(state="failed", error=(r.stderr or r.stdout).strip()[-300:]); save(t); raise RuntimeError(t["error"])
    m = re.search(r"job (\d{4}-\d{6})", r.stdout); t["job"] = m[1] if m else ""; save(t)
    return 0


def run(tid):
    """Inside the job: run the agent in the worktree (stdin closed), commit leftovers, record the result."""
    t = load(tid); log = DIR / f"{tid}.log"
    with open(log, "ab") as f:
        rc = subprocess.call(agent_cmd(t), cwd=t["tree"], stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if git("status", "--porcelain", cwd=t["tree"]).stdout.strip():
        git("add", "-A", cwd=t["tree"]); git("commit", "-qm", f"agent ({t['agent']}): {t['task'][:60]}", cwd=t["tree"])
    t = load(tid)
    t["commits"] = int(git("rev-list", "--count", f"{t['base_commit']}..HEAD", cwd=t["tree"]).stdout.strip() or 0)
    t["stat"] = git("diff", "--shortstat", f"{t['base_commit']}..HEAD", cwd=t["tree"]).stdout.strip()
    t.update(ended=time.time(), rc=rc, state="review" if t["commits"] else "failed")
    if not t["commits"]: t["error"] = f"{t['agent']} made no changes (exit {rc})"
    save(t); return rc


def merge(tid):
    t = load(tid)
    if t["state"] != "review": raise ValueError(f"task is {t['state']}, not ready to merge")
    cur = git("rev-parse", "--abbrev-ref", "HEAD", cwd=t["repo"]).stdout.strip()
    if cur != t["base"]: raise ValueError(f"{t['name']} is on {cur}; switch it to {t['base']} first")
    if git("status", "--porcelain", "--untracked-files=no", cwd=t["repo"]).stdout.strip():
        raise ValueError(f"{t['name']} has uncommitted changes; commit or stash them first")
    r = git("merge", "--no-ff", "-m", f"Merge {t['branch']}: {t['task'][:60]}", t["branch"], cwd=t["repo"])
    if r.returncode:
        git("merge", "--abort", cwd=t["repo"]); raise ValueError("it doesn't merge cleanly; resolve it by hand: "
                                                              f"cd {t['repo']} && git merge {t['branch']}")
    cleanup(t, delete_branch=False); t["state"] = "merged"; save(t)
    return 0


def cleanup(t, delete_branch=True):
    if Path(t["tree"]).exists(): git("worktree", "remove", "--force", t["tree"], cwd=t["repo"])
    git("worktree", "prune", cwd=t["repo"])
    git("branch", "-D" if delete_branch else "-d", t["branch"], cwd=t["repo"])


def discard(tid):
    t = load(tid)
    if t["state"] == "running": raise ValueError("it's still running: job stop " + t.get("job", "ID") + " first")
    cleanup(t); t["state"] = "discarded"; save(t); return 0


def refresh(t):
    """A 'running' task whose job is gone (stopped, crashed, reboot) becomes failed."""
    if t["state"] == "running" and t.get("job"):
        a = subprocess.run(["systemctl", "--user", "is-active", f"job-{t['job']}"], capture_output=True, text=True).stdout.strip()
        if a not in ("active", "activating") and time.time() - t.get("started", 0) > 10:
            t.update(state="failed", error="the job ended before the agent finished"); save(t)
    return t


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "ls"
    try:
        if cmd in ("-h", "--help"): print(__doc__.strip()); return 0
        if cmd == "add":
            pos = [a for a in argv[1:] if not a.startswith("--")]
            agent = argv[argv.index("--agent") + 1] if "--agent" in argv else "claude"
            if agent in pos: pos.remove(agent)
            if len(pos) != 2: print('usage: tasks add REPO "what to do" [--agent claude|codex] [--start]'); return 2
            t = add(pos[0], pos[1], agent); print(f"Queued {t['id']}: {t['agent']} on {t['name']}")
            if "--start" in argv: start(t["id"]); print("Started; you'll get a notification when it's done.")
            return 0
        if cmd == "_run": return run(argv[1])
        if cmd == "ls":
            ts = [refresh(t) for t in all_tasks()]
            if "--json" in argv: print(json.dumps(ts)); return 0
            for t in ts: print(f"{t['id']}  {t['state']:<9} {t['agent']:<6} {t['name']:<18} {t['task'][:50]}" + (f"  ({t['stat']})" if t.get("stat") else ""))
            if not ts: print('No tasks. tasks add REPO "what to do" --start')
            return 0
        if len(argv) < 2: print(__doc__.strip()); return 2
        tid = resolve(argv[1]); t = refresh(load(tid))
        if cmd == "start": start(tid); print(f"Started {tid} on {t['branch']}"); return 0
        if cmd == "diff": return subprocess.call(["git", "-C", t["tree"], "diff", f"{t['base_commit']}..HEAD"] if Path(t["tree"]).exists()
                                                 else ["git", "-C", t["repo"], "log", "-p", "-1", t["branch"]])
        if cmd == "log": return subprocess.call(["tail", *(["-f"] if "-f" in argv else []), "-n", "200", str(DIR / f"{tid}.log")])
        if cmd == "review":
            by = argv[argv.index("--by") + 1] if "--by" in argv else ("codex" if t["agent"] == "claude" else "claude")
            return subprocess.call([shutil.which("agent-review") or "agent-review", "--by", by, "--base", t["base_commit"]], cwd=t["tree"])
        if cmd == "merge": merge(tid); print(f"Merged {t['branch']} into {t['base']} in {t['name']}."); return 0
        if cmd == "discard": discard(tid); print("Discarded."); return 0
    except (ValueError, RuntimeError, OSError, KeyError) as e:
        print(f"tasks: {e}", file=sys.stderr); return 1
    print(__doc__.strip()); return 2


if __name__ == "__main__":
    sys.exit(main())
