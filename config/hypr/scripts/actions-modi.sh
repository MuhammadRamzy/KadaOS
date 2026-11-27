#!/usr/bin/env bash
# rofi "actions" modi for the launcher: system actions searchable next to apps and layouts.
# Type part of a name (e.g. "screenshot", "wifi", "lock", "night") and run it from Super+Space.
set -eu
S="$HOME/.config/hypr/scripts"
run() { setsid sh -c "$1" >/dev/null 2>&1 < /dev/null & }

# "Label<TAB>command<TAB>icon" — label is what rofi shows/matches; command runs on selection.
actions() {
  printf '%s\t%s\t%s\n' \
    "Screenshot: area"              "$S/screenshot.sh area"                 "camera-photo" \
    "Screenshot: full screen"       "$S/screenshot.sh full"                 "camera-photo" \
    "Screenshot: window"            "$S/screenshot.sh window"               "camera-photo" \
    "Screenshot: area + annotate"   "$S/screenshot.sh edit"                 "document-edit" \
    "Clipboard history"             "$HOME/.local/bin/myos-panel clipboard" "edit-paste" \
    "Calendar"                      "$HOME/.local/bin/myos-panel calendar"  "x-office-calendar" \
    "Wi-Fi networks"                "$HOME/.local/bin/myos-panel wifi"      "network-wireless" \
    "Bluetooth devices"             "$HOME/.local/bin/myos-panel bluetooth" "bluetooth" \
    "AI Chat"                       "gtk-launch org.myos.Chat"              "chat-message-new" \
    "Ask AI (selected text)"        "$HOME/.local/bin/ai-menu"              "emblem-system" \
    "Talk to the assistant"         "$HOME/.local/bin/ai-chat --listen"    "audio-input-microphone" \
    "Find files by meaning"         "$HOME/.local/bin/ai-search"           "system-search" \
    "Dictate (voice typing)"        "$HOME/.local/bin/ai-dictate toggle"   "audio-input-microphone" \
    "Lock screen"                   "$S/lock.sh"                            "system-lock-screen" \
    "What needs me"                 "$HOME/.local/bin/myos-panel inbox"     "mail-unread" \
    "Remote devices (SSH)"          "$HOME/.local/bin/myos-panel remote"    "network-server" \
    "Who is on my network"          "ptyxis --new-window -T network -- sh -c '$HOME/.local/bin/board net; echo; read -r -p \"Enter to close \" _'" "network-workgroup" \
    "Serial console"                "ptyxis --new-window -T serial -- sh -c '$HOME/.local/bin/board serial || read -r _'" "utilities-terminal" \
    "My network info (IPs · DNS)"   "ptyxis --new-window -T network -- sh -c '$HOME/.local/bin/board net info; echo; read -r -p \"Enter to close \" _'" "network-wired" \
    "Top bar: show"                 "$S/bar.sh on"                          "view-reveal" \
    "Top bar: hide"                 "$S/bar.sh off"                         "view-conceal" \
    "Top bar: auto-hide"            "$S/bar.sh auto"                        "view-fullscreen" \
    "Night light: toggle"           "$S/nightlight.sh"                      "weather-clear-night" \
    "Power mode: cycle"             "$S/power-profile.sh cycle"            "power-profile-performance" \
    "Do not disturb: toggle"        "swaync-client -d -sw"                 "notifications-disabled" \
    "Pad control (mouse + keyboard)" "$S/tablet-control.py toggle"         "input-mouse" \
    "Pad as second screen"          "$S/tablet-display.sh toggle"          "computer" \
    "Colour picker (copy hex)"      "hyprpicker -a && notify-send 'Color copied' \"\$(wl-paste)\"" "color-select" \
    "Change wallpaper"              "$S/wallpaper.sh"                       "preferences-desktop-wallpaper" \
    "Settings"                      "$S/settings.sh"                        "preferences-system" \
    "Shortcuts (cheatsheet)"        "$S/keyhelp.sh"                         "input-keyboard" \
    "Record screen (start / stop)" "$S/record.sh toggle" "media-record" \
    "Storage: free up space" "$HOME/.local/bin/myos-panel storage" "drive-harddisk" \
    "Security checkup" "$HOME/.local/bin/myos-panel security" "security-high" \
    "Battery health" "$HOME/.local/bin/myos-panel battery" "battery-good" \
    "Profile: choose" "$HOME/.local/bin/profile menu" "applications-science" \
    "Displays: arrange" "nwg-displays" "video-display" \
    "Displays: remember this layout" "$HOME/.local/bin/monitors save" "video-display" \
    "Projects" "$HOME/.local/bin/myos-panel projects" "folder" \
    "Services: ports and Docker" "$HOME/.local/bin/myos-panel services" "network-server" \
    "Agent tasks" "$HOME/.local/bin/myos-panel tasks" "system-run" \
    "Password vault (KeePassXC)" "sh -c 'command -v keepassxc >/dev/null && exec keepassxc || notify-send -a Vault KeePassXC Run:\\ bash\\ scripts/phase14-secrets.sh'" "dialog-password" \
    "Network trust: Home / Work / Public" "$HOME/.local/bin/trust menu" "network-wireless-encrypted" \
    "Phone" "$HOME/.local/bin/myos-panel phone" "phone" \
    "Downloads: tidy now" "$HOME/.local/bin/tidy --apply" "folder-download" \
    "Power menu"                    "$S/power-menu.sh"                      "system-shutdown"
}

case ${ROFI_RETV:-0} in
  0)
    actions | while IFS=$'\t' read -r label _cmd icon; do
      printf '%s\0icon\x1f%s-symbolic\n' "$label" "$icon"
    done
    ;;
  1)
    cmd=$(actions | awk -F'\t' -v l="${1:-}" '$1==l{print $2; exit}')
    [ -n "$cmd" ] && run "$cmd"
    ;;
esac
