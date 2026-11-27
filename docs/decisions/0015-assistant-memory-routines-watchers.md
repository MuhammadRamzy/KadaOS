# 0015: Assistant memory, action log, routines and watchers

Date: 2026-11-06 · Claude · Status: accepted

## Context
Roadmap phases 3–7: the assistant should know what you're doing, remember you, act on windows/media, run things on
a schedule and speak up when something is wrong, without hidden behaviour.

## Decision
- **Memory** is explicit facts in SQLite (`~/.local/share/local-ai/memory.db`) with nomic embeddings. Saved when the
  user says "remember…" or states a lasting preference; facts can be global or scoped to a project folder (those
  are injected only while that project is open). Up to 8 facts per turn, ranked by meaning past 8. `/memory`
  lists them with Forget, and the `forget` tool always asks before deleting. No silent auto-extraction from chats,
  because a 9B model would fill memory with noise.
- **Action log:** every tool step that changed something is appended to `~/.local/state/myos/assistant-actions.jsonl`
  (`/log`). The "Always allow" list is reviewable and revocable with `/permissions`.
- **Routines** are systemd user timers (`myos-routine-<name>`) that run `chat.py --routine <name>` headless. With no
  one to approve, every approval-needing step is declined. The result is a notification and a saved chat;
  `/routines` removes them. Creating a routine needs approval.
- **Watchers** (`watch.py`, `myos-watch.timer`, every 5 min): disk, failed services, low battery, heat and events
  10 min away. Each problem is notified once, then again after 6 h if it's still there. The orb gets a red ring;
  opening the panel lists and clears the alerts. The first run after 06:00 sends the daily briefing (`/briefing`).
- **Agents** (Claude Code, Codex) get `desktop_context` and `desktop_window` through the local-tools MCP server.
  They can arrange windows but can't close them.

## Consequences
Everything the assistant knows or did can be inspected in the chat. Not done: notification history (swaync has no
history API, so only the count is available), a separate quick-ask overlay (Super+Z already opens the panel with the
composer focused) and the llama.cpp speed trial (needs a separate build).
