#!/usr/bin/env python3
"""AI Chat — native GTK4/libadwaita chat with the local model.

Persistent searchable conversations, streaming with Stop, Retry/Edit, file attachments (button or drag-and-drop),
and current web answers with dated, numbered sources from a local SearXNG (started on demand, stopped on exit).
The clipboard is never touched unless you press Copy. Chats: ~/.local/share/local-ai/chats/*.json
"""
import concurrent.futures, ctypes, datetime, html, importlib.util, json, math, os, re, shlex, subprocess, sys, threading, time, urllib.parse, urllib.request, uuid
from html.parser import HTMLParser
from pathlib import Path

HOME = Path.home()
_spec = importlib.util.spec_from_file_location("fai", HOME / ".local/share/local-ai/fai.py")
if not (HOME / ".local/share/local-ai/fai.py").exists():  # running from the repo (tests)
    _spec = importlib.util.spec_from_file_location("fai", Path(__file__).with_name("fai.py"))
fai = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fai)

CHATS = HOME / ".local/share/local-ai/chats"
EXPORTS = HOME / "Documents/AI Chats"
SEARX = "http://127.0.0.1:8888"
UA = "Mozilla/5.0 (X11; Linux x86_64) KadaOS-Chat/1.0"
MAX_ATTACH, MAX_HISTORY_CHARS = 15000, 16000

# ───────────────────────── web evidence (pure, testable) ─────────────────────────
CURRENT = re.compile(r"\b(today|tonight|yesterday|tomorrow|latest|newest|current(ly)?|right now|this (week|month|year)|news|"
                     r"price|prices|cost|weather|score|released?|release date|update[sd]?|version|stock|exchange rate|20[2-9]\d)\b", re.I)
def needs_web(text): return bool(CURRENT.search(text))

class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"}
    def __init__(self): super().__init__(); self.out, self.depth = [], 0
    def handle_starttag(self, tag, a):
        if tag in self.SKIP: self.depth += 1
    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth: self.depth -= 1
    def handle_data(self, d):
        if not self.depth: self.out.append(d)
def html_to_text(page):
    p = _Text()
    try: p.feed(page)
    except Exception: pass
    return re.sub(r"\s+", " ", " ".join(p.out)).strip()

def searx_up():
    try: urllib.request.urlopen(SEARX + "/healthz", timeout=1.5).read(); return True
    except Exception: return False

def ensure_searx(wait=20):
    """Returns (ok, started_by_us, message)."""
    if searx_up(): return True, False, ""
    r = subprocess.run(["docker", "start", "searxng"], capture_output=True, text=True)
    if r.returncode: return False, False, "Web search is not installed (run scripts/install-search.sh)." if "No such container" in r.stderr else f"Could not start web search: {r.stderr.strip()[:160]}"
    for _ in range(wait * 2):
        if searx_up(): return True, True, ""
        time.sleep(0.5)
    return False, True, "Web search did not start in time."

def web_search(query, n=5):
    url = SEARX + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=12) as r:
        data = json.loads(r.read())
    seen, out = set(), []
    for x in data.get("results", []):
        u = x.get("url", "")
        if not u.startswith("http") or u in seen: continue
        seen.add(u); out.append({"title": x.get("title") or u, "url": u, "snippet": x.get("content") or "",
                                 "date": (x.get("publishedDate") or "")[:10]})
        if len(out) >= n: break
    return out

def fetch_text(url, limit=2500):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=6) as r:
        if "html" not in r.headers.get("Content-Type", ""): return ""
        return html_to_text(r.read(600_000).decode(r.headers.get_content_charset() or "utf-8", "replace"))[:limit]

def web_context(query, search=web_search, fetch=fetch_text):
    """(context text, sources). Page reads run in parallel; a failed page falls back to its search snippet."""
    results = search(query)
    with concurrent.futures.ThreadPoolExecutor(5) as ex:
        bodies = list(ex.map(lambda r: _safe(fetch, r["url"]), results))
    parts = []
    for i, (r, body) in enumerate(zip(results, bodies), 1):
        parts.append(f"[{i}] {r['title']} — {r['url']}" + (f" (published {r['date']})" if r["date"] else "") + f"\n{body or r['snippet']}")
    return "\n\n".join(parts), results

def _safe(fn, *a):
    try: return fn(*a)
    except Exception: return ""

# ───────────────────────── conversation model (pure, testable) ─────────────────────────
def system_prompt(web_used, web_error=""):
    today = datetime.date.today().strftime("%A %d %B %Y")
    p = (f"You are a helpful, precise assistant on the user's Linux laptop. Today is {today}. "
         "Answer in clear Markdown: short paragraphs, lists or tables when they help, fenced code blocks with a language. ")
    if web_used:
        p += ("Web search results are supplied in <web>. Base current facts on them and cite like [1] or [2][3] right after "
              "the claim. Prefer the newest dated source; if sources disagree, say so. Never invent a citation.")
    elif web_error:
        p += f"Web search failed ({web_error}). If the question needs current information, say your answer may be outdated."
    else:
        p += "You have no web access in this turn. For news, prices, versions or other current facts, say your knowledge may be outdated."
    return p

def build_messages(history, web_ctx="", web_error=""):
    """history: stored messages (role, content, context). Older turns are dropped to fit the context window."""
    msgs, size = [], 0
    for m in reversed(history):
        body = (strip_tool_echo(m["content"]) if m["role"] == "assistant" else m["content"]) + (f"\n\n<attached>\n{m['context']}\n</attached>" if m.get("context") else "")
        if msgs and size + len(body) > MAX_HISTORY_CHARS: break
        msgs.insert(0, {"role": m["role"], "content": body}); size += len(body)
    if web_ctx and msgs: msgs[-1]["content"] = f"<web>\n{web_ctx}\n</web>\n\n" + msgs[-1]["content"]
    return [{"role": "system", "content": system_prompt(bool(web_ctx), web_error)}] + msgs

# ───────────────────────── local agent ─────────────────────────
# Safe, reversible desktop actions the assistant can perform on request. Key -> shell command.
_S = "~/.config/hypr/scripts"
DESKTOP_ACTIONS = {
    "screenshot_area": f"{_S}/screenshot.sh area", "screenshot_full": f"{_S}/screenshot.sh full",
    "screenshot_window": f"{_S}/screenshot.sh window", "lock_screen": f"{_S}/lock.sh",
    "night_light": f"{_S}/nightlight.sh", "do_not_disturb": "swaync-client -d -sw",
    "volume_up": f"{_S}/osd.sh vol-up", "volume_down": f"{_S}/osd.sh vol-down", "mute": f"{_S}/osd.sh mute",
    "brightness_up": f"{_S}/osd.sh bright-up", "brightness_down": f"{_S}/osd.sh bright-down",
    "clipboard_history": "~/.local/bin/myos-panel clipboard", "calendar": "~/.local/bin/myos-panel calendar",
    "wifi_panel": "~/.local/bin/myos-panel wifi", "bluetooth_panel": "~/.local/bin/myos-panel bluetooth",
    "power_saver": f"{_S}/power-profile.sh set power-saver", "power_balanced": f"{_S}/power-profile.sh set balanced",
    "power_performance": f"{_S}/power-profile.sh set performance", "settings": f"{_S}/settings.sh",
    "dictation": "~/.local/bin/ai-dictate toggle", "file_search": "~/.local/bin/ai-search",
    "keep_awake_on": f"{_S}/keep-awake.sh on", "keep_awake_off": f"{_S}/keep-awake.sh off",
}

def _load(name, *candidates):
    """Import a sibling KadaOS tool (installed path first, then the repo) or None if missing."""
    for c in candidates:
        if Path(c).exists():
            try:
                loader = importlib.machinery.SourceFileLoader(name, str(c))
                mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader)); loader.exec_module(mod)
                return mod
            except Exception:
                pass
    return None

import importlib.machinery
_REPO = Path(__file__).resolve().parents[1]
FA = _load("fileactions", HOME / ".local/share/myos/fileactions.py", _REPO / "desktop/fileactions.py")
SECLAB = _load("seclab", HOME / ".local/share/security-workbench/seclab", _REPO / "security/seclab")
RECIPES = list(SECLAB.RECIPES) if SECLAB else []
WATCH = _load("watch", HOME / ".local/share/local-ai/watch.py", _REPO / "ai/watch.py")

ALLOW = HOME / ".config/local-ai/allow.json"
NEVER_ALWAYS = {"rm", "dd", "mkfs", "shred", "chmod", "chown", "mv", "kill", "pkill", "killall", "reboot", "shutdown",
                "poweroff", "systemctl", "curl", "wget", "bash", "sh", "zsh", "python", "python3", "eval", "exec", "sudo",
                "pkexec", "git", "docker", "nmap", "truncate", "find", "xargs", "tee", "crontab"}

def allow_key(cmd):
    """The program a simple command runs, if it may be 'always allowed' (no shell operators, not destructive)."""
    if re.search(r"[;&|<>`$()\n]", cmd): return None
    try: words = [w for w in shlex.split(cmd) if not re.match(r"^\w+=", w)]
    except ValueError: return None
    prog = Path(words[0]).name if words else ""
    return prog if prog and prog not in NEVER_ALWAYS else None

def allowed():
    try: return set(json.loads(ALLOW.read_text()).get("programs", []))
    except Exception: return set()

def revoke_allow(prog):
    ALLOW.write_text(json.dumps({"programs": sorted(allowed() - {prog})}, indent=1))

SLASH_HELP = [("/memory", "what the assistant remembers about you (forget items)"), ("/remember <fact>", "save a fact"),
              ("/permissions", "programs that run without asking (revoke)"), ("/log", "what it did recently"),
              ("/routines", "scheduled routines (remove)"), ("/briefing", "today's briefing"),
              ("/scan <target>", "security scan"), ("/convert <file> to <format>", "convert a file"),
              ("/layout <name>", "open a work layout"), ("/help", "this list")]
SLASH_REWRITE = {"scan": "Run a security scan of {}", "convert": "Convert {}", "layout": "Open the {} layout"}
SLASH_LOCAL = {"memory", "remember", "permissions", "log", "routines", "briefing", "help"}

FLOW = _load("flow", HOME / ".config/hypr/scripts/flow.py", _REPO / "hypr/scripts/flow.py")

def slash_suggestions(text, recent=None, layouts=None, scope=None):
    """Autocomplete for the composer: [(insert, label, description, ready)]; ready = Enter runs it as is."""
    if not text.startswith("/") or "\n" in text: return []
    m = re.fullmatch(r"/(\w*)", text)
    if m:
        out = []
        for usage, desc in SLASH_HELP:
            cmd = usage.split()[0]
            if cmd[1:].startswith(m.group(1).lower()):
                takes = "<" in usage
                out.append((cmd + (" " if takes else ""), usage, desc, not takes))
        return out
    m = re.fullmatch(r"/(\w+) (.*)", text, re.S)
    if not m: return []
    cmd, arg = m.group(1).lower(), m.group(2)
    low = arg.lower()
    if cmd == "layout":
        names = list(FLOW.PROFILES) if layouts is None and FLOW else layouts or []
        return [(f"/layout {n}", n, "open this work layout", True) for n in names if n.lower().startswith(low)]
    if cmd == "scan":
        if scope is None:
            try: scope = SECLAB.scope(SECLAB.active()) if SECLAB and SECLAB.active() else []
            except Exception: scope = []
        return [(f"/scan {t}", t, "in the active engagement's scope", True) for t in scope if t.lower().startswith(low)]
    if cmd == "convert" and " to " not in arg:
        files = recent_files(12) if recent is None else recent
        return [(f"/convert {f} to ", Path(f).name, str(Path(f).parent).replace(str(HOME), "~"), False)
                for f in files if low in f.lower()][:6]
    return []

def parse_slash(text):
    """('prompt', rewritten request) | ('local', command, argument) | None for ordinary text."""
    m = re.match(r"/([a-z]+)\b\s*(.*)", text.strip(), re.S | re.I)
    if not m: return None
    cmd, arg = m.group(1).lower(), m.group(2).strip()
    if cmd in SLASH_REWRITE: return ("prompt", SLASH_REWRITE[cmd].format(arg)) if arg else ("local", "help", "")
    return ("local", cmd, arg) if cmd in SLASH_LOCAL else ("local", "help", cmd)

def remember_allow(prog):
    ALLOW.parent.mkdir(parents=True, exist_ok=True)
    ALLOW.write_text(json.dumps({"programs": sorted(allowed() | {prog})}, indent=1))

# ── voice: speak replies (voice-server.py, Kokoro on CPU) and hear questions (whisper-server on GPU) ──
VOICE_SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "myos-voice.sock"
VOICE_PY = HOME / ".local/share/local-ai/venv-voice/bin/python"
VOICE_SRV = HOME / ".local/share/local-ai/voice-server.py"

VLOG = HOME / ".cache/myos-assistant.log"
def vlog(msg):
    try:
        VLOG.parent.mkdir(parents=True, exist_ok=True)
        with open(VLOG, "a") as f: f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError: pass

def speakable(text):
    """What to say out loud: prose only. Code, tables and URLs stay on screen."""
    t = re.sub(r"```.*?(```|$)", " ", text, flags=re.S)
    t = "\n".join(l for l in t.splitlines() if not l.lstrip().startswith("|"))
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)            # [label](url) → label
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"[*_#>]+", "", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    return " ".join(t.split())

class SentenceFeeder:
    """Turns a token stream into whole spoken sentences as soon as each one ends (low perceived latency)."""
    def __init__(self, limit=700):
        self.buf, self.said, self.limit, self.capped = "", 0, limit, False
    def feed(self, tok):
        self.buf += tok; out = []
        while True:
            fence = self.buf.find("```")
            if fence == 0:                                            # a code block: skip it whole, never speak it
                end = self.buf.find("```", 3)
                if end < 0: return out                                # still streaming the block
                self.buf = self.buf[end + 3:]; continue
            text = self.buf if fence < 0 else self.buf[:fence]
            m = re.search(r"(.+?[.!?:])(\s+)(?=\S)|\n\n", text, flags=re.S)
            if m:
                chunk, self.buf = text[:m.end()], self.buf[m.end():]
            elif fence > 0:                                           # prose right before a code block
                chunk, self.buf = text, self.buf[fence:]
            else:
                return out
            out += self._take(chunk)
    def flush(self):
        chunk, self.buf = self.buf, ""
        return self._take(chunk)
    def _take(self, chunk):
        say = speakable(chunk)
        if not say or self.capped: return []
        if self.said + len(say) > self.limit:
            self.capped = True; return ["The rest is on screen."]
        self.said += len(say); return [say]

def voice_send(req, start=True):
    """Send one request to the voice server (starting it on demand). Returns the reply dict or None."""
    import socket
    for attempt in range(30):
        try:
            with socket.socket(socket.AF_UNIX) as c:
                c.settimeout(2); c.connect(str(VOICE_SOCK)); c.sendall((json.dumps(req) + "\n").encode())
                if req.get("status"): return json.loads(c.makefile().readline() or "{}")
                return {}
        except OSError:
            if not start or not VOICE_PY.exists(): return None
            if attempt == 0:
                subprocess.Popen([str(VOICE_PY), str(VOICE_SRV)], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.2)
    return None

def calculate(expr):
    """Exact arithmetic for the model (it is unreliable at mental math): + - * / // % ** ( ) and N% → N/100."""
    import ast, operator as op
    ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
           ast.Mod: op.mod, ast.Pow: op.pow, ast.USub: op.neg, ast.UAdd: op.pos}
    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)): return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in ops:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 100: raise ValueError("exponent too large")
            return ops[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in ops: return ops[type(n.op)](ev(n.operand))
        raise ValueError("only numbers and + - * / // % ** ( ) are allowed")
    e = re.sub(r"(\d+(?:\.\d+)?)\s*%(?!\s*[\d(])", r"(\1/100)", expr.replace(",", "").replace("×", "*").replace("÷", "/"))
    r = ev(ast.parse(e, mode="eval").body)
    return str(round(r, 10)).rstrip("0").rstrip(".") if isinstance(r, float) and "." in str(r) else str(r)

def _fa_help():
    if not FA: return ""
    parts = []
    for aid, (label, _k, opts, *_r) in FA.catalogue().items():
        if aid == "copy_path": continue
        parts.append(f"{aid} ({label.rstrip('…')}" + (f"; option: {'|'.join(v for _, v in opts)}" if opts else "") + ")")
    return "; ".join(parts)

SELF_CLASSES = {"org.myos.Chat"}

def _q(*argv, timeout=4):
    try: return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL).stdout.strip()
    except Exception: return ""

def _hypr_json(what):
    try: return json.loads(_q("hyprctl", what, "-j") or "null")
    except Exception: return None

def user_window(clients=None):
    """The window the user was last working in (the chat itself doesn't count)."""
    clients = _hypr_json("clients") if clients is None else clients
    wins = [c for c in clients or [] if c.get("mapped", True) and c.get("class") not in SELF_CLASSES and c.get("focusHistoryID", -1) >= 0]
    return min(wins, key=lambda c: c["focusHistoryID"]) if wins else None

SHELLS = {"bash", "zsh", "fish", "sh", "dash", "nu"}

def shell_cwds(pid, proc=Path("/proc")):
    """Working folders of the shells running under a terminal process (one per tab/pane), newest first."""
    kids = {}
    for d in proc.iterdir():
        if not d.name.isdigit(): continue
        try: f = (d / "stat").read_text(); ppid = int(f[f.rindex(")") + 2:].split()[1])
        except Exception: continue
        kids.setdefault(ppid, []).append(int(d.name))
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        for k in kids.get(p, []):
            todo.append(k)
            try:
                if (proc / str(k) / "comm").read_text().strip() in SHELLS:
                    out.append((k, str((proc / str(k) / "cwd").resolve())))
            except Exception: pass
    seen, cwds = set(), []
    for _k, c in sorted(out, reverse=True):
        if c not in seen: seen.add(c); cwds.append(c)
    return cwds

def git_summary(path):
    top = _q("git", "-C", path, "rev-parse", "--show-toplevel")
    if not top: return ""
    st = _q("git", "-C", top, "status", "--short", "--branch").splitlines()
    head = st[0].lstrip("# ") if st else "?"
    changed = st[1:]
    return f"{top} — branch {head}; " + (f"{len(changed)} changed: " + ", ".join(x.strip() for x in changed[:8]) + (" …" if len(changed) > 8 else "") if changed else "clean")

