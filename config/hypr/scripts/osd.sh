#!/usr/bin/env bash
# osd.sh vol-up|vol-down|mute|mic-mute|bright-up|bright-down|caps|num
# Uses SwayOSD popups when installed; falls back to wpctl/brightnessctl + notification.
osd(){ command -v swayosd-client >/dev/null && pgrep -x swayosd-server >/dev/null; }
n(){ notify-send -t 1200 -h string:x-canonical-private-synchronous:osd -h "int:value:$2" "$1"; }
case "$1" in
  vol-up)      osd && exec swayosd-client --output-volume raise;  wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+; n "Volume" "$(wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print int($2*100)}')";;
  vol-down)    osd && exec swayosd-client --output-volume lower;  wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-; n "Volume" "$(wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print int($2*100)}')";;
  mute)        osd && exec swayosd-client --output-volume mute-toggle; wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle; n "Mute toggled" 0;;
  mic-mute)    osd && exec swayosd-client --input-volume mute-toggle;  wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle; n "Mic mute toggled" 0;;
  bright-up)   osd && exec swayosd-client --brightness raise; brightnessctl -q set 5%+; n "Brightness" "$(brightnessctl -m | cut -d, -f4 | tr -d %)";;
  bright-down) osd && exec swayosd-client --brightness lower; brightnessctl -q set 5%-; n "Brightness" "$(brightnessctl -m | cut -d, -f4 | tr -d %)";;
  caps|num)    sleep 0.05
               led=$(ls /sys/class/leds | grep -m1 "::${1}lock$")
               osd && exec swayosd-client --"$1"-lock-led "$led"
               led=$(cat /sys/class/leds/*::"${1}"lock/brightness 2>/dev/null | sort -r | head -1)
               [ "$led" = 1 ] && s=ON || s=OFF; n "${1^^} LOCK $s" 0;;
esac
