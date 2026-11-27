#!/usr/bin/env python3
"""services: what's running for development on this laptop: listening ports and Docker containers.

  services                     ports your programs listen on (with the program and its folder) + Docker containers
  services --json              the same as data (the Services panel uses it)
  services who PORT            which program is using a port ("who's on :3000")
  services stop-port PORT      stop the program listening on PORT (polite SIGTERM; only your own processes)
  services docker start|stop|restart NAME
  services compose start|stop PROJECT    every container of a compose project
  services logs NAME           follow a container's logs (in this terminal)

It never touches system services, and refuses to stop the programs this setup runs on (agents, the local model, phone link).
"""
import json, os, re, shutil, signal, subprocess, sys
from pathlib import Path

HOME = Path.home()
# programs you don't want to kill from a "stop port" button: this setup's own long-running pieces
PROTECTED = {"claude", "codex", "ollama", "llama-server", "kdeconnectd", "gnome-keyring-d", "Hyprland", "systemd", "adb"}
WELL_KNOWN = {"ollama": "local AI models", "llama-server": "local AI model", "adb": "Android cable link",
              "claude": "Claude Code", "codex": "Codex", "kdeconnectd": "phone link", "code": "VS Code"}


def run(args, timeout=10):
    try: return subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e: return subprocess.CompletedProcess(args, 124, "", str(e))


def parse_ss(text):
    """[{port, addr, name, pid}] from `ss -tlnpH`, only sockets whose process we can see (= our own)."""
    out, seen = [], set()
    for line in (text or "").splitlines():
        f = line.split()
        if len(f) < 4: continue
        addr, _, port = f[3].rpartition(":")
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        if not port.isdigit() or not m or (int(port), m[2]) in seen: continue
        seen.add((int(port), m[2]))
        out.append({"port": int(port), "addr": addr.strip("[]").split("%")[0], "name": m[1], "pid": int(m[2])})
    return sorted(out, key=lambda p: p["port"])


def proc_info(pid):
    """Command line (short) and working folder of a process."""
    try: args = [a.decode(errors="replace") for a in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if a]
    except OSError: args = []
    try: cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError: cwd = ""
    return " ".join(Path(args[0]).name.split() + args[1:4])[:80] if args else "", cwd


def local_only(addr):
    return addr.startswith("127.") or addr in ("::1", "localhost")


def ports():
    out = []
    for p in parse_ss(run(["ss", "-tlnpH"]).stdout):
        cmd, cwd = proc_info(p["pid"])
        p.update(cmd=cmd, cwd=cwd.replace(str(HOME), "~", 1), local=local_only(p["addr"]),
                 what=WELL_KNOWN.get(p["name"], ""), protected=p["name"] in PROTECTED)
        out.append(p)
    return out


def parse_docker(lines):
    """Containers from `docker ps -a --format '{{json .}}'`, with their compose project (or "")."""
    out = []
    for l in (lines or "").splitlines():
        try: c = json.loads(l)
        except ValueError: continue
        labels = dict(kv.split("=", 1) for kv in (c.get("Labels") or "").split(",") if "=" in kv)
        out.append({"name": c.get("Names", ""), "image": c.get("Image", ""), "state": c.get("State", ""),
                    "status": c.get("Status", ""), "ports": c.get("Ports", ""), "health": c.get("HealthStatus", ""),
                    "project": labels.get("com.docker.compose.project", ""),
                    "service": labels.get("com.docker.compose.service", ""),
                    "folder": labels.get("com.docker.compose.project.working_dir", "").replace(str(HOME), "~", 1)})
    return out


def containers():
    if not shutil.which("docker"): return None
    r = run(["docker", "ps", "-a", "--format", "{{json .}}"])
    return parse_docker(r.stdout) if r.returncode == 0 else None


def stacks(cs):
    """Group containers: {project or "": [containers]}, running stacks first."""
    g = {}
    for c in cs or []: g.setdefault(c["project"], []).append(c)
    return dict(sorted(g.items(), key=lambda kv: (not any(c["state"] == "running" for c in kv[1]), kv[0] == "", kv[0])))


def owner(port):
    return [p for p in ports() if p["port"] == port]


def stop_port(port):
    ps = owner(port)
    if not ps: print(f"Nothing of yours is listening on :{port}."); return 1
    for p in ps:
        if p["protected"]: print(f":{port} is {p['name']} ({p['what'] or 'part of this setup'}); not stopping it."); return 1
    for p in ps:
        try: os.kill(p["pid"], signal.SIGTERM); print(f"Stopped {p['name']} (pid {p['pid']}) on :{port}.")
        except OSError as e: print(f"Couldn't stop pid {p['pid']}: {e}"); return 1
    return 0


SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "show"
    if cmd in ("-h", "--help"): print(__doc__.strip()); return 0
    if cmd in ("who", "stop-port"):
        if len(argv) < 2 or not argv[1].lstrip(":").isdigit(): print(f"usage: services {cmd} PORT"); return 2
        port = int(argv[1].lstrip(":"))
        if cmd == "stop-port": return stop_port(port)
        ps = owner(port)
        for p in ps: print(f":{port}  {p['name']} (pid {p['pid']})  {p['cmd']}  in {p['cwd']}")
        if not ps: print(f"Nothing of yours is listening on :{port}.")
        return 0 if ps else 1
    if cmd in ("docker", "compose", "logs"):
        name = argv[-1] if len(argv) >= 2 else ""
        act = argv[1] if cmd != "logs" and len(argv) == 3 else ("logs" if cmd == "logs" else "")
        if not SAFE.match(name) or act not in ("start", "stop", "restart", "logs") or (cmd == "compose" and act == "restart"):
            print(__doc__.strip()); return 2
        if cmd == "logs": return subprocess.call(["docker", "logs", "-f", "--tail", "200", name])
        args = ["docker", "compose", "-p", name, act] if cmd == "compose" else ["docker", act, name]
        r = run(args, timeout=120); print((r.stdout + r.stderr).strip() or "done"); return r.returncode
    ps, cs = ports(), containers()
    if cmd == "--json": print(json.dumps({"ports": ps, "containers": cs, "stacks": stacks(cs)})); return 0
    print("Listening (your programs):")
    for p in ps:
        print(f"  :{p['port']:<6} {p['name']:<14} {'local only' if p['local'] else 'open to network':<15} {p['what'] or p['cwd']}")
    if cs is None: print("Docker: not available"); return 0
    print("Docker:" if cs else "Docker: no containers")
    for proj, items in stacks(cs).items():
        print(f"  {proj or '(single containers)'}")
        for c in items: print(f"    {c['name']:<32} {c['state']:<9} {c['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
