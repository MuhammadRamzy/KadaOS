#!/usr/bin/env bash
# Dropdown ("quake") terminal: a full-width kitty that slides down from the top and hides on toggle.
# Lives on the special:term workspace so it persists across workspaces. Bound to Super+`.
if ! hyprctl clients -j | jq -e '.[] | select(.class=="kitty-dropdown")' >/dev/null 2>&1; then
  hyprctl dispatch exec '[workspace special:term silent] kitty --class kitty-dropdown'
  for _ in $(seq 1 30); do
    hyprctl clients -j | jq -e '.[] | select(.class=="kitty-dropdown")' >/dev/null 2>&1 && break
    sleep 0.05
  done
fi
hyprctl dispatch togglespecialworkspace term
