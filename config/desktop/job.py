#!/usr/bin/env python3
"""job: run a long command on this laptop without it freezing the desktop.

  job -- make -j8                 background; capped memory; notifies when done (and the phone, if you're away)
  job --mem 6G -- python train.py cap at 6 GB (default: 70 % of RAM)
  job --plugged -- ./build.sh     wait until the charger is in, then start
  job --fg -- cargo build         run here in the terminal, with the same memory cap
  job --label NAME -- CMD         the name shown in `job ls` and the notification
  job ls · job log ID [-f] · job stop ID

Each job is its own systemd user service (no sudo): MemoryMax stops it cleanly at its cap (no swap, so
it can't drag the laptop down), and systemd-oomd picks it (not Hyprland or your apps) when memory runs out.
Remote devices have the same idea: `board job`.
"""
import json, os, re, shlex, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
DIR = Path(os.environ.get("JOB_DIR") or HOME / ".local/state/myos/jobs")   # JOB_DIR / JOB_QUIET: tests
SELF = Path(__file__).resolve()
OK, FAIL, USAGE = 0, 1, 2
ID_RE = re.compile(r"^\d{4}-\d{6}$")


def _c(code): return (lambda s: f"\033[{code}m{s}\033[0m") if sys.stdout.isatty() else (lambda s: s)
good, bad, warn, dim = _c("32"), _c("31"), _c("33"), _c("2")


def total_mem():
    m = re.search(r"MemTotal:\s+(\d+) kB", Path("/proc/meminfo").read_text())
    return int(m[1]) * 1024 if m else 8 << 30


def parse_size(text):
    """'6G', '512M', '70%' → bytes."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KMGT%]?)B?", str(text).strip(), re.I)
    if not m: raise ValueError(f"memory size like 6G, 512M or 70%: {text!r}")
    n, unit = float(m[1]), m[2].upper()
    if unit == "%": return int(total_mem() * n / 100)
    return int(n * {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}[unit])


def limits(mem=None):
    """MemoryMax in bytes (default 70 % of RAM). No MemoryHigh: throttling a job that can't shrink freezes it forever
    just under the limit (seen in testing); a clean stop at the cap is better."""
    return parse_size(mem) if mem else int(total_mem() * 0.70)


def human(n):
    for u in ("B", "K", "M", "G"):
        if n < 1024 or u == "G": return f"{n:.0f}{u}" if u in "BK" else f"{n:.1f}{u}"
        n /= 1024


def human_secs(s):
    s = int(s)
    return f"{s}s" if s < 60 else f"{s // 60}m {s % 60:02d}s" if s < 3600 else f"{s // 3600}h {s % 3600 // 60:02d}m"


def parse_args(argv):
    o = {"mem": None, "plugged": False, "fg": False, "label": None, "cmd": []}
    argv = list(argv)
    while argv and argv[0] != "--" and argv[0].startswith("--"):
        a = argv.pop(0)
        if a == "--mem" and argv: o["mem"] = argv.pop(0)
        elif a.startswith("--mem="): o["mem"] = a.split("=", 1)[1]
        elif a == "--plugged": o["plugged"] = True
        elif a == "--fg": o["fg"] = True
        elif a == "--label" and argv: o["label"] = argv.pop(0)
        else: raise ValueError(f"unknown option {a}")
    if argv[:1] == ["--"]: argv.pop(0)
    o["cmd"] = argv
    return o


def on_ac():
    return any((p / "online").read_text().strip() == "1" for p in Path("/sys/class/power_supply").glob("*")
               if (p / "type").exists() and (p / "type").read_text().strip() in ("Mains", "USB") and (p / "online").exists())


def outcome(spec, result, status):
    """Notification (title, urgent) for how a job ended. result/status come from systemd ($SERVICE_RESULT, $EXIT_STATUS)."""
    name = spec.get("label") or spec["cmd"][:40]
    took = human_secs(time.time() - spec.get("started", time.time()))
    if spec.get("stopped"): return "", False                     # you stopped it (systemd calls a SIGTERM stop "success")
    if result == "oom-kill": return f"✗ {name}: stopped, it used all of its {human(spec['max'])} memory", True
    if result == "success": return f"✓ {name} finished ({took})", False
    return f"✗ {name} failed ({'exit ' + status if status.isdigit() else result}, {took})", False


def save(jid, spec):
    DIR.mkdir(parents=True, exist_ok=True)
    p = DIR / f"{jid}.json"; p.write_text(json.dumps(spec)); os.chmod(p, 0o600)


def prune(keep=50):
    """Keep the newest `keep` finished jobs' records and logs."""
    done = sorted((p for p in DIR.glob("*.json") if '"result"' in p.read_text()), key=lambda p: p.stat().st_mtime)
    for p in done[:-keep]:
        p.unlink(missing_ok=True); p.with_suffix(".log").unlink(missing_ok=True)


def load(jid): return json.loads((DIR / f"{jid}.json").read_text())


def unit(jid): return f"job-{jid}"


def resolve(prefix):
    ids = sorted(p.stem for p in DIR.glob("*.json")) if DIR.exists() else []
    m = [i for i in ids if i == prefix or i.endswith(prefix)]
    if len(m) != 1: raise ValueError(f"no single job matches {prefix!r} (job ls)")
    return m[0]


