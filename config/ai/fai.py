#!/usr/bin/env python3
"""fai — KadaOS local AI helper (Ollama on the RTX 5050; optional Claude).

  fai ask [--claude] [--action A] [--text-file F] [question…]   stream an answer to stdout
  fai window --action A [--text-file F] [--question Q] [--paste-to ADDR] [--claude]
                                                                 answer UI for the floating window
  fai cmd <what you want to do>                                  suggest ONE shell command
  fai why [command] [exit-code]   (or: cmd 2>&1 | fai why)       explain an error
  fai index [--full]                                             (re)build the semantic file index
  fai search <query> [-n N] [--json]                             search files by meaning
  fai rag <question>                                             answer from your own files
  fai status                                                     server / model / index status
  fai unload                                                     free the GPU now
"""
import json, os, re, sqlite3, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path

HOME = Path.home()
CFG_PATH = HOME / ".config/local-ai/config.json"
DATA = HOME / ".local/share/local-ai"
DEFAULTS = {
    "host": "http://127.0.0.1:11434",
    "model": "ornith:9b",                 # assistant, agents, text menu (best tool use in our comparison)
    "embed_model": "nomic-embed-text",
    "keep_alive": "5m",
    "search_roots": ["~/Documents", "~/Downloads", "~/Desktop", "~/Projects", "~/Notes", "~/KadaOS/docs", "~/Workspaces"],
    "search_max_mb": 25,
}
CFG = dict(DEFAULTS)
if CFG_PATH.exists():
    try: CFG.update(json.loads(CFG_PATH.read_text()))
    except Exception as e: print(f"fai: bad config {CFG_PATH}: {e}", file=sys.stderr)

C = dict(dim="\033[2m", gold="\033[38;2;224;184;101m", ice="\033[38;2;142;197;224m", red="\033[38;2;229;120;127m",
         green="\033[38;2;143;208;166m", bold="\033[1m", off="\033[0m")
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"): C = {k: "" for k in C}   # pipes and files get clean text

ACTIONS = {
    "explain":   ("Explain", "Explain the following clearly and concisely. Use short paragraphs or bullets. If it is code or an error, say what it does / what went wrong and how to fix it."),
    "summarize": ("Summarize", "Summarize the following in 3-6 bullet points, keeping names, numbers and dates."),
    "fix":       ("Fix grammar & spelling", "Correct the grammar, spelling and punctuation of the following text. Keep the meaning, tone and language. Output ONLY the corrected text, nothing else."),
    "rewrite":   ("Rewrite (clear & professional)", "Rewrite the following to be clear, concise and professional. Keep the meaning and language. Output ONLY the rewritten text."),
    "reply":     ("Draft a reply", "Draft a short, friendly, natural reply to the following message. Output ONLY the reply text."),
    "ask":       ("Ask about it…", "Answer the user's question about the provided text. Be concise."),
    "system":    ("Ask AI  ·  can check your laptop", "You are the laptop's assistant."),
    "error":     ("Explain captured error", "Diagnose the captured error using current laptop facts and KadaOS documentation. Say which observations support the diagnosis; suggest only reviewable fixes."),
    "rag":       ("Ask using your files", "Answer using the retrieved files and cite them."),
    "free":      ("Ask anything…", "You are a concise, practical assistant on the user's Ubuntu 26.04 + Hyprland laptop. Answer directly."),
}
PURE = {"fix", "rewrite", "reply"}   # outputs meant to be pasted as-is


