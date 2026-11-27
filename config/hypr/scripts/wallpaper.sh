#!/usr/bin/env bash
# Pick a wallpaper (Ubuntu backgrounds, ~/Pictures, ~/Downloads) as a thumbnail grid.
# Sets it in Ubuntu AND Hyprland. Falls back to a plain list if myos-pick is unavailable.
shopt -s nullglob 2>/dev/null || true
imgs=(/usr/share/backgrounds/*.png /usr/share/backgrounds/*.jpg ~/Pictures/Wallpapers/* \
      ~/Pictures/*.png ~/Pictures/*.jpg ~/Pictures/*.jpeg ~/Downloads/*.png ~/Downloads/*.jpg ~/Downloads/*.jpeg)

if [ -f ~/.local/share/myos/pick.py ] && python3 -c 'import gi' 2>/dev/null; then
  # label<TAB>thumbnail-path<TAB>subtitle ; label is the file path we act on
  rows=$'Plain black\t\tsolid background\n'
  for f in "${imgs[@]}"; do [ -f "$f" ] && rows+="${f}"$'\t'"${f}"$'\t'"$(basename "$(dirname "$f")")"$'\n'; done
  w=$(printf '%s' "$rows" | python3 ~/.local/share/myos/pick.py --title "Wallpaper" --grid --columns 4) || exit 0
else
  w=$( { echo "Plain black"; printf '%s\n' "${imgs[@]}"; } | ~/.config/hypr/scripts/menu.sh "Wallpaper") || exit 0
fi

[ -n "$w" ] || exit 0
if [ "$w" = "Plain black" ]; then echo black > ~/.config/hypr/wallpaper-mode; pkill -x hyprpaper; exit 0; fi
echo image > ~/.config/hypr/wallpaper-mode
gsettings set org.gnome.desktop.background picture-uri "file://$w"
gsettings set org.gnome.desktop.background picture-uri-dark "file://$w"
~/.config/hypr/scripts/gnome-sync.sh wall
