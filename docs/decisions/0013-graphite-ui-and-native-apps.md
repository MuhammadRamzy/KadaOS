# 0013 — Graphite UI, native apps, and file actions

Date: 2026-11-05 · Status: accepted (Claude, user-authorized implementation)

The user asked for a premium, coherent, Apple-quality desktop with real workflow freedom ("do anything,
beautifully"), referencing Apple HIG and Material, Tangerine-style file tools, and PowerToys-level utilities.
Phase 2 was implemented directly (not just planned). Design language: **Graphite** — neutral graphite
surfaces, one blue accent (matching the GNOME accent), semantic red/green/orange, Adwaita Sans UI font,
JetBrains Mono for code, 12-hour clocks, squircle corners, short no-overshoot motion.

Implemented:
- **Theme** (`scripts/theme.py`): one semantic palette → Hyprland, Waybar, rofi, SwayNC, SwayOSD, Hyprlock,
  Wlogout, Wofi, Kitty, Ptyxis. Adwaita fonts installed to `~/.local/share/fonts/AdwaitaFonts`.
- **Top bar**: decluttered — no hover drawer; at-a-glance keep-awake, power-mode, CPU, temp; transient
  states (dictation, Caps, agents) show only when active. All quick actions live in the control center.
- **Control center** (SwayNC): Wi-Fi, Bluetooth, Night light, Tablet, Screenshot, Clipboard, AI Chat,
  Voice, Find files, Dictate, Shortcuts, Power mode, Settings, Power + volume/brightness/DND.
- **Lock screen** (Hyprlock): identity-forward — glowing "MR" hero wordmark, greeting, glassy password
  field, corner 12-hour clock, battery/now-playing. Monogram/hero generated from the account name.
- **Launcher** (rofi): generic placeholder, secondary app descriptions, no empty icon column, layout icons.
- **Native panels** (`config/desktop/panel.py`, `org.myos.Panel`, resident, D-Bus reopen ~150 ms):
  live Wi-Fi (NetworkManager), Bluetooth (GNOME Bluetooth), and a Win+V clipboard (cliphist) with
  search, image thumbnails, paste-into-previous-window. Super+V / Super+Shift+W / bar / control center.
- **Shortcuts cheatsheet** (`config/desktop/cheatsheet.py`, `org.myos.Shortcuts`): categorized,
  searchable, key-chip layout built from live binds. Replaces the flat rofi list (Super+/).
- **AI Chat** (`config/ai/chat.py`, `org.myos.Chat`): persistent chat, files, local SearXNG web sources.
- **File Actions** (`config/desktop/fileactions.py`): Tangerine-style convert/resize/compress/PDF/archive
  from the Files right-click menu; engines already present (Pillow, ffmpeg, LibreOffice, Ghostscript,
  Poppler, zip/7z); originals preserved, collision-safe output, background jobs with progress + reveal.

Rollback: `scripts/theme.py` regenerates all config from the palette; previous live files were backed up
to `~/.local/share/local-ai/backups-2026-11-04/` and `.../theme-odyssey/`. Each native app is independent
and removable. The previous "Odyssey" navy/gold palette is replaced per the user's explicit redesign request.