# ───────────────────────── Ollama plumbing ─────────────────────────
def _req(path, payload=None, timeout=300):
    data = None if payload is None else json.dumps(payload).encode()
    r = urllib.request.Request(CFG["host"] + path, data=data, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(r, timeout=timeout)

def server_up():
    try: _req("/api/version", timeout=2).read(); return True
    except Exception: return False

def ensure_server():
    if server_up(): return
    started = subprocess.run(["systemctl", "--user", "start", "ollama-local"], capture_output=True)
    if started.returncode:
        raise RuntimeError("Could not start ollama-local; check systemctl --user status ollama-local. For missing installation, run bash ~/KadaOS/scripts/install-ai.sh")
    for _ in range(60):
        if server_up(): return
        time.sleep(0.25)
    raise RuntimeError("Ollama server did not start (check systemctl --user status ollama-local)")

def chat_stream(messages, model=None):
    ensure_server()
    body = {"model": model or CFG["model"], "messages": messages, "stream": True, "think": False,
            "keep_alive": CFG["keep_alive"], "options": {"temperature": 0.3, "num_predict": 1500, "repeat_penalty": 1.1, "num_ctx": 8192}}
    def parts():
        with _req("/api/chat", body) as resp:
            for line in resp:
                if not line.strip(): continue
                j = json.loads(line)
                if "error" in j: raise RuntimeError(j["error"])
                yield j.get("message", {}).get("content", "")
                if j.get("done"): break
    yield from visible_tokens(parts())


def visible_tokens(parts):
    """Remove reasoning blocks even when delimiters span streamed chunks."""
    pending = ""; hidden = False
    for part in parts:
        pending += part
        while pending:
            marker = "</think>" if hidden else "<think>"
            pos = pending.find(marker)
            if pos >= 0:
                if not hidden and pos: yield pending[:pos]
                pending = pending[pos + len(marker):]; hidden = not hidden
                continue
            keep = next((n for n in range(min(len(marker)-1, len(pending)), 0, -1)
                         if pending.endswith(marker[:n])), 0)
            text, pending = (pending[:-keep], pending[-keep:]) if keep else (pending, "")
            if text and not hidden: yield text
            break
    if pending and not hidden: yield pending


def claude_answer(prompt, text):
    try:
        r = subprocess.run(["claude", "-p", prompt], input=text or "", capture_output=True, text=True, timeout=240)
        if r.returncode: raise RuntimeError("Claude failed: " + r.stderr.strip()[:300])
        return r.stdout.strip()
    except FileNotFoundError as e: raise RuntimeError("Claude Code CLI not found") from e
    except subprocess.TimeoutExpired as e: raise RuntimeError("Claude timed out") from e

def build_messages(action, text, question):
    system = ACTIONS.get(action, ACTIONS["free"])[1]
    user = ""
    if text: user += f"<text>\n{text.strip()}\n</text>\n"
    if question: user += f"\nQuestion: {question.strip()}"
    if not user.strip(): user = question or "Hello"
    return [{"role": "system", "content": system}, {"role": "user", "content": user.strip()}]

def embed(texts, kind="document"):
    ensure_server()
    pre = "search_document: " if kind == "document" else "search_query: "
    with _req("/api/embed", {"model": CFG["embed_model"], "input": [pre + t for t in texts], "keep_alive": CFG["keep_alive"]}) as r:
        return json.loads(r.read())["embeddings"]

def clean(s):
    return re.sub(r"<think>.*?</think>", "", s, flags=re.S).strip()

def copy(s):
    try: return subprocess.run(["wl-copy"], input=s, text=True, timeout=5).returncode == 0
    except Exception: return False

# ───────────────────────── commands ─────────────────────────
def stdin_piped():
    """True only for a real pipe or redirected file — never block on a tty/socket/inherited stdin."""
    import stat
    try: mode = os.fstat(sys.stdin.fileno()).st_mode
    except Exception: return False
    return stat.S_ISFIFO(mode) or stat.S_ISREG(mode)

def read_text(path):
    if path and os.path.exists(path):
        with open(path, errors="replace") as source: return source.read(24000)
    if stdin_piped(): return sys.stdin.read(24000)
    return ""

def cmd_ask(a):
    text = read_text(a.text_file)
    q = " ".join(a.question)
    action = a.action or ("ask" if text and q else "explain" if text else "free")
    if a.claude:
        out = claude_answer(ACTIONS[action][1] + ("\n\nQuestion: " + q if q else ""), text); print(out)
    else:
        out = ""
        for t in chat_stream(build_messages(action, text, q)): out += t; print(t, end="", flush=True)
        print()
    if a.copy: copy(clean(out))

def cmd_window(a):
    """Runs inside the floating kitty window: stream, copy, then offer paste / follow-up."""
    text = read_text(a.text_file); q = a.question or ""
    if getattr(a, "clipboard", False):
        try: text = subprocess.run(["wl-paste", "--no-newline", "--type", "text"], capture_output=True, text=True, timeout=2, check=True).stdout
        except (OSError, subprocess.SubprocessError): text = ""
        if not text: raise RuntimeError("Clipboard has no text")
    action = a.action; title, _ = ACTIONS.get(action, ACTIONS["free"])
    backend = "Claude" if a.claude else CFG["model"]
    sources = []
    snapshot = system_status() if action == "error" and not a.claude else ""
    if action == "rag":
        history, sources = rag_messages(q, getattr(a, "project", None))
    else:
        history = build_messages(action, text, q)
    while True:
        os.system("clear"); header(title, backend, text, q)
        if getattr(a, "context_label", None): print(f"{C['dim']}  Source: {a.context_label} · Answer: popup + clipboard{C['off']}\n")
        out = ""; error = None
        try:
            if action == "rag" and not sources:
                error = "No matching indexed files. Run fai index to refresh the index."
            elif action in ("system", "error") and not a.claude:
                # follow-ups keep the live tools; earlier turns go in as context
                prompt = history[-1]["content"] if len(history) > 2 else q or ("Explain this error and check relevant live facts and setup docs." if action == "error" else "Help me with this.")
                out = system_agent(prompt, conversation(history[:-1]) if len(history) > 2 else text, snapshot=snapshot)
            elif a.claude:
                print(f"{C['dim']}  thinking…{C['off']}", end="\r", flush=True)
                out = claude_answer(history[0]["content"], conversation(history)); print(out)
            else:
                for t in chat_stream(history): out += t; print(t, end="", flush=True)
                print()
        except Exception as e:
            error = str(e)
        out = clean(out) if error is None else ""
        if not out and error is None: error = "The model returned no answer. Try again."
        copied = bool(out) and copy(out)
        if out: history.append({"role": "assistant", "content": out})
        redraw(title, backend, text, q, out)
        if getattr(a, "context_label", None): print(f"{C['dim']}  Source: {a.context_label} · Answer: popup + clipboard{C['off']}")
        if snapshot: print(f"{C['dim']}\n  Live facts checked:\n{wrap(snapshot)}{C['off']}")
        if sources:
            for i, path in enumerate(sources, 1):
                print(f"{C['dim']}  [{i}] {path.replace(str(HOME), '~')}{C['off']}")
        if error: print(f"{C['red']}Could not get an answer: {error}{C['off']}")
        keys = "Enter paste into app · " if a.paste_to and copied else ""
        status = "✔ Copied to clipboard" if copied else "Clipboard unchanged"
        extra = " · O open cited source" if sources else ""
        extra += " · H review command/path" if out else ""
        print(f"\n  {status}  {C['dim']}{keys}F follow-up · C Claude{extra} · Esc/Q close{C['off']}")
        while True:
            k = getkey()
            if k in ("o", "O") and sources:
                number = input("\n  Source number to open › ").strip()
                if number.isdigit() and 1 <= int(number) <= len(sources):
                    path = Path(sources[int(number) - 1])
                    if path.is_file() and not path.is_symlink() and not sensitive_index_path(path):
                        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("\n  F follow-up · H review · Esc/Q close")
                continue
            if k in ("h", "H") and out:
                handoff_card(out)
                print("\n  F follow-up · H review · Esc/Q close")
                continue
            if k in ("\r", "\n") and a.paste_to and copied and re.fullmatch(r"0x[0-9a-fA-F]+", a.paste_to):
                subprocess.Popen(["sh", "-c", f"sleep 0.35; hyprctl dispatch focuswindow address:{a.paste_to} >/dev/null; sleep 0.15; wtype -M ctrl v -m ctrl"],
                                 start_new_session=True)
                return
            if k in ("f", "F"):
                q = input(f"\n{C['ice']}  Follow-up › {C['off']}").strip()
                if not q: continue
                history.append({"role": "user", "content": q}); break
            if k in ("c", "C") and not a.claude:  # keep conversation while asking Claude
                a.claude = True; backend = "Claude"
                if history[-1]["role"] == "assistant": history.pop()
                break
            return

def conversation(history):
    """The non-system turns as one text: a single message stays as-is, longer chats are labelled by speaker."""
    turns = [m for m in history if m["role"] != "system"]
    if len(turns) == 1: return turns[0]["content"]
    return "\n\n".join(f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in turns)

def wrap(s, indent="  "):
    import shutil, textwrap
    w = max(40, shutil.get_terminal_size().columns - 4)
    lines = []
    for para in s.splitlines():
        if not para.strip(): lines.append(""); continue
        lead = re.match(r"\s*([-*•]|\d+[.)])\s+", para)
        sub = indent + " " * (len(lead.group(0)) if lead else 0)
        lines += textwrap.wrap(para.strip(), w, initial_indent=indent, subsequent_indent=sub, break_long_words=False) or [""]
    return "\n".join(lines)

def header(title, backend, text, q):
    print(f"{C['gold']}{C['bold']}  {title}{C['off']}  {C['dim']}· {backend}{C['off']}")
    if text:
        import shutil
        n = max(30, shutil.get_terminal_size().columns - 8); prev = " ".join(text.split())
        print(f"{C['dim']}  “{prev[:n]}{'…' if len(prev) > n else ''}”{C['off']}")
    if q: print(f"{C['ice']}  › {q}{C['off']}")
    print()

def md(s):
    """Minimal markdown → ANSI for the answer window."""
    out = []
    for line in wrap(s).splitlines():
        h = re.match(r"(\s*)(#{1,4})\s+(.*)", line)
        if h: out.append(f"{h.group(1)}{C['gold']}{C['bold']}{h.group(3)}{C['off']}"); continue
        line = re.sub(r"\*\*(.+?)\*\*", lambda m: f"{C['bold']}{m.group(1)}{C['off']}", line)
        line = re.sub(r"`([^`]+)`", lambda m: f"{C['ice']}{m.group(1)}{C['off']}", line)
        line = re.sub(r"^(\s*)[-*] ", lambda m: f"{m.group(1)}{C['gold']}•{C['off']} ", line)
        out.append(line)
    return "\n".join(out)

def redraw(title, backend, text, q, out):
    os.system("clear"); header(title, backend, text, q); print(md(out))

def getkey():
    import termios, tty
    fd = sys.stdin.fileno(); old = termios.tcgetattr(fd)
    try: tty.setraw(fd); ch = sys.stdin.read(1)
    finally: termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch

def cmd_cmd(a):
    want = " ".join(a.words).strip()
    if not want: sys.exit("usage: ?? <what you want to do>")
    sysmsg = ("You turn a request into ONE correct shell command for zsh on Ubuntu 26.04 (GNU coreutils). "
              "Available: fd, rg, eza, bat, jq, du, find, sort, docker, git, gh, systemctl, journalctl, nmcli, ss, ffmpeg, uv, pnpm. "
              "Only use flags that really exist. Prefer simple, safe, read-only commands; avoid sudo unless required. "
              "Reply with ONLY the command on one line: no explanation, no backticks.")
    shots = [("find the 5 biggest files in Downloads", "find ~/Downloads -type f -printf '%s %p\\n' | sort -rn | head -5 | numfmt --field=1 --to=iec"),
             ("what is using port 8080", "ss -ltnp 'sport = :8080'"),
             ("show errors from the last boot", "journalctl -b -p err --no-pager"),
             ("search for TODO in python files here", "rg -n 'TODO' --type py"),
             ("disk usage of folders in home, largest first", "du -h --max-depth=1 ~ 2>/dev/null | sort -rh | head -20"),
             ("count lines of code in this repo", "git ls-files | xargs wc -l | tail -1"),
             ("show the saved wifi password", "nmcli -s -g 802-11-wireless-security.psk connection show \"$(nmcli -g NAME connection show --active | head -1)\""),
             ("stop the process listening on port 5173", "fuser -k 5173/tcp")]
    msgs = [{"role": "system", "content": sysmsg}]
    for q_, a_ in shots: msgs += [{"role": "user", "content": q_}, {"role": "assistant", "content": a_}]
    msgs.append({"role": "user", "content": f"(cwd: {os.getcwd()}) {want}"})
    if a.claude:
        out = claude_answer(sysmsg + " Examples: " + "; ".join(f"{q_} => {a_}" for q_, a_ in shots), f"(cwd: {os.getcwd()}) {want}")
    else:
        out = clean("".join(chat_stream(msgs)))
    print(first_command(out))

def first_command(out):
    """The command from a model reply, skipping ``` fence lines (```bash would otherwise yield "bash")."""
    lines = [l.strip() for l in out.strip().splitlines() if l.strip() and not l.strip().startswith("```")]
    return lines[0].strip("`").strip() if lines else ""

def handoff_candidates(answer):
    """Only offer explicit code lines or absolute paths; never execute generated text."""
    blocks = re.findall(r"```(?:bash|sh|zsh|shell)?\s*\n(.*?)```", answer, re.I | re.S)
    candidates = [line.strip() for block in blocks for line in block.splitlines() if line.strip()]
    candidates += [item.strip() for item in re.findall(r"(?<!`)`([^`\n]+)`(?!`)", answer) if item.strip()]
    candidates += [p.rstrip(".,;:)") for p in re.findall(r"(?<!\w)(/[\w./+~-]+)", answer)]
    return list(dict.fromkeys(candidates))[:8]

def handoff_card(answer):
    choices = handoff_candidates(answer)
    if not choices:
        input("\n  No command or path found in the answer. Press Enter to return.")
        return
    print("\n  Review before using anything below. Nothing will run here.")
    for i, item in enumerate(choices, 1): print(f"  [{i}] {item}")
    number = input("\n  Number to preview (Enter returns) › ").strip()
    if not number.isdigit() or not 1 <= int(number) <= len(choices): return
    selected = choices[int(number) - 1]
    print(f"\n  Exact text to copy:\n  {selected}\n")
    if input("  Type COPY to place this on the clipboard › ").strip() == "COPY":
        print("  Copied." if copy(selected) else "  Could not copy.")
    input("  Press Enter to return.")

def cmd_handoff(a):
    """Emit reviewed text for a parent shell's editable prompt; never run it."""
    answer = sys.stdin.read() if a.answer and stdin_piped() else " ".join(a.command)
    choices = handoff_candidates(answer) if a.answer else [answer.strip()] if answer.strip() else []
    if not choices: return
    try: terminal = open("/dev/tty", "r+")
    except OSError: return
    with terminal:
        terminal.write("\nReview terminal handoff. Nothing runs automatically.\n")
        for i, item in enumerate(choices, 1): terminal.write(f"  [{i}] {item}\n")
        terminal.write("Number to put on your editable prompt (Enter cancels) › "); terminal.flush()
        number = terminal.readline().strip()
        if number.isdigit() and 1 <= int(number) <= len(choices):
            selected = choices[int(number) - 1]
            terminal.write(f"Exact text: {selected}\nType INSERT to continue › "); terminal.flush()
            if terminal.readline().strip() == "INSERT": print(selected)

def cmd_why(a):
    data = sys.stdin.read()[-6000:] if stdin_piped() else ""
    ctx = f"Command: {' '.join(a.command)}\n" if a.command else ""
    if a.code: ctx += f"Exit code: {a.code}\n"
    if data: ctx += f"Output:\n{data}\n"
    if not ctx: sys.exit("usage: why   (right after a failed command)   or:  cmd 2>&1 | why")
    sysmsg = ("A command failed on Ubuntu 26.04 (zsh). In at most 6 short lines: say what went wrong, then give the fix "
              "as one command in a ```sh fenced block if there is one. Be concrete. Never run the fix.")
    for t in chat_stream([{"role": "system", "content": sysmsg}, {"role": "user", "content": ctx}]): print(t, end="", flush=True)
    print()



# ───────────────────────── system-aware assistant ─────────────────────────
# The model may call `run` with READ-ONLY diagnostics (strict allow-list) and `search_docs`.
# Anything that changes the system is refused; the assistant tells the user what to run instead.
import shlex
SECRET = re.compile(r"(\.ssh|\.gnupg|restic|password|passwd|shadow|secret|token|\.pem$|id_rsa|id_ed25519|keyring|\.age$|/age/|sops|\.env(?:[./]|$)|auth\.json|credentials)", re.I)
# Validate the complete command shape, including flags. A read-only subcommand
# does not make unrelated flags safe (e.g. nvidia-smi -pl or git branch -D).
DIAGNOSTICS = [
    r'df(?: -(?:h|H|T|i|hT))?(?: /[\w/.-]*)?',
    r'free(?: -(?:h|m|g|b))?', r'uname(?: -[asrvmnop]+)?',
    r'(?:uptime|lscpu|lsusb|lspci|sensors|who|id|lsmod|findmnt|zramctl)',
    r'lsblk(?: -(?:f|a|J))?', r'swapon --show',
    r'ss(?: -[ltnuaps]+)?', r'pgrep(?: -[ax]+)? [\w.-]+',
    r'ps -eo (?:pid|ppid|comm|%cpu|%mem|rss|vsz|stat|etime)(?:,(?:pid|ppid|comm|%cpu|%mem|rss|vsz|stat|etime))*(?: --sort=-?(?:%cpu|%mem|rss|pid))?',
    r'nvidia-smi(?: -q| --query-gpu=[\w.,]+ --format=csv(?:,noheader)?(?:,nounits)?)?',
    r'(?:timedatectl|hostnamectl|localectl)(?: status)?',
    r'loginctl (?:list-sessions|list-users|session-status)',
    r'ip(?: -(?:br|brief|4|6|s|j))? (?:a|addr|address|r|route|link|neigh)(?: show)?',
    r'systemctl(?: --user)? (?:--failed|list-units|list-timers|list-unit-files)(?: --no-pager)?',
    r'systemctl(?: --user)? (?:status|is-active|is-enabled)(?: [\w@][\w@.:-]*)*(?: --no-pager)?',
    r'journalctl(?: --user| --no-pager| -b(?: -?[0-9]+)?| -p (?:[0-7]|emerg|alert|crit|err|warning|notice|info|debug)| -n [0-9]{1,4}| -u [\w@.:-]+)*',
    r'powerprofilesctl (?:get|list)',
    r'nmcli(?: -t)?(?: -f [A-Za-z0-9_,.-]+)? (?:general(?: status)?|device(?: status| show(?: [\w.-]+)?| wifi(?: list)?)?|connection(?: show)?|radio(?: wifi| wwan)?)',
    r'docker (?:ps(?: -(?:a|q|aq))?|images|info|version|stats --no-stream|(?:volume|network) ls|system df)',
    r'hyprctl (?:monitors|clients|workspaces|devices|binds|activewindow|version|layers|configerrors)(?: -j| all)?',
    r'hyprctl getoption [\w:.-]+',
    r'pactl (?:info|get-default-sink|get-default-source|list(?: short)?(?: sinks| sources)?)',
    r'wpctl (?:status|(?:inspect|get-volume) (?:[0-9]+|@DEFAULT_AUDIO_(?:SINK|SOURCE)@))',
    r'bluetoothctl (?:show|devices|list|info [A-Fa-f0-9:]+)',
    r'tailscale (?:status|ip|version)',
    r'git (?:status(?: --short| --porcelain)?|log(?: --oneline)?(?: -n [0-9]{1,3})?|branch)',
    r'gsettings get org\.gnome\.desktop\.(?:interface|peripherals\.(?:mouse|touchpad|keyboard)) [\w-]+',
    r'dpkg (?:-l|-s|-L|--list|--status)(?: [\w][\w.+:-]*)?',
    r'apt (?:list(?: --installed| --upgradable)?|(?:policy|show) [\w.+:-]+)',
    r'apt-cache (?:policy|show|search)(?: [\w][\w.+:-]*)?',
    r'(?:snap|flatpak) (?:list|info [\w.-]+)',
    r'fai status', r'ollama (?:list|ps)', r'fwupdmgr get-devices',
    r'rfkill list(?: bluetooth| wifi)?', r'iw dev(?: [\w.-]+ (?:link|info))?',
    r'swaync-client -(?:D|c)', r'brightnessctl(?: -m)? (?:info|get)',
    r'upower (?:-e|-d|-i /org/freedesktop/UPower/devices/[\w]+)',
    r'(?:which|whereis) [\w.-]+', r'(?:date|locale|fc-list)',
    r'(?:vmstat|iostat)(?: [0-9]{1,2} [0-9]{1,2})?',
    r'top -b -n ?1', r'lsof -i(?: -P)?(?: -n)?',
]


def diagnostic_argv(cmd):
    """Return validated argv or raise ValueError; never execute during validation."""
    if not isinstance(cmd, str) or re.search(r'[;&|<>`$(){}\n\r]', cmd):
        raise ValueError('shell operators are not allowed; run one plain command')
    argv = shlex.split(cmd)
    if not argv or argv[0] == 'sudo':
        raise ValueError('empty command or sudo is not allowed')
    if any(SECRET.search(a) for a in argv[1:]):
        raise ValueError('the request may expose secrets')
    if argv[0] in ('cat', 'head', 'tail'):
        args = argv[1:]
        if argv[0] != 'cat' and len(args) == 3 and args[0] == '-n' and args[1].isdigit() and 0 < int(args[1]) <= 200:
            args = args[2:]
        if len(args) != 1 or args[0].startswith('-'):
            raise ValueError('read one diagnostic file, optionally using -n 1..200')
        path = Path(args[0]).expanduser().resolve()
        metrics = {'/proc/meminfo', '/proc/cpuinfo', '/proc/loadavg', '/proc/uptime',
                   '/proc/version', '/proc/swaps', '/etc/os-release', '/etc/lsb-release'}
        metrics = {str(Path(p).resolve()) for p in metrics}
        roots = [HOME / 'KadaOS/docs', HOME / '.config/hypr', Path('/sys/devices')]
        if SECRET.search(str(path)) or not (str(path) in metrics or any(path.is_relative_to(r.resolve()) for r in roots)):
            raise ValueError('file reads are limited to setup docs, Hyprland config, and system metrics')
        argv[-1] = str(path)
    elif any(re.search(r'\s', a) for a in argv) or not any(re.fullmatch(pattern, ' '.join(argv)) for pattern in DIAGNOSTICS):
        raise ValueError('that command or option is outside the diagnostic allow-list; suggest it to the user')
    if argv[0] == 'journalctl':
        argv += ['--no-pager'] + ([] if '-n' in argv else ['-n', '80'])
    return argv


def run_readonly(cmd):
    try: argv = diagnostic_argv(cmd)
    except ValueError as e: return f'REFUSED: {e}'
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=15,
                           env={**os.environ, 'SYSTEMD_PAGER': '', 'PAGER': 'cat', 'GIT_PAGER': 'cat'},
                           stdin=subprocess.DEVNULL)
        out = (r.stdout + ('\n' + r.stderr if r.stderr.strip() else '')).strip()
    except FileNotFoundError: return f"'{argv[0]}' is not installed."
    except subprocess.TimeoutExpired: return 'timed out after 15 s'
    out = re.sub(r'(psk|password|secret|token)=\S+', r'\1=<hidden>', out, flags=re.I)
    return (out[:3500] + '\n…(truncated)') if len(out) > 3500 else (out or f'(no output, exit {r.returncode})')


