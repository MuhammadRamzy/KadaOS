#!/usr/bin/env bash
# Categorized, searchable keyboard cheatsheet (GTK). Falls back to a rofi list if GTK is unavailable.
if command -v python3 >/dev/null && python3 -c "import gi" 2>/dev/null; then
  exec python3 ~/.local/share/myos/cheatsheet.py
fi
list=$(hyprctl binds -j | jq -r '.[]|select(.description!="")|.description' | sort -u)
printf '%s\n' "$list" | ~/.config/hypr/scripts/menu.sh "Shortcuts"