def gather_context(include_text=False):
    """Read-only snapshot of what the user is doing. Selection/clipboard only when asked (they may hold secrets)."""
    lines, clients = [], _hypr_json("clients")
    w = user_window(clients)
    ws = _hypr_json("activeworkspace") or {}
    if ws: lines.append(f"Workspace: {ws.get('id')} ({ws.get('windows', '?')} windows)")
    if w:
        lines.append(f"Focused app: {w.get('class')} — “{w.get('title', '')[:120]}” on workspace {w.get('workspace', {}).get('id')}"
                     + (" (floating)" if w.get("floating") else "") + (" (fullscreen)" if w.get("fullscreen") else ""))
        cwds = shell_cwds(w["pid"]) if w.get("pid") else []
        if cwds:
            lines.append("Terminal shells in: " + ", ".join(cwds[:4]))
            for g in dict.fromkeys(filter(None, (git_summary(c) for c in cwds[:4]))): lines.append(f"Git: {g}")
    else:
        lines.append("Focused app: none (or Hyprland not reachable)")
    others = [f"{c.get('class')} (ws {c.get('workspace', {}).get('id')})" for c in clients or [] if c is not w and c.get("class") not in SELF_CLASSES]
    if others: lines.append("Other windows: " + ", ".join(others[:12]))
    rec = recent_files()
    if rec: lines.append("Recent files: " + ", ".join(rec))
    n = _q("swaync-client", "-c")
    if n.isdigit(): lines.append(f"Notifications waiting: {n}")
    media = _q("playerctl", "metadata", "--format", "{{status}}: {{artist}} — {{title}} ({{playerName}})")
    lines.append(f"Now playing: {media}" if media else "Now playing: nothing")
    if include_text:
        for label, argv in (("Selected text", ("wl-paste", "-p", "-n")), ("Clipboard", ("wl-paste", "-n", "-t", "text"))):
            t = _q(*argv)
            lines.append(f"{label}: " + (t[:1500] + (" …(truncated)" if len(t) > 1500 else "") if t else "(empty)"))
    return "\n".join(lines)

def recent_files(n=8, xbel=HOME / ".local/share/recently-used.xbel"):
    """Files the user opened most recently (GTK's recently-used list), newest first, existing ones only."""
    import xml.etree.ElementTree as ET
    try: items = ET.parse(xbel).getroot().findall("bookmark")
    except Exception: return []
    items.sort(key=lambda b: b.get("modified") or b.get("visited") or "", reverse=True)
    out = []
    for b in items:
        path = urllib.parse.unquote(urllib.parse.urlparse(b.get("href", "")).path)
        if path and b.get("href", "").startswith("file://") and Path(path).exists() and path not in out: out.append(path)
        if len(out) >= n: break
    return out

WINDOW_ACTIONS = {"focus", "close", "fullscreen", "float", "move_to_workspace", "switch_workspace"}

def window_dispatch(action, target="", workspace=""):
    """hyprctl dispatch argv for a window action, or raise ValueError. target = app class or title text."""
    if action not in WINDOW_ACTIONS: raise ValueError(f"action must be one of {', '.join(sorted(WINDOW_ACTIONS))}")
    ws = str(workspace).strip()
    if action in ("move_to_workspace", "switch_workspace") and not re.fullmatch(r"\d{1,2}|[+-]1|empty", ws):
        raise ValueError("workspace must be a number, +1, -1 or empty")
    if action == "switch_workspace": return [["hyprctl", "dispatch", "workspace", ws]]
    sel = ""
    if target.strip():
        rx = re.escape(target.strip())
        clients = _hypr_json("clients") or []
        hit = next((c for c in clients if re.search(rx, c.get("class", ""), re.I)), None) or \
              next((c for c in clients if re.search(rx, c.get("title", ""), re.I)), None)
        if not hit: raise ValueError(f"no open window matches “{target}”")
        sel = f"address:{hit['address']}"
    else:
        w = user_window()
        if not w: raise ValueError("no window to act on")
        sel = f"address:{w['address']}"
    if action == "focus": return [["hyprctl", "dispatch", "focuswindow", sel]]
    if action == "close": return [["hyprctl", "dispatch", "closewindow", sel]]
    if action == "move_to_workspace": return [["hyprctl", "dispatch", "movetoworkspacesilent", f"{ws},{sel}"]]
    if action == "float": return [["hyprctl", "dispatch", "togglefloating", sel]]
    return [["hyprctl", "dispatch", "focuswindow", sel], ["hyprctl", "dispatch", "fullscreen", "0"]]

# ── memory: facts the user wants kept (SQLite + nomic embeddings), reviewable with /memory ──
MEMORY_DB = HOME / ".local/share/local-ai/memory.db"

def _mem(db_path=None):
    import sqlite3
    p = Path(db_path or MEMORY_DB); p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(p)
    db.execute("create table if not exists facts(id integer primary key, text text not null, project text not null default '', created real, emb text)")
    return db

def remember(text, project="", embed=None, db_path=None):
    text = " ".join(str(text).split())[:500]
    if not text: raise ValueError("nothing to remember")
    with _mem(db_path) as db:
        if db.execute("select id from facts where text = ? and project = ?", (text, project)).fetchone(): return "already remembered"
        try: emb = json.dumps((embed or fai.embed)([text])[0])
        except Exception: emb = None                                  # still saved; matched by recency only
        db.execute("insert into facts(text, project, created, emb) values(?,?,?,?)", (text, project, time.time(), emb))
    return f"remembered: {text}" + (f" (for {project})" if project else "")

def memories(db_path=None):
    with _mem(db_path) as db:
        return db.execute("select id, text, project, created from facts order by created desc").fetchall()

def forget(fid, db_path=None):
    with _mem(db_path) as db: return db.execute("delete from facts where id = ?", (int(fid),)).rowcount

def find_memory(query, db_path=None):
    """The saved fact that best matches some words (for 'forget that …'), or None."""
    words = set(re.findall(r"\w+", query.lower()))
    best = max(((len(words & set(re.findall(r"\w+", t.lower()))), i, t) for i, t, _p, _c in memories(db_path)), default=None)
    return (best[1], best[2]) if best and best[0] else None

def relevant_memories(query, projects=(), k=8, embed=None, db_path=None):
    """Facts for this turn: global ones plus those for the projects the user has open; by meaning when there are many."""
    with _mem(db_path) as db:
        rows = [r for r in db.execute("select text, project, emb from facts order by created desc") if not r[1] or r[1] in projects]
    if len(rows) <= k: return [t for t, _p, _e in rows]
    try:
        import numpy as np
        q = np.array((embed or fai.embed)([query], kind="query")[0], dtype=np.float32)
        scored = []
        for t, _p, e in rows:
            if not e: continue
            v = np.array(json.loads(e), dtype=np.float32)
            scored.append((float(v @ q / (np.linalg.norm(v) * np.linalg.norm(q) + 1e-9)), t))
        return [t for _s, t in sorted(scored, reverse=True)[:k]]
    except Exception:
        return [t for t, _p, _e in rows[:k]]

# ── action log: everything the assistant really did (shown with /log) ──
ACTION_LOG = HOME / ".local/state/myos/assistant-actions.jsonl"

def log_action(tool, args, out, path=None):
    p = Path(path or ACTION_LOG)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps({"t": time.time(), "tool": tool, "label": tool_activity(tool, args), "result": str(out)[:240]}) + "\n")
    except OSError: pass

def recent_actions(n=40, path=None):
    try: lines = Path(path or ACTION_LOG).read_text().splitlines()[-n:]
    except OSError: return []
    out = []
    for l in reversed(lines):
        try: out.append(json.loads(l))
        except ValueError: pass
    return out

# ── media (playerctl) ──
MEDIA_ACTIONS = {"play_pause": "play-pause", "play": "play", "pause": "pause", "next": "next", "previous": "previous",
                 "stop": "stop", "status": None}

MEDIA_ALIASES = {"skip": "next", "next_track": "next", "toggle": "play_pause", "playpause": "play_pause", "resume": "play",
                 "prev": "previous", "back": "previous", "previous_track": "previous", "now_playing": "status"}

def media(action, run=None):
    run = run or (lambda argv: run_capture(argv, timeout=10))
    if action not in MEDIA_ACTIONS: return f"action must be one of {', '.join(MEDIA_ACTIONS)}", False
    if MEDIA_ACTIONS[action]:
        code, out = run(["playerctl", MEDIA_ACTIONS[action]])
        if code != 0: return f"no media player responded ({out.strip() or 'nothing playing'})", False
        time.sleep(0.3)
    code, now = run(["playerctl", "metadata", "--format", "{{status}}: {{artist}} — {{title}} ({{playerName}})"])
    now = now.strip() if code == 0 and now.strip() else "no player"
    return (f"done: {action.replace('_', ' ')}; now: {now}" if MEDIA_ACTIONS[action] else f"now: {now}"), bool(MEDIA_ACTIONS[action])

# ── "what's this?": OCR of the window the user was using (the chat panel is cut out) ──
def capture_rect(win, panel=None):
    """(x, y, w, h) of the window minus a floating chat panel covering its left or right side."""
    x, y = win["at"]; w, h = win["size"]
    if panel and panel.get("workspace", {}).get("id") == win.get("workspace", {}).get("id"):
        px, py = panel["at"]; pw, ph = panel["size"]
        if py < y + h and py + ph > y:                                # overlaps vertically
            if x < px < x + w: w = px - x                             # panel covers the right part
            elif px <= x < px + pw: w, x = w - (px + pw - x), px + pw # panel covers the left part
    return x, y, max(w, 0), h

def read_screen():
    clients = _hypr_json("clients") or []
    w = user_window(clients)
    if not w: return "no window to read"
    panel = next((c for c in clients if c.get("class") in SELF_CLASSES and c.get("mapped", True)), None)
    x, y, cw, ch = capture_rect(w, panel)
    if cw < 20 or ch < 20: return "the window is hidden behind the chat panel"
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        img = f"{d}/w.png"
        if run_capture(["grim", "-g", f"{x},{y} {cw}x{ch}", "-s", "2", img], timeout=15)[0] != 0: return "screen capture failed"
        langs = "eng+mal" if "mal" in _q("tesseract", "--list-langs").split() else "eng"
        code, text = run_capture(["tesseract", img, "-", "-l", langs, "--psm", "3"], timeout=60)
    text = "\n".join(l.rstrip() for l in text.splitlines() if "Warning" not in l).strip()
    if code != 0 or not text: return f"no readable text in {w.get('class')}"
    return f"Text read from {w.get('class')} — “{w.get('title', '')[:80]}” (OCR, may contain errors):\n{text[:5000]}"

# ── routines: scheduled requests (systemd user timers) that run headless and notify ──
UNIT_DIR = HOME / ".config/systemd/user"
ROUTINES = HOME / ".config/local-ai/routines"

def routine_name(name):
    n = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:30]
    if not n: raise ValueError("routine needs a name")
    return n

def routine_units(name, when):
    """(service, timer) unit text; `when` is a systemd OnCalendar expression (validated by the caller)."""
    svc = (f"[Unit]\nDescription=Assistant routine: {name}\n\n[Service]\nType=oneshot\n"
           f"ExecStart=/usr/bin/python3 %h/.local/share/local-ai/chat.py --routine {name}\n")
    tmr = f"[Unit]\nDescription=Assistant routine: {name}\n\n[Timer]\nOnCalendar={when}\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"
    return svc, tmr

def check_calendar(when):
    if not when.strip() or "\n" in when: raise ValueError("empty schedule")
    code, out = run_capture(["systemd-analyze", "calendar", when], timeout=10)
    if code != 0: raise ValueError(f"not a valid schedule: {when} (use systemd form, e.g. 'Mon..Fri 09:00' or 'daily')")
    nxt = re.search(r"Next elapse:\s*(.+)", out)
    return nxt.group(1).strip() if nxt else "?"

def add_routine(name, when, prompt):
    name = routine_name(name); nxt = check_calendar(when)
    ROUTINES.mkdir(parents=True, exist_ok=True); UNIT_DIR.mkdir(parents=True, exist_ok=True)
    (ROUTINES / f"{name}.json").write_text(json.dumps({"name": name, "when": when, "prompt": prompt}))
    svc, tmr = routine_units(name, when)
    (UNIT_DIR / f"myos-routine-{name}.service").write_text(svc); (UNIT_DIR / f"myos-routine-{name}.timer").write_text(tmr)
    run_capture(["systemctl", "--user", "daemon-reload"], timeout=20)
    code, out = run_capture(["systemctl", "--user", "enable", "--now", f"myos-routine-{name}.timer"], timeout=20)
    if code != 0: return f"saved, but enabling the timer failed: {out.strip()}", False
    return f"routine “{name}” scheduled ({when}); next run: {nxt}", True

def list_routines():
    out = []
    for f in sorted(ROUTINES.glob("*.json")) if ROUTINES.exists() else []:
        try: out.append(json.loads(f.read_text()))
        except ValueError: pass
    return out

def remove_routine(name):
    name = routine_name(name)
    run_capture(["systemctl", "--user", "disable", "--now", f"myos-routine-{name}.timer"], timeout=20)
    for p in (UNIT_DIR / f"myos-routine-{name}.service", UNIT_DIR / f"myos-routine-{name}.timer", ROUTINES / f"{name}.json"):
        p.unlink(missing_ok=True)
    run_capture(["systemctl", "--user", "daemon-reload"], timeout=20)
    return f"removed routine {name}"

def notify(title, body=""):
    subprocess.run(["notify-send", "-a", "Assistant", "-i", "chat-message-new", title, body[:300]],
                   capture_output=True, timeout=5)

def run_routine(name):
    """Headless: run the saved request through the agent (approval-needing steps are declined), save it, notify."""
    r = json.loads((ROUTINES / f"{routine_name(name)}.json").read_text())
    history = [{"role": "user", "content": r["prompt"], "time": time.time()}]
    out, steps = "", []
    try:
        for kind, payload in agent_stream(history, confirm=None):
            if kind == "token": out += payload
            elif kind == "step": steps.append(payload)
    except Exception as e:
        out = f"The routine failed: {e}"
    store = Store(); chat = store.new(); chat["title"] = f"Routine · {r['name']}"
    chat["messages"] = history + [{"role": "assistant", "content": fai.clean(out).strip(), "time": time.time(), "steps": steps}]
    store.save(chat)
    notify(f"Routine: {r['name']}", fai.clean(out).strip() or "Done (no reply). Open the assistant to see the steps.")
    return 0

REMOTE_ACTIONS = ("status", "info", "logs", "network", "jobs", "job_log", "run", "start_job", "stop_job", "reboot",
                  "alerts_on", "alerts_off")