def system_status():
    """Compact, pre-interpreted snapshot (the model reads this far better than raw tool output)."""
    def rd(p, d=""):
        try: return Path(p).read_text().strip()
        except Exception: return d
    def q(*c):
        try: return subprocess.run(c, capture_output=True, text=True, timeout=6).stdout.strip()
        except Exception: return ""
    def qr(*c):  # (ok, text): ok only on exit 0; text carries the error otherwise
        try: r = subprocess.run(c, capture_output=True, text=True, timeout=6)
        except FileNotFoundError: return False, f"{c[0]} not installed"
        except subprocess.TimeoutExpired: return False, f"{c[0]} timed out"
        except Exception as e: return False, str(e)
        return r.returncode == 0, (r.stdout.strip() if r.returncode == 0 else (r.stderr or r.stdout).strip() or f"exit {r.returncode}")
    L = []
    b = Path("/sys/class/power_supply/BAT0"); ac = rd("/sys/class/power_supply/ADP1/online") == "1"
    if b.exists():
        cap = rd(b / "capacity"); st = rd(b / "status"); pw = int(rd(b / "power_now", "0") or 0) / 1e6
        if not ac and st == "Discharging" and pw < 0.5 and int(cap or 0) >= 98:
            ac = True; st = "full (firmware wrongly reports the charger as unplugged — known HP quirk; it is on AC)"
        en, ef, ed = (int(rd(b / k, "0") or 0) / 1e6 for k in ("energy_now", "energy_full", "energy_full_design"))
        if st == "Discharging" and pw > 0.5: eta = f"~{en / pw:.1f} h left at {pw:.1f} W"
        elif st == "Charging" and pw > 0.5: eta = f"~{(ef - en) / pw:.1f} h to full at {pw:.1f} W"
        else: eta = "no estimate yet (discharge rate not measured yet — check again in a few minutes)" if not ac else "on AC"
        health = f", health {ef / ed * 100:.0f}% of design" if ed else ""
        L.append(f"Battery: {cap}% {st.lower()}, {'plugged in' if ac else 'on battery'}; {eta}{health}")
    L.append(f"Power profile: {q('powerprofilesctl', 'get')}")
    temps = []
    for z in Path("/sys/class/thermal").glob("thermal_zone*"):
        t = rd(z / "type"); v = rd(z / "temp")
        if v and t in ("x86_pkg_temp", "acpitz", "TCPU"): temps.append(f"{t} {int(v) / 1000:.0f}°C")
    fan = re.search(r"fan1:\s+(\d+ RPM)", q("sensors")); L.append("Temps: " + ", ".join(temps) + (f"; fan {fan.group(1)}" if fan else ""))
    ok, gpu = qr("nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw", "--format=csv,noheader")
    g = [x.strip() for x in gpu.splitlines()[0].split(",")] if ok and gpu else []
    if len(g) == 5:
        L.append(f"NVIDIA GPU: {g[0]}°C, utilization {g[1]}, VRAM {g[2]} / {g[3]} (the local AI model uses ~5.5 GB while loaded), power {g[4]}")
    elif ok: L.append(f"NVIDIA GPU: unknown (unexpected nvidia-smi output: {gpu[:120]!r})")
    else:
        hint = " — driver updated but not loaded yet; reboot to fix" if "mismatch" in gpu.lower() else ""
        L.append(f"NVIDIA GPU: unavailable ({gpu.splitlines()[0][:160] if gpu else 'no output'}){hint}")
    m = q("free", "-h").splitlines()
    if len(m) > 1: f = m[1].split(); L.append(f"Memory: {f[2]} used of {f[1]} (available {f[6]}); swap/zram: {m[2].split()[2] if len(m) > 2 else '?'} used")
    for mp in ("/", "/boot/efi"):
        try: st = os.statvfs(mp); L.append(f"Disk {mp}: {100 - st.f_bavail * 100 / st.f_blocks:.0f}% used, {st.f_bavail * st.f_frsize / 2**30:.0f} GiB free")
        except Exception: pass
    L.append("Load (1/5/15 min): " + " ".join(rd("/proc/loadavg").split()[:3]) + f" on {os.cpu_count()} threads; {q('uptime', '-p')}")
    (oks, fs), (oku, fu) = qr("systemctl", "--failed", "--no-legend", "--plain"), qr("systemctl", "--user", "--failed", "--no-legend", "--plain")
    failed = [l.split()[0] for l, ok in ((l, ok) for t, ok in ((fs, oks), (fu, oku)) if ok for l in t.splitlines()) if l.strip()]
    unk = [n for n, ok in (("system", oks), ("user", oku)) if not ok]
    L.append("Failed services right now: " + (", ".join(failed) if failed else "none") + (f" (could not check {'/'.join(unk)} services)" if unk else ""))
    sv = [(n, q("systemctl", "is-active", n)) for n in ("docker", "tailscaled", "NetworkManager", "bluetooth", "cups", "ufw")]
    sv += [(n, q("systemctl", "--user", "is-active", n)) for n in ("ollama-local", "system-adapt", "swaync", "pipewire")]
    L.append("Key services: " + ", ".join(f"{n} {st}" for n, st in sv))
    dk = q("docker", "ps", "--format", "{{.Names}} ({{.Status}})")
    L.append("Docker containers running: " + (dk.replace("\n", ", ") if dk else "none"))
    L.append("Network: " + "; ".join(l for l in q("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device").splitlines() if ":connected" in l or ":disconnected" in l)[:300])
    L.append("Top memory: " + ", ".join(" ".join(l.split()[1:]) for l in q("ps", "-eo", "pid,comm,%mem", "--sort=-%mem").splitlines()[1:6]))
    L.append("Top CPU: " + ", ".join(" ".join(l.split()[1:]) for l in q("ps", "-eo", "pid,comm,%cpu", "--sort=-%cpu").splitlines()[1:6]))
    return "\n".join(L)

