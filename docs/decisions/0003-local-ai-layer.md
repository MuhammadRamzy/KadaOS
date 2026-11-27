# ADR 0003: A local-first AI layer
**Status:** accepted · 2026-09-25

**Context:** the goal is private, offline, low-latency AI help across the desktop on an 8 GB RTX 5050.

**Decision:**
- **Text:** Qwen3 8B through Ollama, run as a *user* service (`ollama-local`, unloads after 5 min idle), with `think:false`, length limits and a repeat penalty.
- **Search:** nomic-embed-text embeddings in SQLite. The index refreshes hourly on AC power.
- **Speech:** Whisper large-v3-turbo through whisper.cpp's Vulkan backend on the NVIDIA GPU, with a Silero VAD. For live dictation, `whisper-server` starts on demand and a local VAD commits a phrase at each pause.
- **Laptop assistant:** read-only tools only (an allow-list, no sudo, no pipes, no secret paths). It suggests fixes and never applies them.
- **Claude:** an explicit option for harder questions.

**Consequences:**
- About 6 GB of video memory is used while both models are loaded. The GPU is idle otherwise.
- The desktop pop-ups work in Hyprland only; the terminal helpers work everywhere.
