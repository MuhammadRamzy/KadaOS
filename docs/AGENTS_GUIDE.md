# Coding agents: Claude Code · Codex · Antigravity · local AI

## Which one for what
| Agent | Best at | Cost |
|---|---|---|
| **Claude Code** | Deep multi-file work, refactors, docs, careful reasoning | Subscription |
| **Codex** | Implementing, debugging, tests, code review | Subscription |
| **Antigravity** (app + `agy` CLI) | Very large context, research, browser/UI tasks, alternative approaches | Antigravity Pro |
| **Local AI** (Ornith 9B) | Private, offline, bulk summarize/classify/draft, questions about the laptop | Free |

## Launch (Super + K)
**Super + K** lists your projects, with running sessions first, then asks which agent to use.
- **One session per project:** each project gets its own persistent **tmux session** (`ag-<project>`), and each agent is a tab in it.
- **Background work:** close the window and the agents keep working. Super + K brings the session back.
- **Session keys:** `Ctrl+b n` / `Ctrl+b p` switch tabs, `Ctrl+b d` detaches, and the mouse works too.
- **Bar counter:** the bar shows how many agent sessions are running. Click it to open the menu.
- **Quick keys:** Super + C / Super + X open Claude / Codex in this setup repo.
- **Command line:** `agent [dir] [claude|codex|agy|local|shell|antigravity]` · `agent ls` · `agent kill [dir]`.

## Get told when they need you
- **Claude Code** (through its hooks) and **Codex** (through `notify`) send a notification when they finish or wait for approval.
- **Show** jumps to that agent's terminal and tab.
- Nothing is sent if you're already looking at that agent.

## One rulebook for all agents
- `config/agents/global-rules.md` is linked as `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` and `~/.gemini/GEMINI.md`. Edit it once and every agent follows it.
- `proj-init [dir]` (or "Make multi-agent ready" in Super + K) adds these to a project:
  - `AGENTS.md`, the project's source of truth, with build/test/lint commands detected automatically.
  - `CLAUDE.md` (`@AGENTS.md`) and `GEMINI.md` (a symlink to it).
  - `docs/STATUS.md`, `docs/HANDOFF.md`, `docs/decisions/` and `docs/reviews/`.
- **Contract:** agents read STATUS and HANDOFF first, and update HANDOFF before stopping. That way Claude can pick up where Codex left off, and the other way round.

## Cross-review
`agent-review --by codex|claude|agy [--base main]` has a different agent review the current changes, read-only, and saves the review to `docs/reviews/`. It's also in Super + K → Cross-review.

## Local AI inside every agent (MCP server "local-tools")
All agents can call these tools on your laptop. They're free and private:
- `local_ai`: bulk summarize, classify, extract or translate with the local model, which saves your paid usage.
- `search_files` / `ask_files`: search your own documents and projects by meaning.
- `system_status` / `system_command`: live laptop facts. These are read-only and use an allow-list.

Check it's connected: `claude mcp list` · `codex mcp list` · `agy mcp list`.

## Install / repair
- `bash scripts/phase11-agents.sh`: Antigravity (Google's apt repo, needs sudo) plus everything above.
- `bash scripts/install-agents.sh`: the user-level part only. It backs up agent configs to `~/.config/setup-backups/agents-*`.