SYSINFO = HOME / ".cache/local-ai/sysinfo.md"
def sysinfo(refresh=False):
    if SYSINFO.exists() and not refresh and time.time() - SYSINFO.stat().st_mtime < 86400: return SYSINFO.read_text()
    def q(*c):
        try: return subprocess.run(c, capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception: return ""
    osr = dict(l.split("=", 1) for l in Path("/etc/os-release").read_text().splitlines() if "=" in l)
    cpu = re.search(r"Model name:\s*(.*)", q("lscpu")); mem = q("free", "-h").splitlines()
    dmi = lambda f: (Path("/sys/class/dmi/id") / f).read_text().strip() if (Path("/sys/class/dmi/id") / f).exists() else ""
    model = " ".join(x for x in (dmi("sys_vendor"), dmi("product_name")) if x) or "this computer"
    disk = [l.split(None, 1)[1] for l in q("lsblk", "-dno", "NAME,SIZE,MODEL").splitlines()
            if len(l.split()) > 1 and not l.startswith(("zram", "loop", "sr"))]
    gpus = [l.split(": ", 1)[-1] for l in q("lspci").splitlines() if re.search(r"VGA|3D|Display", l)]
    nv = q("nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader")
    info = f"""- Machine: {model} · {cpu.group(1) if cpu else 'CPU unknown'} · RAM {mem[1].split()[1] if len(mem) > 1 else '?'} · disk {disk[0].strip() if disk else '?'}
- GPU: {'; '.join(gpus) or 'unknown'}{f' (NVIDIA driver: {nv})' if nv else ''}
- OS: {osr.get('PRETTY_NAME', '').strip('"')} · kernel {q('uname', '-r')}
- Desktops: Hyprland 0.53 (main, keyboard-first) and GNOME (fallback). Shell: zsh + starship. Terminal: Ptyxis / kitty.
- Setup repo: ~/KadaOS (scripts/, config/, docs/). Guides: docs/HYPRLAND_GUIDE.md, docs/AI_GUIDE.md, docs/STATUS.md.
- Hyprland config ~/.config/hypr (generated from ~/KadaOS/config; theme via scripts/theme.py). Self-test: bash ~/KadaOS/scripts/desktop-check.sh
- Services: Docker, Tailscale, Ollama (user: ollama-local), system-adapt (power/focus/health), swaync, waybar, hypridle.
- Fans/thermals are controlled by the HP firmware (no Linux fan control); ~2000-2600 RPM is the normal idle speed.
  Heat/fan noise mostly comes from CPU/GPU load or the power profile (Super+Shift+P). The local AI model on the GPU draws 10-35 W while busy
  and unloads after 5 idle min (`fai unload` frees it now).
- Backups: restic → external HDD /mnt/backup-hdd (~/Scripts/backup.sh). Power modes: Super+Shift+P. Settings app: Super+I.
"""
    SYSINFO.parent.mkdir(parents=True, exist_ok=True); SYSINFO.write_text(info); return info

SYS_PROMPT = """You are the built-in assistant of the user's Linux laptop. You can inspect it LIVE with tools.
Facts:
{info}
Rules:
- For questions about this machine, FIRST call `status` (live overview). Then, only if you need more detail,
  call `run` with read-only commands (e.g. `df -h`, `free -h`, `systemctl --failed`,
  `journalctl -b -p err`, `nmcli device`, `upower -i /org/freedesktop/UPower/devices/battery_BAT0`, `nvidia-smi`,
  `ps -eo pid,comm,%cpu,%mem --sort=-%mem`, `hyprctl monitors`). Use `search_docs` for questions about the KadaOS setup.
- You cannot change anything. Never claim you did. When a fix is needed, give the exact command(s) for the user to run
  (mark ones that need sudo). Prefer the setup's own tools/shortcuts when they exist.
- Only report problems you actually observed NOW. Old journal lines may be from earlier sessions — confirm with `status`
  (its failed-services line is current) before calling something broken. Never give generic advice (update BIOS,
  reinstall packages, "check logs") unless the evidence points there.
- Be concise and concrete: a short diagnosis with the numbers you observed, then the fix. No filler."""

TOOLS = [
    {"type": "function", "function": {"name": "status", "description": "Get a live overview: battery (with time left), power profile, temperatures, GPU, memory, disk, load, failed services, network, top processes. Call this FIRST for any question about the laptop.",
     "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "run", "description": "Run ONE read-only diagnostic shell command (no pipes, no sudo) and get its output.",
     "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "e.g. 'df -h' or 'systemctl --failed'"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "search_docs", "description": "Search the user's KadaOS setup docs and files by meaning.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

# Setup questions need the current docs, not history: reviews, handoffs, inventories, plans (proposals)
# and reference specs describe past or intended states and used to outrank the real guides.
SETUP_DOCS = HOME / "KadaOS/docs"
HISTORICAL = re.compile(r"(^|/)(reviews|plans|reference)/|HANDOFF|inventory-|PROMPT|PROGRESS|HEALTH_REPORT|INSTALL_MANIFEST")
def search_setup_docs(query, n=4):
    try: res = search(query, n * 4, SETUP_DOCS)
    except Exception as e: return f"search unavailable: {e}"
    cur = [(p, t) for _, p, t in res if not HISTORICAL.search(os.path.relpath(p, SETUP_DOCS))][:n]
    if not cur: return "No current setup doc matches. Say you could not find it in the docs; do not guess."
    return "\n\n".join(f"{p}\n{t[:700]}" for p, t in cur)

class MdOut:
    """`show` for streamed answers: live-rendered Markdown in a terminal (rich), plain text when piped."""
    def __init__(self):
        self.buf, self.live, self.started = "", None, False
        if not sys.stdout.isatty(): return
        try:
            from rich.console import Console
            from rich.live import Live
            from rich.markdown import Heading, Markdown
            from rich.text import Text
        except ImportError: return
        class LeftHeading(Heading):                       # rich centres headings; terminals read better left-aligned
            def __rich_console__(self, console, options):
                t = self.text; t.justify = "left"
                t.stylize("bold #e5b567" if self.tag in ("h1", "h2") else "bold")
                if self.tag in ("h1", "h2"): yield Text("")
                yield t
        class Md(Markdown):
            elements = {**Markdown.elements, "heading_open": LeftHeading}
        self.Md, self.Text = (lambda s: Md(s, code_theme="monokai", hyperlinks=True)), Text
        self.con = Console(highlight=False)
        self.live = Live(console=self.con, refresh_per_second=12, transient=True, vertical_overflow="crop")

    def __call__(self, s="", end="\n", flush=False):
        if not self.live: print(s, end=end, flush=True); return
        if end == "":                                     # a streamed token
            self.buf += s
            if not self.started: self.live.start(); self.started = True
            self.live.update(self.Md(clean(self.buf)))
        else:                                             # a status line (tool call): keep the order on screen
            self.flush(); self.con.print(self.Text.from_ansi(s))

    def flush(self):
        if self.started: self.live.stop(); self.started = False
        if self.live and clean(self.buf): self.con.print(self.Md(clean(self.buf)))
        self.buf = ""


def system_agent(question, text="", show=print, max_steps=6, snapshot=""):
    prompt = SYS_PROMPT.format(info=sysinfo())
    if snapshot:
        prompt = prompt.replace("FIRST call `status` (live overview).", "Use the supplied live status snapshot first.")
    msgs = [{"role": "system", "content": prompt}]
    user = (f"<live_status>\n{snapshot}\n</live_status>\n" if snapshot else "") + (f"<text>\n{text.strip()}\n</text>\n" if text else "") + question
    msgs.append({"role": "user", "content": user})
    ensure_server()
    for step in range(max_steps + 1):
        body = {"model": CFG["model"], "messages": msgs, "stream": True, "think": False, "keep_alive": CFG["keep_alive"],
                "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": 900, "repeat_penalty": 1.1}}
        if step < max_steps: body["tools"] = TOOLS
        content, calls = "", []
        with _req("/api/chat", body, timeout=120) as resp:
            for line in resp:
                if not line.strip(): continue
                j = json.loads(line)
                if "error" in j: raise RuntimeError(f"model error: {j['error']}")
                m = j.get("message", {})
                if m.get("tool_calls"): calls += m["tool_calls"]
                t = m.get("content", "")
                if t and not calls: content += t; show(t, end="", flush=True)
                if j.get("done"): break
        if not calls:
            return clean(content)
        msgs.append({"role": "assistant", "content": content, "tool_calls": calls})
        for c in calls:
            fn = c.get("function", {}).get("name", ""); args = c.get("function", {}).get("arguments") or {}
            if isinstance(args, str):
                try: args = json.loads(args)
                except Exception: args = {"command": args}
            if not isinstance(args, dict): args = {}
            if fn == "status":
                show(f"{C['dim']}  ⟩ checking system status{C['off']}", flush=True); out = system_status()
            elif fn == "run":
                cmd = args.get("command", ""); show(f"{C['dim']}  ⟩ {cmd}{C['off']}", flush=True)
                out = run_readonly(cmd)
            elif fn == "search_docs":
                qq = args.get("query", ""); show(f"{C['dim']}  ⟩ searching docs: {qq}{C['off']}", flush=True)
                out = search_setup_docs(qq)
            else: out = "unknown tool"
            msgs.append({"role": "tool", "content": out, "tool_name": fn})
    return clean(content)

def cmd_sys(a):
    text = read_text(a.text_file)
    out = MdOut()
    try: system_agent(" ".join(a.question) or "Give me a quick health overview of this laptop.", text, show=out)
    finally: out.flush()
    print()

# ───────────────────────── semantic search ─────────────────────────
TEXT_EXT = {".md", ".txt", ".rst", ".org", ".py", ".sh", ".zsh", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml",
            ".ini", ".conf", ".cfg", ".go", ".rs", ".java", ".kt", ".dart", ".c", ".h", ".cpp", ".hpp", ".cs", ".sql", ".html",
            ".css", ".scss", ".csv", ".tex", ".env.example", ".dockerfile", ".tf", ".lua", ".rb", ".php", ".swift", ".vue", ".svelte"}
DOC_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".epub"}
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "target", "dist", "build", ".next", ".cache", "snap",
             ".dart_tool", ".gradle", ".idea", "vendor", ".mypy_cache", ".pytest_cache", "site-packages"}
MARKITDOWN = HOME / "Tools/markitdown/.venv/bin/markitdown"

def db():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DATA / "index.db")
    con.execute("CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, mtime REAL, size INT)")
    con.execute("CREATE TABLE IF NOT EXISTS chunks(path TEXT, pos INT, text TEXT, vec BLOB)")
    con.execute("CREATE INDEX IF NOT EXISTS ch_path ON chunks(path)")
    con.execute("CREATE TABLE IF NOT EXISTS search_meta(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(path UNINDEXED, text, content='chunks', content_rowid='rowid')")
    con.execute("""CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
        INSERT INTO chunks_fts(rowid,path,text) VALUES(new.rowid,new.path,new.text); END""")
    con.execute("""CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts,rowid,path,text) VALUES('delete',old.rowid,old.path,old.text); END""")
    if not con.execute("SELECT 1 FROM search_meta WHERE key='fts5_v1'").fetchone():
        con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        con.execute("INSERT INTO search_meta VALUES('fts5_v1','ready')")
        con.commit()
    return con

