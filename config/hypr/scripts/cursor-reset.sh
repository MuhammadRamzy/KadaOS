#!/usr/bin/env bash
# Clears the frozen "ghost" pointer the login screen leaves on the GPU's cursor plane.
# Hyprland draws its own cursor (no_hardware_cursors = 1) and never touches that plane, so the
# login screen's pointer stays stuck on screen. Briefly using the hardware cursor overwrites it.
# Run by hyprland.conf at login; safe to run by hand any time.
# One 1 px nudge from the *live* position: the old 5 s jiggle kept warping the pointer back
# to where it started, so the mouse fought the user for the first seconds after login.
sleep "${1:-2}"
hyprctl -q keyword cursor:no_hardware_cursors 0
read -r x y < <(hyprctl cursorpos | tr -d ,)
hyprctl -q dispatch movecursor $((x + 1)) "$y"
hyprctl -q dispatch movecursor "$x" "$y"
sleep 1
hyprctl -q keyword cursor:no_hardware_cursors 1
