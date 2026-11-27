#!/usr/bin/env python3
"""myos-run: Super+Space, the one way into everything on this laptop.

Type anything. It searches apps, every feature and action, every keyboard shortcut (read live from the Hyprland
config, with the keys shown so you learn them), Settings pages, config files, projects, open windows, recent and
indexed files, and clipboard history ("clip …"). It answers maths, conversions, hashes and emoji inline, opens
websites, runs "> command" in a terminal, asks the assistant with "? question", and when nothing matches well
Enter searches Google in Chrome ("yt …", "gh …", "w …", "maps …" pick another engine). What you pick ranks higher
next time (history: ~/.local/state/myos/run-history.json). Type "help" for the cheat sheet.

Pure providers (calc / hashes / base conversion / exec parsing) are importable and unit-tested.
"""
import ast, math, operator, hashlib, os as _os, re, shlex, sys

# ───────────────────────── calculator (safe, tested) ─────────────────────────
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {k: getattr(math, k) for k in ("sqrt", "sin", "cos", "tan", "log", "log2", "log10", "exp",
                                        "floor", "ceil", "fabs", "factorial", "radians", "degrees")}
_FUNCS["abs"] = abs; _FUNCS["round"] = round
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

def _eval(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("bad constant")
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    raise ValueError("unsupported expression")

def calc(query):
    """Evaluate an arithmetic expression safely. Returns a formatted string, or None if not math."""
    q = query.strip().rstrip("=").strip()
    if not q or not re.search(r"\d", q) or not re.fullmatch(r"[0-9eiptau.,_\s+\-*/%()^a-z]+", q):
        return None
    if not re.search(r"[-+*/%^]|sqrt|log|sin|cos|tan|exp|factorial|abs|round|ceil|floor", q):
        return None  # a bare number or word is not a calculation
    expr = q.replace("^", "**").replace(",", "")
    try:
        val = _eval(ast.parse(expr, mode="eval").body)
    except Exception:
        return None
    if isinstance(val, float):
        val = round(val, 10)
        if val == int(val):
            val = int(val)
    return f"= {val:,}" if isinstance(val, int) else f"= {val:,}"

# ───────────────────────── hashing (tested) ─────────────────────────
_HASHES = ("md5", "sha1", "sha256", "sha512")

def hash_q(query):
    """"sha256 hello" -> the digest. Returns (algo, digest) or None."""
    m = re.match(r"\s*(md5|sha1|sha256|sha512)\s+(.+)", query, re.I | re.S)
    if not m:
        return None
    algo = m.group(1).lower()
    return algo, hashlib.new(algo, m.group(2).encode()).hexdigest()

# ───────────────────────── base conversion (tested) ─────────────────────────
def _parse_num(tok):
    tok = tok.strip().lower().replace("_", "")
    if tok.startswith("0x"): return int(tok, 16)
    if tok.startswith("0b"): return int(tok, 2)
    if tok.startswith("0o"): return int(tok, 8)
    return int(tok)

def base_q(query):
    """"255 to hex", "0x1f to dec", "0b1010 to bin"… -> converted string, or None."""
    m = re.match(r"\s*(\S+)\s+(?:to|in|as)\s+(hex|dec|bin|oct|decimal|binary|octal|hexadecimal)\s*$", query, re.I)
    if not m:
        return None
    try:
        n = _parse_num(m.group(1))
    except ValueError:
        return None
    t = m.group(2).lower()
    if t in ("hex", "hexadecimal"): return f"{n:#x}"
    if t in ("bin", "binary"): return f"{n:#b}"
    if t in ("oct", "octal"): return f"{n:#o}"
    return f"{n:,}"

# ───────────────────────── unit conversion (tested) ─────────────────────────
# factor to a base unit per category (temperature handled separately)
_UNITS = {
    "length": ({"mm": .001, "cm": .01, "m": 1, "km": 1000, "in": .0254, "inch": .0254, "ft": .3048,
                "foot": .3048, "feet": .3048, "yd": .9144, "mi": 1609.344, "mile": 1609.344, "miles": 1609.344}, "m"),
    "mass":   ({"mg": .001, "g": 1, "kg": 1000, "lb": 453.592, "lbs": 453.592, "oz": 28.3495, "st": 6350.29}, "g"),
    "data":   ({"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4,
                "kib": 1024, "mib": 1024**2, "gib": 1024**3}, "B"),
    "time":   ({"ms": .001, "s": 1, "sec": 1, "min": 60, "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600,
                "day": 86400, "days": 86400, "week": 604800, "weeks": 604800}, "s"),
}
def _fmt(n):
    n = round(n, 6)
    return f"{int(n):,}" if n == int(n) else f"{n:,}"

def unit_q(query):
    """"10 km to mi", "100 c to f", "5 kg to lb", "1 gb to mb" -> converted string, or None."""
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*([a-z°]+)\s+(?:to|in|as)\s+([a-z°]+)\s*$", query, re.I)
    if not m:
        return None
    val = float(m.group(1)); a = m.group(2).lower().strip("°"); b = m.group(3).lower().strip("°")
    if a in ("c", "f", "k") and b in ("c", "f", "k"):
        celsius = {"c": val, "f": (val - 32) / 1.8, "k": val - 273.15}[a]
        out = {"c": celsius, "f": celsius * 1.8 + 32, "k": celsius + 273.15}[b]
        return f"{_fmt(out)} °{b.upper()}"
    for factors, _base in _UNITS.values():
        if a in factors and b in factors:
            return f"{_fmt(val * factors[a] / factors[b])} {b}"
    return None

# ───────────────────────── emoji picker (tested) ─────────────────────────
import unicodedata
_EMOJI_INDEX = None
def _emoji_index():
    global _EMOJI_INDEX
    if _EMOJI_INDEX is None:
        idx = []
        for lo, hi in ((0x1F300, 0x1FAFF), (0x2600, 0x27BF), (0x2190, 0x21FF), (0x2B00, 0x2BFF)):
            for cp in range(lo, hi + 1):
                ch = chr(cp)
                name = unicodedata.name(ch, "")
                if name:
                    idx.append((ch, name.lower()))
        _EMOJI_INDEX = idx
    return _EMOJI_INDEX

def emoji_search(query, limit=12):
    """"emoji heart" or ":fire:" -> [(char, Name)]. Returns [] if the query isn't an emoji search."""
    q = query.strip().lower()
    if q.startswith("emoji"):
        q = q[5:].strip()
    elif q.startswith(":") and len(q) > 1:
        q = q.strip(":").strip()
    else:
        return []
    if not q:
        return []
    words = q.replace("_", " ").split()
    out = [(ch, name) for ch, name in _emoji_index() if all(w in name for w in words)]
    out.sort(key=lambda t: (len(t[1]), t[1]))
    return [(ch, name.title()) for ch, name in out[:limit]]

# ───────────────────────── keyboard shortcuts → searchable actions (tested) ─────────────────────────
_MODS = {"SUPER": "Super", "MOD4": "Super", "WIN": "Super", "CTRL": "Ctrl", "CONTROL": "Ctrl", "SHIFT": "Shift", "ALT": "Alt", "MOD1": "Alt"}
_KEYS = {"space": "Space", "return": "Enter", "grave": "`", "slash": "/", "print": "PrtSc", "tab": "Tab", "escape": "Esc",
         "left": "←", "right": "→", "up": "↑", "down": "↓", "comma": ",", "period": "."}

_MEDIA = {"AudioRaiseVolume": "Volume Up key", "AudioLowerVolume": "Volume Down key", "AudioMute": "Mute key",
          "AudioMicMute": "Mic Mute key", "AudioPlay": "Play key", "AudioPause": "Pause key", "AudioNext": "Next Track key",
          "AudioPrev": "Previous Track key", "AudioStop": "Stop key", "MonBrightnessUp": "Screen Brightness Up key",
          "MonBrightnessDown": "Screen Brightness Down key", "KbdBrightnessUp": "Keyboard Light Up key",
          "KbdBrightnessDown": "Keyboard Light Down key", "Calculator": "Calculator key", "Search": "Search key"}

def combo_label(mods, key):
    """'SUPER CTRL', 'G' -> 'Super + Ctrl + G'."""
    parts = [_MODS.get(m.upper(), m.title()) for m in re.split(r"[\s+_]+", mods.strip()) if m]
    key = key.strip()
    if key.startswith("XF86"):                 # media keys get their plain names
        k = _MEDIA.get(key[4:]) or re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key[4:]) + " key"
    else:
        k = _KEYS.get(key.lower(), key.upper() if len(key) == 1 else key)
    return " + ".join(parts + [k]) if k else " + ".join(parts)

def parse_binds(conf_text):
    """Every described shortcut in a Hyprland config: [{desc, combo, dispatcher, arg}]. Only `bindd…` lines (they carry
    a description); `$variables` are expanded; mouse binds are skipped."""
    variables = dict(re.findall(r"^\s*\$(\w+)\s*=\s*(.+?)\s*(?:#.*)?$", conf_text, re.M))
    expand = lambda s: re.sub(r"\$(\w+)", lambda m: variables.get(m.group(1), m.group(0)), s)
    out = []
    for line in conf_text.splitlines():
        m = re.match(r"^\s*(bind[a-z]*)\s*=\s*(.*)$", line)
        if not m or "d" not in m.group(1)[4:]:
            continue
        parts = [p.strip() for p in expand(m.group(2)).split(",", 4)]
        if len(parts) < 4 or parts[1].lower().startswith("mouse"):
            continue
        out.append({"desc": parts[2], "combo": combo_label(parts[0], parts[1]), "dispatcher": parts[3],
                    "arg": parts[4].split("   #")[0].strip() if len(parts) > 4 else ""})
    return out

# ───────────────────────── ranking: typo-tolerant, learns from use (tested) ─────────────────────────
import difflib, json as _json, math as _math, time as _time

