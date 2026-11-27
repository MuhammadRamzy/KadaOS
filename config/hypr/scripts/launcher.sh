#!/usr/bin/env bash
# Super+Space launcher. Native myos-run (apps + actions + layouts + calculator/hash/convert), kept
# resident for instant reopen; falls back to a rofi combi if GTK is unavailable.
pkill -x rofi 2>/dev/null && exit 0
if [ -f ~/.local/share/myos/run.py ]; then
  # toggle: if the launcher window is showing, hide it (close-request hides the resident app)
  if hyprctl clients -j 2>/dev/null | grep -q '"org.myos.Run"'; then
    hyprctl dispatch closewindow 'class:^(org\.myos\.Run)$'; exit 0
  fi
  # already resident: wake it over D-Bus (~10 ms instead of ~190 ms of Python + GTK start-up)
  gdbus call --session --dest org.myos.Run --object-path /org/myos/Run \
    --method org.gtk.Application.Activate '{}' >/dev/null 2>&1 && exit 0
  python3 -c 'import gi' 2>/dev/null && exec python3 ~/.local/share/myos/run.py   # first start
fi
d="$(dirname "$0")"
if command -v rofi >/dev/null; then
  exec rofi -show combi -show-icons \
    -modi "combi,drun,flow:$d/flow-modi.sh,actions:$d/actions-modi.sh" \
    -combi-modi 'flow,drun,actions' \
    -theme-str 'entry { placeholder: "Search apps, layouts and actions"; }'
fi
exec wofi --show drun --allow-images
