#!/usr/bin/env bash
# Keep the laptop awake (no dim, lock or sleep) until turned off.
# Holds a logind idle+sleep inhibitor, which hypridle honours.   keep-awake.sh on|off|toggle|status
pidf="${XDG_RUNTIME_DIR:-/tmp}/keep-awake.pid"
running() { [ -f "$pidf" ] && kill -0 "$(cat "$pidf")" 2>/dev/null; }
case "${1:-toggle}" in
  on)
    running || { setsid systemd-inhibit --what=idle:sleep --who=KadaOS --why="Keep awake" sleep infinity >/dev/null 2>&1 &
                 echo $! > "$pidf"; }
    notify-send -a "Keep awake" -i weather-clear-symbolic "Keep awake: on" "No dimming, lock or sleep until you turn it off." ;;
  off)
    running && kill -- "-$(cat "$pidf")" 2>/dev/null; rm -f "$pidf"
    notify-send -a "Keep awake" -i weather-clear-night-symbolic "Keep awake: off" "Normal dim, lock and sleep timers are back." ;;
  toggle) if running; then "$0" off; else "$0" on; fi ;;
  status) if running; then echo on; else echo off; fi ;;
  *) echo "usage: keep-awake.sh on|off|toggle|status" >&2; exit 2 ;;
esac
