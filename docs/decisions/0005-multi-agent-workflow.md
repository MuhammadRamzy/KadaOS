# ADR 0005: Multi-agent workflow
**Status:** accepted · 2026-09-25

**Decision:**
- **Shared rules:** one global rulebook, symlinked into every agent's config directory. Per project, `AGENTS.md` is the source of truth, and `CLAUDE.md` and `GEMINI.md` point to it.
- **Local AI for agents:** one dependency-free stdio MCP server (`local-tools`) exposes the local AI to all agents.
- **Sessions:** persistent tmux sessions per project (`ag-<project>`), opened with Super+K.
- **Notifications:** Claude hooks and Codex `notify` both call `agent-notify`.
- **Cross-review:** read-only, with the result saved to `docs/reviews/`.

**Why:** the user pays for several agents. Shared state (AGENTS.md, HANDOFF.md) and shared local tools let them hand work to each other, and the free local model takes low-stakes bulk work.
