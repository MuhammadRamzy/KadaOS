#!/usr/bin/env bash
# Restart the top bar in its saved mode (on / off / auto-hide). Starting `waybar` directly would add a second bar
# that ignores auto-hide, and the auto-hide watcher would toggle the wrong one.
exec ~/.config/hypr/scripts/bar.sh start
