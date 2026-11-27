#!/usr/bin/env python3
"""tidy: sort ~/Downloads into folders by kind. Off until you turn it on; shows what it would do first.

  tidy                 preview: what would move where (changes nothing)
  tidy --apply         do it now
  tidy on | off        tidy automatically once a day (the assistant's watcher runs it) / stop
  tidy rules           where the rules live and what they say

Default rules: images → Downloads/Images, PDFs and office files → Documents, archives → Archives, installers
(.deb, .AppImage, .iso…) → Installers, video, audio, code. Only files older than a day are moved (so a download you're
about to open stays put); unfinished downloads, hidden files and folders are never touched; a name clash gets " (2)".
Installers older than 30 days can go to the Trash (off by default: "trash_installers_after_days").
Rules: ~/.config/myos/tidy.json (written with the defaults on first use; edit freely).
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

HOME = Path.home()
CONF = Path(os.environ.get("TIDY_CONF") or HOME / ".config/myos/tidy.json")
STATE = Path(os.environ.get("TIDY_STATE") or HOME / ".local/state/myos/tidy.json")
DEFAULT = {
    "enabled": False,
    "folder": "~/Downloads",
    "min_age_hours": 24,
    "trash_installers_after_days": 0,
    "rules": {
        "Images": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".heic", ".bmp", ".avif"],
        "Documents": [".pdf", ".doc", ".docx", ".odt", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp", ".txt", ".md", ".csv", ".epub", ".rtf"],
        "Archives": [".zip", ".tar", ".gz", ".tgz", ".xz", ".bz2", ".7z", ".rar", ".zst"],
        "Installers": [".deb", ".rpm", ".appimage", ".iso", ".img", ".run", ".exe", ".msi", ".flatpakref"],
        "Videos": [".mp4", ".mkv", ".webm", ".mov", ".avi"],
        "Audio": [".mp3", ".wav", ".flac", ".ogg", ".m4a", ".opus"],
        "Code": [".py", ".js", ".ts", ".json", ".sh", ".ipynb", ".c", ".cpp", ".h", ".rs", ".go", ".yaml", ".yml", ".toml"],
    },
}
PARTIAL = (".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload")


def load():
    try: c = {**DEFAULT, **json.loads(CONF.read_text())}
    except FileNotFoundError:
        CONF.parent.mkdir(parents=True, exist_ok=True); CONF.write_text(json.dumps(DEFAULT, indent=2) + "\n"); c = dict(DEFAULT)
    except ValueError: raise SystemExit(f"tidy: {CONF} isn't valid JSON; fix it or delete it to get the defaults")
    return c


def dest_for(name, rules):
    n = name.lower()
    ext = ".tar.gz" if n.endswith(".tar.gz") else Path(n).suffix
    for folder, exts in rules.items():
        if ext in exts or (ext == ".tar.gz" and ".gz" in exts): return folder
    return None


def free_name(path):
    if not path.exists(): return path
    stem, suf, i = path.stem, path.suffix, 2
    while (path.with_name(f"{stem} ({i}){suf}")).exists(): i += 1
    return path.with_name(f"{stem} ({i}){suf}")


def plan(c, now=None):
    """[(action, src, dst)] with action 'move' or 'trash'. Pure apart from reading the folder."""
    now = now or time.time()
    root = Path(c["folder"]).expanduser()
    out, targets = [], set(c["rules"])
    if not root.is_dir(): return out
    for p in sorted(root.iterdir()):
        if p.name.startswith(".") or not p.is_file() or p.is_symlink() or p.name.lower().endswith(PARTIAL): continue
        if p.with_name(p.name + ".crdownload").exists() or p.with_name(p.name + ".part").exists(): continue
        age = now - p.stat().st_mtime
        if age < c["min_age_hours"] * 3600: continue
        folder = dest_for(p.name, c["rules"])
        if not folder: continue
        days = c.get("trash_installers_after_days") or 0
        if folder == "Installers" and days and age > days * 86400: out.append(("trash", p, None)); continue
        out.append(("move", p, root / folder / p.name))
    for f in targets:                                   # old installers already sorted into Installers/
        d, days = root / f, c.get("trash_installers_after_days") or 0
        if f == "Installers" and days and d.is_dir():
            out += [("trash", p, None) for p in sorted(d.iterdir()) if p.is_file() and now - p.stat().st_mtime > days * 86400]
    return out


def apply(steps):
    done = []
    for action, src, dst in steps:
        try:
            if action == "trash":
                if subprocess.run(["gio", "trash", str(src)], capture_output=True).returncode == 0: done.append((action, src, None))
            else:
                dst.parent.mkdir(exist_ok=True); dst = free_name(dst); shutil.move(str(src), str(dst)); done.append((action, src, dst))
        except OSError: pass
    return done


def summary(steps):
    moved = {}
    for a, _, d in steps:
        key = "Trash" if a == "trash" else d.parent.name
        moved[key] = moved.get(key, 0) + 1
    return ", ".join(f"{n} → {k}" for k, n in sorted(moved.items()))


def daily():
    """Watcher hook: once a day, if turned on. Returns the summary (empty if nothing ran)."""
    c = load()
    if not c.get("enabled"): return ""
    try: last = json.loads(STATE.read_text()).get("last", 0)
    except (OSError, ValueError): last = 0
    if time.time() - last < 23 * 3600: return ""
    done = apply(plan(c))
    STATE.parent.mkdir(parents=True, exist_ok=True); STATE.write_text(json.dumps({"last": time.time(), "moved": len(done)}))
    return summary(done)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "preview"
    if cmd in ("-h", "--help"): print(__doc__.strip()); return 0
    c = load()
    if cmd in ("on", "off"):
        c["enabled"] = cmd == "on"; CONF.write_text(json.dumps(c, indent=2) + "\n")
        print("Tidying Downloads once a day." if cmd == "on" else "Automatic tidying is off."); return 0
    if cmd == "rules":
        print(f"{CONF}  (automatic: {'on' if c['enabled'] else 'off'})")
        for k, v in c["rules"].items(): print(f"  {k:<11} {' '.join(v)}")
        return 0
    if cmd == "_daily":
        s = daily()
        if s: subprocess.run(["notify-send", "-a", "Downloads", "Tidied Downloads", s], capture_output=True)
        return 0
    steps = plan(c)
    if not steps: print("Nothing to tidy."); return 0
    if cmd == "--apply":
        done = apply(steps); print(f"Done: {summary(done)}"); return 0
    for a, s, d in steps: print(f"  {s.name}  →  {'Trash' if a == 'trash' else d.parent.name + '/'}")
    print(f"\n{len(steps)} file(s): {summary(steps)}.  Run `tidy --apply` to do it" + ("" if c["enabled"] else ", or `tidy on` for every day") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
