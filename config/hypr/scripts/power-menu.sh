#!/usr/bin/env bash
# Power menu: one row of square-ish buttons, centred on the focused screen.
pkill -x wlogout && exit 0
h=$(hyprctl monitors -j | jq '.[]|select(.focused)|.height/.scale|floor'); w=$(hyprctl monitors -j | jq '.[]|select(.focused)|.width/.scale|floor')
v=$(( (h - 260) / 2 )); s=$(( (w - 1100) / 2 )); [ $s -lt 20 ] && s=20
exec wlogout -b 5 -p layer-shell -T $v -B $v -L $s -R $s