def score(query, title, keywords=""):
    """How well `query` matches an item (higher is better), or None. Every query word must appear in the title or
    keywords, as a substring or a close spelling ('bluetoth' finds Bluetooth)."""
    q = query.lower().strip()
    if not q:
        return None
    t = title.lower()
    hay = t + " " + keywords.lower()
    words = re.findall(r"[\w+#.-]+", hay)
    exact = all(w in hay for w in q.split())
    if not exact:
        for w in q.split():
            if w not in hay and not (len(w) >= 4 and difflib.get_close_matches(w, words, n=1, cutoff=0.78)):
                return None
    if t == q: s = 120
    elif t.startswith(q): s = 100
    elif any(x.startswith(q) for x in re.findall(r"\w+", t)): s = 85
    elif q in t: s = 70
    elif exact and all(any(x.startswith(w) for x in words) for w in q.split()): s = 55
    elif exact: s = 40
    else: s = 20
    return s - min(len(t), 80) / 40

def frecency_boost(entry, now=None):
    """Points for an item you pick often and recently: up to ~30, halving every two weeks unused."""
    if not entry:
        return 0.0
    count, last = entry
    age_days = max(0.0, ((now or _time.time()) - last) / 86400)
    return min(30.0, 8 * _math.log2(1 + count)) * 0.5 ** (age_days / 14)

def bump(history, key, now=None):
    count, _ = history.get(key, (0, 0))
    history[key] = (count + 1, now or _time.time())
    if len(history) > 400:                                   # keep the 300 most recent
        for k, _v in sorted(history.items(), key=lambda kv: kv[1][1])[:len(history) - 300]:
            history.pop(k)
    return history

# ───────────────────────── web search, recent files (tested) ─────────────────────────
import urllib.parse
ENGINES = {"g": ("Google", "https://www.google.com/search?q="), "yt": ("YouTube", "https://www.youtube.com/results?search_query="),
           "gh": ("GitHub", "https://github.com/search?q="), "w": ("Wikipedia", "https://en.wikipedia.org/w/index.php?search="),
           "maps": ("Google Maps", "https://www.google.com/maps/search/"), "img": ("Google Images", "https://www.google.com/search?tbm=isch&q="),
           "ddg": ("DuckDuckGo", "https://duckduckgo.com/?q="), "so": ("Stack Overflow", "https://stackoverflow.com/search?q=")}

def web_search(query):
    """(engine name, url, terms) for a query: 'yt lofi' → YouTube, 'gh hyprland' → GitHub, anything else → Google."""
    q = query.strip()
    head, _, rest = q.partition(" ")
    if head.lower() in ENGINES and rest.strip():
        name, base = ENGINES[head.lower()]; q = rest.strip()
    else:
        name, base = ENGINES["g"]
    return name, base + urllib.parse.quote_plus(q) if "maps" not in base else base + urllib.parse.quote(q), q

def chrome_profile(local_state_text, override=""):
    """Which Chrome profile a search opens in: yours if set in the launcher settings, else the one you used last
    (so Chrome never shows its profile picker and reuses that profile's open window)."""
    try: info = _json.loads(local_state_text).get("profile", {})
    except (ValueError, AttributeError): return override or "Default"
    known = info.get("info_cache", {})
    if override:
        for d, v in known.items():
            if override in (d, v.get("name")): return d
    last = info.get("last_used") or ""
    return last if last in known else (next(iter(known), "Default"))

def looks_like_url(q):
    q = q.strip()
    return bool(re.match(r"^(https?://\S+|www\.\S+|[\w-]+(\.[\w-]+)*\.(com|org|net|io|dev|in|ai|app|co|edu|gov|me|xyz)(/\S*)?)$", q, re.I))

def recent_files(xbel_text, limit=200):
    """Local paths from GTK's recently-used.xbel, newest first."""
    items = re.findall(r'<bookmark href="file://([^"]+)"[^>]*modified="([^"]+)"', xbel_text)
    items.sort(key=lambda x: x[1], reverse=True)
    seen, out = set(), []
    for href, _m in items:
        p = urllib.parse.unquote(href)
        if p not in seen:
            seen.add(p); out.append(p)
    return out[:limit]

# ───────────────────────── commands with values (tested) ─────────────────────────
_UNIT = r"seconds|second|secs|sec|s|minutes|minute|mins|min|m|hours|hour|hrs|hr|h"

def _secs(n, unit):
    u = (unit or "min").lower()
    return int(float(n) * (1 if u.startswith("s") else 3600 if u.startswith("h") else 60))

def _later(secs, title, body):
    return (f"systemd-run --user --quiet --on-active={secs}s --timer-property=AccuracySec=1s "
            f"notify-send -a Reminder -u critical {shlex.quote(title)} {shlex.quote(body)}")

def parse_command(query, now=None):
    """'volume 30', 'brightness 70', 'timer 10 min tea', 'remind me in 20 min to call Ali', 'remind me at 18:30 to …',
    'wifi off', 'bluetooth on', 'dnd on', 'mute', 'kill 3000' -> (title, subtitle, shell command), or None."""
    q = query.strip()
    m = re.fullmatch(r"(?:volume|vol|sound)\s+(\d{1,3})\s*%?", q, re.I)
    if m:
        v = min(int(m[1]), 150)
        return (f"Set volume to {v} %", "Sound", f"wpctl set-mute @DEFAULT_AUDIO_SINK@ 0; wpctl set-volume @DEFAULT_AUDIO_SINK@ {v}%")
    if re.fullmatch(r"(?:mute|unmute|toggle mute)", q, re.I):
        return ("Mute / unmute the sound", "Sound", "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle")
    m = re.fullmatch(r"(?:brightness|bright|screen)\s+(\d{1,3})\s*%?", q, re.I)
    if m:
        v = max(1, min(int(m[1]), 100))
        return (f"Set screen brightness to {v} %", "Display", f"brightnessctl -q set {v}%")
    m = re.fullmatch(r"timer\s+(\d+(?:\.\d+)?)\s*(" + _UNIT + r")?\b\s*(.*)", q, re.I)
    if m:
        secs, label = _secs(m[1], m[2]), m[3].strip() or "Time's up"
        return (f"Timer: {m[1]} {m[2] or 'min'}" + (f" · {label}" if m[3].strip() else ""), "A notification when it ends", _later(secs, "⏰ " + label, f"{m[1]} {m[2] or 'min'} timer"))
    m = re.fullmatch(r"remind me in\s+(\d+(?:\.\d+)?)\s*(" + _UNIT + r")?\b\s+(?:to\s+)?(.+)", q, re.I)
    if m:
        return (f"Remind me in {m[1]} {m[2] or 'min'}: {m[3]}", "A notification at that time", _later(_secs(m[1], m[2]), "Reminder", m[3]))
    m = re.fullmatch(r"remind me at\s+(\d{1,2})[:.](\d{2})\s*(am|pm)?\s+(?:to\s+)?(.+)", q, re.I)
    if m:
        h, mi = int(m[1]) % 24, int(m[2])
        if m[3]: h = h % 12 + (12 if m[3].lower() == "pm" else 0)
        t = _time.localtime(now or _time.time())
        secs = (h * 3600 + mi * 60) - (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)
        day = "Today"
        if secs <= 0: secs, day = secs + 86400, "Tomorrow"
        return (f"Remind me at {h:02d}:{mi:02d}: {m[4]}", day, _later(secs, "Reminder", m[4]))
    m = re.fullmatch(r"(wi-?fi|bluetooth|bt|dnd|do not disturb)\s+(on|off)", q, re.I)
    if m:
        what, on = m[1].lower(), m[2].lower() == "on"
        if what.startswith("wi"): return (f"Wi-Fi {m[2].lower()}", "Network", f"nmcli radio wifi {m[2].lower()}")
        if what in ("bluetooth", "bt"): return (f"Bluetooth {m[2].lower()}", "Bluetooth", f"bluetoothctl power {m[2].lower()}")
        return (f"Do not disturb {m[2].lower()}", "Notifications", "swaync-client -dn" if on else "swaync-client -df")
    m = re.fullmatch(r"(?:kill|stop|free)\s+(?:port\s+)?:?(\d{2,5})", q, re.I)
    if m:
        return (f"Stop what's using port {m[1]}", "Services (refuses the setup's own pieces)", f"{_os.path.expanduser('~')}/.local/bin/services stop-port {m[1]} | xargs -0 notify-send -a Services 'Port {m[1]}'")
    return None

def command_icon(pc):
    """An icon that says what a command does (alarm for timers, a speaker for volume…)."""
    t = pc[0].lower()
    for word, icon in (("timer", "alarm-symbolic"), ("remind", "alarm-symbolic"), ("volume", "audio-volume-high-symbolic"),
                       ("mute", "audio-volume-muted-symbolic"), ("brightness", "display-brightness-symbolic"),
                       ("wi-fi", "network-wireless-symbolic"), ("bluetooth", "bluetooth-symbolic"),
                       ("disturb", "notifications-disabled-symbolic"), ("port", "process-stop-symbolic")):
        if word in t: return icon
    return "emblem-ok-symbolic"

# ───────────────────────── understanding plain language: local AI (tested parts) ─────────────────────────
def cosine(a, b):
    num = sum(x * y for x, y in zip(a, b))
    den = _math.sqrt(sum(x * x for x in a)) * _math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0

def intent_prompt(query, titles):
    return ("You are the search box of a Linux desktop. Pick the ONE action that best does what the user wants, "
            "or 0 if none fits (then the user gets a web search). When they describe a situation, prefer an action or setting "
            "that changes the laptop over opening an app, unless they name the app.\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
            + f'\nUser: "{query}"\nAnswer as JSON {{"pick": number}}.')

def parse_pick(response_text, n):
    """The chosen index (0-based) from the model's JSON answer, or None (no pick / garbage / out of range)."""
    try:
        p = int(_json.loads(response_text).get("pick", 0))
    except (ValueError, TypeError, AttributeError):
        return None
    return p - 1 if 1 <= p <= n else None

