#!/usr/bin/env python3
"""disk: what's filling the disk, and freeing it safely.

  disk                     free space + everything that can be freed, biggest first
  disk clean ID…           free those (e.g. disk clean docker-build npm)    ·   disk clean --all-safe
  disk big                 big files in ~/Downloads (≥ 200 MB) · disk dupes: duplicate files
  disk trash PATH…         move files to the Trash (reversible)
  disk --json              the same as data (the Storage panel and the watcher use it)

Only regenerable things are deleted outright (caches, build cache, logs); your own files only ever go to the Trash.
Anything that needs root is shown as the exact command for you to run.
"""
import hashlib, json, re, shutil, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
BIG = 200 << 20
OK, FAIL, USAGE = 0, 1, 2


def _c(code): return (lambda s: f"\033[{code}m{s}\033[0m") if sys.stdout.isatty() else (lambda s: s)
good, bad, warn, dim, bold = _c("32"), _c("31"), _c("33"), _c("2"), _c("1")


def run(*argv, timeout=60):
    try: return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e: return subprocess.CompletedProcess(argv, 124, "", str(e))


def have(c): return shutil.which(c) is not None


def du(*paths):
    ps = [str(p) for p in paths if Path(p).exists()]
    if not ps: return 0
    return sum(int(l.split()[0]) for l in run("du", "-sb", *ps, timeout=120).stdout.splitlines() if l.split() and l.split()[0].isdigit())


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or u == "TB": return f"{n:.0f} {u}" if u in ("B", "KB", "MB") else f"{n:.1f} {u}"
        n /= 1000


def parse_docker_size(s):
    """'9.271GB' / '350.1MB (4%)' / '0B' → bytes (Docker uses SI units)."""
    m = re.match(r"([\d.]+)\s*([kKMGT]?B)", s or "")
    return int(float(m[1]) * {"B": 1, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}[m[2]]) if m else 0


def docker_df():
    if not have("docker"): return {}
    out = {}
    for line in run("docker", "system", "df", "--format", "{{json .}}", timeout=30).stdout.splitlines():
        try: d = json.loads(line); out[d["Type"]] = parse_docker_size(d.get("Reclaimable", ""))
        except (ValueError, KeyError): pass
    return out


def wipe(path):
    """Delete a cache folder's contents (the folder itself stays, so apps don't trip over it)."""
    p = Path(path)
    if not p.is_dir(): return
    for c in p.iterdir():
        shutil.rmtree(c, ignore_errors=True) if c.is_dir() and not c.is_symlink() else c.unlink(missing_ok=True)


def chrome_running(): return run("pgrep", "-x", "chrome", timeout=3).returncode == 0


def clean_chrome():
    if chrome_running(): raise RuntimeError("close Chrome first")
    wipe(HOME / ".cache/google-chrome")


def dangling_images():
    if not have("docker"): return 0
    return sum(parse_docker_size(s) for s in run("docker", "image", "ls", "-f", "dangling=true", "--format", "{{.Size}}", timeout=30).stdout.split())


