#!/usr/bin/env python3
"""secretary — the desktop's memory of what needs you (shared by system-adapt, the top bar and the "What needs me" panel).

  secretary.py bar        waybar JSON: inbox icon + count of things that need you
  secretary.py list       print the inbox (what the panel shows)
  secretary.py seen       mark messages read (the panel does this when opened)
  secretary.py clear      mark everything read, including finished agents
  secretary.py test       self-check

Data (all local, never sent anywhere):
  ~/.local/state/myos/notifications.jsonl   every notification, sorted into needs / people / system / low (system-adapt writes it)
  ~/.local/state/myos/inbox-seen            when you last opened the inbox
  $XDG_RUNTIME_DIR/myos-agents.json         agent sessions (agent-notify writes it)
  ~/.cache/myos-assistant-alerts.json       assistant warnings (watch.py writes it)
"""
import json, os, re, sys, time
from pathlib import Path

HOME = Path.home()
STATE_DIR = Path(os.environ.get("MYOS_SECRETARY_DIR") or HOME / ".local/state/myos")
LOG = STATE_DIR / "notifications.jsonl"
SEEN = STATE_DIR / "inbox-seen"
AGENTS = Path(os.environ.get("MYOS_AGENT_STATE") or Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "myos-agents.json")
ALERTS = HOME / ".cache/myos-assistant-alerts.json"
KEEP, WINDOW = 400, 12 * 3600          # log lines kept; how far back the inbox looks
AGENT_NAMES = {"claude": "Claude", "codex": "Codex", "agy": "Antigravity", "gemini": "Gemini"}

# where a notification came from: matched against app name + text (browser notifications carry the site)
SOURCES = [("whatsapp", "WhatsApp"), ("teams", "Teams"), ("telegram", "Telegram"), ("signal", "Signal"), ("slack", "Slack"),
           ("discord", "Discord"), ("messenger", "Messenger"), (r"mail\.google|gmail", "Gmail"), ("zoho", "Zoho Mail"),
           ("outlook", "Outlook"), ("thunderbird|evolution|geary", "Mail"), ("element|matrix", "Element"),
           ("calendar", "Calendar"), ("github", "GitHub"), ("linkedin", "LinkedIn")]
PEOPLE = {"WhatsApp", "Teams", "Telegram", "Signal", "Slack", "Discord", "Messenger", "Gmail", "Zoho Mail", "Outlook", "Mail", "Element", "LinkedIn"}
NEEDS_RE = re.compile(r"\b(approve|approval|permission|password|passcode|verif(y|ication)|otp|one[- ]time|code is|2fa|confirm|"
                      r"invited you|invitation|is calling|incoming call|missed call|mentioned you|asked you|needs you|waiting for you|"
                      r"review requested|requested your review|deadline|due (today|tomorrow|in))\b", re.I)
SYSTEM_APPS = re.compile(r"^(myos|notify-send|networkmanager|blueman|udiskie|swayosd|power|upower|gnome-|xdg-desktop-portal|systemd)", re.I)


def source(app, summary="", body=""):
    hay = f"{app} {summary} {body}".lower()
    for pat, name in SOURCES:
        if re.search(pat, hay): return name
    return app or "An app"


def classify(app, summary="", body="", urgency=1):
    """-> needs | people | system | low"""
    src = source(app, summary, body)
    if urgency >= 2 or NEEDS_RE.search(f"{summary} {body}"): return "needs"
    if src in PEOPLE: return "people"
    if SYSTEM_APPS.search(app or ""): return "system"
    return "low"


