#!/usr/bin/env bash
# Wi-Fi picker (bar Wi-Fi icon / Super+Shift+W): scan, choose, enter the password if needed. Uses NetworkManager (nmcli).
M=~/.config/hypr/scripts/menu.sh
pkill -x rofi && exit 0
state=$(nmcli -t -f WIFI radio)
if [ "$state" != enabled ]; then
  a=$(printf 'Turn Wi-Fi on\n' | $M "Wi-Fi" -mesg "Wi-Fi is off") || exit 0; nmcli radio wifi on; sleep 2; fi
( nmcli device wifi rescan >/dev/null 2>&1 & )            # refresh in the background; show the cached list now
list=$(nmcli -t -f IN-USE,SIGNAL,SECURITY,SSID device wifi list --rescan no | awk -F: '$4!="" && !seen[$4]++ {
  lock=($3==""||$3=="--")?" ":"🔒"; mark=($1=="*")?"✔ ":"   "; printf "%d\t%s%3s%%  %s  %s\n", ($1=="*"), mark, $2, lock, $4 }' | sort -t$'\t' -k1,1nr -s | cut -f2-)
choice=$(printf '%s\n%s\n' "$list" "⚙  Network settings…" | $M "Wi-Fi" -mesg "✔ = connected · 🔒 = needs password") || exit 0
[[ $choice == *"Network settings"* ]] && exec ~/.config/hypr/scripts/settings.sh wifi
ssid=$(sed -E 's/^.{3} *[0-9]+%  .  //' <<<"$choice" | sed -E 's/^ *//')
[[ $choice == "✔"* ]] && { notify-send "Wi-Fi" "Already connected to $ssid"; exit 0; }
if nmcli -t -f NAME connection show | grep -qxF "$ssid"; then out=$(nmcli connection up id "$ssid" 2>&1)
elif [[ $choice == *"🔒"* ]]; then
  pw=$(printf '' | rofi -dmenu -password -p "Password for $ssid" -l 0 2>/dev/null) || exit 0
  out=$(nmcli device wifi connect "$ssid" password "$pw" 2>&1)
else out=$(nmcli device wifi connect "$ssid" 2>&1); fi
[ $? -eq 0 ] && notify-send "Wi-Fi" "Connected to $ssid" || notify-send -u critical "Wi-Fi" "Could not connect to $ssid: ${out##*:}"
