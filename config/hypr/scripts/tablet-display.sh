#!/usr/bin/env bash
# Use an Android tablet as a second screen (extends the desktop to the right of the laptop).
#   tablet-display.sh start [usb|tailscale]   (default usb)
#   tablet-display.sh stop | toggle | status
# On the tablet: install "AVNC" (Play Store / F-Droid).
#   usb:       enable USB debugging on the Pad, plug in the cable, connect AVNC to 127.0.0.1 port 5900
#   tailscale: both devices on your tailnet, connect AVNC to this laptop's Tailscale IP, port 5900
# Nothing is opened to your normal Wi-Fi/LAN; the firewall is left untouched.
set -u
RES="${TABLET_RES:-1800x1125}"; HZ="${TABLET_HZ:-60}"; PORT=5900
state=$XDG_RUNTIME_DIR/tablet-display; n(){ notify-send -i video-display "Tablet display" "$1"; echo "$1"; }
out(){ cat "$state" 2>/dev/null; }
start(){
  mode="${1:-usb}"
  command -v wayvnc >/dev/null || { n "wayvnc not installed: run phase8b-hyprland-polish.sh"; exit 1; }
  [ -n "$(out)" ] && { n "Already running on $(out)"; exit 0; }
  "$(dirname "$0")/tablet-control.py" stop >/dev/null 2>&1   # one Pad mode at a time
  before=$(hyprctl monitors all -j | jq -r '.[].name')
  hyprctl output create headless >/dev/null
  name=$(hyprctl monitors all -j | jq -r '.[].name' | grep -vxF -f <(printf '%s\n' "$before") | head -1)
  [ -n "$name" ] || { n "Could not create a virtual screen"; exit 1; }
  echo "$name" > "$state"
  x=$(hyprctl monitors -j | jq '[.[]|select(.name!="'"$name"'")|.x+.width]|max')
  hyprctl keyword monitor "$name,${RES}@${HZ},${x}x0,1" >/dev/null
  case $mode in
    usb) command -v adb >/dev/null || { n "adb missing"; stop; exit 1; }
         adb wait-for-device >/dev/null 2>&1 & sleep 3; kill %1 2>/dev/null
         adb reverse tcp:$PORT tcp:$PORT >/dev/null 2>&1 || { n "Tablet not found over USB. Enable USB debugging and accept the prompt on the Pad."; stop; exit 1; }
         addr=127.0.0.1;;
    tailscale) addr=$(tailscale ip -4 2>/dev/null | head -1); [ -n "$addr" ] || { n "Tailscale is not connected (run: sudo tailscale up)"; stop; exit 1; };;
    *) echo "mode must be usb or tailscale"; stop; exit 1;;
  esac
  setsid -f wayvnc -o "$name" -r -f "$HZ" "$addr" "$PORT" >"$XDG_RUNTIME_DIR/wayvnc.log" 2>&1
  n "Ready: open AVNC on the Pad and connect to $addr:$PORT (screen $name, $RES). Move windows there with Super+Shift+Right."
}
stop(){
  pkill -x wayvnc; adb reverse --remove tcp:$PORT >/dev/null 2>&1
  [ -n "$(out)" ] && hyprctl output remove "$(out)" >/dev/null; rm -f "$state"; n "Stopped"
}
case "${1:-toggle}" in
  start) start "${2:-usb}";; stop) stop;;
  toggle) [ -n "$(out)" ] && stop || start usb;;
  status) [ -n "$(out)" ] && echo "running on $(out)" || echo "off";;
  json) [ -n "$(out)" ] && printf '{"text":"\U000F04F6","class":"on","tooltip":"Tablet screen ON (%s) - click to stop"}\n' "$(out)" \
                          || printf '{"text":"\U000F04F6","class":"off","tooltip":"Tablet as second screen (Super+F12) - click to start"}\n';;
esac