def record(app, summary, body, urgency=1, now=None):
    """Append one notification to the log (system-adapt calls this for every notification)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    body = " ".join(str(body).split())[:300]
    e = {"t": now or time.time(), "app": app, "summary": str(summary)[:160], "body": body, "urgency": urgency,
         "kind": classify(app, summary, body, urgency), "source": source(app, summary, body)}
    new = not LOG.exists()
    with open(LOG, "a") as f: f.write(json.dumps(e, ensure_ascii=False) + "\n")
    if new: os.chmod(LOG, 0o600)
    if LOG.stat().st_size > 400_000:   # keep it small
        lines = LOG.read_text().splitlines()[-KEEP:]; LOG.write_text("\n".join(lines) + "\n")
    return e


def notifications(since=0):
    try: lines = LOG.read_text().splitlines()
    except OSError: return []
    out = []
    for l in lines:
        try:
            e = json.loads(l)
            if e["t"] >= since: out.append(e)
        except (ValueError, KeyError): pass
    return out


def seen_at():
    try: return float(SEEN.read_text())
    except (OSError, ValueError): return 0.0


def mark_seen(now=None):
    STATE_DIR.mkdir(parents=True, exist_ok=True); SEEN.write_text(str(now or time.time()))


def agents():
    try: return json.loads(AGENTS.read_text())
    except (OSError, ValueError): return {}


def inbox(now=None):
    """What needs you, grouped: needs, done, messages, warnings. Each item is a dict with title, detail, and maybe address/ws."""
    now = now or time.time(); since = max(seen_at(), now - WINDOW)
    box = {"needs": [], "done": [], "messages": [], "warnings": []}
    for key, e in sorted(agents().items(), key=lambda kv: -kv[1].get("since", 0)):
        if e.get("state") not in ("needs", "done"): continue
        name = AGENT_NAMES.get(e.get("agent"), str(e.get("agent", "Agent")).title())
        box[e["state"]].append({"kind": "agent", "key": key, "title": f"{name} · {e.get('proj', '')}", "detail": e.get("summary", ""),
                                "ws": e.get("ws"), "address": e.get("address"), "t": e.get("since", now)})
    for n in reversed(notifications(since)):
        summ, src = n["summary"], n["source"]
        title = summ if src.lower() in summ.lower() else (f"{src} · {summ}" if summ else src)   # no "GitHub · GitHub"
        detail = re.sub(r"^\S+\.(com|org|net|io|app|in)\S*\s+", "", n["body"])   # browsers prefix the site
        item = {"kind": "notification", "title": title, "detail": detail, "t": n["t"]}
        if n["kind"] == "needs": box["needs"].append(item)
        elif n["kind"] == "people": box["messages"].append(item)
    try: alerts = json.loads(ALERTS.read_text())
    except (OSError, ValueError): alerts = []
    box["warnings"] = [{"kind": "alert", "title": a.get("title", ""), "detail": a.get("body", ""), "t": a.get("t", now)}
                       for a in alerts if now - a.get("t", 0) < 6 * 3600][-5:][::-1]
    return box


def bar(now=None):
    b = inbox(now)
    n_needs, n = len(b["needs"]), len(b["needs"]) + len(b["done"]) + len(b["messages"])
    lines = [f"{len(b[k])} {label}" for k, label in (("needs", "need you"), ("done", "agents finished"), ("messages", "new messages")) if b[k]]
    tip = ("What needs you\n" + "\n".join(lines) if lines else "Nothing needs you right now") + "\nClick: open (Super+Y)"
    icon = "\U000F0EB2" if n else "\U000F02FB"   # inbox-full / inbox
    return {"text": f"{icon} {n}" if n else icon, "class": "needs" if n_needs else ("some" if n else "none"), "tooltip": tip}


def digest(notes, minutes, while_="busy"):
    """One short summary of what arrived while you were busy (Do Not Disturb) or away (locked). -> (title, body) or None"""
    notes = [n for n in notes if n["kind"] != "system"]
    if not notes: return None
    counts = {}
    for n in notes: counts[n["source"]] = counts.get(n["source"], 0) + 1
    tally = " · ".join(f"{c} {s}" for s, c in sorted(counts.items(), key=lambda kv: -kv[1])[:4])
    top = sorted(notes, key=lambda n: ({"needs": 0, "people": 1}.get(n["kind"], 2), -n["t"]))[:3]
    body = tally + "\n" + "\n".join(f"• {n['source']}: {n['summary']}"[:90] for n in top)
    return f"While you were {while_} ({minutes} min): {len(notes)} notification{'s' * (len(notes) != 1)}", body


AWAY_MIN = 10 * 60      # shorter breaks don't need a summary


def away_digest(locked_at, now=None):
    """After unlocking: what arrived while the screen was locked, if you were gone at least AWAY_MIN."""
    now = now or time.time()
    if now - locked_at < AWAY_MIN: return None
    return digest(notifications(locked_at), round((now - locked_at) / 60), "away")


def clear():
    mark_seen()
    try:
        import fcntl
        with open(str(AGENTS) + ".lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            d = agents()
            for e in d.values():
                if e.get("state") in ("needs", "done"): e["state"] = "seen"
            tmp = str(AGENTS) + ".tmp"; Path(tmp).write_text(json.dumps(d)); os.replace(tmp, AGENTS)
    except OSError: pass


def _test():
    import tempfile
    global STATE_DIR, LOG, SEEN, AGENTS
    with tempfile.TemporaryDirectory() as d:
        STATE_DIR, AGENTS = Path(d), Path(d) / "agents.json"; LOG, SEEN = STATE_DIR / "n.jsonl", STATE_DIR / "seen"
        assert classify("Google Chrome", "Prajin I R", "web.whatsapp.com hey are you free?") == "people"
        assert source("Google Chrome", "Prajin", "teams.microsoft.com call at 5") == "Teams"
        assert classify("Google Chrome", "Your verification code is 482913", "") == "needs"
        assert classify("Discord", "x", "y", urgency=2) == "needs"
        assert classify("NetworkManager", "Connected", "Wi-Fi") == "system"
        assert classify("Spotify", "Now playing", "song") == "low"
        now = 2_000_000
        record("Google Chrome", "Prajin I R", "web.whatsapp.com are you coming?", now=now - 60)
        record("Google Chrome", "Code", "Your OTP is 1234", now=now - 30)
        record("Spotify", "Now playing", "x", 0, now=now - 10)
        AGENTS.write_text(json.dumps({"a": {"agent": "codex", "proj": "lab", "state": "needs", "summary": "Run tests?", "since": now - 5, "ws": "2"},
                                      "b": {"agent": "claude", "proj": "KadaOS", "state": "done", "summary": "Fixed it", "since": now - 9},
                                      "c": {"agent": "claude", "proj": "x", "state": "seen", "since": now}}))
        b = inbox(now)
        assert [i["title"] for i in b["needs"]] == ["Codex · lab", "Google Chrome · Code"], b["needs"]
        assert b["messages"][0]["detail"] == "are you coming?", b["messages"]
        assert len(b["needs"]) == 2 and len(b["done"]) == 1 and len(b["messages"]) == 1, b
        r = bar(now); assert r["class"] == "needs" and r["text"].endswith(" 4"), r
        mark_seen(now); b = inbox(now + 1)
        assert not b["messages"] and len(b["needs"]) == 1   # messages read; the waiting agent still needs you
        t = digest(notifications(now - 3600), 35)
        assert t[0].startswith("While you were busy (35 min): 3") and "WhatsApp" in t[1], t
        assert digest([], 5) is None
        assert away_digest(now - 300, now) is None, "a 5-minute break: no summary"
        a = away_digest(now - 3600, now)
        assert a and a[0] == "While you were away (60 min): 3 notifications" and "WhatsApp" in a[1], a
        clear(); assert bar(now + 2)["class"] == "none"
    print("ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "test": _test()
    elif cmd == "bar":
        try: print(json.dumps(bar(), ensure_ascii=False))
        except Exception as e: print(json.dumps({"text": "\U000F02FB", "class": "none", "tooltip": str(e)}))
    elif cmd == "away":                   # lock.sh, after unlocking: away SECONDS_SINCE_EPOCH_WHEN_LOCKED
        d = away_digest(float(sys.argv[2]))
        if d:
            import subprocess
            helper = HOME / ".config/hypr/scripts/notify-action.py"
            act = subprocess.run([str(helper), "-i", "view-list-symbolic", "-t", "20", d[0], d[1], "open=Open inbox"],
                                 capture_output=True, text=True).stdout.strip()
            if act == "open": subprocess.Popen([str(HOME / ".local/bin/myos-panel"), "inbox"], start_new_session=True)
    elif cmd == "seen": mark_seen()
    elif cmd == "clear": clear()
    elif cmd == "list": print(json.dumps(inbox(), indent=2, ensure_ascii=False))
    else: print(__doc__); sys.exit(2)