def extract(p):
    ext = p.suffix.lower()
    if ext in DOC_EXT:
        if not MARKITDOWN.exists(): return ""
        try: return subprocess.run([str(MARKITDOWN), str(p)], capture_output=True, text=True, timeout=90).stdout
        except Exception: return ""
    try: return p.read_text(errors="replace")
    except Exception: return ""

def chunks_of(text, size=1200, overlap=150):
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    out, i = [], 0
    while i < len(text) and len(out) < 200:
        out.append(text[i:i + size]); i += size - overlap
    return [c for c in out if len(c.strip()) > 40]

def sensitive_index_path(path):
    """Exclude credential files without excluding projects such as 'tokenizer'."""
    path = Path(path)
    if any(p in {'.ssh', '.gnupg', '.aws', 'secrets', 'credentials'} for p in path.parts): return True
    return bool(re.fullmatch(
        r"(?:\.env(?:\..*)?|auth\.json|credentials(?:\..*)?|(?:secrets?|passwords?|tokens?)(?:\.(?:json|ya?ml|toml|ini|conf|txt))?|id_(?:rsa|ed25519)(?:\.pub)?|.*\.(?:pem|key|p12|pfx|age))",
        path.name, flags=re.I))


def walk():
    for root in CFG["search_roots"]:
        r = Path(os.path.expanduser(root))
        if not r.exists(): continue
        for dp, dns, fns in os.walk(r):
            dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
            for f in fns:
                p = Path(dp) / f
                if p.is_symlink() or sensitive_index_path(p): continue
                ext = p.suffix.lower()
                if ext in TEXT_EXT or ext in DOC_EXT or f.lower() in ("readme", "makefile", "dockerfile"):
                    yield p