PHONE_ACTIONS = ("status", "send", "text", "clipboard", "find", "push")
AGENT_TOOLS = [
    {"type": "function", "function": {"name": "system_status", "description":
        "Live facts about THIS laptop: battery, power profile, temperatures, GPU, memory, disk, load, failed services, network, top processes. Call for any question about the machine's current state.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "run", "description":
        "Run ONE read-only diagnostic shell command (no pipes, no sudo, no changes) and return its output. Use for specifics like `nvidia-smi`, `df -h`, `systemctl --user status swaync`, `hyprctl monitors`, `ip a`.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "search_config", "description":
        "Search the user's own KadaOS/Hyprland setup documentation and config notes (shortcuts, how things are wired, decisions). Use for questions about THIS custom setup.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "search_files", "description":
        "Semantic search across the user's own files and projects. Use to find or answer from their documents, code or notes.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "desktop_action", "description":
        "Perform ONE safe, reversible desktop action for the user (take a screenshot, lock, toggle night light / do-not-disturb (silences notifications ONLY), keep the laptop awake on/off (stops dim/lock/sleep), change volume/brightness, set power mode, open the clipboard/calendar/wifi/bluetooth panel, open settings, toggle dictation, open file search). Only call when the user asks you to DO something.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": list(DESKTOP_ACTIONS)}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "open_app", "description":
        "Launch an application by name (e.g. 'firefox', 'code', 'files', 'blender'). Use when the user asks to open or start an app.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "search_web", "description":
        "Search the web and read top results for CURRENT or external information (news, versions, prices, how others solved something, docs). Returns dated sources. Use when the answer needs up-to-date or outside knowledge.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "calculate", "description":
        "Exact arithmetic. ALWAYS use this for any calculation (percentages, totals, conversions, dates math) instead of "
        "computing in your head. Example: '17% * 2340' or '(1200-350)/4'.",
        "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}},
    {"type": "function", "function": {"name": "file_action", "description":
        "Convert / resize / compress / merge files on disk (originals are kept; output is saved beside them). "
        "Give absolute paths (find them first with search_files or `run ls -t DIR` if unknown). Actions: " + _fa_help(),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": [a for a in (FA.catalogue() if FA else {}) if a != "copy_path"]},
            "paths": {"type": "array", "items": {"type": "string"}},
            "option": {"type": "string", "description": "one of the action's option values, if it has options"}},
            "required": ["action", "paths"]}}},
    {"type": "function", "function": {"name": "start_layout", "description":
        "Open a work layout on a fresh workspace: a profile (Coding, Web dev, Research, Security lab) or a plain "
        "request like 'two terminals and vscode' or 'chrome and files'.",
        "parameters": {"type": "object", "properties": {"request": {"type": "string"}}, "required": ["request"]}}},
    {"type": "function", "function": {"name": "security_recipe", "description":
        "Run a security-lab recipe against a target in the ACTIVE engagement's scope (seclab refuses anything out of "
        "scope; the user confirms first). Runs right here in the chat; the real output comes back and is saved to the engagement.",
        "parameters": {"type": "object", "properties": {"recipe": {"type": "string", "enum": RECIPES},
                                                         "target": {"type": "string"}}, "required": ["recipe", "target"]}}},
    {"type": "function", "function": {"name": "set_scope", "description":
        "Create/activate a security engagement and add targets to its scope (IP, CIDR, host or domain). The user must "
        "confirm they are authorized. Needed before security_recipe can scan anything.",
        "parameters": {"type": "object", "properties": {"engagement": {"type": "string", "description": "short name, e.g. home-network"},
                                                         "targets": {"type": "array", "items": {"type": "string"}}},
                       "required": ["engagement", "targets"]}}},
    {"type": "function", "function": {"name": "run_command", "description":
        "Do ANYTHING else on this computer with a bash command: windows/workspaces (hyprctl dispatch), media (playerctl), "
        "network (nmcli), Bluetooth (bluetoothctl), services (systemctl --user), settings (gsettings), packages, files, git… "
        "The user approves each command (or has always-allowed it) and you get its real output. For root tasks set "
        "admin=true (do NOT write sudo): the system password prompt appears. Prefer dedicated tools when one fits.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"},
                                                         "reason": {"type": "string", "description": "one short line: what this does"},
                                                         "admin": {"type": "boolean", "description": "needs root (apt, system files, system services)"}},
                       "required": ["command", "reason"]}}},
    {"type": "function", "function": {"name": "get_context", "description":
        "What the user is doing right now (read-only): the app/window they were last using and its title, the workspace, "
        "the folders and git status of shells in that terminal, other open windows, and what's playing. Call this for "
        "'this', 'here', 'what am I working on', or before acting on 'this window'. Set include_text=true ONLY when the "
        "user refers to selected/copied text (it reads the selection and clipboard).",
        "parameters": {"type": "object", "properties": {"include_text": {"type": "boolean"}}}}},
    {"type": "function", "function": {"name": "window", "description":
        "Control windows and workspaces: focus an app, close it, toggle fullscreen or floating, move it to a workspace "
        "(stays where you are), or switch workspace. target = app name/class or words from its title; empty = the "
        "window the user was last using. Closing asks the user first.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": sorted(WINDOW_ACTIONS)},
            "target": {"type": "string"}, "workspace": {"type": "string", "description": "number, +1, -1 or empty"}},
            "required": ["action"]}}},
    {"type": "function", "function": {"name": "read_screen", "description":
        "Read the text on the window the user was using (screenshot + OCR). Call for 'what's this?', 'read this', "
        "'explain this error on screen', or when get_context's title isn't enough.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "calendar", "description":
        "The user's upcoming calendar events (their Google/online calendars). Call for 'what's on today', 'am I free at 3', 'next meeting'.",
        "parameters": {"type": "object", "properties": {"days": {"type": "integer", "description": "how many days ahead, default 2"}}}}},
    {"type": "function", "function": {"name": "media", "description":
        "Control music/video players (Spotify, browser, mpv…): play_pause, play, pause, next, previous, stop, or status.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": list(MEDIA_ACTIONS)}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "remember", "description":
        "Save a durable fact about the user for future chats: a preference, a person, a routine, a project detail. Call "
        "when they say 'remember…', and when they state a lasting preference ('I prefer…', 'my … is …'). Not for "
        "one-off details. project = a folder path if it only applies to that project, else empty.",
        "parameters": {"type": "object", "properties": {"fact": {"type": "string", "description": "one short sentence in third person, e.g. 'The user prefers pnpm over npm.'"},
                                                         "project": {"type": "string"}}, "required": ["fact"]}}},
    {"type": "function", "function": {"name": "forget", "description":
        "Delete a saved fact ('forget that…'). Give words from the fact; the user confirms which one is deleted.",
        "parameters": {"type": "object", "properties": {"about": {"type": "string"}}, "required": ["about"]}}},
    {"type": "function", "function": {"name": "schedule_routine", "description":
        "Schedule a request to run automatically (systemd timer), e.g. every weekday at 9 open the coding layout. It runs "
        "without the chat open: steps that need approval are skipped; the result arrives as a notification and a saved chat. "
        "when = systemd OnCalendar form: 'Mon..Fri 09:00', 'daily', '*-*-* 18:30', 'Sun 10:00'.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "when": {"type": "string"},
                                                         "prompt": {"type": "string", "description": "the request to run, written as the user would ask it"}},
                       "required": ["name", "when", "prompt"]}}},
    {"type": "function", "function": {"name": "show_control", "description":
        "Show a LIVE interactive control inline in the chat so the user can adjust a setting themselves right here "
        "(a slider for brightness/volume, a switch for night light / do-not-disturb / Wi-Fi / Bluetooth, a selector "
        "for power mode). Call this whenever the user wants to change or set one of these, instead of only doing it blindly.",
        "parameters": {"type": "object", "properties": {"control": {"type": "string",
            "enum": ["brightness", "volume", "night_light", "do_not_disturb", "wifi", "bluetooth", "power_mode"]}},
            "required": ["control"]}}},
    {"type": "function", "function": {"name": "remote", "description":
        "The user's own remote devices (Raspberry Pis, servers, boards; managed by `board`). Read-only, no approval: "
        "status (every device: online, temp, disk, power problems), info (one device), logs (one device's recent "
        "warnings/errors; unit = a systemd service), network (who is on the local network), jobs (background jobs), "
        "job_log (output of one job). Asks the user first: run (a shell command on a device, or @tag for several), "
        "start_job (a long command that keeps running on the device; the user is notified when it ends), stop_job, "
        "reboot. alerts_on/alerts_off turn device notifications (offline, hot, low power, disk full) on or off.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": list(REMOTE_ACTIONS)},
            "device": {"type": "string", "description": "device name (status/network/jobs: leave empty); run also takes @tag"},
            "command": {"type": "string", "description": "for run / start_job"},
            "unit": {"type": "string", "description": "for logs: a service name, optional"},
            "job": {"type": "string", "description": "job ID for job_log / stop_job"}},
            "required": ["action"]}}},
    {"type": "function", "function": {"name": "phone", "description":
        "The user's Android phone (linked over Wi-Fi with KDE Connect, or a USB cable). status: connected?, battery, alerts. "
        "send: files (absolute paths) or links to the phone (asks the user first). text: a short text to the phone. "
        "clipboard: the laptop clipboard to the phone now. find: ring the phone (even on silent). "
        "push: an alert notification to the phone that works anywhere (ntfy).",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": list(PHONE_ACTIONS)},
            "items": {"type": "array", "items": {"type": "string"}, "description": "for send: absolute file paths or URLs"},
            "text": {"type": "string", "description": "for text / push"}},
            "required": ["action"]}}},
]
CONTROLS = ["brightness", "volume", "night_light", "do_not_disturb", "wifi", "bluetooth", "power_mode"]

def agent_system_prompt(sysinfo_text, web_used, web_error="", memory=()):
    import datetime
    p = ("You are the user's local assistant on their own Linux laptop — a private, capable helper that can both "
         "answer and ACT. The machine runs a custom keyboard-first Hyprland desktop the user calls KadaOS.\n"
         f"Today is {datetime.date.today():%A %d %B %Y}.\n\n"
         "Machine facts:\n" + sysinfo_text.strip() + "\n\n"
         "You have tools: system_status (live state), run (read-only diagnostics), search_config (the user's own "
         "KadaOS setup docs), search_files (their files), search_web (current/outside info), desktop_action and "
         "open_app (to actually do things), file_action (convert/resize/compress files), start_layout (app layouts), "
         "security_recipe (scoped scans), get_context (what the user is doing now), window (focus/move/close windows, "
         "switch workspaces), read_screen (OCR of the window), calendar (events), media (players), remember/forget (long-term memory), "
         "schedule_routine (recurring requests), remote (the user's Pis/servers/boards: status, logs, run, background jobs), phone (send files/links/text to their phone, ring it, push alerts) and run_command (anything else; the user approves each command).\n"
         "RULES:\n"
         "- For ANY question about keyboard shortcuts, keybindings, how this desktop/setup works, or where "
         "something is configured, you MUST call search_config FIRST and answer ONLY from what it returns. Never "
         "state a shortcut or config detail from your own training — this is a bespoke setup and your built-in "
         "knowledge of it is wrong. If search_config doesn't contain the answer, say you couldn't find it.\n"
         "- 'This', 'here', 'what I'm working on', 'this window/project': call get_context first; never guess the app or folder.\n"
         "- 'What's this?' / 'read this' / an error on screen: call read_screen.\n"
         "- When the user says 'remember…' or states a lasting preference or fact about themselves, call remember. "
         "Facts under 'What you know about the user' are ALREADY saved: use them, don't save them again or recite them unasked.\n"
         "- When you mention a file, folder or project, write its FULL absolute path (e.g. /home/user/Projects/app): "
         "the chat turns real paths, links and single shell commands into Open / VS Code / Terminal / Run buttons under your reply, "
         "so don't tell the user to cd or open things by hand.\n"
         "- For the machine's current state (battery, GPU, disk, services, network…), call system_status or run.\n"
         "- When the user asks you to DO something a tool covers (screenshot, open an app, change volume/brightness, "
         "night light, power mode, lock, open a panel), call the tool, then confirm briefly what you did.\n"
         "- Use search_web when the answer needs current or external information.\n"
         "- Only claim what a tool actually does. Do-not-disturb ONLY silences notifications; keeping the system "
         "awake is keep_awake_on. If no tool does what the user asked, say so plainly and suggest the closest real "
         "option. Never pretend an action happened or invent what it does.\n"
         "- Every tool call is shown to the user as a step with its REAL output. NEVER invent tool output, data, "
         "devices, IPs, MACs, file contents, numbers or success. Report only what tools returned in this conversation "
         "(earlier tool calls and their results are in the history); if you need data, call a tool. If a step failed or was declined, say so.\n"
         "- Settings the user wants to see or change (brightness, volume, night light, do-not-disturb, Wi-Fi, Bluetooth, "
         "power mode): call show_control once per setting so live controls appear in the chat, then report ONLY the real "
         "values those calls return. Don't send them to menus or keyboard shortcuts instead.\n"
         "- Truth only: never present a guess as fact. Don't explain WHY something is the way it is (e.g. 'because you're "
         "on battery') unless a tool result showed it; if you don't know, say you don't know.\n"
         "- Act, don't announce: never end a reply with 'I'll now…' / 'Let's begin' — call the tool in the same turn.\n"
         "- Work inside the chat: never tell the user to open a terminal or another app to finish; use tools, chain "
         "several if needed, then summarize the real results (tables are good for lists).\n"
         "- 'My network' / 'the Wi-Fi I'm on': first get the real subnet with run `ip -o -4 addr show`. Scans need the "
         "target in an engagement scope: if it isn't, call set_scope (the user authorizes), then security_recipe. "
         "lan-discover lists devices (with MACs); nmap-vuln checks for known vulnerabilities.\n"
         "- If the user wants something done and no dedicated tool covers it, use run_command with a correct, minimal "
         "bash command — don't just explain how. For root tasks use run_command with admin=true.\n"
         "Answer in clear Markdown — short paragraphs, bullet lists, tables when comparing, and fenced code blocks. "
         "Be concise and concrete. You are not a generic cloud model; you know and act on THIS machine.")
    if memory:
        p += "\n\nWhat you know about the user (their saved memory):\n" + "\n".join(f"- {m}" for m in memory)
    if web_used:
        p += "\n\nWeb results are in <web>; use them for current facts and cite like [1]."
    elif web_error:
        p += f"\n\nWeb search was unavailable ({web_error}); say so if the answer needs current info."
    return p

def agent_messages(history, web_ctx="", web_error=""):
    sys_text = ""
    try: sys_text = fai.sysinfo()
    except Exception: pass
    msgs, size = [], 0
    for m in reversed(history):
        body = (strip_tool_echo(m["content"]) if m["role"] == "assistant" else m["content"]) + (f"\n\n<attached>\n{m['context']}\n</attached>" if m.get("context") else "")
        turn = [{"role": m["role"], "content": body}]
        if m.get("steps"):   # replay what really happened as native tool calls/results (the model won't echo these)
            calls = [{"function": {"name": st["tool"], "arguments": st.get("args") or {}}} for st in m["steps"]]
            res = [{"role": "tool", "content": st["out"][:1500], "tool_name": st["tool"]} for st in m["steps"]]
            turn = [{"role": "assistant", "content": "", "tool_calls": calls}] + res + turn
        n = sum(len(t["content"]) for t in turn)
        if msgs and size + n > MAX_HISTORY_CHARS: break
        msgs[0:0] = turn; size += n
    if web_ctx and msgs: msgs[-1]["content"] = f"<web>\n{web_ctx}\n</web>\n\n" + msgs[-1]["content"]
    mem = []
    try:
        q = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
        w = user_window(); projects = tuple(filter(None, (_q("git", "-C", c, "rev-parse", "--show-toplevel") for c in (shell_cwds(w["pid"])[:4] if w and w.get("pid") else []))))
        mem = relevant_memories(q, projects)
    except Exception: pass
    return [{"role": "system", "content": agent_system_prompt(sys_text, bool(web_ctx), web_error, mem)}] + msgs

def _tool_args(call):
    args = call.get("function", {}).get("arguments") or {}
    if isinstance(args, str):
        try: args = json.loads(args)
        except Exception: args = {}
    return args if isinstance(args, dict) else {}

def tool_activity(name, args):
    if name == "system_status": return "checking system status"
    if name == "run": return f"running: {args.get('command', '')[:50]}"
    if name == "search_config": return f"searching your setup: {args.get('query', '')[:40]}"
    if name == "search_files": return f"searching your files: {args.get('query', '')[:40]}"
    if name == "desktop_action": return f"doing: {args.get('action', '').replace('_', ' ')}"
    if name == "open_app": return f"opening {args.get('name', '')}"
    if name == "calculate": return f"calculating {args.get('expression', '')[:40]}"
    if name == "file_action": return f"working on {len(args.get('paths') or [])} file(s): {args.get('action', '').replace('_', ' ')}"
    if name == "start_layout": return f"opening layout: {args.get('request', '')[:40]}"
    if name == "security_recipe": return f"{args.get('recipe', '')} on {args.get('target', '')}"
    if name == "set_scope": return f"scope {args.get('engagement', '')}: {', '.join(args.get('targets') or [])}"
    if name == "run_command": return f"$ {args.get('command', '')[:60]}"
    if name == "get_context": return "looking at what you're doing"
    if name == "read_screen": return "reading the screen"
    if name == "media": return f"media: {args.get('action', '').replace('_', ' ')}"
    if name == "calendar": return f"checking your calendar ({args.get('days') or 2} days)"
    if name == "remember": return f"remembering: {args.get('fact', '')[:50]}"
    if name == "forget": return f"forgetting: {args.get('about', '')[:50]}"
    if name == "schedule_routine": return f"scheduling “{args.get('name', '')}” ({args.get('when', '')})"
    if name == "phone": return f"phone: {args.get('action', '')}"
    if name == "remote": return f"remote: {args.get('action', '').replace('_', ' ')} {args.get('device') or args.get('job') or ''}".strip()
    if name == "window": return f"window: {args.get('action', '').replace('_', ' ')} {args.get('target', '') or args.get('workspace', '')}".strip()
    return name

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

def run_capture(argv, cancel=None, progress=None, timeout=1800):
    """Run argv, return (exit code, output). Stop kills the whole process group; progress gets the latest line."""
    import os, signal
    out, t0 = [], time.time()
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                          cwd=str(HOME), start_new_session=True, stdin=subprocess.DEVNULL) as p:
        def pump():
            for line in p.stdout:
                line = ANSI.sub("", line); out.append(line)
                if progress and line.strip(): progress(line.strip()[:70])
        th = threading.Thread(target=pump, daemon=True); th.start()
        while p.poll() is None:
            if (cancel is not None and cancel.is_set()) or time.time() - t0 > timeout:
                os.killpg(p.pid, signal.SIGTERM); p.wait(); th.join(1)
                return -1, "".join(out)[-6000:] + "\n(stopped)"
            time.sleep(0.2)
        th.join(2)
    return p.returncode, "".join(out)[-6000:]

REMOTE_CONFIRM = {"run": "Run on {device}?", "start_job": "Start a background job on {device}?", "stop_job": "Stop job {job}?",
                  "reboot": "Reboot {device}?"}
_DEV_RE = re.compile(r"^@?[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")
_JOB_RE = re.compile(r"^[0-9a-f-]{4,20}$")

def remote_argv(action, device="", command="", unit="", job="", board=None):
    """The `board` command for a remote action (raises ValueError on bad input)."""
    b = board or str(HOME / ".local/bin/board")
    if action not in REMOTE_ACTIONS: raise ValueError(f"action must be one of {', '.join(REMOTE_ACTIONS)}")
    needs_dev = action in ("info", "logs", "run", "start_job", "reboot", "alerts_on", "alerts_off")
    if needs_dev and not _DEV_RE.match(device or ""): raise ValueError("give a device name (see action=status)")
    if device.startswith("@") and action != "run": raise ValueError("@tag only works with run")
    if action in ("run", "start_job") and not command.strip(): raise ValueError("no command")
    if action in ("job_log", "stop_job") and not _JOB_RE.match(job or ""): raise ValueError("give a job ID (see action=jobs)")
    if unit and not re.match(r"^[A-Za-z0-9@._:-]{1,100}$", unit): raise ValueError("bad unit name")
    return {"status": [b, "json", "status"], "info": [b, "info", device, "--json"],
            "logs": [b, "run", device, "--here", "--", "journalctl -b -n 80 -p warning --no-pager -o short-iso"
                     + (f" -u {shlex.quote(unit)}" if unit else "") + " 2>/dev/null || tail -n 80 /var/log/syslog"],
            "network": [b, "net", "--fast", "--json"], "jobs": [b, "job", "ls", "--json"],
            "job_log": [b, "job", "log", job, "-n", "60"], "run": [b, "run", device, "--", command],
            "start_job": [b, "job", device, "--", command], "stop_job": [b, "job", "kill", job],
            "reboot": [b, "reboot", device, "-y"], "alerts_on": [b, "watch", "on", device],
            "alerts_off": [b, "watch", "off", device]}[action]

def remote_summary(action, out):
    """Shorten board's JSON so the model gets facts, not noise. Falls back to the raw text."""
    try: data = json.loads(out)
    except ValueError: return out.strip() or "(no output)"
    if action == "status":
        rows = []
        for n, f in sorted(data.items()):
            bits = [f.get("state", "?")]
            if f.get("via"): bits.append(f"via {f['via']}")
            if f.get("temp_c"): bits.append(f"{f['temp_c']:.0f}°C")
            if f.get("disk_total_kb"): bits.append(f"disk {100 - 100 * (f.get('disk_free_kb') or 0) / f['disk_total_kb']:.0f}% used")
            if f.get("load") is not None: bits.append(f"load {f['load']}")
            if f.get("throttled"): bits.append("power: " + ", ".join(f["throttled"]))
            if f.get("state") != "online" and f.get("seen"): bits.append(f"last seen {time.strftime('%d %b %H:%M', time.localtime(f['seen']))}")
            rows.append(f"{n}: " + " · ".join(bits))
        return "\n".join(rows) or "0 devices registered (the user adds them with Super+R or `board add`)"
    if action == "network":
        return "\n".join(f"{h['ip']} {h.get('name') or ''} {h.get('vendor') or ''} {h.get('mac') or ''}"
                         + (f" [{h['role']}]" if h.get("role") else "") + (f" [their device {h['known']}]" if h.get("known") else "")
                         + (" [NEW]" if h.get("new") else "") for h in data) or "0 devices found on the network"
    if action == "jobs":
        return "\n".join(f"{k}: {j.get('state')}" + (f" exit {j['rc']}" if j.get("rc") is not None else "") + f" on {j['device']}: {j['cmd'][:80]}"
                         for k, j in data.items()) or "0 background jobs"
    return json.dumps(data)[:4000]