def start(o):
    if not o["cmd"]: raise ValueError("Usage: job [--mem 6G] [--plugged] [--fg] -- COMMAND")
    cap = limits(o["mem"])
    cmd = " ".join(o["cmd"]) if len(o["cmd"]) > 1 else o["cmd"][0]
    props = ["-p", f"MemoryMax={cap}", "-p", "MemorySwapMax=0", "-p", "OOMPolicy=stop"]   # no swap: stop at the cap, don't thrash
    if o["fg"]:
        return subprocess.call(["systemd-run", "--user", "--scope", "-q", *props, "--", "bash", "-c", cmd])
    jid = time.strftime("%m%d-%H%M%S")
    while (DIR / f"{jid}.json").exists(): time.sleep(1); jid = time.strftime("%m%d-%H%M%S")   # two jobs in one second
    try: words = shlex.split(cmd)
    except ValueError: words = cmd.split()          # unbalanced quote: bash will report it; the label just needs words
    label = o.get("label") or ((Path(words[0]).name + (" " + words[1] if len(words) > 1 else "")) if words else cmd)
    spec = {"id": jid, "cmd": cmd, "label": label[:40], "cwd": os.getcwd(), "max": cap,
            "plugged": o["plugged"], "created": time.time()}
    save(jid, spec); prune()
    env = [f"--setenv={k}={os.environ[k]}" for k in ("JOB_DIR", "JOB_QUIET") if os.environ.get(k)]
    r = subprocess.run(["systemd-run", "--user", "-q", f"--unit={unit(jid)}", "--collect", *props, *env,
                        "-p", f"WorkingDirectory={os.getcwd()}", "-p", f"ExecStopPost={sys.executable} {SELF} _done {jid}",
                        "--", sys.executable, str(SELF), "_exec", jid], capture_output=True, text=True)
    if r.returncode: raise RuntimeError((r.stderr or r.stdout).strip() or "systemd-run failed")
    print(good(f"✓ job {jid} running") + dim(f" (memory cap {human(cap)}" + (", waits for the charger" if o["plugged"] else "") + ")")
          + dim(f"\n  job log {jid} -f   ·   job stop {jid}   ·   you get a notification when it ends"))
    return OK


def run_exec(jid):
    """Inside the service: wait for the charger if asked, then run the command with output to the job's log."""
    spec = load(jid)
    if spec.get("plugged"):
        while not on_ac(): time.sleep(30)
    spec["started"] = time.time(); save(jid, spec)
    with open(DIR / f"{jid}.log", "ab") as log:
        return subprocess.call(["bash", "-c", spec["cmd"]], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


def run_done(jid):
    """ExecStopPost: systemd tells how it ended; record it and notify."""
    spec = load(jid)
    result, status = os.environ.get("SERVICE_RESULT", "?"), os.environ.get("EXIT_STATUS", "")
    spec.update(ended=time.time(), result=result, status=status); save(jid, spec)
    title, urgent = outcome(spec, result, status)
    if not title: return OK
    tail = ""
    try: tail = "\n".join((DIR / f"{jid}.log").read_text(errors="replace").splitlines()[-3:])
    except OSError: pass
    if os.environ.get("JOB_QUIET"): return OK                                      # tests
    subprocess.run(["notify-send", "-a", "Jobs", "-u", "critical" if urgent else "normal", title, tail[:300]], capture_output=True)
    phone = HOME / ".local/bin/phone"
    if phone.exists(): subprocess.run([str(phone), "_alert", title, "", *(["--urgent"] if urgent else [])], capture_output=True, timeout=20)
    return OK


def state_of(jid, spec):
    if "result" in spec: return "stopped" if spec.get("stopped") else "done" if spec["result"] == "success" else "failed"
    active = subprocess.run(["systemctl", "--user", "is-active", unit(jid)], capture_output=True, text=True).stdout.strip()
    if active in ("active", "activating"): return "running" if spec.get("started") else "waiting"
    return "lost"


def cmd_ls():
    specs = sorted((json.loads(p.read_text()) for p in DIR.glob("*.json")), key=lambda s: s["created"], reverse=True)[:15] if DIR.exists() else []
    if not specs: print("No jobs. Start one: job -- COMMAND"); return OK
    for s in specs:
        st = state_of(s["id"], s)
        mark = {"running": warn("● running"), "waiting": dim("◌ waiting for charger"), "done": good("✓ done"),
                "stopped": dim("■ stopped"), "lost": bad("✗ lost")}.get(st, bad(f"✗ {s.get('result')}"))
        print(f"{s['id']}  {mark:<24} {dim(human(s['max']))}  {s['cmd'][:60]}")
    return OK


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if not argv or argv[0] in ("-h", "--help", "help"): print(__doc__.strip()); return OK
        if argv[0] == "_exec": return run_exec(argv[1])
        if argv[0] == "_done": return run_done(argv[1])
        if argv[0] == "ls": return cmd_ls()
        if argv[0] == "log":
            jid = resolve(argv[1] if len(argv) > 1 else ""); log = DIR / f"{jid}.log"
            if "-f" in argv: os.execvp("tail", ["tail", "-n", "100", "-F", str(log)])
            print(log.read_text(errors="replace")[-8000:] if log.exists() else "(no output yet)", end=""); return OK
        if argv[0] == "stop":
            jid = resolve(argv[1] if len(argv) > 1 else ""); spec = load(jid); spec["stopped"] = True; save(jid, spec)
            subprocess.run(["systemctl", "--user", "stop", unit(jid)], capture_output=True)
            print(good(f"✓ stopped {jid}")); return OK
        return start(parse_args(argv))
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        print(bad("✗ ") + str(e), file=sys.stderr); return USAGE if isinstance(e, ValueError) else FAIL


if __name__ == "__main__":
    sys.exit(main())