def items(dock=None):
    """Everything that can be freed: [{id, title, why, size, how}] (how = None for root-only: then `cmd` to show)."""
    dock = docker_df() if dock is None else dock
    c = HOME / ".cache"
    L = [
        ("docker-build", "Docker build cache", "Rebuilt when you build an image again (the first build is slower).",
         dock.get("Build Cache", 0), lambda: run("docker", "builder", "prune", "-af", timeout=600)),
        ("docker-leftovers", "Docker leftovers", "Stopped containers and untagged images.",
         dock.get("Containers", 0) + (dangling_images() if dock else 0),
         lambda: (run("docker", "container", "prune", "-f", timeout=300), run("docker", "image", "prune", "-f", timeout=300))),
        ("npm", "npm download cache", "Packages are downloaded again when a project needs them.", du(HOME / ".npm/_cacache"),
         lambda: run("npm", "cache", "clean", "--force", timeout=600) if have("npm") else wipe(HOME / ".npm/_cacache")),
        ("pnpm", "pnpm cache", "Metadata cache; refilled on the next install.", du(c / "pnpm"), lambda: wipe(c / "pnpm")),
        ("uv", "uv (Python) cache", "Re-downloaded on the next install.", du(c / "uv"),
         lambda: run("uv", "cache", "clean", timeout=600) if have("uv") else wipe(c / "uv")),
        ("pip", "pip cache", "Re-downloaded on the next install.", du(c / "pip"), lambda: wipe(c / "pip")),
        ("chrome-cache", "Chrome's disk cache", "Web pages load a little slower at first. Sign-ins, history and tabs are kept "
         "(they're in ~/.config). Close Chrome first.", du(c / "google-chrome"),
         clean_chrome),
        ("trivy", "Security scanner database (trivy)", "Downloaded again on the next scan.", du(c / "trivy"), lambda: wipe(c / "trivy")),
        ("rpi-imager", "Raspberry Pi Imager downloads", "OS images it cached; downloaded again if you flash the same one.",
         du(c / "Raspberry Pi"), lambda: wipe(c / "Raspberry Pi")),
        ("thumbnails", "Picture thumbnails", "Files makes them again as you browse.", du(c / "thumbnails"), lambda: wipe(c / "thumbnails")),
        ("user-logs", "Your old logs (older than 2 weeks)", "App logs you're unlikely to need.", 0,
         lambda: run("journalctl", "--user", "--vacuum-time=2weeks", timeout=120)),
        ("trash", "Trash", "Files you already deleted. This empties it for good.", du(HOME / ".local/share/Trash"),
         lambda: run("gio", "trash", "--empty", timeout=300)),
    ]
    out = [{"id": i, "title": t, "why": w, "size": s, "how": h} for i, t, w, s, h in L if s > 0 or i == "user-logs"]
    root = [("apt", "Downloaded system packages", "Already installed; safe to delete.", du("/var/cache/apt/archives"), "sudo apt clean"),
            ("snap-old", "Old snap versions", "Snap keeps the previous version of each app.",
             0, "snap list --all | awk '/disabled/{print $1, $3}' | while read n r; do sudo snap remove \"$n\" --revision=\"$r\"; done"),
            ("system-logs", "System logs older than 2 weeks", "", 0, "sudo journalctl --vacuum-time=2weeks")]
    out += [{"id": i, "title": t, "why": w, "size": s, "how": None, "cmd": cmd} for i, t, w, s, cmd in root]
    return sorted(out, key=lambda x: (x["how"] is None, -x["size"]))


def free_space(path="/"):
    u = shutil.disk_usage(path); return {"free": u.free, "total": u.total, "used_pct": round(u.used / u.total * 100)}


def big_files(root=None, min_size=BIG):
    root = Path(root or HOME / "Downloads"); out = []
    for p in root.rglob("*") if root.exists() else []:
        try:
            if p.is_file() and not p.is_symlink() and (st := p.stat()).st_size >= min_size: out.append({"path": str(p), "size": st.st_size, "mtime": st.st_mtime})
        except OSError: pass
    return sorted(out, key=lambda x: -x["size"])


def duplicates(roots=None, min_size=1 << 20):
    """Groups of identical files (same size, then same SHA-256), biggest waste first. Hidden folders are skipped."""
    roots = roots or [HOME / d for d in ("Downloads", "Documents", "Pictures", "Desktop", "Videos")]
    by_size = {}
    for r in roots:
        for p in Path(r).rglob("*") if Path(r).exists() else []:
            if any(part.startswith(".") for part in p.relative_to(r).parts): continue
            try:
                if p.is_file() and not p.is_symlink() and (s := p.stat().st_size) >= min_size: by_size.setdefault(s, []).append(p)
            except OSError: pass
    def digest(p, limit=None):
        h = hashlib.sha256()
        try:
            with open(p, "rb") as f:
                if limit: h.update(f.read(limit))
                else:
                    for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
        except OSError: return None
        return h.hexdigest()
    groups = []
    for size, ps in by_size.items():
        if len(ps) < 2: continue
        heads = {}                                   # first 64 KB first: most same-size files differ early, so big ones
        for p in ps: heads.setdefault(digest(p, 1 << 16), []).append(p)          # are rarely read in full
        for head, same in heads.items():
            if head is None or len(same) < 2: continue
            full = {}
            for p in same: full.setdefault(digest(p) if size > (1 << 16) else head, []).append(str(p))
            groups += [{"size": size, "paths": sorted(g, key=lambda x: (len(x), x))} for k, g in full.items() if k and len(g) > 1]
    return sorted(groups, key=lambda g: -g["size"] * (len(g["paths"]) - 1))