def index_on_ac(root=Path("/sys/class/power_supply"), interval=30):
    """Conservative charger gate with the same HP zero-watt workaround as adapt."""
    def read(p):
        try: return p.read_text().strip()
        except OSError: return ""
    batteries = [p for p in root.glob("*") if read(p / "type") == "Battery"]
    previous = None
    for attempt in range(4):
        if any(read(p / "type") in ("Mains", "USB") and read(p / "online") == "1" for p in root.glob("*")):
            return True
        if not batteries: return False
        energies = []
        for bat in batteries:
            if read(bat / "status") in ("Charging", "Full", "Not charging"):
                continue
            try:
                watts = int(read(bat / "power_now"))
                capacity = int(read(bat / "capacity"))
                energy = int(read(bat / "energy_now"))
            except ValueError: return False
            if watts > 500000: return False
            if capacity < 98: energies.append(energy)
        if not energies: return True
        if previous is not None and sum(energies) < previous: return False
        previous = sum(energies)
        if attempt < 3: time.sleep(interval)
    return True


def cmd_index(a):
    import numpy as np
    if getattr(a, "on_ac", False) and not index_on_ac():
        print("Index skipped: running on battery or charger status is uncertain")
        return
    con = db(); seen = set(); n_new = 0; t0 = time.time()
    known = {r[0]: r[1] for r in con.execute("SELECT path, mtime FROM files")}
    maxb = CFG["search_max_mb"] * 1024 * 1024
    for p in walk():
        try: st = p.stat()
        except OSError: continue
        sp = str(p)
        if st.st_size > maxb or st.st_size == 0: continue
        seen.add(sp)
        if not a.full and known.get(sp) == st.st_mtime: continue
        text = extract(p)
        cs = chunks_of(f"{p.name}\n{text}")
        con.execute("DELETE FROM chunks WHERE path=?", (sp,))
        for i in range(0, len(cs), 32):
            batch = cs[i:i + 32]
            vecs = np.array(embed(batch), dtype=np.float32)
            vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9
            con.executemany("INSERT INTO chunks VALUES(?,?,?,?)", [(sp, i + j, c, v.tobytes()) for j, (c, v) in enumerate(zip(batch, vecs))])
        con.execute("INSERT OR REPLACE INTO files VALUES(?,?,?)", (sp, st.st_mtime, st.st_size))
        n_new += 1
        if n_new % 20 == 0: con.commit(); print(f"  indexed {n_new} files…", flush=True)
    gone = [p for p in known if p not in seen]
    for p in gone:
        con.execute("DELETE FROM chunks WHERE path=?", (p,)); con.execute("DELETE FROM files WHERE path=?", (p,))
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    print(f"index: {n_new} updated, {len(gone)} removed, {total} files total ({time.time() - t0:.0f}s)")

