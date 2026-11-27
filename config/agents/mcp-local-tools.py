#!/usr/bin/env python3
"""local-tools — an MCP server (stdio) that shares this laptop's local AI with every agent
(Claude Code, Codex, Antigravity).

Tools
  local_ai        run a quick job on the LOCAL model (Ornith 9B on the RTX 5050): summarize, classify, draft,
                  translate, extract… — free, private, offline. Use it to save paid-model usage on bulk text.
  search_files    semantic search over the user's documents/projects (the same index as Super+Shift+F)
  ask_files       answer a question from the user's own files, with sources
  system_status   live laptop overview (battery, thermals, GPU, memory, disk, services, network, top processes)
  system_command  run ONE read-only diagnostic command (strict allow-list; nothing that changes the system)
  desktop_context what the user is doing: focused window, workspace, terminal folders + git status, now playing
  desktop_window  focus a window, move it to a workspace, toggle fullscreen/floating, switch workspace (no closing)

No dependencies beyond fai.py (installed at ~/.local/share/local-ai/fai.py). Protocol: MCP over stdio (JSON-RPC 2.0).
"""
import contextlib, importlib.util, io, json, sys, traceback
from pathlib import Path

_spec = importlib.util.spec_from_file_location("fai", str(Path.home() / ".local/share/local-ai/fai.py"))
fai = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fai)
_chat = None
def chat():
    """The assistant's desktop helpers (chat.py), loaded on first use."""
    global _chat
    if _chat is None:
        s = importlib.util.spec_from_file_location("chat", str(Path.home() / ".local/share/local-ai/chat.py"))
        _chat = importlib.util.module_from_spec(s); s.loader.exec_module(_chat)
    return _chat

TOOLS = [
    {"name": "local_ai",
     "description": "Run a task on the user's LOCAL model (Ornith 9B, on-device, free, private). Good for summarizing or "
                    "classifying large text, drafting, extracting fields. Not for hard reasoning, arithmetic or translation.",
     "inputSchema": {"type": "object", "properties": {
         "task": {"type": "string", "description": "What to do, e.g. 'Summarize in 5 bullets' or 'Extract all dates as JSON'"},
         "text": {"type": "string", "description": "Optional input text to work on"}}, "required": ["task"]}},
    {"name": "search_files",
     "description": "Semantic search over the user's documents and projects (Documents, Downloads, Projects, notes, setup docs). "
                    "Returns paths, scores and snippets.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 8}},
                     "required": ["query"]}},
    {"name": "ask_files",
     "description": "Answer a question using ONLY the user's own files (retrieval + local model), with numbered sources.",
     "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
    {"name": "system_status",
     "description": "Live overview of this laptop: battery/AC, power profile, temperatures, GPU, memory, disk, key services, "
                    "Docker containers, network, top processes.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "system_command",
     "description": "Run ONE read-only diagnostic command on this laptop (e.g. 'journalctl -b -p err', 'systemctl status docker', "
                    "'nmcli device'). Strict allow-list: no sudo, pipes or anything that changes the system.",
     "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "desktop_context",
     "description": "What the user is doing on this laptop right now: last-used window and title, workspace, the folders and "
                    "git status of shells in that terminal, other open windows, now playing. Read-only.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "desktop_window",
     "description": "Arrange the user's Hyprland desktop: focus a window, move it to a workspace (silently), toggle fullscreen "
                    "or floating, or switch workspace. target = app class or title words (empty = last-used window). Cannot close windows.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["focus", "fullscreen", "float", "move_to_workspace", "switch_workspace"]},
         "target": {"type": "string"}, "workspace": {"type": "string"}}, "required": ["action"]}},
]

def call(name, a):
    if name == "local_ai":
        msgs = [{"role": "system", "content": "You are a concise assistant. Do exactly the task; output only the result."},
                {"role": "user", "content": (f"<text>\n{a['text']}\n</text>\n\n" if a.get("text") else "") + a["task"]}]
        return fai.clean("".join(fai.chat_stream(msgs)))
    if name == "search_files":
        res = fai.search(a["query"], int(a.get("limit", 8)))
        return "\n".join(f"{s:.2f}  {p}\n      {' '.join(t.split())[:240]}" for s, p, t in res) or "No results (index may be empty: run `fai index`)."
    if name == "ask_files":
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fai.C = {k: "" for k in fai.C}           # no ANSI colours in tool output
            fai.cmd_rag(type("A", (), {"question": [a["question"]]})())
        return buf.getvalue().strip()
    if name == "system_status":
        return fai.system_status()
    if name == "system_command":
        return fai.run_readonly(a["command"])
    if name == "desktop_context":
        return chat().gather_context(False)
    if name == "desktop_window":
        if a.get("action") == "close": raise ValueError("closing windows is not allowed from agents")
        out = []
        for argv in chat().window_dispatch(a.get("action", ""), a.get("target", "") or "", a.get("workspace", "") or ""):
            out.append(chat().run_capture(argv, timeout=10)[1].strip())
        return "; ".join(out) or "ok"
    raise ValueError(f"unknown tool {name}")

def reply(i, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": i}
    if error: msg["error"] = {"code": -32603, "message": error}
    else: msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n"); sys.stdout.flush()

def main():
    for line in sys.stdin:
        if not line.strip(): continue
        try: req = json.loads(line)
        except Exception: continue
        m, i, p = req.get("method"), req.get("id"), req.get("params") or {}
        if i is None: continue                                   # notifications (e.g. notifications/initialized)
        try:
            if m == "initialize":
                reply(i, {"protocolVersion": p.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                          "serverInfo": {"name": "local-tools", "version": "1.0"},
                          "instructions": "Local, free, private helpers on the user's laptop. Prefer local_ai for bulk "
                                          "summarize/classify/translate jobs; use search_files/ask_files to find the user's own documents."})
            elif m == "ping": reply(i, {})
            elif m == "tools/list": reply(i, {"tools": TOOLS})
            elif m == "tools/call":
                try: out = call(p["name"], p.get("arguments") or {}); err = False
                except BaseException as e: out, err = f"Error: {e}", True
                reply(i, {"content": [{"type": "text", "text": out}], "isError": err})
            elif m in ("resources/list", "prompts/list"): reply(i, {m.split("/")[0]: []})
            else: reply(i, error=f"method not found: {m}")
        except Exception:
            reply(i, error=traceback.format_exc(limit=2))

if __name__ == "__main__":
    main()
