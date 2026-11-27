#!/usr/bin/env bash
# Top bar (waybar) visibility. Mode is remembered in ~/.config/hypr/bar-mode.
#   bar.sh on | off | auto   set the mode (auto = hidden, shows when the mouse touches the top edge)
#   bar.sh toggle            show/hide (Super+Shift+B)
#   bar.sh start             apply the saved mode (run at login)
# A supervisor restarts waybar if it ever crashes, so the bar can't silently go missing.
MODE_FILE="$HOME/.config/hypr/bar-mode"
RT="${XDG_RUNTIME_DIR:-/tmp}"; AUTO_CFG="$RT/waybar-auto.json"; SUP_PID="$RT/bar-supervisor.pid"; WATCH_PID="$RT/bar-watch.pid"
mode=$(cat "$MODE_FILE" 2>/dev/null || echo on)

stop() {
  for f in "$SUP_PID" "$WATCH_PID"; do kill "$(cat "$f" 2>/dev/null)" 2>/dev/null; rm -f "$f"; done
  pkill -x waybar; pkill -x swaync-client   # its watcher would be orphaned
  for _ in 1 2 3 4 5 6 7 8; do pgrep -x waybar >/dev/null || break; sleep 0.1; done
}

apply() {
  stop
  case $mode in
    off) ;;
    auto)
      # Same bar, but floats over windows (no reserved space) and starts hidden.
      python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); c.update(exclusive=False, layer="overlay", start_hidden=True); json.dump(c, open(sys.argv[2], "w"))' \
        ~/.config/waybar/config.jsonc "$AUTO_CFG"
      setsid -f "$0" supervise -c "$AUTO_CFG" -s ~/.config/waybar/style.css >/dev/null 2>&1
      setsid -f "$0" watch >/dev/null 2>&1 ;;
    *) setsid -f "$0" supervise >/dev/null 2>&1 ;;
  esac
}

case ${1:-start} in
  on|off|auto) mode=$1; echo "$mode" > "$MODE_FILE"; apply
               notify-send -a KadaOS -t 1500 -i view-reveal-symbolic "Top bar" "Mode: $mode" 2>/dev/null ;;
  toggle) [ "$mode" = on ] && exec "$0" off || exec "$0" on ;;
  start) apply ;;
  supervise)
    shift; echo $$ > "$SUP_PID"; trap 'kill "$wb" 2>/dev/null; exit 0' TERM INT
    fails=0
    while :; do
      t0=$(date +%s); waybar "$@" >/dev/null 2>&1 & wb=$!; wait "$wb"
      # crashed: restart; back off if it keeps dying right away (broken config) instead of spinning
      [ $(( $(date +%s) - t0 )) -lt 10 ] && fails=$((fails + 1)) || fails=0
      [ "$fails" -ge 5 ] && { notify-send -a KadaOS -u critical "Top bar keeps crashing" "Run: waybar  (in a terminal) to see why"; sleep 60; fails=0; }
      sleep 2
    done ;;
  watch)
    # ponytail: polls the cursor 5x/s (hyprctl has no cursor events); cheap, but a socket-based listener would be idle-free.
    echo $$ > "$WATCH_PID"; shown=0; pid=""
    while :; do
      now=$(pgrep -x waybar | head -1)
      if [ -z "$now" ]; then sleep 1; continue; fi
      if [ "$now" != "$pid" ]; then pid=$now; shown=0; sleep 1; continue; fi   # (re)started hidden; SIGUSR1 before it's ready would kill it
      y=$(hyprctl cursorpos 2>/dev/null | cut -d, -f2 | tr -d ' ')
      if [ "$shown" = 0 ] && [ "${y:-99}" -le 2 ]; then kill -USR1 "$pid"; shown=1
      elif [ "$shown" = 1 ] && [ "${y:-0}" -gt 60 ]; then kill -USR1 "$pid"; shown=0; fi
      sleep 0.2
    done ;;
  *) echo "usage: bar.sh on|off|auto|toggle|start" >&2; exit 2 ;;
esac
