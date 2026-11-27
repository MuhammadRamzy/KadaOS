#!/usr/bin/env bash
# Toggle the laptop panel between its fastest refresh rate and 60 Hz (saves battery). Works on any panel.
m=$(hyprctl monitors -j | jq -c '[.[] | select(.name | startswith("eDP"))][0] // empty')
[ -n "$m" ] || { notify-send "Display" "No laptop panel found"; exit 0; }
name=$(jq -r .name <<<"$m"); w=$(jq -r .width <<<"$m"); h=$(jq -r .height <<<"$m"); cur=$(jq -r '.refreshRate|floor' <<<"$m")
max=$(jq -r --arg r "${w}x${h}@" '[.availableModes[] | select(startswith($r)) | ltrimstr($r) | rtrimstr("Hz") | tonumber | floor] | max // 60' <<<"$m")
pos=$(jq -r '"\(.x)x\(.y)"' <<<"$m"); scale=$(jq -r .scale <<<"$m")
if [ "$cur" -gt 61 ]; then hz=60; msg="60 Hz (saves battery)"; else hz=$max; msg="$max Hz"; fi
[ "$hz" = "$cur" ] && { notify-send "Display" "This panel only runs at ${cur} Hz"; exit 0; }
hyprctl keyword monitor "$name,${w}x${h}@$hz,$pos,$scale" >/dev/null && notify-send "Display" "$msg"
