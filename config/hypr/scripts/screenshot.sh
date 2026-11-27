#!/usr/bin/env bash
# screenshot.sh [area|window|full|edit|menu|timer]
# Saves to ~/Pictures/Screenshots (same folder GNOME uses) and copies to the clipboard.
d="$(xdg-user-dir PICTURES 2>/dev/null || echo ~/Pictures)/Screenshots"; mkdir -p "$d"
f="$d/Screenshot from $(date '+%Y-%m-%d %H-%M-%S').png"
mode="${1:-area}"
if [ "$mode" = menu ]; then
  mode=$(printf '%s\n' \
    "Area	camera-photo-symbolic	drag a region" \
    "Window	view-restore-symbolic	the active window" \
    "Full screen	video-display-symbolic	the whole display" \
    "Area + annotate	document-edit-symbolic	select, then draw on it" \
    "Full screen in 5s	alarm-symbolic	timer before capture" \
    "Record screen…	media-record-symbolic	video (Ctrl+Shift+Alt+R)" \
    | ~/.config/hypr/scripts/menu.sh "Screenshot") || exit 0
  case $mode in Record*) exec ~/.config/hypr/scripts/record.sh menu;; *annotate*) mode=edit;; *5s*) mode=timer;; Area*) mode=area;; Window*) mode=window;; *) mode=full;; esac
  sleep 0.3
fi
sel(){ slurp -d -b 1e1e2e66 -c 89b4faff -w 2; }
case $mode in
  area|edit) g=$(sel) || exit 0; grim -g "$g" "$f";;
  window)    g=$(hyprctl activewindow -j | jq -r '"\(.at[0]),\(.at[1]) \(.size[0])x\(.size[1])"'); grim -g "$g" "$f";;
  timer)     notify-send -t 4000 "Screenshot in 5 seconds…"; sleep 5; grim "$f";;
  *)         grim "$f";;
esac
[ -s "$f" ] || exit 1
if [ "$mode" = edit ] && command -v swappy >/dev/null; then swappy -f "$f" -o "$f"; fi
wl-copy --type image/png < "$f"
act=$(~/.config/hypr/scripts/notify-action.py -i "$f" -t 12 "Screenshot copied" "$(basename "$f")" open=Open edit=Annotate folder="Show in folder")
case $act in open) xdg-open "$f";; edit) swappy -f "$f" -o "$f" && wl-copy --type image/png < "$f";; folder) nautilus --select "$f";; esac
