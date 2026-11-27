#!/usr/bin/env bash
# menu.sh "Prompt" [-mesg HINT] [-l 0] [-back] — themed picker (myos-pick), falling back to rofi/wofi.
# -back (submenus): offers Back; exits with status 2 when the user goes back.
# A list on stdin becomes a grid/list picker; empty stdin or `-l 0` becomes a free-text entry.
p="${1:-Select}"; shift 2>/dev/null || true
hint=""; input=0; back=0; rest=()
while [ $# -gt 0 ]; do
  case "$1" in
    -mesg) hint="${2:-}"; shift 2 || shift;;
    -l) [ "${2:-}" = 0 ] && input=1; shift 2 || shift;;
    -back) back=1; shift;;
    *) rest+=("$1"); shift;;
  esac
done
if command -v python3 >/dev/null && python3 -c 'import gi' 2>/dev/null; then
  data=""; [ "$input" = 1 ] || data=$(cat)
  args=(--title "$p"); [ -n "$hint" ] && args+=(--placeholder "$hint"); [ "$back" = 1 ] && args+=(--back)
  if [ "$input" = 1 ] || [ -z "$data" ]; then
    args+=(--input); exec python3 ~/.local/share/myos/pick.py "${args[@]}" </dev/null
  fi
  printf '%s' "$data" | exec python3 ~/.local/share/myos/pick.py "${args[@]}"
elif command -v rofi >/dev/null; then
  exec rofi -dmenu -i -p "$p" ${hint:+-mesg "$hint"} "${rest[@]}"
else
  exec wofi --dmenu -i -p "$p" --cache-file /dev/null
fi