def project_path(value):
    if not value: return None
    try: path = Path(os.path.expanduser(value)).resolve(strict=True)
    except OSError as e: raise RuntimeError(f"Project is unavailable: {value}") from e
    if not path.is_dir(): raise RuntimeError(f"Project is not a directory: {path}")
    return path

def search(query, n=8, project=None):
    import numpy as np
    con = db()
    scope = project_path(project)
    eligible = {}; rows = []
    sql = "SELECT rowid, path, text, vec FROM chunks"
    params = ()
    if scope is not None:
        sql += " WHERE path >= ? AND path < ?"
        prefix = str(scope) + os.sep
        params = (prefix, prefix + "\uffff")
    for row in con.execute(sql, params):
        path = row[1]
        if path not in eligible:
            p = Path(path)
            eligible[path] = (not sensitive_index_path(p) and p.is_file() and not p.is_symlink()
                              and (scope is None or p.is_relative_to(scope)))
        if eligible[path]: rows.append(row)
    if not rows: return []
    q = np.array(embed([query], "query")[0], dtype=np.float32); q /= np.linalg.norm(q) + 1e-9
    M = np.frombuffer(b"".join(r[3] for r in rows), dtype=np.float32).reshape(len(rows), -1)
    scores = M @ q
    stop = {"the", "and", "for", "from", "with", "what", "which", "where", "when", "how", "does", "can", "into", "this", "that", "are", "was", "who", "why"}
    words = list(dict.fromkeys(w[:-1] if w.endswith("s") and len(w) > 4 else w
                               for w in re.findall(r"\w+", query.lower()) if len(w) > 2 and w not in stop))
    ranks = {}
    if words:
        fts_query = " OR ".join('"' + w.replace('"', '') + '"*' for w in words[:12])
        where = "chunks_fts MATCH ?"
        params = [fts_query]
        if scope is not None:
            prefix = str(scope) + os.sep
            where += " AND substr(path,1,?)=?"
            params.extend([len(prefix), prefix])
        hits = con.execute(f"SELECT rowid FROM chunks_fts WHERE {where} ORDER BY bm25(chunks_fts) LIMIT 400", params)
        ranks = {rowid: rank for rank, (rowid,) in enumerate(hits)}
    best = {}
    for idx in range(len(rows)):
        rowid, path, text = rows[idx][:3]
        lower = text.lower(); name = Path(path).name.lower()
        hits = [lower.find(w) for w in words]
        matched = [pos for pos in hits if pos >= 0]
        # Combine semantic similarity with exact terms. Nearby terms favor the
        # excerpt that actually answers a question over a generic file intro.
        lexical = 0.08 * len(matched) + 0.025 * sum(w in name for w in words)
        if len(matched) >= 2 and max(matched) - min(matched) < 350: lexical += 0.06
        if words and len(matched) == len(words): lexical += 0.05
        if "shortcut" in words or "keyboard" in words or "key" in words:
            subject = [w for w in words if w not in {"shortcut", "keyboard", "key", "hyprland"}]
            if any(re.search(r"\b(super|ctrl|alt)\s*\+", line, re.I) and
                   sum(w in line.lower() for w in subject) >= min(2, len(subject))
                   for line in text.splitlines()):
                lexical += 0.4
        s = float(scores[idx]) + lexical + (0.18 / (1 + ranks[rowid] / 20) if rowid in ranks else 0)
        if path not in best or s > best[path][0]: best[path] = (s, text)
    return sorted(((s, p, t) for p, (s, t) in best.items()), reverse=True)[:n]

