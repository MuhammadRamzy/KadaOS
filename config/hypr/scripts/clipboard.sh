#!/usr/bin/env bash
# clipboard.sh [pick|delete|wipe] — history via cliphist (text + images). Enter pastes into the focused window.
M=~/.config/hypr/scripts/menu.sh
case "${1:-pick}" in
  pick)   s=$(cliphist list | $M "Clipboard" -mesg "Enter: copy+paste · Super+Shift+V then 'delete'/'wipe' via bar right-click") || exit 0
          cliphist decode <<<"$s" | wl-copy
          command -v wtype >/dev/null && { sleep 0.15; wtype -M ctrl v -m ctrl; };;
  delete) s=$(cliphist list | $M "Delete entry") && cliphist delete <<<"$s" && notify-send "Clipboard" "Entry deleted";;
  wipe)   a=$(printf 'No\nYes, wipe all history\n' | $M "Wipe clipboard history?") && [[ $a == Yes* ]] && cliphist wipe && notify-send "Clipboard" "History wiped";;
esac
