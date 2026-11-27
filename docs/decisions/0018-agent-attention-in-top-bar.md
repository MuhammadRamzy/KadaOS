# 0018 — Agent and window attention in the top bar

Date: 2026-11-20 · Status: accepted

## Context
The user runs several agents (Claude Code, Codex, …) in terminals across workspaces. When one finished or needed
approval, the only sign was a popup with a raw text dump, and the bar showed nothing. They want the desktop to act like
a secretary: know what each agent is doing, show what needs them, and keep notifications short and useful.

## Decision
- `agent-notify` (called by Claude Code hooks `UserPromptSubmit`/`Stop`/`Notification` and Codex `notify`) keeps one
  state file, `$XDG_RUNTIME_DIR/myos-agents.json`: per session agent, project, terminal window address, workspace,
  state (`working → done | needs → seen`) and a one-line summary.
- **Which window?** Ptyxis runs every window in one process, so a PID can't identify one. The window that is focused
  when you submit a prompt is the agent's terminal; that address is remembered. Fallback: match by tmux session,
  project or agent name in terminal titles.
- **Bar:** `bar-status.py attention` merges agent state with Hyprland `urgent` events. Priority: needs you, then a window
  wants attention, then finished. Focusing the window marks it seen. One reminder after 5 minutes of "needs you".
  Clicking the pill jumps to the window (`bar-status.py goto`).
- **Notifications:** no popup if you're already looking at that window. Text is a plain one-liner. The local model
  rewrites it only when it is already loaded (never wakes the GPU); `MYOS_NO_AI=1` turns that off. "Needs you" stays
  up until acted on; "finished" times out after 12 s. Claude's repeated `idle_prompt` is ignored.

## Consequences
- A session started without a prompt typed in a terminal (for example by a script) has no remembered window until the
  title fallback finds one.
- Stage 2 (built the same day): `secretary.py` sorts all notifications; quiet mode for fullscreen, calls and screen
  sharing with a digest afterwards; a "What needs me" panel (Super+Y) and a bar inbox count. Everything stays on the
  laptop; the only AI use is the already-loaded local model for agent summaries.