def cmd_search(a):
    res = search(" ".join(a.query), a.n, getattr(a, "project", None))
    if a.json: print(json.dumps([{"score": round(s, 3), "path": p, "snippet": " ".join(t.split())[:220]} for s, p, t in res])); return
    if not res: print("No results (run: fai index)"); return
    for s, p, t in res:
        print(f"{C['gold']}{s:.2f}{C['off']}  {p.replace(str(HOME), '~')}\n      {C['dim']}{' '.join(t.split())[:160]}{C['off']}")

def rag_messages(question, project=None):
    """Build one grounded conversation for both terminal and desktop file answers."""
    res = search(question, 6, project)
    if not res: return [], []
    ctx = "\n\n".join(f"[{i + 1}] {p}\n{t}" for i, (_, p, t) in enumerate(res))
    sysmsg = ("Answer the question using ONLY the numbered excerpts from the user's own files. Cite sources like [1]. "
              "If the answer is not there, say so briefly. Use the same excerpts for follow-up questions.")
    return ([{"role": "system", "content": sysmsg},
             {"role": "user", "content": f"{ctx}\n\nQuestion: {question}"}],
            [p for _, p, _ in res])

def cmd_rag(a):
    q = " ".join(a.question)
    messages, sources = rag_messages(q, getattr(a, "project", None))
    if not sources:
        print("No matching indexed files. Run fai index to refresh the index.")
        return
    for t in chat_stream(messages):
        print(t, end="", flush=True)
    print("\n")
    for i, path in enumerate(sources, 1): print(f"{C['dim']}[{i}] {path.replace(str(HOME), '~')}{C['off']}")


def cmd_status(a):
    up = server_up(); print(f"server:  {'up' if up else 'down'}  ({CFG['host']})")
    print(f"model:   {CFG['model']}   embed: {CFG['embed_model']}")
    if up:
        ps = json.loads(_req("/api/ps").read()).get("models", [])
        print("loaded:  " + (", ".join(f"{m['name']} ({m.get('size_vram', 0) / 2**30:.1f} GiB VRAM)" for m in ps) or "none (GPU free)"))
    con = db(); f = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]; c = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"index:   {f} files, {c} chunks  ({DATA / 'index.db'})")

def cmd_unload(a):
    if not server_up(): print("server not running"); return
    for m in json.loads(_req("/api/ps").read()).get("models", []):
        _req("/api/generate", {"model": m["name"], "keep_alive": 0}).read(); print("unloaded", m["name"])


def main():
    import argparse
    ap = argparse.ArgumentParser(prog="fai", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd")
    p = sp.add_parser("ask"); p.add_argument("question", nargs="*"); p.add_argument("--action"); p.add_argument("--text-file")
    p.add_argument("--claude", action="store_true"); p.add_argument("--copy", action="store_true"); p.set_defaults(f=cmd_ask)
    p = sp.add_parser("window"); p.add_argument("--action", default="free"); p.add_argument("--text-file"); p.add_argument("--question")
    p.add_argument("--paste-to"); p.add_argument("--claude", action="store_true")
    p.add_argument("--project"); p.add_argument("--context-label"); p.add_argument("--clipboard", action="store_true"); p.set_defaults(f=cmd_window)
    p = sp.add_parser("cmd"); p.add_argument("words", nargs="*"); p.add_argument("--claude", action="store_true"); p.set_defaults(f=cmd_cmd)
    p = sp.add_parser("why"); p.add_argument("command", nargs="*"); p.add_argument("--code"); p.set_defaults(f=cmd_why)
    p = sp.add_parser("handoff"); p.add_argument("command", nargs="*"); p.add_argument("--answer", action="store_true"); p.set_defaults(f=cmd_handoff)
    p = sp.add_parser("index"); p.add_argument("--full", action="store_true"); p.add_argument("--on-ac", action="store_true"); p.set_defaults(f=cmd_index)
    p = sp.add_parser("search"); p.add_argument("query", nargs="+"); p.add_argument("-n", type=int, default=8)
    p.add_argument("--json", action="store_true"); p.add_argument("--project"); p.set_defaults(f=cmd_search)
    p = sp.add_parser("rag"); p.add_argument("question", nargs="+"); p.add_argument("--project"); p.set_defaults(f=cmd_rag)
    p = sp.add_parser("sys"); p.add_argument("question", nargs="*"); p.add_argument("--text-file"); p.set_defaults(f=cmd_sys)
    sp.add_parser("status").set_defaults(f=cmd_status); sp.add_parser("unload").set_defaults(f=cmd_unload)
    a = ap.parse_args()
    if not a.cmd: ap.print_help(); return
    try: a.f(a)
    except RuntimeError as e: sys.exit(f"fai: {e}")
    except KeyboardInterrupt: print()
    except urllib.error.URLError as e: sys.exit(f"fai: cannot reach Ollama: {e}")

if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)          # `ai … | head` ends quietly instead of BrokenPipeError
    main()
