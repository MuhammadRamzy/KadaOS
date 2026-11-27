#!/usr/bin/env bash
# Opens the same default browser as Ubuntu/GNOME (xdg-settings).
b=$(xdg-settings get default-web-browser 2>/dev/null); exec gtk-launch "${b%.desktop}" 2>/dev/null || exec xdg-open https://