def looks_like_sentence(q):
    """Worth asking the AI: a few words of plain language, not a calculation or a path."""
    w = q.split()
    return len(w) >= 3 and not re.search(r"[=*/\\{}<>|]|^[>?]", q) and sum(c.isalpha() for c in q) > len(q) * 0.6

# ───────────────────────── live state on results + "right now" suggestions (tested) ─────────────────────────
def live_sub(title, st):
    """A subtitle with the current state for actions that have one ('On now · Enter turns it off'), else None."""
    on_off = lambda v: "On now · Enter turns it off" if v else "Off now · Enter turns it on"
    if not st: return None
    if title == "Night light: toggle" and "night" in st: return on_off(st["night"])
    if title == "Do not disturb: toggle" and "dnd" in st: return on_off(st["dnd"])
    if title == "Keep awake: toggle" and "awake" in st: return on_off(st["awake"])
    if title.startswith("Top bar: ") and st.get("bar"):
        mode = {"show": "on", "hide": "off", "auto-hide (shows at the top edge)": "auto"}.get(title[9:])
        return "● Current" if mode == st["bar"] else None
    if title.startswith("Profile: ") and st.get("profile"):
        names = {"AI work": "ai", "Battery saver": "battery", "Presenting (no notifications, no sleep)": "present", "Automatic": "auto"}
        return "● Current profile" if names.get(title[9:]) == st["profile"] else None
    if title == "Wi-Fi networks" and "wifi" in st: return f"Connected: {st['wifi']}" if st["wifi"] else "Not connected"
    if title == "Battery health" and st.get("battery"):
        pct, state = st["battery"]; return f"{pct} % · {state.lower()}"
    if title == "Record screen (start / stop)" and st.get("recording"): return "● Recording now · Enter stops it"
    if title == "Storage: free up space" and st.get("disk_free") is not None: return f"{st['disk_free'] / 1e9:.0f} GB free"
    if title == "Agent tasks: give Claude or Codex a task" and st.get("review"): return f"{st['review']} ready to review"
    return None

def suggestions(st, hour):
    """[(action title, why)] worth offering the moment Super+Space opens, most useful first."""
    out = []
    if st.get("recording"): out.append(("Record screen (start / stop)", "Recording now · Enter stops it"))
    if st.get("review"): out.append(("Agent tasks: give Claude or Codex a task", f"{st['review']} agent task(s) ready to review"))
    if st.get("disk_free") is not None and st["disk_free"] < 15e9:
        out.append(("Storage: free up space", f"Only {st['disk_free'] / 1e9:.0f} GB free"))
    bat = st.get("battery")
    if bat and bat[1] == "Discharging" and bat[0] <= 25 and st.get("profile") != "battery":
        out.append(("Profile: Battery saver", f"Battery at {bat[0]} %"))
    if st.get("dnd"): out.append(("Do not disturb: toggle", "Do not disturb is on"))
    if (hour >= 21 or hour < 5) and st.get("night") is False: out.append(("Night light: toggle", "It's late: easier on the eyes"))
    if 6 <= hour < 11: out.append(("What needs me: agents, messages, meetings, warnings", "Start of the day"))
    return out

# ───────────────────────── exec parsing (tested) ─────────────────────────
def clean_exec(exec_line):
    """Strip .desktop field codes (%f %u %U %i %c %k…) from an Exec line and return argv."""
    cleaned = re.sub(r"%[fFuUdDnNickvm]", "", exec_line).strip()
    try:
        return shlex.split(cleaned)
    except ValueError:
        return cleaned.split()

