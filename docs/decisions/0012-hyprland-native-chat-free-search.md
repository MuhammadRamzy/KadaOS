# 0012 — Keep Hyprland, native AI chat app, free web search

Date: 2026-11-04 · Status: accepted (user)

The user decided:

1. **Desktop:** stay on Hyprland and make it better. No move to GNOME, no new shell. GNOME stays installed as
   the fallback session.
2. **AI chat:** a native desktop app (GTK4/libadwaita), not a browser page.
3. **Web search:** a free provider. Choice: a local SearXNG metasearch container (Docker, localhost only). It
   needs no API key or account, sends no queries to a single tracking provider, has no per-query cost, and
   can be removed with `docker rm`. Answers that use the web show dated source links.
