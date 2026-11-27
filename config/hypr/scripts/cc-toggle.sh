#!/usr/bin/env bash
# Control-center toggles.  cc-toggle.sh <wifi|bt|night|tablet> [state]
# With "state": print true/false. Without: apply $SWAYNC_TOGGLE_STATE (set by swaync) or flip.
S=~/.config/hypr/scripts
state(){ case $1 in
  wifi)   [ "$(nmcli radio wifi)" = enabled ];;
  bt)     bluetoothctl show | grep -q 'Powered: yes';;
  night)  pgrep -x wlsunset >/dev/null;;
  tablet) [ "$($S/tablet-control.py status)" = on ];;
esac; }
if [ "${2:-}" = state ]; then state "$1" && echo true || echo false; exit 0; fi
want=${SWAYNC_TOGGLE_STATE:-}; [ -z "$want" ] && { state "$1" && want=false || want=true; }
case $1 in
  wifi)   [ "$want" = true ] && nmcli radio wifi on || nmcli radio wifi off;;
  bt)     rfkill unblock bluetooth 2>/dev/null; [ "$want" = true ] && bluetoothctl power on || bluetoothctl power off;;
  night)  [ "$want" = true ] && { pgrep -x wlsunset >/dev/null || setsid -f wlsunset -t 4000 -T 4001 -S 06:30 -s 19:00 >/dev/null 2>&1; } || pkill -x wlsunset;;
  tablet) [ "$want" = true ] && $S/tablet-control.py start || $S/tablet-control.py stop;;
esac >/dev/null 2>&1
pkill -RTMIN+8 waybar 2>/dev/null; true