def trash(paths):
    bad_ = [p for p in paths if run("gio", "trash", "--", p).returncode]
    return len(paths) - len(bad_), bad_


def clean(ids, its=None):
    """Run the chosen cleanups. Returns [(id, ok, message)]."""
    its = {i["id"]: i for i in (its or items())}; res = []
    for i in ids:
        it = its.get(i)
        if not it: res.append((i, False, "unknown item")); continue
        if it["how"] is None: res.append((i, False, f"needs your password: ! {it['cmd']}")); continue
        before = shutil.disk_usage("/").free
        try:
            r = it["how"]()
            bad_ = [x for x in (r if isinstance(r, tuple) else (r,)) if isinstance(x, subprocess.CompletedProcess) and x.returncode]
            if bad_: res.append((i, False, (bad_[0].stderr or bad_[0].stdout or "failed").strip().splitlines()[-1][:200])); continue
            res.append((i, True, f"freed {human(max(0, shutil.disk_usage('/').free - before))}"))
        except Exception as e: res.append((i, False, str(e)))
    return res


def report(dock=None):
    its = items(dock)
    return {"disk": free_space(), "items": [{k: v for k, v in i.items() if k != "how"} | {"root": i["how"] is None} for i in its],
            "safe_total": sum(i["size"] for i in its if i["how"] is not None)}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["-h"], ["--help"], ["help"]): print(__doc__.strip()); return OK
    if argv[:1] == ["clean"]:
        its = items()
        ids = [i["id"] for i in its if i["how"] is not None and i["id"] not in ("trash", "chrome-cache")] if "--all-safe" in argv else [a for a in argv[1:] if not a.startswith("--")]
        if not ids: print("Usage: disk clean ID… (see `disk`)"); return USAGE
        res = clean(ids, its)
        if "--json" in argv: print(json.dumps(res)); return OK
        for i, ok, msg in res: print((good("✓ ") if ok else bad("✗ ")) + f"{i}: {msg}")
        return OK if all(ok for _, ok, _ in res) else FAIL
    if argv[:1] == ["big"]:
        fs = big_files()
        if "--json" in argv: print(json.dumps(fs)); return OK
        for f in fs: print(f"{human(f['size']):>9}  {time.strftime('%d %b %Y', time.localtime(f['mtime']))}  {f['path']}")
        return OK
    if argv[:1] == ["dupes"]:
        gs = duplicates()
        if "--json" in argv: print(json.dumps(gs)); return OK
        for g in gs[:30]: print(bold(f"{human(g['size'])} × {len(g['paths'])}") + "".join(f"\n  {p}" for p in g["paths"]))
        return OK
    if argv[:1] == ["trash"]:
        n, failed = trash(argv[1:]); print(good(f"✓ {n} moved to the Trash") + (bad(f"  ✗ {', '.join(failed)}") if failed else ""))
        return OK if not failed else FAIL
    r = report()
    if "--json" in argv: print(json.dumps(r)); return OK
    d = r["disk"]
    print(bold(f"{human(d['free'])} free") + dim(f" of {human(d['total'])} ({d['used_pct']} % used)"))
    print(f"Can be freed safely: {bold(human(r['safe_total']))}\n")
    for i in r["items"]:
        size = human(i["size"]) if i["size"] else "—"
        print(f"  {size:>9}  {i['title']:<38} {dim(i['id'] if not i['root'] else '! ' + i['cmd'][:60])}")
    print(dim("\nFree some: disk clean docker-build npm …   ·   everything safe: disk clean --all-safe"))
    return OK


if __name__ == "__main__":
    sys.exit(main())
