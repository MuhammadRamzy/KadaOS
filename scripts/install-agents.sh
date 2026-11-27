#!/usr/bin/env bash
# Multi-agent workflow: shared rules, local-AI MCP server, launcher, notifications, cross-review.
# User-level (no sudo). Re-runnable; backs up agent configs first.
set -u
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; src="$root/config/agents"
bk=~/.config/setup-backups/agents-$(date +%Y%m%d-%H%M%S); mkdir -p "$bk" ~/.local/bin ~/.local/share/local-ai ~/.claude ~/.codex ~/.gemini
for f in ~/.claude/settings.json ~/.claude/CLAUDE.md ~/.codex/config.toml ~/.codex/AGENTS.md ~/.gemini/settings.json ~/.gemini/GEMINI.md; do
  [ -e "$f" ] && cp -aL "$f" "$bk/$(echo "$f" | sed "s#$HOME/##; s#/#_#g")"; done
echo "backup: $bk"

# 1. one rulebook → every agent
for t in ~/.claude/CLAUDE.md ~/.codex/AGENTS.md ~/.gemini/GEMINI.md; do
  [ -e "$t" ] && [ ! -L "$t" ] && mv "$t" "$t.pre-setup"
  ln -sfn "$src/global-rules.md" "$t"; done
echo "rules linked: ~/.claude/CLAUDE.md ~/.codex/AGENTS.md ~/.gemini/GEMINI.md -> config/agents/global-rules.md"

# 2. tools
for b in "$src"/bin/*; do install -m755 "$b" ~/.local/bin/; done
install -m755 "$src/mcp-local-tools.py" ~/.local/share/local-ai/mcp-local-tools.py
MCP="$HOME/.local/share/local-ai/mcp-local-tools.py"
# token savers: markitdown (docs → Markdown) and the ponytail minimal-code plugin
command -v uv >/dev/null && { command -v markitdown >/dev/null || uv tool install 'markitdown[all]' >/dev/null && echo "markitdown installed"; }
if command -v claude >/dev/null; then
  claude plugin marketplace add DietrichGebert/ponytail >/dev/null 2>&1
  claude plugin install ponytail@ponytail >/dev/null 2>&1 && echo "claude: ponytail plugin installed"; fi

# 3. MCP "local-tools" for Claude Code, Codex, Antigravity
if command -v claude >/dev/null; then
  claude mcp remove -s user local-tools >/dev/null 2>&1; claude mcp add -s user local-tools -- python3 "$MCP" >/dev/null && echo "claude: mcp local-tools added"; fi
python3 - "$MCP" <<'PY'
import json, os, re, sys
from pathlib import Path
mcp = sys.argv[1]; H = Path.home()
# Codex config.toml: top-level notify must precede the first [table]; mcp server as its own table
p = H / ".codex/config.toml"; s = p.read_text() if p.exists() else ""
notify = f'notify = ["python3", "{H}/.local/bin/agent-notify", "codex"]'
s = re.sub(r'(?m)^notify\s*=.*\n?', '', s)
first = re.search(r'(?m)^\[', s)
s = (s[:first.start()] + notify + "\n\n" + s[first.start():]) if first else (s + "\n" + notify + "\n")
s = re.sub(r'(?ms)^\[mcp_servers\.local-tools\]\n(?:(?!^\[).*\n?)*', '', s).rstrip() + "\n"
s += f'\n[mcp_servers.local-tools]\ncommand = "python3"\nargs = ["{mcp}"]\nstartup_timeout_sec = 20\ntool_timeout_sec = 180\n'
p.write_text(s); print("codex: notify + mcp local-tools configured")
# Claude Code hooks → notifications
p = H / ".claude/settings.json"; c = json.loads(p.read_text()) if p.exists() else {}
hooks = c.setdefault("hooks", {})
for ev in ("Notification", "Stop", "UserPromptSubmit"):
    cmd = f"{H}/.local/bin/agent-notify claude {'Prompt' if ev == 'UserPromptSubmit' else ev}"
    arr = [h for h in hooks.get(ev, []) if not any("agent-notify" in x.get("command", "") for x in h.get("hooks", []))]
    arr.append({"matcher": "", "hooks": [{"type": "command", "command": cmd, "timeout": 10}]} if ev == "Notification"
               else {"hooks": [{"type": "command", "command": cmd, "timeout": 10}]})
    hooks[ev] = arr
p.write_text(json.dumps(c, indent=2) + "\n"); print("claude: notification hooks configured")
# Antigravity app MCP
for p in (H / ".gemini/antigravity/mcp_config.json",):
    p.parent.mkdir(parents=True, exist_ok=True)
    c = json.loads(p.read_text()) if p.exists() and p.read_text().strip() else {}
    c.setdefault("mcpServers", {})["local-tools"] = {"command": "python3", "args": [mcp], "timeout": 180000}
    p.write_text(json.dumps(c, indent=2) + "\n")
print("antigravity app: mcp local-tools configured")
PY

# Antigravity CLI (agy) keeps its own MCP list
command -v agy >/dev/null && agy mcp add local-tools python3 "$MCP" >/dev/null 2>&1 && echo "agy: mcp local-tools added"

# 4. tmux: titled, themed agent sessions
touch ~/.tmux.conf; install -m644 "$src/tmux-agents.conf" ~/.config/tmux-agents.conf
grep -q tmux-agents.conf ~/.tmux.conf || printf '\nsource-file ~/.config/tmux-agents.conf\n' >> ~/.tmux.conf
tmux source-file ~/.tmux.conf 2>/dev/null || true

# 6. Obsidian vault over every project's docs (live links) + hourly refresh
for u in docs-vault-sync.service docs-vault-sync.timer; do install -m644 "$root/config/ai/systemd/$u" ~/.config/systemd/user/; done
systemctl --user daemon-reload; systemctl --user enable --now docs-vault-sync.timer >/dev/null 2>&1
bash "$root/scripts/vault-sync.sh"
command -v obsidian >/dev/null || echo "Obsidian app not installed: sudo snap install obsidian --classic"
echo "Multi-agent workflow installed. Try: Super+K, or: agent ~/KadaOS codex"
