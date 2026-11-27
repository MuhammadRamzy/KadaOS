#!/usr/bin/env bash
# Quick menu for mouse + touchpad speed. Writes Ubuntu's setting, so both desktops match.
c=$(printf '%s\n' "Very fast (1.0)" "Fast (0.6)" "Medium-fast (0.3)" "Default (0)" "Slow (-0.4)" "Open full Mouse & Touchpad settings" | ~/.config/hypr/scripts/menu.sh "Pointer speed") || exit 0
case $c in Open*) exec ~/.config/hypr/scripts/settings.sh mouse;; esac
v=$(grep -o '(-\?[0-9.]*)' <<<"$c" | tr -d '()')
gsettings set org.gnome.desktop.peripherals.mouse speed "$v"; gsettings set org.gnome.desktop.peripherals.touchpad speed "$v"
~/.config/hypr/scripts/gnome-sync.sh once; notify-send "Pointer speed" "$c (Hyprland + Ubuntu)"
