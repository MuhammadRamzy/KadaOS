#!/usr/bin/env bash
# Runs in the Hyprland session. Applies Ubuntu (GNOME) settings to Hyprland at login and live whenever
# they change — so Ubuntu Settings (Super+I) controls mouse/touchpad speed, scrolling, cursor, keyboard repeat,
# dark mode and wallpaper in BOTH desktops.
g(){ gsettings get "$1" "$2" 2>/dev/null | tr -d "'"; }
tp(){ hyprctl devices -j | jq -r '.mice[].name' | grep -i touchpad; }
apply(){
  ms=$(g org.gnome.desktop.peripherals.mouse speed); ts=$(g org.gnome.desktop.peripherals.touchpad speed)
  hyprctl keyword input:sensitivity "${ms:-0}" >/dev/null
  prof=$(g org.gnome.desktop.peripherals.mouse accel-profile); [ "$prof" = flat ] && hyprctl keyword input:accel_profile flat >/dev/null || hyprctl keyword input:accel_profile adaptive >/dev/null
  hyprctl keyword input:natural_scroll "$(g org.gnome.desktop.peripherals.mouse natural-scroll)" >/dev/null
  hyprctl keyword input:left_handed "$(g org.gnome.desktop.peripherals.mouse left-handed)" >/dev/null
  for d in $(tp); do
    hyprctl keyword "device[$d]:sensitivity" "${ts:-0}" >/dev/null
    hyprctl keyword "device[$d]:natural_scroll" "$(g org.gnome.desktop.peripherals.touchpad natural-scroll)" >/dev/null
    hyprctl keyword "device[$d]:tap-to-click" "$(g org.gnome.desktop.peripherals.touchpad tap-to-click)" >/dev/null
    hyprctl keyword "device[$d]:disable_while_typing" "$(g org.gnome.desktop.peripherals.touchpad disable-while-typing)" >/dev/null
  done
  if [ "$(g org.gnome.desktop.peripherals.keyboard repeat)" = true ]; then
    del=$(gsettings get org.gnome.desktop.peripherals.keyboard delay | awk '{print $2}')
    iv=$(gsettings get org.gnome.desktop.peripherals.keyboard repeat-interval | awk '{print $2}')
    hyprctl keyword input:repeat_delay "${del:-250}" >/dev/null
    [ "${iv:-0}" -gt 0 ] && hyprctl keyword input:repeat_rate "$((1000 / iv))" >/dev/null
  fi
  cur=$(g org.gnome.desktop.interface cursor-theme); [ "$cur" = default ] && cur=Yaru
  hyprctl setcursor "$cur" "$(g org.gnome.desktop.interface cursor-size)" >/dev/null
  numlock=$(g org.gnome.desktop.peripherals.keyboard numlock-state); hyprctl keyword input:numlock_by_default "${numlock:-true}" >/dev/null
}
wall(){
  [ "$(cat ~/.config/hypr/wallpaper-mode 2>/dev/null)" = image ] || { pkill -x hyprpaper; return; }   # black background mode
  # Ubuntu keeps its wallpaper as ~/.config/background (no extension) which hyprpaper rejects,
  # and the Odyssey image is 7680x4320. Make a screen-sized JPG copy and point hyprpaper at it.
  uri=$(g org.gnome.desktop.background picture-uri-dark); src="${uri#file://}"; src="${src//%20/ }"
  [ -f "$src" ] || return
  out=~/.cache/setup/wallpaper.jpg; mkdir -p ~/.cache/setup
  # brightness factor (1 = as is, 0.55 = about half as bright) keeps text and glass readable over any picture
  dim=$(cat ~/.config/hypr/wallpaper-dim 2>/dev/null || echo 0.55)
  if [ ! -s "$out" ] || [ "$src" -nt "$out" ] || [ "$(cat ~/.cache/setup/wallpaper.src 2>/dev/null)" != "$src|$dim" ]; then
    python3 - "$src" "$out" "$dim" <<'PY' || cp "$src" "$out"
import sys
from PIL import Image, ImageEnhance, ImageOps
im = Image.open(sys.argv[1]); im = ImageOps.exif_transpose(im).convert("RGB")
im = ImageOps.fit(im, (2560, 1600), Image.LANCZOS)
ImageEnhance.Brightness(im).enhance(float(sys.argv[3])).save(sys.argv[2], "JPEG", quality=92)
PY
    echo "$src|$dim" > ~/.cache/setup/wallpaper.src
  fi
  printf 'splash = false
ipc = true
wallpaper {
    monitor =
    path = %s
    fit_mode = cover
}
' "$out" > ~/.config/hypr/hyprpaper.conf
  pkill -x hyprpaper; sleep 0.3; setsid -f hyprpaper >/dev/null 2>&1
}
[ "${1:-}" = wall ] && { wall; exit 0; }
[ "${1:-}" = apply ] && { apply; exit 0; }   # input/cursor only (system-adapt runs this after a config reload)
apply; wall
[ "${1:-}" = once ] && exit 0
# live: re-apply whenever GNOME settings change (e.g. from Super+I Settings)
{ gsettings monitor org.gnome.desktop.peripherals.mouse & gsettings monitor org.gnome.desktop.peripherals.touchpad &
  gsettings monitor org.gnome.desktop.peripherals.keyboard & gsettings monitor org.gnome.desktop.interface &
  gsettings monitor org.gnome.desktop.background & wait; } | while read -r line; do
  case $line in picture-uri*) wall;; *) apply;; esac
done
