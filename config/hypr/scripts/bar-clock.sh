#!/usr/bin/env bash
# Top-bar clock (waybar custom/clock, long-running). Left click = calendar (set in waybar),
# right click runs "bar-clock.sh toggle" to switch short <-> long date. State lives in the runtime dir.
long="${XDG_RUNTIME_DIR:-/tmp}/bar-clock-long"; pidf="${XDG_RUNTIME_DIR:-/tmp}/bar-clock.pid"
if [ "${1:-}" = toggle ]; then
  if [ -e "$long" ]; then rm -f "$long"; else touch "$long"; fi
  kill -USR1 "$(cat "$pidf" 2>/dev/null)" 2>/dev/null   # redraw now instead of on the next tick
  exit 0
fi
echo $$ > "$pidf"
trap ':' USR1                              # interrupts the wait below: redraw at once
read -r _ _ _ parent _ < /proc/$$/stat   # waybar; if it goes away we must too (else every bar restart leaks a clock)
exec 3<> <(:)                            # a pipe nobody writes: "read -t 1" on it = a 1 s sleep with no process spawned
tip='Click: calendar and upcoming events\nRight-click: long / short date'
while :; do
  read -r _ _ _ now _ < /proc/$$/stat; [ "$now" = "$parent" ] || exit 0
  # bash built-ins only (printf %()T, [ -e ]): no date/sleep processes every second
  if [ -e "$long" ]; then printf -v t '%(%A, %d %B %Y  %I:%M:%S %p)T' -1; c=long; else printf -v t '%(%a %d %b  %I:%M %p)T' -1; c=short; fi
  [ "$t" = "$last" ] || printf '{"text":"%s","tooltip":"%s","class":"%s"}\n' "$t" "$tip" "$c"   # redraw only on change
  last=$t
  read -r -t 1 -u 3 _
done
