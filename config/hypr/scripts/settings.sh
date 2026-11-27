#!/usr/bin/env bash
# Open Ubuntu's Settings app inside Hyprland (Wi-Fi, sound, mouse, appearance, default apps…).
# Bluetooth: GNOME's panel needs gnome-settings-daemon (GNOME session only) and would claim
# "No Bluetooth found — plug in a dongle" here, so use Blueman instead.
if [ "${1:-}" = bluetooth ] && [ "${XDG_CURRENT_DESKTOP:-}" = Hyprland ] && command -v blueman-manager >/dev/null; then
  exec blueman-manager
fi
exec env XDG_CURRENT_DESKTOP=GNOME gnome-control-center "${1:-}"