def phone_argv(action, items=(), text="", phone=None):
    """The `phone` command for an assistant action (raises ValueError on bad input)."""
    b = phone or str(HOME / ".local/bin/phone")
    if action not in PHONE_ACTIONS: raise ValueError(f"action must be one of {', '.join(PHONE_ACTIONS)}")
    if action == "send":
        items = [str(i).strip() for i in items or [] if str(i).strip()]
        if not items: raise ValueError("give absolute file paths or URLs in items")
        missing = [i for i in items if "://" not in i and not Path(i).expanduser().exists()]
        if missing: raise ValueError(f"file not found: {', '.join(missing)}")
        return [b, "send", *items]
    if action in ("text", "push") and not (text or "").strip(): raise ValueError("no text")
    return {"status": [b, "status"], "text": [b, "send", "-t", text.strip()], "clipboard": [b, "clip"],
            "find": [b, "find"], "push": [b, "push", text.strip()[:500]]}[action]

def run_agent_tool(name, args, run=None, confirm=None, cancel=None, progress=None):
    """Execute a tool, return (result_text, did_action). `run` is an injectable runner (for tests);
    `confirm(title, detail, note) -> bool` asks the user (None = no UI: anything needing approval is declined)."""
    import subprocess
    run = run or (lambda cmd: subprocess.Popen(["setsid", "sh", "-c", cmd], start_new_session=True,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    if name == "system_status":
        return fai.system_status(), False
    if name == "run":
        out = fai.run_readonly(args.get("command", ""))
        if out.startswith("REFUSED"):
            out += ". `run` is read-only diagnostics only: use run_command (the user approves it) for anything else, or security_recipe for scans."
        return out, False
    if name == "search_config":
        return fai.search_setup_docs(args.get("query", "")), False
    if name == "search_files":
        try:
            res = fai.search(args.get("query", ""), 5)
            return ("\n\n".join(f"{p}\n{t[:600]}" for _, p, t in res) or "no matching files"), False
        except Exception as e:
            return f"file search unavailable: {e}", False
    if name == "desktop_action":
        act = args.get("action", "")
        if act not in DESKTOP_ACTIONS:
            return f"unknown action: {act}", False
        run(DESKTOP_ACTIONS[act])
        return f"done: {act.replace('_', ' ')}", True
    if name == "open_app":
        app = args.get("name", "").strip()
        if not app:
            return "no app name", False
        # match a .desktop app or fall back to the bare command
        run(f"gtk-launch {shlex.quote(app)} 2>/dev/null || {shlex.quote(app)}")
        return f"opening {app}", True
    if name == "search_web":
        ok, _started, msg = ensure_searx()
        if not ok:
            return f"web search unavailable: {msg}", False
        try:
            ctx, srcs = web_context(args.get("query", ""))
            return (ctx or "no web results"), False
        except Exception as e:
            return f"web search failed: {e}", False
    if name == "calculate":
        try: return f"{args.get('expression', '')} = {calculate(args.get('expression', ''))}", False
        except Exception as e: return f"could not calculate: {e}", False
    if name == "file_action":
        if not FA: return "file actions are not installed", False
        aid = args.get("action", ""); paths = [str(Path(p).expanduser()) for p in args.get("paths") or []]
        missing = [p for p in paths if not Path(p).exists()]
        if not paths or missing: return f"file not found: {', '.join(missing) or '(no paths)'}", False
        applicable = dict(FA.actions_for(paths))
        if aid not in applicable: return f"{aid} does not apply to these files; options: {', '.join(applicable)}", False
        opts = FA.catalogue()[aid][2]; value = None
        if opts:
            vals = [v for _, v in opts]; value = args.get("option") or vals[0]
            if value not in vals: return f"option must be one of: {', '.join(vals)}", False
        outs, errs = FA.run_action(aid, value, paths)
        return (f"created: {', '.join(outs)}" if outs else "nothing created") + (f"; errors: {'; '.join(errs)}" if errs else ""), bool(outs)
    if name == "start_layout":
        req = args.get("request", "").strip()
        if not req: return "no layout request", False
        run(f"{_S}/flow.py --ai -- {shlex.quote(req)}")
        return f"opening layout: {req}", True
    if name == "security_recipe":
        rec, tgt = args.get("recipe", ""), args.get("target", "").strip()
        if rec not in RECIPES or not tgt: return f"recipe must be one of {', '.join(RECIPES)} with a target", False
        if SECLAB and SECLAB.active() and not SECLAB.in_scope(tgt, SECLAB.scope(SECLAB.active())):
            return f"{tgt} is not in the active engagement's scope; the user must add it (only if authorized)", False
        if not (confirm and confirm("Run security recipe?", f"seclab run {rec} {tgt}", "Scoped to the active engagement; output is saved.")):
            return "the user declined", False
        code, out = run_capture([str(HOME / ".local/bin/seclab"), "run", rec, tgt], cancel, progress)
        if rec == "lan-discover" and code == 0:
            out += "\n\nMAC addresses (ip neigh):\n" + run_capture(["ip", "-4", "neigh", "show"])[1]
        return f"exit {code}\n{out}", code == 0
    if name == "set_scope":
        if not SECLAB: return "security lab is not installed", False
        eng_name, targets = args.get("engagement", "").strip() or "engagement", [t.strip() for t in args.get("targets") or [] if t.strip()]
        if not targets: return "no targets given", False
        if not (confirm and confirm("Authorize these targets?", "\n".join(targets),
                                    f"Engagement “{eng_name}”. Only approve networks and hosts you own or have written permission to test.")):
            return "the user did not authorize these targets", False
        eng = SECLAB.new_engagement(eng_name); have = SECLAB.scope(eng)
        with open(eng / "scope.txt", "a") as f: f.write("".join(t + "\n" for t in targets if t not in have))
        return f"active engagement {eng.name}; scope: {', '.join(SECLAB.scope(eng))}", True
    if name == "run_command":
        cmd, admin = args.get("command", "").strip(), bool(args.get("admin"))
        if not cmd: return "no command", False
        if re.match(r"^\s*sudo\s+(-\S+\s+)*", cmd):   # the model wrote sudo: treat as an admin request
            cmd, admin = re.sub(r"^\s*sudo\s+(-\S+\s+)*", "", cmd), True
        if re.search(r"(^|[;&|\s])(sudo|su)\s", cmd + " "):
            return "don't embed sudo/su; send the command alone with admin=true", False
        key = None if admin else allow_key(cmd)
        if not (key and key in allowed()):
            ans = confirm and confirm("Run as administrator?" if admin else "Run this command?", cmd,
                                      (args.get("reason", "") + ("  ·  The system password prompt will follow." if admin else "")).strip(" ·"),
                                      key)
            if not ans: return "the user declined to run it", False
            if ans == "always" and key: remember_allow(key)
        cmd = "set -o pipefail; " + cmd       # a failing command piped into tail/head must still count as failed
        argv = ["pkexec", "bash", "-c", cmd] if admin else ["bash", "-lc", cmd]
        code, out = run_capture(argv, cancel, progress, timeout=900)
        if admin and code in (126, 127) and not out.strip(): return "the password prompt was cancelled", False
        return f"exit {code}\n{out.strip() or '(no output)'}", code == 0
    if name == "read_screen":
        return read_screen(), False
    if name == "media":
        act = str(args.get("action", "")).lower().replace("-", "_").replace(" ", "_")
        return media(MEDIA_ALIASES.get(act, act))
    if name == "calendar":
        if not WATCH: return "calendar unavailable", False
        try: days = max(1, min(int(args.get("days") or 2), 31))
        except (TypeError, ValueError): days = 2
        evs = WATCH.events(days)
        return ("\n".join(time.strftime("%a %d %b ", time.localtime(t)) + ("all day" if a else time.strftime("%H:%M", time.localtime(t)))
                          + f" — {s_} ({c})" for t, s_, c, a in evs) or f"no events in the next {days} day(s)"), False
    if name == "remember":
        fact = args.get("fact") or args.get("about") or args.get("text") or next((v for v in args.values() if isinstance(v, str)), "")
        try: r = remember(fact, (args.get("project") or "").strip()); return r, r.startswith("remembered")
        except ValueError as e: return str(e), False
    if name == "forget":
        hit = find_memory(args.get("about") or args.get("fact") or next((v for v in args.values() if isinstance(v, str)), ""))
        if not hit: return "no saved fact matches that", False
        if not (confirm and confirm("Forget this?", hit[1], "It is deleted from the assistant's memory.")): return "the user kept it", False
        forget(hit[0]); return f"forgot: {hit[1]}", True
    if name == "schedule_routine":
        r = args
        if not (confirm and confirm("Schedule this routine?", f"{r.get('when', '')}: {r.get('prompt', '')}",
                                    "Runs on its own; steps that need approval are skipped. Remove it with /routines.")):
            return "the user declined", False
        try: return add_routine(r.get("name", ""), r.get("when", ""), r.get("prompt", "").strip() or "hello")
        except ValueError as e: return str(e), False
    if name == "get_context":
        return gather_context(bool(args.get("include_text"))), False
    if name == "window":
        act = args.get("action", "")
        try: cmds = window_dispatch(act, args.get("target", "") or "", args.get("workspace", "") or "")
        except ValueError as e: return str(e), False
        if act == "close" and not (confirm and confirm("Close this window?", " ".join(cmds[0][2:]), "Unsaved work in it may be lost.")):
            return "the user declined", False
        outs = [run_capture(c, timeout=10) for c in cmds]
        bad = [o.strip() for code, o in outs if code != 0 or o.strip() not in ("ok", "")]
        return (f"failed: {'; '.join(bad)}", False) if bad else (f"done: {act.replace('_', ' ')}", True)
    if name == "remote":
        act = args.get("action", ""); dev = (args.get("device") or "").strip(); cmd = args.get("command") or ""
        job = (args.get("job") or "").strip()
        try: argv = remote_argv(act, dev, cmd, (args.get("unit") or "").strip(), job)
        except ValueError as e: return str(e), False
        if not Path(argv[0]).exists(): return "remote devices aren't set up (bash scripts/install-remote.sh)", False
        if act in REMOTE_CONFIRM and not (confirm and confirm(REMOTE_CONFIRM[act].format(device=dev, job=job),
                                                              cmd or f"board {' '.join(argv[1:])}", "Runs on the device over SSH.")):
            return "the user declined", False
        code, out = run_capture(argv, cancel, progress, timeout=120 if act in ("status", "network") else 900)
        if code and act in ("status", "info", "jobs", "network"): return f"exit {code}\n{out.strip()}", False
        return (remote_summary(act, out) if code == 0 else f"exit {code}\n{out.strip() or '(no output)'}"), code == 0 and (act in REMOTE_CONFIRM or act.startswith("alerts"))
    if name == "phone":
        act = args.get("action", "")
        try: argv = phone_argv(act, args.get("items") or [], args.get("text") or "")
        except ValueError as e: return str(e), False
        if not Path(argv[0]).exists(): return "the phone link isn't set up (bash scripts/install-phone.sh, then phone setup)", False
        if act == "send" and not (confirm and confirm("Send to your phone?", "\n".join(argv[2:]), "Over Wi-Fi (KDE Connect) or the USB cable.")):
            return "the user declined", False
        code, out = run_capture(argv, cancel, progress, timeout=900)
        return (out.strip() or "(no output)") if code == 0 else f"exit {code}\n{out.strip()}", code == 0 and act != "status"
    if name == "show_control":
        ctl = args.get("control", "")
        if ctl not in CONTROLS:
            return f"unknown control: {ctl}", False
        st = control_state(ctl)
        now = ("unknown" if st is None else f"{st}%" if isinstance(st, int) and not isinstance(st, bool)
               else ("on" if st else "off") if isinstance(st, bool) else str(st))
        what = {"brightness": "a 1–100% slider", "volume": "a 0–100% slider", "night_light": "an on/off switch (no temperature setting)",
                "do_not_disturb": "an on/off switch", "wifi": "an on/off switch", "bluetooth": "an on/off switch",
                "power_mode": "a Saver / Balanced / Performance selector"}[ctl]
        return (f"Shown in the chat: {CONTROL_LABELS[ctl]} control ({what}). Current real value: {now}. "
                "State exactly this value; do not invent other values or options."), False
    return "unknown tool", False

CONTROL_LABELS = {"brightness": "Brightness", "volume": "Volume", "night_light": "Night light",
                  "do_not_disturb": "Do not disturb", "wifi": "Wi-Fi", "bluetooth": "Bluetooth", "power_mode": "Power mode"}

def _run_out(cmd):
    import subprocess
    try: return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception: return ""

def control_state(ctl):
    """Current value: int 0-100 (brightness/volume), bool (toggles), or str (power_mode). None if unknown."""
    try:
        if ctl == "brightness":
            parts = _run_out("brightnessctl -m").split(",")
            return int(parts[3].rstrip("%")) if len(parts) > 3 else None
        if ctl == "volume":
            m = re.search(r"([\d.]+)", _run_out("wpctl get-volume @DEFAULT_AUDIO_SINK@"))
            return int(float(m.group(1)) * 100) if m else None
        if ctl == "night_light": return bool(_run_out("pgrep -x wlsunset"))
        if ctl == "do_not_disturb": return _run_out("swaync-client -D") == "true"
        if ctl == "wifi": return _run_out("nmcli radio wifi") == "enabled"
        if ctl == "bluetooth": return "yes" in _run_out("bluetoothctl show 2>/dev/null | grep -i powered").lower()
        if ctl == "power_mode": return _run_out("powerprofilesctl get") or "balanced"
    except Exception:
        return None

def control_apply(ctl, value):
    """Apply a new value. Returns the shell command used (for testability)."""
    import subprocess
    cmd = None
    if ctl == "brightness": cmd = f"brightnessctl set {int(value)}%"
    elif ctl == "volume": cmd = f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {int(value)}%"
    elif ctl == "wifi": cmd = f"nmcli radio wifi {'on' if value else 'off'}"
    elif ctl == "bluetooth": cmd = f"bluetoothctl power {'on' if value else 'off'}"
    elif ctl == "power_mode": cmd = f"powerprofilesctl set {shlex.quote(str(value))}"
    elif ctl == "night_light":
        if bool(value) != bool(control_state("night_light")): cmd = "~/.config/hypr/scripts/nightlight.sh"
    elif ctl == "do_not_disturb":
        cmd = f"swaync-client -d {'true' if value else 'false'}"
    if cmd:
        subprocess.Popen(["sh", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return cmd

CONTROL_WORDS = {
    "brightness": r"\bbright|\bdim(mer)?\b|backlight|screen (light|level)",
    "volume": r"\bvolume\b|\bsound\b|louder|quieter|\bmute\b|\baudio level",
    "night_light": r"night ?light|blue ?light|warm(er)? (screen|colou?rs?)",
    "do_not_disturb": r"do not disturb|\bdnd\b|silence (my )?notifications",
    "wifi": r"\bwi-?fi\b|wireless network",
    "bluetooth": r"\bbluetooth\b",
    "power_mode": r"power (mode|profile|saver)|performance mode|battery saver|balanced mode",
}

def detect_controls(text):
    """Settings the user mentions → live controls shown right away (deterministic; the model doesn't have to choose)."""
    t = text.lower()
    found = [c for c, pat in CONTROL_WORDS.items() if re.search(pat, t)]
    if re.search(r"display settings|screen settings", t):
        found += [c for c in ("brightness", "night_light") if c not in found]
    return found

def step_status(out):
    o = out.lower()
    if "declined" in o or "did not authorize" in o: return "declined"
    if o.startswith(("tool error", "refused", "unknown", "needs admin", "file not found", "no ")) or "not in the" in o \
            or re.match(r"exit (-?[1-9])", o) or "failed" in o[:60]: return "failed"
    return "done"

def agent_stream(history, web_ctx="", web_error="", cancel=None, on_activity=None, runner=None, max_steps=8, confirm=None):
    """Agentic generator: yields answer tokens; runs tools between model turns. Keeps full history."""
    msgs = agent_messages(history, web_ctx, web_error); seen = set()
    shown = detect_controls(history[-1]["content"]) if history and history[-1]["role"] == "user" else []
    if shown:
        for ctl in shown: yield ("control", ctl)
        live = "; ".join(run_agent_tool("show_control", {"control": c})[0] for c in shown)
        msgs[-1] = dict(msgs[-1], content=msgs[-1]["content"] + "\n\n<live_controls>These controls are ALREADY shown under your reply: "
                        + live + " Confirm the real values in one or two short sentences; don't call tools for them, and don't guess reasons.</live_controls>")
    fai.ensure_server()
    for step in range(max_steps + 1):
        body = {"model": fai.CFG["model"], "messages": msgs, "stream": True, "think": False,
                "keep_alive": fai.CFG["keep_alive"],
                "options": {"temperature": 0.3, "num_ctx": 12288, "num_predict": 1500, "repeat_penalty": 1.1}}
        if step < max_steps:
            body["tools"] = AGENT_TOOLS
        content, calls = "", []
        with fai._req("/api/chat", body, timeout=180) as resp:
            for line in resp:
                if cancel is not None and cancel.is_set(): return
                if not line.strip(): continue
                j = json.loads(line)
                if "error" in j: raise RuntimeError(f"model error: {j['error']}")
                m = j.get("message", {})
                if m.get("tool_calls"): calls += m["tool_calls"]
                t = m.get("content", "")
                if t and not calls:
                    content += t; yield ("token", t)
                if j.get("done"): break
        if not calls:
            return
        msgs.append({"role": "assistant", "content": content, "tool_calls": calls})
        for c in calls:
            name = c.get("function", {}).get("name", ""); args = _tool_args(c)
            key = (name, json.dumps(args, sort_keys=True))
            if key in seen:   # small models loop on a refused call: push them to change approach
                msgs.append({"role": "tool", "content": "You already made this exact call and saw its result. Do something different.", "tool_name": name})
                continue
            seen.add(key)
            if on_activity: on_activity(tool_activity(name, args))
            yield ("tool", tool_activity(name, args))
            if name == "show_control" and args.get("control") in CONTROLS:
                yield ("control", args["control"])
            try:
                prog = (lambda line, a=tool_activity(name, args): on_activity(f"{a} · {line}")) if on_activity else None
                out, _did = run_agent_tool(name, args, run=runner, confirm=confirm, cancel=cancel, progress=prog)
                if _did and runner is None: log_action(name, args, out)
            except Exception as e:
                out = f"tool error: {e}"
            yield ("step", {"tool": name, "args": args, "label": tool_activity(name, args), "status": step_status(str(out)), "out": str(out)[:8000]})
            msgs.append({"role": "tool", "content": str(out), "tool_name": name})

def md_to_markup(text):
    """Small, safe Markdown -> Pango subset for one non-code block."""
    out = []
    for line in html.escape(text, quote=False).split("\n"):
        h = re.match(r"(#{1,4})\s+(.*)", line)
        if h: line = f"<span size='{['x-large', 'large', 'medium', 'medium'][len(h[1]) - 1]}' weight='bold'>{h[2]}</span>"
        line = re.sub(r"^(\s*)[-*]\s+", lambda m: m[1] + "  •  ", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", line)
        line = re.sub(r"`([^`]+)`", r"<tt>\1</tt>", line)
        line = re.sub(r"\[(\d{1,2})\]", r"<span size='small' rise='3000' foreground='#86b6ff'>[\1]</span>", line)  # citations
        line = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<a href="{m[2]}">{m[1]}</a>', line)
        out.append(line)
    return "\n".join(out)

def parse_table(lines):
    """A Markdown table (header row, |---| separator, body rows) -> [[header...], [row...], ...] or None."""
    rows = [l for l in lines if l.strip()]
    if len(rows) < 2 or "|" not in rows[0] or not re.match(r"^\s*\|?[\s:|-]+\|?\s*$", rows[1]) or "-" not in rows[1]:
        return None
    def cells(line): return [c.strip() for c in line.strip().strip("|").split("|")]
    out = [cells(rows[0])] + [cells(r) for r in rows[2:]]
    return out if len(out) >= 1 else None

def split_text_and_tables(text):
    """Split a text block into ('text', str) and ('table', rows) segments."""
    out, buf, i, lines = [], [], 0, text.split("\n")
    while i < len(lines):
        # a table starts where a '|' line is followed by a separator line
        if "|" in lines[i] and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]) and "-" in lines[i + 1]:
            j = i
            while j < len(lines) and "|" in lines[j]:
                j += 1
            tbl = parse_table(lines[i:j])
            if tbl:
                if buf: out.append(("text", "\n".join(buf).strip("\n"))); buf = []
                out.append(("table", tbl)); i = j; continue
        buf.append(lines[i]); i += 1
    if buf: out.append(("text", "\n".join(buf).strip("\n")))
    return out

def split_blocks(text):
    """[(kind, body)]: 'text', 'code:<lang>', or 'table' (body is parsed rows). Unclosed fences count as code."""
    blocks, pos = [], 0
    for m in re.finditer(r"```([\w+-]*)\n(.*?)(?:```|\Z)", text, re.S):
        if m.start() > pos: blocks += split_text_and_tables(text[pos:m.start()].strip("\n"))
        blocks.append(("code:" + m[1], m[2].rstrip("\n"))); pos = m.end()
    if pos < len(text): blocks += split_text_and_tables(text[pos:].strip("\n"))
    return [b for b in blocks if (b[0] == "table" and b[1]) or (isinstance(b[1], str) and b[1].strip())]

def strip_tool_echo(text):
    """Older replies sometimes echoed raw <tool_results> blocks; never show or replay them."""
    return re.sub(r"<tool_results>.*?(</tool_results>|$)", "", text, flags=re.S).strip()

TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".sh", ".css", ".html", ".yml", ".yaml", ".toml",
            ".conf", ".ini", ".rs", ".go", ".c", ".h", ".cpp", ".java", ".php", ".sql", ".env.example", ".log", ".csv", ".xml"}

def suggest_actions(text, have=None):
    """Buttons for what an answer mentions: real folders/projects, files, links and shell commands.
    [(label, icon, kind, value)]: kind is folder | vscode | terminal | open | reveal | link | run."""
    import shutil
    have = have or shutil.which
    out, seen = [], set()
    def add(*a):
        if (a[2], a[3]) not in seen: seen.add((a[2], a[3])); out.append(a)
    body = re.sub(r"```.*?(```|$)", " ", text, flags=re.S)                      # paths in prose (code handled below)
    for raw in re.findall(r"(?<![\w/.])(~/[^\s`*'\"<>|()\[\]]*|/(?:home|etc|opt|srv|usr|var|tmp|mnt|media)/[^\s`*'\"<>|()\[\]]*)", body):
        path = Path(raw.rstrip(".,:;!?")).expanduser()
        if len(seen) >= 12 or not path.exists(): continue
        if path.is_dir():
            git = (path / ".git").exists()
            add(f"Open {path.name or path}" if git else "Open folder", "folder-symbolic", "folder", str(path))
            if have("code"): add("VS Code", "text-editor-symbolic", "vscode", str(path))
            add("Terminal here", "utilities-terminal-symbolic", "terminal", str(path))
        else:
            add(f"Open {path.name}", "document-open-symbolic", "open", str(path))
            add("Show in folder", "folder-symbolic", "reveal", str(path.parent))
            if path.suffix.lower() in TEXT_EXT and have("code"): add("VS Code", "text-editor-symbolic", "vscode", str(path))
    for url in re.findall(r"https?://[^\s)\]>`\"']+", body):
        add(f"Open {urllib.parse.urlparse(url).netloc.removeprefix('www.')}", "web-browser-symbolic", "link", url.rstrip(".,;:"))
    for lang, code in re.findall(r"```(\w*)\n(.*?)```", text, flags=re.S):
        lines = [l.strip().removeprefix("$ ") for l in code.strip().splitlines() if l.strip() and not l.strip().startswith("#")]
        if lang in ("sh", "bash", "shell", "zsh", "console") and len(lines) == 1 and len(lines[0]) < 200:
            add("Run", "media-playback-start-symbolic", "run", lines[0])
    return out[:8]

def title_from(text): t = " ".join(text.split()); return (t[:48] + "…") if len(t) > 48 else (t or "New chat")

def read_attachment(path):
    """(text, error). Documents go through MarkItDown; images/binaries are refused with a reason."""
    p = Path(path)
    if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic"}:
        return "", f"{p.name}: images aren't supported by the local model (use OCR, Super+Shift+T)"
    if p.suffix.lower() in fai.DOC_EXT:
        if not fai.MARKITDOWN.exists(): return "", f"{p.name}: document converter missing"
        try: r = subprocess.run([str(fai.MARKITDOWN), str(p)], capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired: return "", f"{p.name}: conversion took too long"
        return (r.stdout[:MAX_ATTACH], "") if r.returncode == 0 and r.stdout.strip() else ("", f"{p.name}: could not convert")
    try: raw = p.read_bytes()[:MAX_ATTACH * 4]
    except OSError as e: return "", f"{p.name}: {e.strerror}"
    if b"\0" in raw[:4096]: return "", f"{p.name}: binary file"
    return raw.decode("utf-8", "replace")[:MAX_ATTACH], ""

class Store:
    def __init__(self, root=CHATS): self.root = root; root.mkdir(parents=True, exist_ok=True)
    def all(self):
        chats = []
        for f in self.root.glob("*.json"):
            try: chats.append(json.loads(f.read_text()))
            except Exception: pass  # a damaged file must not hide the others
        return sorted(chats, key=lambda c: c.get("updated", 0), reverse=True)
    def save(self, chat):
        chat["updated"] = time.time(); tmp = self.root / f".{chat['id']}.tmp"
        tmp.write_text(json.dumps(chat, ensure_ascii=False, indent=1)); tmp.replace(self.root / f"{chat['id']}.json")
    def delete(self, chat): (self.root / f"{chat['id']}.json").unlink(missing_ok=True)
    @staticmethod
    def new(): return {"id": uuid.uuid4().hex[:12], "title": "New chat", "created": time.time(), "updated": time.time(), "messages": []}

def to_markdown(chat):
    lines = [f"# {chat['title']}\n"]
    for m in chat["messages"]:
        lines.append(f"**{'You' if m['role'] == 'user' else 'Assistant'}:**\n\n{m['content']}\n")
        for i, s in enumerate(m.get("sources", []), 1): lines.append(f"[{i}] {s['title']} — {s['url']}")
    return "\n".join(lines) + "\n"

def relative(ts):
    d = (datetime.date.today() - datetime.date.fromtimestamp(ts)).days
    return "Today" if d == 0 else "Yesterday" if d == 1 else datetime.date.fromtimestamp(ts).strftime("%d %b")

# ───────────────────────── GTK interface ─────────────────────────
def run_app():
    import gi
    gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

    CSS = """
    .msg-user { background: alpha(@accent_bg_color, 0.16); border-radius: 18px; padding: 10px 14px; }
    .msg-assistant { padding: 4px 2px; }
    .ai-time { font-size: 8.5pt; opacity: .45; }
    button.smart { padding: 4px 10px; border-radius: 999px; min-height: 0; font-size: 9.5pt;
                   background: alpha(@accent_bg_color, .14); box-shadow: inset 0 0 0 1px alpha(@accent_bg_color, .35); }
    button.smart:hover { background: alpha(@accent_bg_color, .26); }
    .msg-actions { opacity: 0; transition: opacity 120ms ease; min-height: 30px; }
    .msg-assistant:hover .msg-actions, .msg-actions:focus-within, .msg-actions.keep { opacity: 1; }
    .codeblock { background: alpha(@view_fg_color, 0.06); border-radius: 12px; }
    .codeblock label.code { font-family: "JetBrains Mono", monospace; font-size: 10.5pt; padding: 10px 12px; }
    .codeblock .lang { font-size: 9pt; opacity: .6; padding: 6px 12px 0 12px; }
    .table { background: alpha(@view_fg_color, 0.04); border-radius: 12px; padding: 2px; margin: 4px 0; }
    .table .th { font-weight: 700; padding: 8px 14px; background: alpha(@view_fg_color, 0.06); }
    .table .th:first-child { border-top-left-radius: 10px; }
    .table .th:last-child { border-top-right-radius: 10px; }
    .table .td { padding: 7px 14px; border-top: 1px solid alpha(@view_fg_color, 0.07); }
    .ctl-card { background: alpha(@accent_bg_color, 0.10); border-radius: 14px; padding: 12px 14px; margin: 6px 0;
                border: 1px solid alpha(@accent_bg_color, 0.25); }
    .ctl-card image { color: @accent_color; }
    .ctl-title { font-weight: 600; font-size: 10.5pt; }
    .ctl-val { font-family: "Adwaita Mono", monospace; font-size: 10pt; opacity: .7; }
    .composer { border-radius: 20px; padding: 4px 6px 6px 6px; background: @card_bg_color;
                box-shadow: 0 2px 10px alpha(black, .28), inset 0 0 0 1px alpha(@view_fg_color, .09); }
    .composer:focus-within { box-shadow: 0 2px 10px alpha(black, .28), inset 0 0 0 1px alpha(@accent_bg_color, .55); }
    .composer textview, .composer textview text { background: transparent; min-height: 0; padding: 0 8px; }
    .pill { border-radius: 99px; padding: 2px 10px; min-height: 28px; font-size: 9.5pt; font-weight: 600; }
    .pill:checked { background: alpha(@accent_bg_color, .22); color: @accent_color; }
    .sendbtn { min-width: 34px; min-height: 34px; padding: 0; }
    .hint { font-size: 8.5pt; opacity: .5; }
    .hello { font-size: 20pt; font-weight: 800; letter-spacing: -0.3px; }
    .hello-sub { font-size: 12pt; opacity: .6; }
    .suggest { border-radius: 14px; padding: 10px 12px; background: alpha(@view_fg_color, .05);
               box-shadow: inset 0 0 0 1px alpha(@view_fg_color, .07); }
    .suggest:hover { background: alpha(@view_fg_color, .09); }
    .suggest image { color: @accent_color; }
    .suggest .s-title { font-weight: 600; font-size: 10pt; }
    .suggest .s-sub { font-size: 9pt; opacity: .6; }
    .ai-head { font-size: 9pt; font-weight: 700; opacity: .75; }
    .step { background: alpha(@view_fg_color, .04); border-radius: 10px; padding: 6px 10px; }
    .step .st-label { font-size: 9.5pt; font-family: "JetBrains Mono", monospace; opacity: .85; }
    .st-done { color: @success_color; } .st-failed { color: @error_color; } .st-declined { opacity: .5; }
    .st-out { font-family: "JetBrains Mono", monospace; font-size: 9pt; opacity: .85; padding: 8px 2px 4px 2px; }
    .face-bg { border-radius: 99px; background: linear-gradient(180deg, shade(@accent_bg_color, 1.18), shade(@accent_bg_color, .8)); }
    .avatar-orb { box-shadow: 0 8px 24px alpha(@accent_bg_color, .35), inset 0 1px 0 alpha(white, .3); }
    window.orb-window { background: transparent; box-shadow: none; }
    .orb { min-width: 54px; min-height: 54px; padding: 0; margin: 12px; outline: none; border: none;
           box-shadow: 0 6px 16px alpha(black, .5), inset 0 1px 0 alpha(white, .35);
           transition: transform 180ms cubic-bezier(.2,.8,.2,1), box-shadow 180ms; }
    .orb:hover { transform: scale(1.08); }
    .orb:active { transform: scale(.94); }
    .orb.open { box-shadow: 0 6px 16px alpha(black, .5), 0 0 0 3px alpha(@accent_bg_color, .45), inset 0 1px 0 alpha(white, .35); }
    .orb.busy { animation: orb-pulse 1.3s ease-in-out infinite; }
    .orb.listening { box-shadow: 0 6px 16px alpha(black, .5), 0 0 0 4px alpha(@success_color, .7); }
    .orb.speaking { animation: orb-pulse 0.9s ease-in-out infinite; }
    .orb.approval { box-shadow: 0 6px 16px alpha(black, .5), 0 0 0 4px alpha(@warning_color, .85); }
    .orb.alert { box-shadow: 0 6px 16px alpha(black, .5), 0 0 0 3px alpha(@error_color, .8); }
    .listening-bar { background: alpha(@success_color, .14); border-radius: 12px; padding: 8px 12px; }
    @keyframes orb-pulse {
      0%, 100% { box-shadow: 0 6px 16px alpha(black, .5), 0 0 0 0 alpha(@accent_bg_color, .7); }
      50% { box-shadow: 0 6px 16px alpha(black, .5), 0 0 0 9px alpha(@accent_bg_color, 0); } }
    .composer scrolledwindow { min-height: 0; }
    list.suggest { background: @card_bg_color; border-radius: 14px; padding: 4px; margin-bottom: 4px;
                   box-shadow: 0 4px 14px alpha(black, .3), inset 0 0 0 1px alpha(white, .06); }
    list.suggest row { border-radius: 10px; }
    list.suggest row:selected { background: alpha(@accent_bg_color, .28); }
    .sugg-cmd { font-family: monospace; font-weight: 600; }
    .source { font-size: 9.5pt; font-weight: normal; padding: 3px 10px; min-height: 22px; border-radius: 99px;
              background: alpha(@view_fg_color, .07); color: @view_fg_color; }
    .source:hover { background: alpha(@view_fg_color, .12); }
    .status { font-size: 10pt; opacity: .7; }
    .chip { border-radius: 99px; padding: 2px 4px 2px 10px; background: alpha(@view_fg_color, .08); font-size: 9.5pt; }
    """

    CHAT_CLS = "class:^(org\\.myos\\.Chat)$"
    PANEL_W, ORB_EDGE, ORB_BOX = 420, 10, 78   # orb layer margin + its window (54px orb + 12px margins)

    # gtk4-layer-shell through ctypes (no GObject typelib on this system). The launcher LD_PRELOADs it;
    # without that the orb is skipped and the panel works alone.
    LAYER = None
    if "gtk4-layer-shell" in os.environ.get("LD_PRELOAD", ""):
        try:
            LAYER = ctypes.CDLL("libgtk4-layer-shell.so.0")
            ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
            ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
            LAYER.gtk_layer_set_namespace.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            if not LAYER.gtk_layer_is_supported(): LAYER = None
        except OSError:
            LAYER = None
        os.environ.pop("LD_PRELOAD", None)   # already loaded; keep it out of hyprctl/ollama/docker children

    def focused_monitor():
        """(x, y, logical width, logical height) of the focused monitor."""
        mons = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True).stdout)
        m = next((m for m in mons if m["focused"]), mons[0]); sc = m.get("scale", 1) or 1
        return m["x"], m["y"], int(m["width"] / sc), int(m["height"] / sc)

    ORB_POS = HOME / ".config/local-ai/orb.json"

    def orb_margins():
        """(right, bottom) margins of the orb from the screen corner; the user can drag it anywhere."""
        try: d = json.loads(ORB_POS.read_text()); return int(d["right"]), int(d["bottom"])
        except Exception: return ORB_EDGE, ORB_EDGE

    def panel_geometry(mon, margins=None):
        """The chat panel opens next to the orb: above it if there is room, else below; kept on screen."""
        mx, my, mw, mh = mon; r, b = margins or orb_margins()
        orb_right, orb_top, orb_bottom = mw - r - 12, mh - b - ORB_BOX + 12, mh - b - 12
        h = max(420, min(780, mh - 52 - 16))
        x = min(max(orb_right - PANEL_W, 8), mw - PANEL_W - 8)
        if orb_top - 6 - h >= 44: y = orb_top - 6 - h                 # above the orb
        elif orb_bottom + 6 + h <= mh - 8: y = orb_bottom + 6         # below it
        else:                                                          # beside it, full height
            h = mh - 52; y = 44
            x = orb_right - ORB_BOX - PANEL_W if orb_right - ORB_BOX - PANEL_W >= 8 else min(orb_right + 6, mw - PANEL_W - 8)
        return mx + x, my + y, PANEL_W, h

    class Face(Gtk.DrawingArea):
        """The assistant's own avatar: two eyes on a blue disc (the disc is CSS `.face-bg`).
        Blinks now and then, glances toward the panel when it is open, looks around while thinking."""
        def __init__(self, size, live=True):
            super().__init__(content_width=size, content_height=size, can_target=False)
            self.busy, self.look, self.blink_at, self.tick, self.mode = False, (0.0, 0.0), 0.0, None, "idle"
            self.set_draw_func(self.draw)
            if live: GLib.timeout_add(4700, self._blink)
        def _blink(self):
            if self.get_mapped(): self.blink_at = time.monotonic(); self._animate()
            return True
        def set_busy(self, busy): self.busy = busy; self._animate()
        def set_mode(self, mode): self.mode = mode; self._animate()     # idle | listening | speaking
        def set_look(self, dx, dy): self.look = (dx, dy); self.queue_draw()
        def _animate(self):
            if self.tick is None: self.tick = self.add_tick_callback(self._on_tick)
        def _on_tick(self, *_):
            self.queue_draw()
            if self.busy or self.mode != "idle" or time.monotonic() - self.blink_at < 0.2: return True
            self.tick = None; return False
        def draw(self, _a, cr, w, h):
            now = time.monotonic(); d = now - self.blink_at
            lid = max(0.1, abs(d - 0.09) / 0.09) if d < 0.18 else 1.0
            dx, dy = self.look
            if self.busy: dx, dy = math.sin(now * 3.4) * 0.08, -0.04 + math.cos(now * 6.8) * 0.015
            if self.mode == "listening":   # attentive: wide eyes, a gentle breathing pulse
                lid = 1.22 + 0.06 * math.sin(now * 5); dx, dy = 0, -0.02
            ew, eh = 0.13 * w, 0.25 * h * lid; r = ew / 2
            cr.set_source_rgba(1, 1, 1, 0.97)
            for cx in (0.36, 0.64):
                x, y = (cx + dx) * w - r, (0.47 + dy) * h - eh / 2
                cr.new_sub_path()
                if eh <= ew:
                    cr.rectangle(x, y, ew, max(eh, 1.5))
                else:
                    cr.arc(x + r, y + r, r, math.pi, 0); cr.arc(x + r, y + eh - r, r, 0, math.pi); cr.close_path()
            cr.fill()
            if self.mode == "speaking":    # a mouth that moves while it talks
                mh = h * (0.035 + 0.05 * abs(math.sin(now * 11) * math.sin(now * 4.3)))
                mw, mx, my = 0.2 * w, 0.4 * w, 0.72 * h - mh / 2
                cr.new_sub_path(); cr.arc(mx + mh / 2, my + mh / 2, mh / 2, math.pi / 2, 3 * math.pi / 2)
                cr.arc(mx + mw - mh / 2, my + mh / 2, mh / 2, 3 * math.pi / 2, math.pi / 2); cr.close_path(); cr.fill()

    def face_disc(size, extra=(), live=True):
        f = Face(size, live)
        f.add_css_class("face-bg")
        for c in extra: f.add_css_class(c)
        return f

    class Orb(Gtk.Window):
        """The always-there assistant bubble: click to open/close the chat, right-click for more."""
        def __init__(self, app):
            super().__init__(application=app, title="AI Orb", decorated=False, resizable=False, css_classes=["orb-window"])
            p = ctypes.c_void_p(ctypes.pythonapi.PyCapsule_GetPointer(self.__gpointer__, None))
            LAYER.gtk_layer_init_for_window(p); LAYER.gtk_layer_set_namespace(p, b"myos-orb")
            LAYER.gtk_layer_set_layer(p, 2)                    # TOP: above windows, below fullscreen video
            self.ptr = p; self.right, self.bottom = orb_margins()
            for edge in (1, 3): LAYER.gtk_layer_set_anchor(p, edge, True)
            self.place()
            LAYER.gtk_layer_set_keyboard_mode(p, 0)            # never steals focus
            self.face = Face(54)
            self.btn = Gtk.Button(child=self.face, css_classes=["orb", "face-bg"], tooltip_text="Assistant · click: open (Super+Z) · hold: talk (Super+Shift+D) · drag: move · right-click: more")
            self.btn.update_property([Gtk.AccessibleProperty.LABEL], ["Open assistant"])
            self.btn.connect("clicked", lambda *_: None if self.dragged else app.toggle())
            # drag anywhere: each drag-update offset is the movement since the surface last moved
            self.dragged = False; self.moved = 0
            drag = Gtk.GestureDrag(); drag.connect("drag-begin", self._drag_begin)
            drag.connect("drag-update", self._drag_update); drag.connect("drag-end", self._drag_end)
            self.btn.add_controller(drag)
            lp = Gtk.GestureLongPress(); lp.connect("pressed", lambda *_: None if self.dragged else app.listen())
            self.btn.add_controller(lp)
            menu = Gio.Menu(); menu.append("New chat", "app.new-chat"); menu.append("Reset position", "app.reset-orb")
            menu.append("Hide bubble", "app.hide-orb")
            menu.append("Quit assistant", "app.quit")
            pop = Gtk.PopoverMenu(menu_model=menu, has_arrow=False); pop.set_parent(self.btn)
            rc = Gtk.GestureClick(button=3); rc.connect("pressed", lambda *_: pop.popup()); self.btn.add_controller(rc)
            self.set_child(self.btn)
        def place(self):
            LAYER.gtk_layer_set_margin(self.ptr, 1, self.right); LAYER.gtk_layer_set_margin(self.ptr, 3, self.bottom)
        def _drag_begin(self, *_): self.dragged = False; self.moved = 0
        def _drag_update(self, _g, dx, dy):
            self.moved += abs(dx) + abs(dy)
            if self.moved < 6: return                       # a click, not a drag
            self.dragged = True
            try: _x, _y, mw, mh = focused_monitor()
            except Exception: mw, mh = 1920, 1200
            self.right = int(min(max(self.right - dx, 0), mw - ORB_BOX))
            self.bottom = int(min(max(self.bottom - dy, 0), mh - ORB_BOX))
            self.place()
        def _drag_end(self, *_):
            if self.dragged:
                ORB_POS.parent.mkdir(parents=True, exist_ok=True)
                ORB_POS.write_text(json.dumps({"right": self.right, "bottom": self.bottom}))
                GLib.timeout_add(50, lambda: setattr(self, "dragged", False) or False)   # swallow the click that ends a drag
                app = self.get_application()
                if app.win and app.win.get_visible() and app.win.docked: app.win.apply_dock()
        def reset(self):
            self.right = self.bottom = ORB_EDGE; self.place(); ORB_POS.unlink(missing_ok=True)
        def state(self, open_=None, busy=None, mode=None, approval=None, alert=None):
            for cls, on in (("approval", approval), ("alert", alert)):
                if on is not None: (self.btn.add_css_class if on else self.btn.remove_css_class)(cls)
            if mode is not None:
                self.face.set_mode(mode)
                for m in ("listening", "speaking"): (self.btn.add_css_class if m == mode else self.btn.remove_css_class)(m)
            for cls, on in (("open", open_), ("busy", busy)):
                if on is not None: (self.btn.add_css_class if on else self.btn.remove_css_class)(cls)
            if busy is not None: self.face.set_busy(busy)
            if open_ is not None: self.face.set_look(-0.05 if open_ else 0, -0.05 if open_ else 0)   # glance at the panel

    class Window(Adw.ApplicationWindow):
        def __init__(self, app, dock=True):
            super().__init__(application=app, title="AI Chat",
                             default_width=PANEL_W if dock else 1120, default_height=760)
            self.docked = dock
            self.store, self.chat, self.attachments = Store(), None, []
            self.busy, self.cancel, self.started_searx = False, threading.Event(), False
            self.speak_this, self.listening, self.voice_mod = False, False, None
            self.connect("close-request", lambda *_: (self.stop_listening(), self.set_visible(False), app.orb_state(open_=False), True)[3])  # resident: hide
            self.toasts = Adw.ToastOverlay()
            split = Adw.NavigationSplitView(min_sidebar_width=250, max_sidebar_width=320)
            split.set_sidebar(self._sidebar()); split.set_content(self._content())
            self.toasts.set_child(split); self.set_content(self.toasts)
            bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
            bp.add_setter(split, "collapsed", True); self.add_breakpoint(bp); self.split = split
            self._actions(); self._speak_toggle(); self._drop(); self.refresh_list(); self.open_chat(None)

        def apply_dock(self):
            """Place the panel above the orb, pinned. Runs as a GLib timeout: returns True (retry)
            until Hyprland has mapped the window, ~2 s max."""
            self._dock_tries = getattr(self, "_dock_tries", 0) + 1
            if self.client() is None and self._dock_tries < 40: return True
            self._dock_tries = 0
            try:
                x, y, w, h = panel_geometry(focused_monitor())
                for d in (["setfloating", CHAT_CLS], ["resizewindowpixel", f"exact {w} {h},{CHAT_CLS}"],
                          ["movewindowpixel", f"exact {x} {y},{CHAT_CLS}"]):
                    subprocess.run(["hyprctl", "dispatch", *d], capture_output=True)
                self.set_pinned(True)
            except Exception:
                pass
            return False

        def toggle_dock(self, *_):
            self.docked = not self.docked
            if self.docked:
                self.apply_dock()
            else:
                try:
                    self.set_pinned(False)
                    subprocess.run(["hyprctl", "dispatch", "resizewindowpixel", f"exact 1120 780,{CHAT_CLS}"], capture_output=True)
                    subprocess.run(["hyprctl", "dispatch", "centerwindow"], capture_output=True)
                except Exception: pass

        @staticmethod
        def client():
            """This window's Hyprland client record, or None if it isn't mapped (yet)."""
            try:
                cl = json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True).stdout)
                return next((c for c in cl if c.get("class") == "org.myos.Chat"), None)
            except Exception:
                return None

        def set_pinned(self, want):
            """`pin` toggles in Hyprland, so only dispatch it when the state differs."""
            c = self.client()
            if c is not None and c.get("pinned", False) != want:
                subprocess.run(["hyprctl", "dispatch", "pin", CHAT_CLS], capture_output=True)

        # sidebar: search + conversation list
        def _sidebar(self):
            tv = Adw.ToolbarView(); hb = Adw.HeaderBar(show_title=False)
            new = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New chat (Ctrl+N)", action_name="win.new")
            hb.pack_start(new); hb.set_title_widget(Gtk.Label(label="Chats", css_classes=["heading"])); tv.add_top_bar(hb)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=8, margin_end=8, margin_bottom=8)
            self.search = Gtk.SearchEntry(placeholder_text="Search chats"); self.search.connect("search-changed", lambda *_: self.refresh_list())
            self.list = Gtk.ListBox(css_classes=["navigation-sidebar"]); self.list.connect("row-activated", lambda _l, r: self.open_chat(r.chat))
            self.empty_list = Gtk.Label(label="No chats yet", css_classes=["dim-label"], margin_top=24)
            sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER); sw.set_child(self.list)
            box.append(self.search); box.append(self.empty_list); box.append(sw); tv.set_content(box)
            return Adw.NavigationPage(title="Chats", child=tv)

        # content: header, transcript, composer
        def _content(self):
            tv = Adw.ToolbarView(); hb = Adw.HeaderBar(css_classes=["flat"])
            self.win_title = Adw.WindowTitle(title="New chat", subtitle=f"Local · {fai.CFG['model'].split('/')[-1]}")
            hb.set_title_widget(self.win_title)
            menu = Gio.Menu(); menu.append("Expand / shrink window", "win.dock")
            menu.append("Rename…", "win.rename"); menu.append("Export as Markdown", "win.export")
            menu.append("Delete…", "win.delete"); menu.append("Speak every reply", "win.speak-all"); menu.append("Quit assistant", "win.quit")
            hb.pack_end(Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=menu, tooltip_text="Chat options"))
            hb.pack_end(Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New chat (Ctrl+N)", action_name="win.new"))
            tv.add_top_bar(hb)

            self.msgs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18, margin_bottom=18, margin_start=16, margin_end=16)
            clamp = Adw.Clamp(maximum_size=820, tightening_threshold=600); clamp.set_child(self.msgs)
            self.scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER); self.scroller.set_child(clamp)
            self.empty = self._welcome()
            self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150)
            self.stack.add_named(self.empty, "empty"); self.stack.add_named(self.scroller, "chat")

            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); body.append(self.stack); body.append(self._composer())
            tv.set_content(body)
            return Adw.NavigationPage(title="Chat", child=tv)

        def _welcome(self):
            hour = datetime.datetime.now().hour
            part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
            name = (GLib.get_real_name() or "").split()[0] if GLib.get_real_name() not in ("", "Unknown") else ""
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER, vexpand=True,
                          margin_start=18, margin_end=18, margin_bottom=12)
            self.avatar = face_disc(60, ["avatar-orb"]); self.avatar.set_halign(Gtk.Align.CENTER); self.avatar.set_margin_bottom(10)
            box.append(self.avatar)
            box.append(Gtk.Label(label=f"Good {part}" + (f", {name}" if name else ""), css_classes=["hello"], wrap=True, justify=Gtk.Justification.CENTER))
            box.append(Gtk.Label(label="What can I do for you?", css_classes=["hello-sub"], margin_bottom=16))
            grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1, max_children_per_line=2,
                               homogeneous=True, row_spacing=8, column_spacing=8)
            for icon, title, sub, prompt, web in (
                    ("utilities-system-monitor-symbolic", "Check my laptop", "GPU, memory, disk, battery",
                     "How is my laptop doing right now? Check GPU, memory, disk and battery.", False),
                    ("web-browser-symbolic", "What's new in security", "Fresh news, with sources",
                     "What are the most important cybersecurity news and new CVEs this week?", True),
                    ("display-brightness-symbolic", "Quick controls", "Brightness, volume, Wi-Fi",
                     "Show me brightness, volume and Wi-Fi controls.", False),
                    ("mail-attachment-symbolic", "Ask about a file", "PDF, docs, code, logs", None, False)):
                b = Gtk.Button(css_classes=["flat", "suggest"])
                row = Gtk.Box(spacing=10); row.append(Gtk.Image(icon_name=icon, valign=Gtk.Align.START, margin_top=2))
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                col.append(Gtk.Label(label=title, xalign=0, css_classes=["s-title"], ellipsize=Pango.EllipsizeMode.END))
                col.append(Gtk.Label(label=sub, xalign=0, css_classes=["s-sub"], ellipsize=Pango.EllipsizeMode.END))
                row.append(col); b.set_child(row)
                b.connect("clicked", lambda _b, p=prompt, w=web: self.suggest(p, w)); grid.append(b)
            box.append(grid)
            sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER); sw.set_child(box)
            return sw

        def suggest(self, prompt, web):
            if prompt is None: self.pick_files(); return
            self.text.get_buffer().set_text(prompt); self.web.set_active(web); self.submit()

        def ai_head(self, ts=None):
            h = Gtk.Box(spacing=7)
            h.append(face_disc(20, live=False))
            h.append(Gtk.Label(label="Assistant", css_classes=["ai-head"]))
            if ts: h.append(Gtk.Label(label=time.strftime("%H:%M", time.localtime(ts)), css_classes=["ai-time"]))
            return h

        def listen(self):
            """Hear one spoken request and send it to the assistant; the reply is spoken back."""
            if getattr(self, "listening", False):
                if getattr(self, "voice_mod", None): self.voice_mod.cancelled = True
                return
            if self.busy: self.cancel.set()
            voice_send({"stop": True}, start=False)                       # barge-in: stop talking, listen
            app = self.get_application(); self.listening = True; app.orb_state(mode="listening")
            self.placeholder.set_label("Listening… speak, then pause"); self.text.get_buffer().set_text("")
            def work():
                heard, err = "", ""
                try:
                    def engine():   # start Whisper while the user is talking, so it's ready when they stop
                        subprocess.run(["systemctl", "--user", "start", "whisper-server"], capture_output=True)
                        for _ in range(150):
                            try: urllib.request.urlopen("http://127.0.0.1:8178", timeout=1); return
                            except urllib.error.HTTPError: return
                            except Exception: time.sleep(0.1)
                    warm = threading.Thread(target=engine, daemon=True); warm.start()
                    if self.voice_mod is None:
                        sp = importlib.util.spec_from_file_location("voice_ask", HOME / ".local/share/local-ai/voice-ask.py")
                        self.voice_mod = importlib.util.module_from_spec(sp); sp.loader.exec_module(self.voice_mod)
                    self.voice_mod.cancelled = False
                    vlog("listen: recording")
                    pcm = self.voice_mod.capture()
                    warm.join(20)
                    vlog(f"listen: captured {len(pcm) / 32000:.1f}s of speech" + (" (cancelled)" if self.voice_mod.cancelled else ""))
                    if pcm: heard = self.voice_mod.speech.transcribe(pcm); vlog(f"listen: heard {heard!r}")
                    if pcm and not heard: err = "Sorry, I couldn't make that out."
                    elif not self.voice_mod.cancelled: err = "I didn't hear anything."
                except Exception as e: err = f"Voice input failed: {e}"; vlog(f"listen: error {e!r}")
                subprocess.Popen(["sh", "-c", "sleep 120; ~/.local/bin/ai-dictate expire"], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                GLib.idle_add(self._heard, heard, err)
            threading.Thread(target=work, daemon=True).start()

        def _heard(self, text, err):
            self.listening = False; self.get_application().orb_state(mode="idle")
            self.placeholder.set_label("Ask anything…")
            if err: self.toast(err); return False
            if not text: return False
            self.speak_this = True
            self.text.get_buffer().set_text(text); self.submit()
            return False

        def stop_listening(self):
            if self.listening and self.voice_mod: self.voice_mod.cancelled = True

        def escape(self):
            """Esc: stop talking, stop listening, stop the answer; if nothing is running, hide the panel."""
            if self.sugg.get_visible(): self.sugg.set_visible(False); return     # first Esc closes the suggestions
            was = self.listening or self.busy
            voice_send({"stop": True}, start=False); self.stop_listening(); self.cancel.set()
            if not was: self.close()

        def speaking_watch(self):
            """Keep the orb's mouth moving while the voice server is talking."""
            if getattr(self, "_watching", False): return
            self._watching = True
            def tick():
                st = voice_send({"status": True}, start=False) or {}
                if st.get("speaking"): self.get_application().orb_state(mode="speaking"); return True
                if not getattr(self, "listening", False): self.get_application().orb_state(mode="idle")
                self._watching = False; return False
            GLib.timeout_add(300, tick)

        def set_busy(self, busy):
            self.busy = busy; self.get_application().orb_state(busy=busy)
            self.send.set_icon_name("media-playback-stop-symbolic" if busy else "go-up-symbolic")
            self.send.set_tooltip_text("Stop (Esc)" if busy else "Send (Enter)")
            for c, on in (("destructive-action", busy), ("suggested-action", not busy)):
                (self.send.add_css_class if on else self.send.remove_css_class)(c)
            buf = self.text.get_buffer()
            self.send.set_sensitive(busy or buf.get_char_count() > 0 or bool(self.attachments))

        def _composer(self):
            outer = Adw.Clamp(maximum_size=820, margin_start=12, margin_end=12, margin_bottom=10, margin_top=4)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self.chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, visible=False)
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, css_classes=["composer"])
            self.sugg = Gtk.ListBox(css_classes=["suggest"], visible=False, selection_mode=Gtk.SelectionMode.SINGLE,
                                    activate_on_single_click=True)
            self.sugg.update_property([Gtk.AccessibleProperty.LABEL], ["Command suggestions"])
            self.sugg.connect("row-activated", lambda _l, row: self.accept_suggestion(row.get_index()))
            self.sugg_items = []
            attach = Gtk.Button(icon_name="mail-attachment-symbolic", tooltip_text="Attach files (or drop them here)",
                                css_classes=["flat", "circular"])
            attach.connect("clicked", self.pick_files)
            self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=9, bottom_margin=9, accepts_tab=False, hexpand=True)
            self.text.update_property([Gtk.AccessibleProperty.LABEL], ["Message"])
            self.placeholder = Gtk.Label(label="Ask anything…", css_classes=["dim-label"], halign=Gtk.Align.START,
                                         can_target=False, margin_top=9, margin_start=8, valign=Gtk.Align.START)
            ov = Gtk.Overlay(hexpand=True, valign=Gtk.Align.CENTER); tsw = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=220,
                                                                    hscrollbar_policy=Gtk.PolicyType.NEVER)
            tsw.set_child(self.text); ov.set_child(tsw); ov.add_overlay(self.placeholder)
            self.text.get_buffer().connect("changed", lambda b: self.placeholder.set_visible(b.get_char_count() == 0))
            key = Gtk.EventControllerKey(); key.connect("key-pressed", self.on_key)
            key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)    # before the window's Esc/Enter shortcuts
            self.text.add_controller(key)
            self.text.get_buffer().connect("changed", lambda b: self.update_suggestions())
            self.web = Gtk.ToggleButton(tooltip_text="Search the web for this message (auto for news, prices, versions…)",
                                        css_classes=["flat", "pill"])
            wb = Gtk.Box(spacing=5); wb.append(Gtk.Image(icon_name="web-browser-symbolic")); wb.append(Gtk.Label(label="Web"))
            self.web.set_child(wb)
            self.send = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Send (Enter)",
                                   css_classes=["suggested-action", "circular", "sendbtn"], sensitive=False)
            self.send.connect("clicked", lambda *_: self.cancel.set() if self.busy else self.submit())
            self.text.get_buffer().connect("changed", lambda b: self.send.set_sensitive(self.busy or b.get_char_count() > 0 or bool(self.attachments)))
            tools = Gtk.Box(spacing=4)
            mic = Gtk.Button(icon_name="audio-input-microphone-symbolic", css_classes=["flat", "circular"],
                             tooltip_text="Talk (Ctrl+Space / Super+Shift+D, or hold the orb) · it answers out loud")
            mic.connect("clicked", lambda *_: self.listen())
            for w in (attach, self.web, Gtk.Box(hexpand=True), mic, self.send): tools.append(w)
            card.append(ov); card.append(tools)
            hint = Gtk.Label(label="Runs on your GPU · private · can make mistakes", css_classes=["hint"],
                             wrap=True, justify=Gtk.Justification.CENTER)
            col.append(self.chips); col.append(self.sugg); col.append(card); col.append(hint); outer.set_child(col)
            return outer

        def _actions(self):
            for name, cb, accel in [("new", lambda *_: self.open_chat(None), "<Ctrl>n"), ("rename", self.rename, "F2"),
                                    ("export", self.export, "<Ctrl><Shift>e"), ("delete", self.delete, None),
                                    ("find", lambda *_: self.search.grab_focus(), "<Ctrl>f"),
                                    ("stop", lambda *_: self.escape(), "Escape"), ("close", lambda *_: self.close(), "<Ctrl>w"),
                                    ("dock", self.toggle_dock, None), ("listen", lambda *_: self.listen(), "<Ctrl>space"),
                                    ("quit", lambda *_: self.get_application().quit(), "<Ctrl>q")]:
                a = Gio.SimpleAction.new(name, None); a.connect("activate", cb); self.add_action(a)
                if accel: self.get_application().set_accels_for_action(f"win.{name}", [accel])

        def _speak_toggle(self):
            on = fai.CFG.get("speak_replies") == "always"
            act = Gio.SimpleAction.new_stateful("speak-all", None, GLib.Variant.new_boolean(on))
            def flip(a, _p):
                val = not a.get_state().get_boolean(); a.set_state(GLib.Variant.new_boolean(val))
                fai.CFG["speak_replies"] = "always" if val else "voice"
                try:
                    c = json.loads(fai.CFG_PATH.read_text()); c["speak_replies"] = fai.CFG["speak_replies"]
                    fai.CFG_PATH.write_text(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
                except Exception: pass
                if not val: voice_send({"stop": True}, start=False)
            act.connect("activate", flip); self.add_action(act)

        def _drop(self):
            t = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
            t.connect("drop", lambda _t, files, *_: [self.add_attachment(f.get_path()) for f in files.get_files() if f.get_path()] or True)
            self.add_controller(t)

        # list
        def refresh_list(self):
            q = self.search.get_text().lower().strip()
            while (row := self.list.get_row_at_index(0)): self.list.remove(row)
            chats = [c for c in self.store.all() if c["messages"] and (not q or q in c["title"].lower()
                     or any(q in m["content"].lower() for m in c["messages"]))]
            for c in chats:
                row = Gtk.ListBoxRow(); row.chat = c
                b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6, margin_bottom=6, margin_start=4)
                b.append(Gtk.Label(label=c["title"], xalign=0, ellipsize=Pango.EllipsizeMode.END))
                b.append(Gtk.Label(label=relative(c["updated"]), xalign=0, css_classes=["caption", "dim-label"]))
                row.set_child(b); self.list.append(row)
                if self.chat and c["id"] == self.chat["id"]: self.list.select_row(row)
            self.empty_list.set_visible(not chats)
            self.empty_list.set_label("No matching chats" if q else "No chats yet")

        def open_chat(self, chat):
            if self.busy: self.toast("Stop the current answer first"); return
            self.chat = chat or Store.new()
            while (c := self.msgs.get_first_child()): self.msgs.remove(c)
            for i, m in enumerate(self.chat["messages"]): self.add_message(m, last=i == len(self.chat["messages"]) - 1)
            self.win_title.set_title(self.chat["title"]); self.stack.set_visible_child_name("chat" if self.chat["messages"] else "empty")
            self.split.set_show_content(True); self.text.grab_focus(); self.scroll_end()
            row = next((r for i in range(999) if (r := self.list.get_row_at_index(i)) is None or r.chat["id"] == self.chat["id"]), None)
            self.list.select_row(row) if row else self.list.unselect_all()

        # messages
        def add_message(self, m, last=False):
            if m["role"] == "user":
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.END)
                bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, css_classes=["msg-user"])
                bubble.append(Gtk.Label(label=m["content"], wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, xalign=0, selectable=True, max_width_chars=60))
                for n in m.get("attachments", []):
                    bubble.append(Gtk.Label(label="📎 " + n, xalign=0, css_classes=["caption", "dim-label"]))
                col.append(bubble)
                if last and not self.busy:
                    e = Gtk.Button(label="Edit", css_classes=["flat", "caption"], halign=Gtk.Align.END); e.connect("clicked", self.edit_last)
                    col.append(e)
                self.msgs.append(col); return col
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["msg-assistant"])
            self.fill_assistant(box, m, last); self.msgs.append(box); return box

        def fill_assistant(self, box, m, last):
            while (c := box.get_first_child()): box.remove(c)
            box.append(self.ai_head(m.get("time")))
            for st in m.get("steps", []): box.append(self.step_widget(st))
            if m.get("error"):
                box.append(Gtk.Label(label=m["error"], wrap=True, xalign=0, css_classes=["error"]))
            for kind, body in split_blocks(strip_tool_echo(m["content"]) if m["role"] == "assistant" else m["content"]):
                if kind == "text":
                    lbl = Gtk.Label(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, xalign=0, selectable=True, use_markup=True)
                    try: lbl.set_markup(md_to_markup(body))
                    except Exception: lbl.set_text(body)
                    if lbl.get_label() == "" and body: lbl.set_text(body)  # invalid markup fallback
                    box.append(lbl)
                elif kind == "table":
                    box.append(self.table_widget(body))
                else:
                    box.append(self.code_block(kind[5:], body))
            for ctl in m.get("controls", []):
                w = self.control_widget(ctl)
                if w: box.append(w)
            acts = suggest_actions(strip_tool_echo(m["content"])) if m["content"] else []
            if acts:
                fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, row_spacing=4, column_spacing=4,
                                 css_classes=["smart-actions"])
                for label, icon, kind, value in acts:
                    b = Gtk.Button(css_classes=["smart"], tooltip_text=value)
                    inner = Gtk.Box(spacing=6); inner.append(Gtk.Image(icon_name=icon))
                    inner.append(Gtk.Label(label=label, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=22)); b.set_child(inner)
                    b.connect("clicked", lambda _b, k=kind, v=value: self.smart_action(k, v)); fb.append(b)
                box.append(fb)
            if m.get("sources"):
                fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, row_spacing=4, column_spacing=4)
                for i, s in enumerate(m["sources"], 1):
                    host = urllib.parse.urlparse(s["url"]).netloc.removeprefix("www.")
                    b = Gtk.LinkButton(uri=s["url"], label=f"{i}  {host}" + (f" · {s['date']}" if s.get("date") else ""),
                                       tooltip_text=s["title"], css_classes=["source"])
                    fb.append(b)
                box.append(fb)
            row = Gtk.Box(spacing=4)
            if m["content"]:
                cp = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy answer", css_classes=["flat", "circular"])
                cp.connect("clicked", lambda *_: self.copy(m["content"])); row.append(cp)
            if last:
                rt = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Retry", css_classes=["flat", "circular"])
                rt.connect("clicked", lambda *_: self.retry()); row.append(rt)
            if m.get("web"): row.append(Gtk.Label(label="Answered with web sources", css_classes=["caption", "dim-label"], margin_start=6))
            if m.get("stopped"): row.append(Gtk.Label(label="Stopped", css_classes=["caption", "dim-label"], margin_start=6))
            row.add_css_class("msg-actions")
            if last: row.add_css_class("keep")
            box.append(row)

        def smart_action(self, kind, value):
            if kind == "run":                                    # through the agent, so the approval card applies
                if self.busy: return
                self.text.get_buffer().set_text(f"Run this command: `{value}`"); self.submit(); return
            argv = {"folder": ["gio", "open", value], "open": ["gio", "open", value], "reveal": ["gio", "open", value],
                    "link": ["gio", "open", value], "vscode": ["code", value],
                    "terminal": ["ptyxis", "--new-window", "-d", value]}[kind]
            try: subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e: self.toast(f"Couldn't open: {e}"); return
            log_action(f"open_{kind}", {"name": value}, value)

        def control_widget(self, ctl):
            """A live inline control card the user can operate right in the chat."""
            if ctl not in CONTROL_LABELS:
                return None
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["ctl-card"])
            head = Gtk.Box(spacing=8)
            icon = {"brightness": "display-brightness-symbolic", "volume": "audio-volume-high-symbolic",
                    "night_light": "night-light-symbolic", "do_not_disturb": "notifications-disabled-symbolic",
                    "wifi": "network-wireless-symbolic", "bluetooth": "bluetooth-symbolic",
                    "power_mode": "power-profile-balanced-symbolic"}.get(ctl, "preferences-system-symbolic")
            head.append(Gtk.Image(icon_name=icon))
            head.append(Gtk.Label(label=CONTROL_LABELS[ctl], xalign=0, hexpand=True, css_classes=["ctl-title"]))
            state = control_state(ctl)
            if ctl in ("brightness", "volume"):
                val = Gtk.Label(label=f"{state if state is not None else 0}%", css_classes=["ctl-val"]); head.append(val)
                card.append(head)
                sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1 if ctl == "brightness" else 0, 100, 1)
                sc.set_value(state if state is not None else 50); sc.set_hexpand(True); sc.set_draw_value(False)
                def on_val(s, _c=ctl, _v=val):
                    v = int(s.get_value()); _v.set_label(f"{v}%"); control_apply(_c, v)
                sc.connect("value-changed", on_val)
                card.append(sc)
            elif ctl == "power_mode":
                card.append(head)
                seg = Gtk.Box(spacing=4, homogeneous=True, css_classes=["linked"])
                cur = state or "balanced"
                for mode, lbl in (("power-saver", "Saver"), ("balanced", "Balanced"), ("performance", "Performance")):
                    b = Gtk.ToggleButton(label=lbl, active=(cur == mode))
                    b.connect("toggled", lambda btn, mode=mode: btn.get_active() and control_apply("power_mode", mode))
                    seg.append(b)
                card.append(seg)
            else:  # boolean toggle
                sw = Gtk.Switch(active=bool(state), valign=Gtk.Align.CENTER)
                sw.connect("state-set", lambda _s, active, _c=ctl: (control_apply(_c, active), False)[1])
                head.append(sw); card.append(head)
            return card

        def table_widget(self, rows):
            grid = Gtk.Grid(css_classes=["table"], column_homogeneous=False)
            for r, cells in enumerate(rows):
                for c, cell in enumerate(cells):
                    wide = len(rows[0]) > 3                       # many columns: one line each, scroll sideways
                    lbl = Gtk.Label(xalign=0, wrap=not wide, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=True,
                                    use_markup=True, hexpand=True, max_width_chars=-1 if wide else 34,
                                    css_classes=["th"] if r == 0 else ["td"])
                    try: lbl.set_markup(md_to_markup(cell))
                    except Exception: lbl.set_text(cell)
                    grid.attach(lbl, c, r, 1, 1)
            if len(rows[0]) <= 3: return grid                     # wraps to the panel width, exact height
            sw = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                    hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, overlay_scrolling=False)
            sw.set_child(grid); return sw

        def code_block(self, lang, body):
            frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["codeblock"])
            top = Gtk.Box(); top.append(Gtk.Label(label=lang, css_classes=["lang"], hexpand=True, xalign=0))
            cp = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy code", css_classes=["flat", "circular"], margin_end=4, margin_top=2)
            cp.connect("clicked", lambda *_: self.copy(body)); top.append(cp)
            code = Gtk.Label(label=body, xalign=0, selectable=True, wrap=True, wrap_mode=Pango.WrapMode.CHAR, css_classes=["code"])
            attrs = Pango.AttrList(); attrs.insert(Pango.attr_insert_hyphens_new(False)); code.set_attributes(attrs)
            frame.append(top); frame.append(code); return frame      # no scroller: a wrapping label in one clips

        # composer / attachments
        def update_suggestions(self):
            buf = self.text.get_buffer(); text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            items = slash_suggestions(text) if not self.busy else []
            if [i[0] for i in items] == [i[0] for i in self.sugg_items] and self.sugg.get_visible() == bool(items): return
            self.sugg_items = items
            while (r := self.sugg.get_row_at_index(0)): self.sugg.remove(r)
            for _ins, label, desc, _ready in items:
                row = Gtk.Box(spacing=10, margin_start=10, margin_end=10, margin_top=5, margin_bottom=5)
                row.append(Gtk.Label(label=label, xalign=0, css_classes=["sugg-cmd"], ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=28))
                row.append(Gtk.Label(label=desc, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["caption", "dim-label"]))
                self.sugg.append(row)
            self.sugg.set_visible(bool(items))
            if items: self.sugg.select_row(self.sugg.get_row_at_index(0))

        def accept_suggestion(self, i, run=False):
            if not 0 <= i < len(self.sugg_items): return
            ins, _l, _d, ready = self.sugg_items[i]
            buf = self.text.get_buffer(); buf.set_text(ins); buf.place_cursor(buf.get_end_iter())
            self.text.grab_focus()
            if run and ready: self.submit()

        def on_key(self, _c, keyval, _code, state):
            if self.sugg.get_visible() and self.sugg_items:
                row = self.sugg.get_selected_row(); i = row.get_index() if row else 0; n = len(self.sugg_items)
                if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
                    i = (i + (1 if keyval == Gdk.KEY_Down else -1)) % n
                    self.sugg.select_row(self.sugg.get_row_at_index(i)); return True
                if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab): self.accept_suggestion(i); return True
                if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not state & Gdk.ModifierType.SHIFT_MASK:
                    buf = self.text.get_buffer(); typed = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
                    if typed == self.sugg_items[i][0] and not self.sugg_items[i][3]: return True   # waiting for the argument
                    self.accept_suggestion(i, run=True); return True
                if keyval == Gdk.KEY_Escape: self.sugg.set_visible(False); return True
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not state & Gdk.ModifierType.SHIFT_MASK:
                if getattr(self, "pending", None): self.pending(); return True     # Enter = approve the card
                self.submit(); return True
            return False

        def pick_files(self, *_):
            d = Gtk.FileDialog(title="Attach files")
            d.open_multiple(self, None, lambda dlg, res: [self.add_attachment(f.get_path()) for f in _finish(dlg, res)])

        def add_attachment(self, path):
            text, err = read_attachment(path)
            if err: self.toast(err); return
            name = Path(path).name; self.attachments.append((name, text))
            chip = Gtk.Box(spacing=2, css_classes=["chip"]); chip.append(Gtk.Label(label=name, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=28))
            x = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat", "circular"], tooltip_text=f"Remove {name}")
            item = (name, text); x.connect("clicked", lambda *_: self.remove_attachment(item, chip)); chip.append(x)
            self.chips.append(chip); self.chips.set_visible(True); self.send.set_sensitive(True)
            if len(text) >= MAX_ATTACH: self.toast(f"{name}: only the first {MAX_ATTACH // 1000}k characters are used")

        def remove_attachment(self, item, chip):
            if item in self.attachments: self.attachments.remove(item)
            self.chips.remove(chip.get_parent()); self.chips.set_visible(bool(self.attachments))

        def submit(self):
            if self.busy: return
            buf = self.text.get_buffer(); text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
            if not text and not self.attachments: return
            sl = parse_slash(text) if not self.attachments else None
            if sl and sl[0] == "local": buf.set_text(""); self.slash(sl[1], sl[2]); return
            if sl: text = sl[1]
            text = text or "Summarize the attached file(s)."
            m = {"role": "user", "content": text, "time": time.time()}
            if self.attachments:
                m["attachments"] = [n for n, _ in self.attachments]
                m["context"] = "\n\n".join(f"--- {n} ---\n{t}" for n, t in self.attachments)
            buf.set_text(""); self.attachments.clear()
            while (c := self.chips.get_first_child()): self.chips.remove(c)
            self.chips.set_visible(False)
            if not self.chat["messages"]: self.chat["title"] = title_from(text); self.win_title.set_title(self.chat["title"])
            self.chat["messages"].append(m); self.relayout(); self.generate(self.web.get_active() or needs_web(text))
            self.web.set_active(False)

        def panel(self, title, rows, empty=""):
            """A local card in the chat (not sent to the model). rows: (text, sub, button label | None, callback)."""
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["msg-assistant"]); box.append(self.ai_head())
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["ctl-card"])
            card.append(Gtk.Label(label=title, xalign=0, css_classes=["ctl-title"]))
            if not rows: card.append(Gtk.Label(label=empty, xalign=0, wrap=True, css_classes=["dim-label"]))
            for text, sub, blabel, cb in rows:
                r = Gtk.Box(spacing=8); col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
                lbl = Gtk.Label(xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=True, use_markup=True)
                try: lbl.set_markup(md_to_markup(text))
                except Exception: lbl.set_text(text)
                col.append(lbl)
                if sub: col.append(Gtk.Label(label=sub, xalign=0, wrap=True, css_classes=["caption", "dim-label"]))
                r.append(col)
                if blabel:
                    b = Gtk.Button(label=blabel, css_classes=["flat"], valign=Gtk.Align.CENTER)
                    def done(btn, cb=cb, r=r):
                        try: msg = cb()
                        except Exception as e: msg = f"Failed: {e}"
                        btn.set_label("Done"); r.set_sensitive(False)
                        if isinstance(msg, str): self.toast(msg)
                    b.connect("clicked", done); r.append(b)
                card.append(r)
            box.append(card); self.msgs.append(box); self.stack.set_visible_child_name("chat"); self.scroll_end()

        def slash(self, cmd, arg):
            when = lambda t: time.strftime("%d %b %H:%M", time.localtime(t))
            if cmd == "memory":
                self.panel("Memory", [(t, (f"for {p} · " if p else "") + when(c), "Forget", lambda i=i: forget(i) and "Forgotten")
                                      for i, t, p, c in memories()],
                           "Nothing saved yet. Say “remember that …” or use /remember.")
            elif cmd == "remember":
                if not arg: self.toast("Usage: /remember <fact>"); return
                threading.Thread(target=lambda: GLib.idle_add(self.toast, remember(arg)), daemon=True).start()
            elif cmd == "permissions":
                self.panel("Always allowed", [(f"`{p}`", "runs without asking (simple commands only)", "Revoke",
                                               lambda p=p: revoke_allow(p) or f"{p} will ask again") for p in sorted(allowed())],
                           "Nothing is always-allowed. Approval cards offer “Always allow” for simple, safe programs.")
            elif cmd == "log":
                self.panel("What the assistant did", [(e.get("label", e.get("tool", "")), f"{when(e['t'])} · {e.get('result', '')[:120]}", None, None)
                                                     for e in recent_actions(40)], "Nothing yet.")
            elif cmd == "routines":
                self.panel("Routines", [(r["prompt"], f"{r['name']} · {r['when']}", "Remove", lambda n=r["name"]: remove_routine(n))
                                        for r in list_routines()],
                           "None. Ask e.g. “every weekday at 9 open the coding layout”.")
            elif cmd == "briefing":
                self.panel("Briefing", [(WATCH.briefing() if WATCH else "watch.py is not installed", "", None, None)])
            else:
                self.panel("Commands" + (f" (no /{arg})" if arg and cmd == "help" and arg not in SLASH_REWRITE else ""),
                           [(f"`{c}`", d, None, None) for c, d in SLASH_HELP])

        def show_alerts(self):
            alerts = WATCH.load(WATCH.ALERTS, []) if WATCH else []
            if not alerts: return
            WATCH.ALERTS.unlink(missing_ok=True); self.get_application().orb_state(alert=False)
            self.panel("While you were away", [(a["title"], f"{time.strftime('%H:%M', time.localtime(a['t']))} · {a['body']}", None, None) for a in alerts])

        def relayout(self):
            while (c := self.msgs.get_first_child()): self.msgs.remove(c)
            ms = self.chat["messages"]
            for i, m in enumerate(ms): self.add_message(m, last=i == len(ms) - 1)
            self.stack.set_visible_child_name("chat" if ms else "empty"); self.scroll_end()

        # generation
        def generate(self, use_web):
            self.cancel.clear(); self.set_busy(True)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["msg-assistant"])
            status = Gtk.Box(spacing=8); spin = Adw.Spinner(); slabel = Gtk.Label(css_classes=["status"])
            status.append(spin); status.append(slabel)
            live = Gtk.Label(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, xalign=0, selectable=True)
            stepsbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.append(self.ai_head()); box.append(stepsbox); box.append(status); box.append(live); self.msgs.append(box); self.scroll_end()
            question = self.chat["messages"][-1]["content"]; history = list(self.chat["messages"])
            say = lambda s: GLib.idle_add(slabel.set_label, s)
            controls, steps = [], []
            speak = self.speak_this or fai.CFG.get("speak_replies") == "always"
            self.speak_this = False
            feeder = SentenceFeeder() if speak else None
            def say_out(sentences):
                if sentences:
                    for s_ in sentences: voice_send({"say": s_})
                    GLib.idle_add(lambda: self.speaking_watch() or False)

            def work():
                ctx, sources, web_err, out, err = "", [], "", "", None
                try:
                    if use_web:
                        say("Searching the web…")
                        ok, started, msg = ensure_searx()
                        self.started_searx |= started
                        if ok:
                            try:
                                ctx, sources = web_context(question)
                                say(f"Read {len(sources)} sources · thinking…" if sources else "No web results · thinking…")
                                if not sources: web_err = "no results"
                            except Exception as e: web_err = f"search failed: {e}"
                        else: web_err = msg
                        if web_err: GLib.idle_add(self.toast, f"Web: {web_err}")
                    if self.cancel.is_set(): raise InterruptedError
                    say("Loading model…" if not fai.server_up() else "Thinking…")
                    t0, last = time.time(), 0.0
                    gen = agent_stream(history, ctx, web_err, cancel=self.cancel, on_activity=say,
                                       confirm=lambda t, d, n="", k=None: self.ask_confirm(box, t, d, n, k))
                    try:
                        for kind, payload in gen:
                            if self.cancel.is_set(): break
                            if kind == "tool":
                                say(payload)   # show what the assistant is doing
                                continue
                            if kind == "control":
                                if payload not in controls: controls.append(payload)
                                continue
                            if kind == "step":
                                steps.append(payload); GLib.idle_add(lambda st=payload: (stepsbox.append(self.step_widget(st)), self.scroll_end()) and False)
                                continue
                            out += payload
                            if feeder: say_out(feeder.feed(payload))
                            if time.time() - last > 0.05:
                                last = time.time(); GLib.idle_add(self._live, live, status, out)
                            elif not out.strip() and time.time() - t0 > 4: say("Loading model… (first answer after a pause takes longer)")
                    finally: gen.close()
                except InterruptedError: pass
                except Exception as e: err = f"Couldn't get an answer: {e}"
                if feeder and not self.cancel.is_set():
                    rest = feeder.flush()
                    say_out(rest if (rest or feeder.said) else ["Done. The details are on screen."] if out.strip() or steps else [])
                GLib.idle_add(self._done, box, out, sources, err, use_web and bool(sources), controls, steps)
            threading.Thread(target=work, daemon=True).start()

        def ask_confirm(self, box, title, detail, note="", key=None):
            """Called from the worker: show an inline Run/Cancel card and block until the user answers (or Stop)."""
            ev, res = threading.Event(), {"ok": False}
            def build():
                card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["ctl-card"])
                head = Gtk.Box(spacing=8); head.append(Gtk.Image(icon_name="utilities-terminal-symbolic"))
                head.append(Gtk.Label(label=title, xalign=0, hexpand=True, css_classes=["ctl-title"])); card.append(head)
                card.append(Gtk.Label(label=detail, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.CHAR, selectable=True, css_classes=["ctl-val"]))
                if note: card.append(Gtk.Label(label=note, xalign=0, wrap=True, css_classes=["caption", "dim-label"]))
                row = Gtk.Box(spacing=6, halign=Gtk.Align.END)
                no = Gtk.Button(label="Cancel", css_classes=["flat"]); ok = Gtk.Button(label="Run", css_classes=["suggested-action", "pill"])
                always = Gtk.Button(label=f"Always allow {key}", css_classes=["flat"], visible=bool(key),
                                    tooltip_text=f"Run simple `{key}` commands without asking (remove in {ALLOW})")
                def answer(v):
                    res["ok"] = v; ev.set(); self.pending = None; self.get_application().orb_state(approval=False)
                    if card.get_parent(): card.get_parent().remove(card)   # the step row shows what happened
                no.connect("clicked", lambda *_: answer(False)); ok.connect("clicked", lambda *_: answer(True))
                always.connect("clicked", lambda *_: answer("always"))
                row.append(always); row.append(no); row.append(ok); card.append(row); box.append(card); ok.grab_focus(); self.scroll_end()
                card.append(Gtk.Label(label="Enter to run · Esc to cancel", xalign=1, css_classes=["caption", "dim-label"]))
                self.pending = lambda: answer(True); self.get_application().orb_state(approval=True)
                return False
            GLib.idle_add(build)
            while not ev.wait(0.2):
                if self.cancel.is_set(): return False
            return res["ok"]

        def _live(self, live, status, text):
            status.set_visible(False); live.set_text(fai.clean(text)); self.scroll_end(); return False

        def step_widget(self, st):
            """One real action the assistant took: what it did, did it work, and the actual output (expand)."""
            icon = {"done": "object-select-symbolic", "declined": "action-unavailable-symbolic"}.get(st["status"], "dialog-error-symbolic")
            row = Gtk.Box(spacing=8)
            row.append(Gtk.Image(icon_name=icon, css_classes=[f"st-{st['status']}"]))
            row.append(Gtk.Label(label=st["label"], xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END, css_classes=["st-label"]))
            exp = Gtk.Expander(label_widget=row, css_classes=["step"])
            if st["out"].strip():
                sw = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=260, hscrollbar_policy=Gtk.PolicyType.NEVER)
                sw.set_child(Gtk.Label(label=st["out"].strip(), xalign=0, yalign=0, wrap=True, wrap_mode=Pango.WrapMode.CHAR,
                                       selectable=True, css_classes=["st-out"]))
                exp.set_child(sw)
            made = re.match(r"created: (.+?)(?:; errors:|$)", st["out"])
            files = [f for f in (made.group(1).split(", ") if made else []) if f.startswith("/")]
            if not files: return exp
            wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2); wrap.append(exp)
            acts = Gtk.Box(spacing=4, margin_start=24)
            for label, cb in (("Open", lambda *_: subprocess.Popen(["gio", "open", files[0]])),
                              ("Show in folder", lambda *_: subprocess.Popen(["gio", "open", str(Path(files[0]).parent)])),
                              ("Copy path", lambda *_: self.copy("\n".join(files)))):
                b = Gtk.Button(label=label, css_classes=["flat", "caption"]); b.connect("clicked", cb); acts.append(b)
            wrap.append(acts); return wrap

        def _done(self, box, out, sources, err, web_used, controls=None, steps=None):
            out = re.sub(r"</?tool_results>.*?(</tool_results>|$)", "", fai.clean(out), flags=re.S).strip(); stopped = self.cancel.is_set()
            m = {"role": "assistant", "content": out, "time": time.time()}
            if sources and web_used: m["sources"] = sources; m["web"] = True
            if controls: m["controls"] = controls
            if steps: m["steps"] = steps
            if stopped: m["stopped"] = True
            if err or (not out and not stopped): m["error"] = err or "The model returned no answer. Try Retry."
            self.chat["messages"].append(m)
            self.set_busy(False)
            self.store.save(self.chat); self.refresh_list(); self.relayout(); self.text.grab_focus()
            return False

        def retry(self):
            if self.busy: return
            ms = self.chat["messages"]
            if ms and ms[-1]["role"] == "assistant": ms.pop()
            if ms and ms[-1]["role"] == "user":
                self.relayout(); self.generate(needs_web(ms[-1]["content"]) or any(m.get("web") for m in ms[-2:]))

        def edit_last(self, *_):
            ms = self.chat["messages"]
            if self.busy or not ms: return
            if ms[-1]["role"] == "assistant": ms.pop()
            if ms and ms[-1]["role"] == "user":
                u = ms.pop(); self.text.get_buffer().set_text(u["content"]); self.relayout(); self.text.grab_focus()

        # chat actions
        def rename(self, *_):
            if not self.chat["messages"]: return
            d = Adw.AlertDialog(heading="Rename chat"); e = Gtk.Entry(text=self.chat["title"], activates_default=True)
            d.set_extra_child(e); d.add_response("cancel", "Cancel"); d.add_response("ok", "Rename")
            d.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED); d.set_default_response("ok")
            def done(_d, r):
                if r == "ok" and e.get_text().strip():
                    self.chat["title"] = e.get_text().strip()[:80]; self.store.save(self.chat); self.win_title.set_title(self.chat["title"]); self.refresh_list()
            d.connect("response", done); d.present(self)

        def delete(self, *_):
            if not self.chat["messages"] or self.busy: return
            d = Adw.AlertDialog(heading="Delete this chat?", body=f"“{self.chat['title']}” will be permanently deleted.")
            d.add_response("cancel", "Cancel"); d.add_response("delete", "Delete")
            d.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
            d.connect("response", lambda _d, r: r == "delete" and (self.store.delete(self.chat), self.open_chat(None), self.refresh_list(), self.toast("Chat deleted")))
            d.present(self)

        def export(self, *_):
            if not self.chat["messages"]: return
            EXPORTS.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^\w\- ]+", "", self.chat["title"]).strip() or "chat"
            p = EXPORTS / f"{safe} {datetime.date.today()}.md"; n = 2
            while p.exists(): p = EXPORTS / f"{safe} {datetime.date.today()} ({n}).md"; n += 1
            p.write_text(to_markdown(self.chat)); self.toast(f"Exported to {str(p).replace(str(HOME), '~')}")

        # helpers
        def copy(self, text): self.get_clipboard().set(text); self.toast("Copied")
        def toast(self, msg): self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(msg), timeout=3)); return False
        def scroll_end(self):
            GLib.idle_add(lambda: (a := self.scroller.get_vadjustment()).set_value(a.get_upper()) or False)

    def _finish(dlg, res):
        try: return list(dlg.open_multiple_finish(res))
        except GLib.Error: return []  # dialog cancelled

    class App(Adw.Application):
        """Resident: `--background` (login) shows just the orb, `--toggle` (orb/Super+Z) flips the panel,
        anything else (launcher, menus) shows it."""
        def __init__(self):
            super().__init__(application_id="org.myos.Chat", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
            self.win = self.orb = None
            self.connect("shutdown", self.on_shutdown)
            for name, cb in (("new-chat", lambda *_: (self.show_panel(), self.win.open_chat(None))),
                             ("hide-orb", lambda *_: self.orb and self.orb.set_visible(False)),
                             ("reset-orb", lambda *_: self.orb and self.orb.reset()),
                             ("quit", lambda *_: self.quit())):
                act = Gio.SimpleAction.new(name, None); act.connect("activate", cb); self.add_action(act)
        def ensure_ui(self):
            if self.win: return
            prov = Gtk.CssProvider(); prov.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
            self.win = Window(self)
            if LAYER: self.orb = Orb(self); self.orb.present()
            def poll_alerts():
                if WATCH and self.orb: self.orb.state(alert=bool(WATCH.load(WATCH.ALERTS, [])))
                return True
            poll_alerts(); GLib.timeout_add_seconds(30, poll_alerts)
            self.hold()
        def orb_state(self, **kw):
            if self.orb: self.orb.state(**kw)
        def show_panel(self):
            if self.orb: self.orb.set_visible(True)
            self.win.present(); self.orb_state(open_=True); self.win.text.grab_focus(); self.win.show_alerts()
            if self.win.docked: GLib.timeout_add(40, self.win.apply_dock)
        def listen(self):
            self.show_panel(); self.win.listen()
        def toggle(self):
            if self.win.get_visible(): self.win.close()
            else: self.show_panel()
        def do_command_line(self, cl):
            args = cl.get_arguments()[1:]; self.ensure_ui()
            if "--background" in args: pass
            elif "--listen" in args: self.listen()
            elif "--ask" in args and args.index("--ask") + 1 < len(args):   # other tools hand a request to the assistant
                self.show_panel(); self.win.open_chat(None)
                self.win.text.get_buffer().set_text(args[args.index("--ask") + 1]); self.win.submit()
            elif "--toggle" in args or "--dock" in args: self.toggle()
            else: self.show_panel()
            return 0
        def do_activate(self):
            self.ensure_ui(); self.show_panel()
        def on_shutdown(self, *_):
            if self.win and self.win.started_searx:
                subprocess.Popen(["docker", "stop", "searxng"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return App().run(sys.argv)

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--routine": sys.exit(run_routine(sys.argv[2]))
    sys.exit(run_app())