# ───────────────────────── GUI ─────────────────────────
def run_app():
    import gi
    gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango
    import subprocess, time
    from pathlib import Path

    HOME = Path.home()
    S = str(HOME / ".config/hypr/scripts")
    CSS = """
    window.run { border-radius: 18px; background: alpha(#17171a, .92); }  /* dark glass: readable over white pages */
    .run-entry { font-size: 15pt; }
    row.rr { border-radius: 10px; }
    .rr { padding: 9px 12px; }
    .rr:selected, .rr:hover { background: alpha(@accent_bg_color, .20); }
    .rr-title { font-size: 11.5pt; }
    .rr-sub { font-size: 9pt; opacity: .6; }
    .rr-kind { font-size: 8.5pt; opacity: .45; }
    .rr-ai .rr-sub { color: @accent_color; opacity: .95; }
    .keycap { font-size: 8.5pt; font-weight: 600; padding: 1px 7px; border-radius: 6px; background: alpha(white, .08);
              border: 1px solid alpha(white, .14); border-bottom-width: 2px; color: alpha(white, .85); }
    .section { font-size: 8.5pt; font-weight: 700; letter-spacing: .06em; opacity: .5; margin: 8px 6px 2px; }
    .run-foot { font-size: 8.5pt; opacity: .45; }
    row.sec { padding: 0; min-height: 0; background: none; }
    .rr-big { font-size: 13pt; font-weight: 700; font-family: "Adwaita Mono", monospace; }
    """

    def notify(t, b="", i="dialog-information-symbolic"):
        subprocess.run(["notify-send", "-a", "Run", "-i", i, t, b], check=False)

    def copy(text):
        subprocess.run(["wl-copy"], input=text, text=True)

    def sh(cmd):
        subprocess.Popen(["setsid", "sh", "-c", cmd], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    B = f"{HOME}/.local/bin"

    def term(title, cmd):
        """A terminal that runs cmd and waits for Enter (cmd must not contain single quotes)."""
        return f"ptyxis --new-window -T '{title}' -- bash -c '{cmd}; echo; read -r -p \"Enter to close \" _'"

    # action list (kept in sync with actions-modi.sh conceptually)
    ACTIONS = [
        ("Screenshot: area", f"{S}/screenshot.sh area", "camera-photo-symbolic"),
        ("Screenshot: full screen", f"{S}/screenshot.sh full", "camera-photo-symbolic"),
        ("Screenshot: window", f"{S}/screenshot.sh window", "camera-photo-symbolic"),
        ("Screenshot: area + annotate", f"{S}/screenshot.sh edit", "document-edit-symbolic"),
        ("Clipboard history", f"{HOME}/.local/bin/myos-panel clipboard", "edit-paste-symbolic"),
        ("Calendar", f"{HOME}/.local/bin/myos-panel calendar", "x-office-calendar-symbolic"),
        ("Hydration: water breaks and settings", f"{HOME}/.local/bin/myos-hydration panel", "weather-showers-symbolic"),
        ("Hydration: drank water", f"{HOME}/.local/bin/myos-hydration drank", "emblem-ok-symbolic"),
        ("Hydration: pause today", f"{HOME}/.local/bin/myos-hydration pause", "media-playback-pause-symbolic"),
        ("Hydration: resume reminders", f"{HOME}/.local/bin/myos-hydration resume", "media-playback-start-symbolic"),
        ("Pad control: laptop mouse + keyboard on the tablet", f"{HOME}/.config/hypr/scripts/tablet-control.py toggle", "input-mouse-symbolic"),
        ("Pad as second screen", f"{HOME}/.config/hypr/scripts/tablet-display.sh toggle", "video-display-symbolic"),
        ("Wi-Fi networks", f"{HOME}/.local/bin/myos-panel wifi", "network-wireless-symbolic"),
        ("Bluetooth devices", f"{HOME}/.local/bin/myos-panel bluetooth", "bluetooth-symbolic"),
        ("AI Chat", "gtk-launch org.myos.Chat", "chat-message-new-symbolic"),
        ("Ask AI (selected text)", f"{HOME}/.local/bin/ai-menu", "emblem-system-symbolic"),
        ("Talk to the assistant (voice)", f"{HOME}/.local/bin/ai-chat --listen", "audio-input-microphone-symbolic"),
        ("Find files by meaning", f"{HOME}/.local/bin/ai-search", "system-search-symbolic"),
        ("Convert files… (resize, compress, PDF, video, audio)", f"python3 {HOME}/.local/share/myos/fileactions.py", "emblem-shared-symbolic"),
        ("Keep awake: toggle", f"{S}/keep-awake.sh toggle", "weather-clear-symbolic"),
        ("Dictate (voice typing)", f"{HOME}/.local/bin/ai-dictate toggle", "audio-input-microphone-symbolic"),
        ("Lock screen", f"{S}/lock.sh", "system-lock-screen-symbolic"),
        ("What needs me: agents, messages, meetings, warnings", f"{HOME}/.local/bin/myos-panel inbox", "mail-unread-symbolic"),
        ("Top bar: show", f"{S}/bar.sh on", "view-reveal-symbolic"),
        ("Top bar: hide", f"{S}/bar.sh off", "view-conceal-symbolic"),
        ("Top bar: auto-hide (shows at the top edge)", f"{S}/bar.sh auto", "view-fullscreen-symbolic"),
        ("Night light: toggle", f"{S}/nightlight.sh", "weather-clear-night-symbolic"),
        ("Power mode: cycle", f"{S}/power-profile.sh cycle", "power-profile-performance-symbolic"),
        ("Do not disturb: toggle", "swaync-client -d -sw", "notifications-disabled-symbolic"),
        ("Change wallpaper", f"{S}/wallpaper.sh", "preferences-desktop-wallpaper-symbolic"),
        ("Settings", f"{S}/settings.sh", "preferences-system-symbolic"),
        ("Shortcuts (cheatsheet)", f"{S}/keyhelp.sh", "input-keyboard-symbolic"),
        ("Power menu", f"{S}/power-menu.sh", "system-shutdown-symbolic"),
        # build program 2026-11: every feature's actions (docs/plans/build-program-2026-11.md)
        ("Record screen (start / stop)", f"{S}/record.sh toggle", "media-record-symbolic"),
        ("Long jobs: list", term("jobs", f"{B}/job ls"), "system-run-symbolic"),
        ("Storage: free up space", f"{B}/myos-panel storage", "drive-harddisk-symbolic"),
        ("Security checkup", f"{B}/myos-panel security", "security-high-symbolic"),
        ("Battery health", f"{B}/myos-panel battery", "battery-good-symbolic"),
        ("Profile: AI work", f"{B}/profile ai", "applications-science-symbolic"),
        ("Profile: Battery saver", f"{B}/profile battery", "battery-good-symbolic"),
        ("Profile: Presenting (no notifications, no sleep)", f"{B}/profile present", "video-display-symbolic"),
        ("Profile: Automatic", f"{B}/profile auto", "emblem-synchronizing-symbolic"),
        ("Displays: arrange", "nwg-displays", "video-display-symbolic"),
        ("Displays: remember this layout", f"{B}/monitors save && notify-send -a Displays 'Layout saved' 'It comes back when these displays are connected'", "video-display-symbolic"),
        ("Projects: every repo, CI and PRs", f"{B}/myos-panel projects", "folder-symbolic"),
        ("Services: dev servers, ports, Docker", f"{B}/myos-panel services", "network-server-symbolic"),
        ("New project…", term("new project", f'read -r -p "Project name: " n && {B}/new-project "$n" --open'), "folder-new-symbolic"),
        ("Agent tasks: give Claude or Codex a task", f"{B}/myos-panel tasks", "system-run-symbolic"),
        ("Password vault (KeePassXC)", "sh -c 'command -v keepassxc >/dev/null && exec keepassxc || notify-send -a Vault KeePassXC Run:\\ bash\\ scripts/phase14-secrets.sh'", "dialog-password-symbolic"),
        ("Network trust: Home / Work / Public", f"{B}/trust menu", "network-wireless-encrypted-symbolic"),
        ("USB devices (USB guard)", term("USB devices", f"{B}/usb-guard"), "drive-removable-media-symbolic"),
        ("Remote devices (SSH)", f"{B}/myos-panel remote", "network-server-symbolic"),
        ("Phone", f"{B}/myos-panel phone", "phone-symbolic"),
        ("Who is on my network", term("network", f"{B}/board net"), "network-workgroup-symbolic"),
        ("Security lab: engagement report", term("report", f"{B}/seclab report"), "x-office-document-symbolic"),
        ("Security lab: Wi-Fi adapters for testing", term("wifi", f"{B}/seclab wifi"), "network-wireless-symbolic"),
        ("Security lab: isolated lab network up", term("lab", f"{B}/seclab lab up"), "network-wired-symbolic"),
        ("CTF workspace…", term("CTF", f'read -r -p "CTF name: " n && {B}/seclab ctf "$n"'), "applications-games-symbolic"),
        ("Downloads: tidy (preview)", term("tidy", f"{B}/tidy"), "folder-download-symbolic"),
        ("Downloads: tidy now", f"{B}/tidy --apply | tail -1 | xargs -0 notify-send -a Downloads 'Downloads tidied'", "folder-download-symbolic"),
        ("Border signals: show them all (look away, attention, done, fail, battery)", f"{B}/border-signal test", "starred-symbolic"),
        ("Zen: import from Chrome (bookmarks, history, passwords; pick the profile)", f"{B}/zen --migration", "web-browser-symbolic"),
    ]
    def ask(title, prompt, cmd):
        """A small terminal that asks one thing ($a) and runs cmd with it (no single quotes in cmd)."""
        return term(title, f'read -r -p "{prompt}: " a && [ -n "$a" ] && {cmd}')

    SCR = f"{HOME}/Scripts"
    REPO_S = f"{HOME}/KadaOS/scripts"
    # the rest of the setup, so every part of it is one search away (title, command, icon, search words)
    TOOLS = [
        # assistant / local AI
        ("Read text from the screen (OCR, copies it)", f"{B}/ai-ocr copy", "scanner-symbolic", "ocr text image screenshot malayalam"),
        ("Ask AI about text on the screen", f"{B}/ai-ocr ask", "scanner-symbolic", "ocr explain translate"),
        ("Ask a spoken question", f"{B}/ai-voice", "audio-input-microphone-symbolic", "voice speak talk"),
        ("Suggest a shell command…", ask("command", "What do you want to do", f'{B}/fai cmd "$a"'), "utilities-terminal-symbolic", "how do i terminal command"),
        ("Answer from my own files…", ask("my files", "Question", f'{B}/fai rag "$a"'), "system-search-symbolic", "rag documents notes"),
        ("Chat with the local AI in a terminal", term("local AI", f"{B}/fai-chat"), "utilities-terminal-symbolic", "fai chat"),
        ("Local AI status (model, GPU, index)", term("AI status", f"{B}/fai status"), "applications-science-symbolic", "ollama model gpu"),
        ("Free the GPU (unload the local model)", f"{B}/fai unload && notify-send -a AI 'Model unloaded'", "applications-science-symbolic", "vram memory ollama"),
        ("Rebuild the file search index", term("index", f"{B}/fai index"), "system-search-symbolic", "semantic search files"),
        # coding agents
        ("Coding agent: pick a project and an agent", f"{B}/agent-menu", "utilities-terminal-symbolic", "claude codex antigravity agy tmux session"),
        ("Coding agent sessions", term("agents", f"{B}/agent ls"), "utilities-terminal-symbolic", "claude codex tmux"),
        ("Second opinion: another agent reviews a project's changes…", ask("review", "Project folder (e.g. ~/Projects/app)", f'cd "${{a/#\\~/$HOME}}" && {B}/agent-review'), "system-search-symbolic", "code review diff"),
        ("Make a repo ready for agents…", ask("agents", "Project folder", f'{B}/proj-init "${{a/#\\~/$HOME}}"'), "folder-new-symbolic", "agents.md handoff"),
        # remote devices
        ("Remote devices: list", term("devices", f"{B}/board ls"), "network-server-symbolic", "ssh pi raspberry board"),
        ("Remote: terminal on a device…", ask("ssh", "Device name", f'{B}/board ssh "$a"'), "utilities-terminal-symbolic", "ssh pi"),
        ("Remote: VS Code on a device…", ask("code", "Device name", f'{B}/board code "$a"'), "folder-symbolic", "ssh remote code"),
        ("Remote: device files…", ask("files", "Device name", f'{B}/board files "$a"'), "folder-remote-symbolic", "sftp"),
        ("Remote: device details…", ask("info", "Device name", f'{B}/board info "$a"'), "network-server-symbolic", "temperature disk"),
        ("Remote: what's wrong (doctor)", term("doctor", f"{B}/board doctor"), "dialog-question-symbolic", "ssh fix"),
        ("Serial console (Pi / microcontroller)", term("serial", f"{B}/board serial"), "utilities-terminal-symbolic", "uart usb tty arduino esp32"),
        ("My network info (IPs, DNS)", term("network", f"{B}/board net info"), "network-wired-symbolic", "ip address dns gateway"),
        # phone
        ("Phone: send a file…", ask("phone", "File or link", f'{B}/phone send "${{a/#\\~/$HOME}}"'), "phone-symbolic", "share transfer"),
        ("Phone: send the clipboard", f"{B}/phone clip", "phone-symbolic", "copy paste"),
        ("Phone: ring it (find my phone)", f"{B}/phone find", "phone-symbolic", "lost find"),
        ("Phone: mirror its screen", f"{B}/phone mirror", "phone-symbolic", "scrcpy cast"),
        ("Phone: get its latest downloads", term("phone", f"{B}/phone get 5"), "phone-symbolic", "files download"),
        ("Phone: send an alert…", ask("alert", "Message", f'{B}/phone push "$a"'), "phone-symbolic", "ntfy notify"),
        ("Phone: what's wrong (doctor)", term("phone", f"{B}/phone doctor"), "dialog-question-symbolic", "kde connect adb fix"),
        # security lab (the tools themselves are listed from the catalogue below)
        ("Security lab menu", f"{B}/seclab menu", "security-high-symbolic", "pentest workbench"),
        ("Security lab: new engagement…", ask("engagement", "Engagement name", f'{B}/seclab new "$a"'), "folder-new-symbolic", "pentest client scope"),
        ("Security lab: add to scope…", ask("scope", "Targets (IP, CIDR, domain)", f"{B}/seclab scope add $a"), "list-add-symbolic", "authorized targets"),
        ("Security lab: record a finding…", ask("finding", "Finding title", f'{B}/seclab finding "$a"'), "document-new-symbolic", "vulnerability report"),
        ("Security lab: findings", term("findings", f"{B}/seclab findings"), "x-office-document-symbolic", "vulnerabilities"),
        ("Security lab: isolated lab network down", term("lab", f"{B}/seclab lab down"), "network-wired-symbolic", "vm libvirt"),
        ("Security lab: ask the AI…", ask("security AI", "Question", f'{B}/seclab ai "$a"'), "chat-message-new-symbolic", "pentest explain"),
        ("Scan a repo for secrets…", ask("secrets", "Repo folder", f'{B}/secret-scan --all "${{a/#\\~/$HOME}}"'), "dialog-password-symbolic", "gitleaks keys tokens leak"),
        # jobs, disk, ports
        ("Run a long command without freezing the desktop…", ask("job", "Command", f"{B}/job -- $a"), "system-run-symbolic", "build compile memory background"),
        ("Disk: what can be freed", term("disk", f"{B}/disk"), "drive-harddisk-symbolic", "space clean"),
        ("Battery health in a terminal", term("battery", f"{B}/battery-health"), "battery-good-symbolic", "wear cycles"),
        ("Security checkup in a terminal", term("security", f"{B}/security-check"), "security-high-symbolic", "audit firewall"),
        ("Who is using a port…", ask("port", "Port", f'{B}/services who "$a"'), "network-server-symbolic", "3000 8080 address in use"),
        # files, drive, backups
        ("Google Drive", "nautilus --new-window ~/GoogleDrive", "folder-remote-symbolic", "gdrive cloud"),
        ("Google Drive: connect / sign in", term("Drive", f"bash {REPO_S}/drive-connect.sh"), "folder-remote-symbolic", "gdrive rclone"),
        ("Back up now (external drive)", term("backup", f"{SCR}/backup.sh"), "drive-harddisk-symbolic", "restic backup"),
        ("Check the backups", term("backup", f"{SCR}/verify-backups.sh"), "drive-harddisk-symbolic", "restic verify restore"),
        # robotics
        ("ROS 2 terminal (Lyrical)", f"ptyxis --new-window -T ROS -- bash -c 'source {SCR}/ros-lyrical-env.sh; exec bash'", "utilities-terminal-symbolic", "ros robot colcon"),
        ("Space ROS container", term("Space ROS", f"{SCR}/space-ros-shell.sh"), "utilities-terminal-symbolic", "ros docker space"),
        # developer tools
        ("Git in a terminal (lazygit)…", ask("lazygit", "Repo folder", f'cd "${{a/#\\~/$HOME}}" && lazygit'), "utilities-terminal-symbolic", "git commit branch"),
        ("Docker in a terminal (lazydocker)", f"ptyxis --new-window -T docker -- lazydocker", "utilities-terminal-symbolic", "containers"),
        ("Jupyter Lab", term("jupyter", "jupyter-lab"), "applications-science-symbolic", "notebook python"),
        ("System monitor (btop)", "ptyxis --new-window -T btop -- btop", "utilities-system-monitor-symbolic", "cpu ram processes task manager"),
        # help and the setup itself
        ("Terminal tools guide", term("help", "helpme"), "help-browser-symbolic", "how to cheat sheet"),
        ("System info", term("system", "sysinfo"), "computer-symbolic", "fastfetch specs"),
        ("Check the desktop setup", term("check", f"bash {REPO_S}/desktop-check.sh"), "emblem-default-symbolic", "health test"),
        ("Run every setup test", term("tests", f"bash {HOME}/KadaOS/tests/run-all.sh --quick"), "emblem-default-symbolic", "test suite"),
        ("Boot and login screens: KadaOS look (asks your password)", term("brand", f"bash {REPO_S}/phase17-brand.sh"), "kadaos", "plymouth gdm logo splash branding startup"),
        ("Boot and login screens: back to Ubuntu's (asks your password)", term("brand", f"bash {REPO_S}/phase17-brand.sh undo"), "edit-undo-symbolic", "plymouth gdm logo splash branding startup"),
        ("Update the system (asks your password)", term("update", "sudo apt update && sudo apt upgrade"), "software-update-available-symbolic", "upgrade apt packages"),
    ]
    LAYOUTS = [("Start: Coding", "Coding"), ("Start: Web dev", "Web dev"),
               ("Start: Research", "Research"), ("Start: Security lab", "Security lab"), ("Start: Wireless", "Wireless")]
    # search words people actually type, for actions whose title doesn't contain them
    KEYWORDS = {"Storage: free up space": "disk space clean delete full cache", "Security checkup": "firewall ports audit",
                "Battery health": "wear cycles charge", "Record screen (start / stop)": "video capture screencast",
                "Network trust: Home / Work / Public": "wifi privacy mac firewall", "Night light: toggle": "blue light warm",
                "Do not disturb: toggle": "dnd mute notifications silence", "Lock screen": "away",
                "Power menu": "shutdown reboot restart logout sleep suspend", "Keep awake: toggle": "caffeine no sleep",
                "Clipboard history": "copy paste", "Agent tasks: give Claude or Codex a task": "ai coding worktree",
                "Services: dev servers, ports, Docker": "containers port kill", "Change wallpaper": "background",
                "Profile: Presenting (no notifications, no sleep)": "presentation talk give a talk meeting demo slides screen share",
                "Security checkup": "firewall ports audit hacked hacking attacker safe secure breach",
                "What needs me: agents, messages, meetings, warnings": "inbox agents finished done waiting messages missed",
                "Profile: AI work": "local model fast performance gpu", "Profile: Battery saver": "save battery last longer unplugged",
                "Network trust: Home / Work / Public": "wifi privacy mac firewall cafe hotel airport public wifi"}
    # Settings pages (Ubuntu's Settings app, opened through settings.sh) + search words
    SETTINGS = [("Wi-Fi", "wifi", "wireless internet network-wireless-symbolic"), ("Network", "network", "ethernet vpn proxy network-wired-symbolic"),
                ("Bluetooth", "bluetooth", "headphones pair bluetooth-symbolic"), ("Displays", "display", "screen monitor resolution scale refresh video-display-symbolic"),
                ("Sound", "sound", "volume audio speaker microphone mic audio-speakers-symbolic"), ("Power", "power", "battery sleep suspend power-profile-balanced-symbolic"),
                ("Mouse & Touchpad", "mouse", "trackpad pointer speed scroll input-mouse-symbolic"), ("Keyboard", "keyboard", "layout language input input-keyboard-symbolic"),
                ("Appearance", "background", "theme dark light wallpaper preferences-desktop-appearance-symbolic"),
                ("Notifications", "notifications", "alerts preferences-system-notifications-symbolic"), ("Apps & default apps", "apps", "default browser permissions application-x-executable-symbolic"),
                ("Printers", "printers", "print printer-symbolic"), ("Privacy & security", "privacy", "location camera screen lock security-high-symbolic"),
                ("Online accounts", "online-accounts", "google login avatar-default-symbolic"), ("Sharing", "sharing", "remote desktop media folder-publicshare-symbolic"),
                ("Accessibility", "universal-access", "zoom large text contrast preferences-desktop-accessibility-symbolic"),
                ("System: date, time, users, about", "system", "clock timezone region language users about updates preferences-system-symbolic"),
                ("Colour (screen calibration)", "color", "colour profile icc applications-graphics-symbolic")]
    # files you might want to change, opened in the editor (live user settings; the desktop's own config is in the repo)
    REPO = HOME / "KadaOS"
    CONFIGS = [("Shortcuts and window rules (Hyprland)", REPO / "config/hypr/hyprland.conf", "keybindings binds hyprland conf"),
               ("Top bar (Waybar)", REPO / "config/waybar/config.jsonc", "waybar bar modules"),
               ("Theme colours (Graphite)", REPO / "scripts/theme.py", "theme colors palette"),
               ("Downloads tidy rules", HOME / ".config/myos/tidy.json", "tidy downloads"),
               ("Monitor layouts", HOME / ".config/myos/monitor-profiles.json", "displays monitors"),
               ("Local AI settings", HOME / ".config/local-ai/config.json", "model ollama assistant"),
               ("Hydration settings", HOME / ".config/myos/hydration.json", "water reminders"),
               ("Border signals settings", HOME / ".config/myos/border-signals.json", "look away eye break 20 minutes reminder outline window border attention"),
               ("Chrome flags (swipes, video decode)", HOME / ".config/chrome-flags.conf", "chrome browser flags wayland gpu"),
               ("Shell (zsh)", HOME / ".zshrc", "terminal aliases path"),
               ("Launcher settings (Chrome profile…)", HOME / ".config/myos/launcher.json", "launcher super space browser chrome profile")]
    apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]
    HISTORY = HOME / ".local/state/myos/run-history.json"
    HYPR_CONF = Path(__import__("os").environ.get("MYOS_HYPR_CONF") or HOME / ".config/hypr/hyprland.conf")
    import shutil as _sh, threading

    LAUNCHER_CONF = HOME / ".config/myos/launcher.json"

    def launcher_conf():
        try: return _json.loads(LAUNCHER_CONF.read_text())
        except (OSError, ValueError): return {}

    def chrome(url):
        """Open url as a new tab in the Chrome you already have (your usual profile, no picker), then bring it forward.
        Chrome starts only if it isn't running."""
        b = _sh.which("google-chrome-stable") or _sh.which("google-chrome")
        if not b: return sh(f"xdg-open {shlex.quote(url)}")
        try: ls = (HOME / ".config/google-chrome/Local State").read_text()
        except OSError: ls = ""
        prof = chrome_profile(ls, launcher_conf().get("browser_profile", ""))
        try:
            wins = [c for c in _json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True).stdout)
                    if c.get("class", "").lower().startswith("google-chrome")]
        except Exception: wins = []
        focus = ""
        if wins:          # the Chrome window you used last (lowest focus history) comes forward, wherever it is
            w = min(wins, key=lambda c: c.get("focusHistoryID", 99))
            focus = f"; sleep 0.4; hyprctl dispatch focuswindow address:{w['address']}"
        sh(f"{b} --profile-directory={shlex.quote(prof)} {shlex.quote(url)}{focus}")

    def editor(path):
        path = Path(path)
        if not path.exists(): path.parent.mkdir(parents=True, exist_ok=True); path.touch()
        sh(f"code {shlex.quote(str(path))}" if _sh.which("code") else f"xdg-open {shlex.quote(str(path))}")

    def open_path(p):
        sh(("nautilus --new-window " if Path(p).is_dir() else "xdg-open ") + shlex.quote(p))

    def hypr_run(dispatcher, arg):
        if dispatcher == "exec": return sh(arg)
        sh("sleep 0.15; hyprctl dispatch " + shlex.quote(dispatcher) + (" " + shlex.quote(arg) if arg else ""))

    def norm(cmd):
        """Same command written two ways (full home path vs ~) counts once."""
        return cmd.replace(str(HOME), "~").replace("$HOME", "~").strip()

    class Catalog:
        """Everything Super+Space can reach. Static parts are built once (and the shortcuts again when the config changes);
        files are indexed in the background so typing never waits."""
        def __init__(self):
            self.items, self.conf_mtime, self.files, self.recent, self.indexed = [], 0, [], [], 0.0
            if not LAUNCHER_CONF.exists():
                try:
                    LAUNCHER_CONF.parent.mkdir(parents=True, exist_ok=True)
                    LAUNCHER_CONF.write_text(_json.dumps({"browser_profile": "", "_browser_profile": "empty = the Chrome profile you "
                                             "used last; or a profile name, e.g. \"Personal\""}, indent=2) + "\n")
                except OSError: pass
            try: self.history = {k: tuple(v) for k, v in _json.loads(HISTORY.read_text()).items()}
            except (OSError, ValueError): self.history = {}
            self.rebuild()
            threading.Thread(target=self.index_files, daemon=True).start()

        def rebuild(self):
            items = []            # (id, title, subtitle, icon, kind, keywords, fn)
            cmds = set()
            for name, cmd, icon in ACTIONS:
                if name.startswith("Hydration:") and not (HOME / ".local/bin/myos-hydration").exists(): continue
                items.append(("a:" + name, name, "Action", icon, "action", KEYWORDS.get(name, ""), lambda cmd=cmd: sh(cmd))); cmds.add(norm(cmd))
            for name, cmd, icon, kw in TOOLS:
                items.append(("a:" + name, name, "Action", icon, "action", kw, lambda cmd=cmd: sh(cmd))); cmds.add(norm(cmd))
            try:                                              # every security tool in the workbench catalogue
                for t in _json.loads((HOME / ".local/share/security-workbench/tools.json").read_text()):
                    n = t["name"]
                    run_it = f"{n}" if t.get("gui") else term(n, f"{B}/seclab {n} --help; echo; exec bash")
                    items.append(("t:" + n, f"Security tool: {n}", f"{t['category']} · " + ("opens it" if t.get("gui") else "help in a terminal"),
                                  "security-high-symbolic", "tool", f"{t['category']} pentest hacking", lambda c=run_it: sh(c)))
            except (OSError, ValueError, KeyError):
                pass
            try:                                              # scan recipes (only against the active engagement's scope)
                for line in subprocess.run([f"{B}/seclab", "recipes"], capture_output=True, text=True, timeout=3).stdout.splitlines():
                    parts = re.split(r"\s{2,}", line.strip())
                    if len(parts) >= 2:
                        items.append(("r:" + parts[0], f"Security recipe: {parts[1]}", f"seclab run {parts[0]} · in scope only", "security-high-symbolic",
                                      "recipe", parts[0] + " scan " + (parts[2].split()[0] if len(parts) > 2 else ""), lambda r=parts[0]: sh(ask("recipe", "Target (must be in scope)", f'{B}/seclab run {r} "$a"'))))
            except Exception:
                pass
            try:
                self.conf_mtime = HYPR_CONF.stat().st_mtime
                for b in parse_binds(HYPR_CONF.read_text()):
                    if norm(b["arg"]) in cmds or "launcher" in b["arg"] or b["desc"] in ("App launcher",): continue
                    items.append(("k:" + b["desc"], b["desc"], f"{b['combo']}  ·  Keyboard shortcut", "input-keyboard-symbolic", "shortcut",
                                  b["combo"] + " " + b["dispatcher"], lambda b=b: hypr_run(b["dispatcher"], b["arg"])))
            except OSError:
                pass
            for title, panel, extra in SETTINGS:
                icon = extra.split()[-1]; kw = " ".join(extra.split()[:-1]) + " settings preferences"
                items.append(("s:" + title, f"Settings: {title}", "Settings", icon, "settings", kw, lambda p=panel: sh(f"{S}/settings.sh {p}")))
            for title, path, kw in CONFIGS:
                items.append(("c:" + title, f"Edit: {title}", str(path).replace(str(HOME), "~"), "document-edit-symbolic", "config",
                              kw + " config edit configure", lambda p=path: editor(p)))
            for label, prof in LAYOUTS:
                items.append(("l:" + label, label, "Work layout", "preferences-system-windows-symbolic", "layout", "workspace",
                              lambda prof=prof: sh(f"{S}/flow.py --ai -- {shlex.quote(prof)}")))
            roots = [HOME / "Projects"]
            for d in sorted([c for r in roots if r.is_dir() for c in r.iterdir() if (c / ".git").exists()] + [REPO]):
                items.append(("p:" + d.name, f"Project: {d.name}", str(d).replace(str(HOME), "~") + "  ·  VS Code + terminal",
                              "folder-symbolic", "project", "repo code git open", lambda d=d: sh(f"{B}/projects open {shlex.quote(str(d))}")))
            for a in apps:
                kw = " ".join(filter(None, [a.get_description() or "", a.get_executable() or "", " ".join(a.get_keywords() if hasattr(a, "get_keywords") and a.get_keywords() else [])]))
                items.append(("app:" + (a.get_id() or a.get_display_name()), a.get_display_name(), a.get_description() or "Application",
                              a.get_icon(), "app", kw, lambda a=a: a.launch([], None)))
            self.items = items
            self.by_id = {it[0]: it for it in items}
            ids = [it[0] for it in items]
            pick = lambda *needles: next((i for n in needles for i in ids if i.lower().startswith("app:") and n in i.lower()), None)
            self.essentials = [x for x in (pick("google-chrome"), pick("ptyxis", "kitty"), pick("nautilus"), pick("code.desktop", "visual-studio-code"),
                                           "a:What needs me: agents, messages, meetings, warnings", "a:Clipboard history", "a:Settings") if x]

        def index_files(self):
            self.indexed = time.time()
            fd = _sh.which("fd") or _sh.which("fdfind")
            try: self.recent = recent_files((HOME / ".local/share/recently-used.xbel").read_text(errors="ignore"))
            except OSError: self.recent = []
            if not fd: return
            ex = sum((["--exclude", e] for e in ("node_modules", ".git", ".cache", "__pycache__", ".venv", "venv", "snap",
                                                 "target", "build", "dist", ".local", ".npm", ".cargo", ".rustup")), [])
            r = subprocess.run([fd, ".", str(HOME), "--max-depth", "7", *ex, "--max-results", "300000"],
                               capture_output=True, text=True, timeout=60)
            self.files = r.stdout.splitlines()

        def remember(self, key):
            bump(self.history, key)
            try:
                HISTORY.parent.mkdir(parents=True, exist_ok=True); HISTORY.write_text(_json.dumps(self.history))
            except OSError: pass

    OLLAMA = _os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    EMBED_CACHE = HOME / ".cache/myos/run-embed.json"

    def ai_conf():
        try: return _json.loads((HOME / ".config/local-ai/config.json").read_text())
        except (OSError, ValueError): return {}

    def ollama(path, body, timeout):
        import urllib.request
        req = urllib.request.Request(OLLAMA + path, _json.dumps(body).encode(), {"Content-Type": "application/json"})
        return _json.loads(urllib.request.urlopen(req, timeout=timeout).read())

    def battery_profile():
        try: return _json.loads((HOME / ".local/state/myos/profile.json").read_text()).get("name") == "battery"
        except (OSError, ValueError): return False

    class Brain:
        """Understands plain language with the local models: embeddings narrow the catalogue to ~25 candidates, the chat
        model picks one. Runs in the background; if the models aren't running it quietly does nothing."""
        def __init__(self, cat):
            self.cat, self.vecs, self.ok, self.down_until = cat, {}, False, 0.0
            try: self.vecs = _json.loads(EMBED_CACHE.read_text())
            except (OSError, ValueError): self.vecs = {}
            threading.Thread(target=self.warm, daemon=True).start()

        def text_of(self, it): return (it[1] + " " + (it[5] or ""))[:200]

        def warm(self):
            c = ai_conf()
            try:
                if _os.environ.get("MYOS_RUN_NO_AI"): raise RuntimeError("AI off")       # tests
                if battery_profile(): raise RuntimeError("Battery profile: the model stays unloaded")
                missing = [self.text_of(it) for it in self.cat.items if self.text_of(it) not in self.vecs]
                for i in range(0, len(missing), 64):
                    r = ollama("/api/embed", {"model": c.get("embed_model", "nomic-embed-text"), "input": missing[i:i + 64], "keep_alive": c.get("keep_alive", "5m")}, 60)
                    self.vecs.update(zip(missing[i:i + 64], r["embeddings"]))
                live = {self.text_of(it) for it in self.cat.items}
                if missing or set(self.vecs) - live:                  # renamed/removed items drop out of the cache
                    self.vecs = {k: v for k, v in self.vecs.items() if k in live}
                    EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True); EMBED_CACHE.write_text(_json.dumps(self.vecs))
                ollama("/api/embed", {"model": c.get("embed_model", "nomic-embed-text"), "input": ["warm"], "keep_alive": c.get("keep_alive", "5m")}, 30)
                ollama("/api/generate", {"model": c.get("model", "ornith:9b"), "prompt": "", "keep_alive": c.get("keep_alive", "5m")}, 60)
                self.ok = True
            except Exception:
                self.ok, self.down_until = False, time.time() + 60

        def suggest(self, q):
            """The catalogue item that does what `q` asks, or None."""
            if battery_profile(): return None
            if not self.ok:
                if time.time() > self.down_until: threading.Thread(target=self.warm, daemon=True).start()
                return None
            c = ai_conf()
            try:
                qv = ollama("/api/embed", {"model": c.get("embed_model", "nomic-embed-text"), "input": [q], "keep_alive": c.get("keep_alive", "5m")}, 3)["embeddings"][0]
                cands = sorted(((cosine(qv, self.vecs[self.text_of(it)]), it) for it in self.cat.items if self.text_of(it) in self.vecs),
                               key=lambda x: -x[0])[:25]
                if not cands: return None
                titles = [it[1] + (f" (for: {it[5][:70]})" if it[5] and it[4] in ("action", "settings", "shortcut") else "") for _s, it in cands]
                r = ollama("/api/generate", {"model": c.get("model", "ornith:9b"), "prompt": intent_prompt(q, titles), "format": "json",
                                             "stream": False, "think": False, "keep_alive": c.get("keep_alive", "5m"),
                                             "options": {"temperature": 0, "num_predict": 12}}, 6)
                i = parse_pick(r.get("response", ""), len(titles))
                return cands[i][1] if i is not None else None
            except Exception:
                return None

    def read_status():
        """A snapshot of what's on right now (each read is tiny; any that fails is just left out)."""
        st = {}
        def out(*a):
            try: return subprocess.run(a, capture_output=True, text=True, timeout=1.5).stdout.strip()
            except Exception: return None
        v = out("swaync-client", "-D");             st["dnd"] = v == "true" if v else None
        v = out(f"{S}/nightlight.sh", "status")
        try: st["night"] = _json.loads(v)["class"] == "on"
        except Exception: pass
        v = out(f"{S}/keep-awake.sh", "status");    st["awake"] = v == "on" if v else None
        try: st["bar"] = (HOME / ".config/hypr/bar-mode").read_text().strip()
        except OSError: pass
        try: st["profile"] = _json.loads(out(f"{B}/profile", "--json") or "{}").get("name")
        except ValueError: pass
        v = out("nmcli", "-t", "-f", "NAME,TYPE", "con", "show", "--active")
        if v is not None: st["wifi"] = next((l.rsplit(":", 1)[0] for l in v.splitlines() if l.endswith(":802-11-wireless")), "")
        for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
            try: st["battery"] = (int((b / "capacity").read_text()), (b / "status").read_text().strip()); break
            except (OSError, ValueError): pass
        try: st["recording"] = _json.loads(out(f"{S}/record.sh", "status") or "{}").get("class") == "recording"
        except ValueError: pass
        st["disk_free"] = _sh.disk_usage(str(HOME)).free
        tdir = HOME / ".local/state/myos/tasks"
        try: st["review"] = sum(1 for f in tdir.glob("t*.json") if '"state": "review"' in f.read_text())
        except OSError: pass
        return {k: v for k, v in st.items() if v is not None}

    KIND_LABEL = {"app": "App", "action": "Action", "shortcut": "Shortcut", "settings": "Setting", "config": "Edit", "layout": "Layout",
                  "project": "Project", "window": "Window", "file": "File", "web": "Google", "ask": "Assistant", "run": "Terminal",
                  "do": "Do it", "calc": "Copy", "hash": "Copy", "conv": "Copy", "emoji": "Copy", "clip": "Copy", "now": "Now",
                  "ai": "✦ Understood", "help": "Tip", "section": "", "tool": "Tool", "recipe": "Recipe"}

    def help_rows():
        tips = [("Type anything: an app, a setting, a feature, a file, a project", "Results learn what you pick"),
                ("Enter on text that matches nothing searches Google in Chrome", "yt … YouTube · gh … GitHub · w … Wikipedia · maps … · img …"),
                ("? question  asks the assistant", "e.g. ? how do I free disk space"),
                ("> command  runs it in a terminal", "e.g. > htop"),
                ("Maths and conversions: 12*7 · 10 km to mi · 255 to hex · sha256 text", "Enter copies the answer"),
                ("clip word  searches clipboard history", "Enter copies it again"),
                ("emoji heart  ·  layout chrome and 2 terminals", "emoji picker · tile apps on an empty workspace")]
        return [(t, sub, "dialog-information-symbolic", "help", lambda: None) for t, sub in tips]

    if sys.argv[1:2] == ["--understand"]:                 # run.py --understand "make the screen dimmer": what would ✦ pick?
        cat = Catalog(); brain = Brain.__new__(Brain); brain.cat, brain.ok, brain.down_until = cat, False, 0.0
        try: brain.vecs = _json.loads(EMBED_CACHE.read_text())
        except (OSError, ValueError): brain.vecs = {}
        brain.warm()
        for q in sys.argv[2:]:
            t = time.time(); it = brain.suggest(q)
            print(f"{time.time() - t:4.2f}s  {q!r} -> {it[1] if it else '(nothing: web search)'}")
        return 0

    class Win(Adw.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="Run", default_width=680, default_height=560, css_classes=["run"])
            self.cat = Catalog(); self.brain = Brain(self.cat); self.status, self._gen = {}, 0
            threading.Thread(target=self._read_status, daemon=True).start()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_start=12, margin_end=12, margin_bottom=12)
            self.entry = Gtk.SearchEntry(placeholder_text="Search anything, or just say what you want",
                                         css_classes=["run-entry"])
            self.entry.connect("search-changed", lambda *_: self.refill())
            self.entry.connect("activate", lambda *_: self.run_selected())
            self.entry.connect("stop-search", lambda *_: self.dismiss())
            top = Gtk.Box(spacing=11); self.entry.set_hexpand(True)
            mark = next((m for m in (HOME / ".local/share/myos/kadaos-mark.svg",   # installed; else the repo copy
                                     Path(__file__).resolve().parents[1] / "brand/kadaos-mark-small.svg") if m.exists()), None)
            if mark: top.append(Gtk.Image(file=str(mark), pixel_size=22, margin_start=18, tooltip_text="KadaOS"))
            top.append(self.entry); box.append(top)
            self.list = Gtk.ListBox(css_classes=["navigation-sidebar"])
            self.list.connect("row-activated", lambda _l, r: self.invoke(r.result, r.key))
            sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER); sw.set_child(self.list)
            box.append(sw)
            box.append(Gtk.Label(label="↑ ↓ choose  ·  Enter run  ·  Esc close  ·  type help for everything", css_classes=["run-foot"]))
            self.set_content(box)
            self.refill()
            key = Gtk.EventControllerKey(); key.connect("key-pressed", self.on_key); self.add_controller(key)
            self._born = time.time()
            self.connect("notify::is-active", self._focus)
            self.connect("close-request", lambda *_: (self.dismiss(), True)[1])  # stay resident

        def dismiss(self):
            self.set_visible(False)

        def reshow(self):
            """Reset for an instant reopen (the app stays resident); re-read the shortcuts if the config changed."""
            try:
                if HYPR_CONF.stat().st_mtime != self.cat.conf_mtime: self.cat.rebuild()
            except OSError: pass
            if time.time() - self.cat.indexed > 300:          # new files show up (indexing takes ~50 ms, in the background)
                threading.Thread(target=self.cat.index_files, daemon=True).start()
            threading.Thread(target=self._read_status, daemon=True).start()   # live state, refreshed every open
            if not self.brain.ok: threading.Thread(target=self.brain.warm, daemon=True).start()
            self.entry.set_text(""); self.refill()
            self._born = time.time(); self.present(); self.entry.grab_focus()

        def _read_status(self):
            st = read_status()
            GLib.idle_add(self._got_status, st)

        def _got_status(self, st):
            self.status = st
            if not self.entry.get_text().strip(): self.refill()     # the "right now" rows depend on it
            return False

        def _focus(self, *_):
            if self.is_active():      # focus the search box once the compositor really hands us the keyboard (reopens too)
                self.entry.grab_focus(); return
            if not self.is_active() and self.is_visible() and time.time() - self._born > 0.6:
                self.dismiss()

        def results(self, q):
            """[(title, subtitle, icon, kind, callable, history key)] best-first."""
            ql = q.lower().strip()
            cat = self.cat
            if not ql:
                sec = lambda t: (t, "", None, "section", None, None)
                row_of = lambda it, sub=None, kind=None: (it[1], sub or live_sub(it[1], self.status) or it[2], it[3], kind or it[4], it[6], it[0])
                now_rows = [row_of(cat.by_id["a:" + t], "✦ " + why, "now") for t, why in suggestions(self.status, time.localtime().tm_hour)
                            if "a:" + t in cat.by_id]
                used = {r[5] for r in now_rows}
                fav = [k for b, k in sorted(((frecency_boost(v), k) for k, v in cat.history.items() if k in cat.by_id), reverse=True)
                       if b > 0.5 and k not in used][:6]
                used |= set(fav)
                ess = [k for k in cat.essentials if k in cat.by_id and k not in used][:6]
                out = []
                if now_rows: out += [sec("Right now")] + now_rows
                if fav: out += [sec("Frequent")] + [row_of(cat.by_id[k]) for k in fav]
                if ess: out += [sec("Essentials")] + [row_of(cat.by_id[k]) for k in ess]
                show_help = lambda: self.entry.set_text("help"); show_help.keep_open = True
                out += [sec("Tip"), ("Type what you want: an app, a setting, a file, or plain words like “make the screen dimmer”",
                                     "Enter shows everything you can type", "dialog-information-symbolic", "help", show_help, None)]
                return out
            if ql in ("help", "?"):
                return [(t, s_, i, k, f, None) for t, s_, i, k, f in help_rows()]
            top = []                  # inline answers: always first
            hint = {"volume": "volume 30", "vol": "volume 30", "brightness": "brightness 70", "timer": "timer 10 min tea",
                    "remind": "remind me in 20 min to …", "remind me": "remind me in 20 min to …", "kill": "kill 3000"}.get(ql)
            if hint:
                fill = lambda h=hint: (self.entry.set_text(h.split(" …")[0].rsplit(" ", 1)[0] + " "), self.entry.set_position(-1))
                fill.keep_open = True
                top.append((f"Type a value: {hint}", "Enter starts it for you", "input-keyboard-symbolic", "help", fill, None))
            pc = parse_command(q)
            if pc:
                top.append((pc[0], pc[1] + " · Enter", command_icon(pc), "do", lambda c=pc[2]: sh(c), None))
            c = calc(q)
            if c:
                top.append((c, "Calculator · Enter to copy", "accessories-calculator-symbolic", "calc", lambda c=c: (copy(c.lstrip("= ")), notify("Copied", c)), None))
            h = hash_q(q)
            if h:
                top.append((h[1], f"{h[0].upper()} · Enter to copy", "channel-secure-symbolic", "hash", lambda h=h: (copy(h[1]), notify("Copied", f"{h[0]} digest")), None))
            b = base_q(q) or unit_q(q)
            if b:
                top.append((b, "Convert · Enter to copy", "accessories-calculator-symbolic", "conv", lambda b=b: (copy(b), notify("Copied", b)), None))
            for ch, name in emoji_search(q):
                top.append((f"{ch}   {name}", "Emoji · Enter to copy", "face-smile-symbolic", "emoji", lambda ch=ch, name=name: (copy(ch), notify("Copied", f"{ch} {name}")), None))
            if looks_like_url(q):
                u = q.strip(); u = u if re.match(r"https?://", u) else "https://" + u
                top.append((f"Open {u}", "Website", "web-browser-symbolic", "web", lambda u=u: chrome(u), None))
            if q.startswith("?") and len(q) > 2:
                question = q[1:].strip()
                return top + [(f"Ask the assistant: {question}", "Local AI assistant", "chat-message-new-symbolic", "ask",
                               lambda x=question: sh(f"{B}/ai-chat --ask {shlex.quote(x)}"), None)]
            if q.startswith(">") and len(q) > 2:
                cmd = q[1:].strip()
                return top + [(f"Run in a terminal: {cmd}", "Terminal", "utilities-terminal-symbolic", "run",
                               lambda c=cmd: sh(term("run", c.replace("'", "'\\''"))), None)]
            if ql.startswith(("layout ", "layout:")) and " " in q:
                spec = q.split(None, 1)[1].lstrip(": ")
                top.append((f"Open layout: {spec}", "Tile these apps", "preferences-system-windows-symbolic", "layout",
                            lambda spec=spec: sh(f"{S}/flow.py --ai -- {shlex.quote(spec)}"), None))
            if ql.startswith(("clip ", "cb ")) and " " in q:
                words = q.split(None, 1)[1].lower()
                try: lines = subprocess.run(["cliphist", "list"], capture_output=True, text=True, timeout=2).stdout.splitlines()
                except Exception: lines = []
                for line in [l for l in lines if words in l.lower()][:10]:
                    cid, _, text = line.partition("\t")
                    top.append((text[:80], "Clipboard history · Enter to copy", "edit-paste-symbolic", "clip",
                                lambda cid=cid: sh(f"cliphist decode {shlex.quote(cid)} | wl-copy"), None))
                return top
            scored = []
            for it in cat.items:
                sc = score(ql, it[1], it[5])
                if sc is not None:
                    scored.append((sc + frecency_boost(cat.history.get(it[0])), it))
            # open windows
            try:
                for w in _json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True).stdout):
                    if not w.get("title") or (w.get("workspace", {}).get("id", 0) < 0 and w["class"] != "kitty-dropdown"): continue
                    sc = score(ql, w["title"], w.get("class", ""))
                    if sc is not None:
                        scored.append((sc - 5, ("w:" + w["address"], w["title"][:70], f"Switch to window · {w['class']}", "focus-windows-symbolic",
                                               "window", "", lambda a=w["address"]: sh(f"hyprctl dispatch focuswindow address:{a}"))))
            except Exception:
                pass
            # files: recent ones first, then the index (from 3 letters)
            if len(ql) >= 3:
                hits = []
                for path in cat.recent:
                    if ql in Path(path).name.lower(): hits.append((45, path))
                n = 0
                for path in cat.files:
                    name = path.rsplit("/", 1)[-1].lower()
                    if ql in name:
                        hits.append((35 if name.startswith(ql) else 25, path)); n += 1
                        if n > 60: break
                seen = set()
                for sc, path in sorted(hits, key=lambda h: (-h[0], len(h[1])))[:8]:
                    if path in seen: continue
                    seen.add(path)
                    scored.append((sc + frecency_boost(cat.history.get("f:" + path)), ("f:" + path, path.rsplit("/", 1)[-1],
                                   path.replace(str(HOME), "~", 1), "folder-symbolic" if Path(path).is_dir() else "text-x-generic-symbolic",
                                   "file", "", lambda p=path: open_path(p))))
            scored.sort(key=lambda x: -x[0])
            out = top + [(it[1], live_sub(it[1], self.status) or it[2], it[3], it[4], it[6], it[0]) for _sc, it in scored[:30]]
            # the fallbacks: a web search (top when nothing matches well), the assistant, and a terminal for commands
            engine, url, terms = web_search(q)
            web = (f"Search {engine} for “{terms}”", "Chrome · Enter", "web-browser-symbolic", "web", lambda u=url: chrome(u), None)
            strong = top or (scored and scored[0][0] >= 50)
            self._weak = not (top or (scored and scored[0][0] >= 85))      # the AI may know better (see ask_brain)
            out = out + [web] if strong else [web] + out
            first = q.split()[0]
            if _sh.which(first) and not looks_like_sentence(q) and (not scored[:1] or " " in q):   # "git status", not "make the screen dimmer"
                out.append((f"Run in a terminal: {q}", "Terminal", "utilities-terminal-symbolic", "run",
                            lambda c=q: sh(term("run", c.replace("'", "'\\''"))), None))
            if len(q.split()) >= 2:
                out.append((f"Ask the assistant: {q}", "Local AI assistant", "chat-message-new-symbolic", "ask",
                            lambda x=q: sh(f"{B}/ai-chat --ask {shlex.quote(x)}"), None))
            return out

        def _make_row(self, title, sub, icon, kind, fn, key):
            if kind == "section":
                row = Gtk.ListBoxRow(css_classes=["sec"], activatable=False, selectable=False, focusable=False); row.result = None; row.key = None
                row.set_child(Gtk.Label(label=title.upper(), xalign=0, css_classes=["section"])); return row
            row = Gtk.ListBoxRow(css_classes=["rr"] + (["rr-ai"] if kind in ("ai", "now") else [])); row.result = fn; row.key = key
            r = Gtk.Box(spacing=11)
            if isinstance(icon, str):
                r.append(Gtk.Image(icon_name=icon, pixel_size=22))
            elif icon is not None:
                img = Gtk.Image(pixel_size=22); img.set_from_gicon(icon); r.append(img)
            txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
            big = kind in ("calc", "hash", "conv")
            txt.append(Gtk.Label(label=title, xalign=0, ellipsize=Pango.EllipsizeMode.END, css_classes=["rr-big" if big else "rr-title"]))
            shown = sub.split("  ·  ", 1)[1] if kind == "shortcut" and "  ·  " in sub else sub
            txt.append(Gtk.Label(label=shown, xalign=0, css_classes=["rr-sub"], ellipsize=Pango.EllipsizeMode.END))
            r.append(txt)
            if kind == "shortcut" and "  ·  " in sub:          # keys as key caps on the right: easy to read, easy to learn
                caps = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
                for k in sub.split("  ·  ")[0].split(" + "): caps.append(Gtk.Label(label=k, css_classes=["keycap"]))
                r.append(caps)
            else:
                r.append(Gtk.Label(label=KIND_LABEL.get(kind, kind.title()), css_classes=["rr-kind"], valign=Gtk.Align.CENTER))
            row.set_child(r); return row

        def refill(self):
            child = self.list.get_first_child()
            while child:
                self.list.remove(child); child = self.list.get_first_child()
            self._rows = self.results(self.entry.get_text())
            for title, sub, icon, kind, fn, key in self._rows[:40]:
                self.list.append(self._make_row(title, sub, icon, kind, fn, key))
            self._select_from(0, 1, focus=False)          # select, but never take focus from the search box
            self._gen += 1
            q = self.entry.get_text().strip()
            if q and looks_like_sentence(q) and getattr(self, "_weak", False):
                gen = self._gen
                GLib.timeout_add(280, lambda: (gen == self._gen and threading.Thread(target=self._ask_brain, args=(q, gen), daemon=True).start(), False)[1])

        def _ask_brain(self, q, gen):
            it = self.brain.suggest(q)
            if it: GLib.idle_add(self._show_suggestion, it, gen)

        def _show_suggestion(self, it, gen):
            """Put the AI's pick on top, without stealing a selection you already moved."""
            if gen != self._gen: return False
            row = self._make_row(f"✦ {it[1]}", "Understood by the local AI · Enter", it[3], "ai", it[6], it[0])
            sel = self.list.get_selected_row()
            self.list.insert(row, 0)
            if sel is None or sel.get_index() == 1: self.list.select_row(row)
            return False

        def _select_from(self, i, step, focus=True):
            """Select the next row that can be run, skipping section headers. focus scrolls it into view (arrow keys,
            which hand focus straight back to the search box); a list rebuild must not take focus, or typing after
            a reopen lands in the list (the live-status refresh rebuilds it just after the window appears)."""
            while 0 <= i:
                row = self.list.get_row_at_index(i)
                if row is None: return
                if row.get_selectable():
                    self.list.select_row(row); row.grab_focus() if focus and step and i else None
                    return
                i += step

        def invoke(self, fn, key=None):
            if fn is None: return
            if getattr(fn, "keep_open", False):
                fn(); return                                  # a tip that fills the search box keeps the launcher open
            self.dismiss()  # hide first so focus returns to the app being launched
            if key: self.cat.remember(key)               # what you pick ranks higher next time
            try:
                fn()
            except Exception as e:
                notify("Couldn't run", str(e), "dialog-error-symbolic")

        def run_selected(self):
            r = self.list.get_selected_row() or self.list.get_row_at_index(0)
            if r:
                self.invoke(r.result, r.key)

        def on_key(self, _c, keyval, _code, _state):
            if keyval == Gdk.KEY_Escape:
                self.dismiss(); return True
            if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
                r = self.list.get_selected_row()
                step = 1 if keyval == Gdk.KEY_Down else -1
                self._select_from((r.get_index() if r else -1) + step, step)
                self.entry.grab_focus()
                return True
            return False

    class App(Adw.Application):
        def __init__(self):
            # single-instance: a second launch just re-shows the resident window (instant reopen)
            super().__init__(application_id="org.myos.Run", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
            self.win = None

        def do_activate(self):
            if self.win:
                self.win.reshow(); return
            prov = Gtk.CssProvider(); prov.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
            self.win = Win(self); self.win.present(); self.hold()  # stay resident

    App().run(sys.argv)


if __name__ == "__main__":
    sys.exit(run_app())
