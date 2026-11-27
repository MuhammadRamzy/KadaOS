#!/usr/bin/env bash
# rofi "flow" modi for the app launcher: work-layout profiles + a reliable Custom-layout entry.
# Selecting an entry (ROFI_RETV=1) or typing custom text then Ctrl+Enter (ROFI_RETV=2) launches flow.py.
set -eu
self="$(dirname "$0")"
run() { setsid "$self/flow.py" --ai -- "$1" >/dev/null 2>&1 < /dev/null & }
case ${ROFI_RETV:-0} in
  0)
    for p in Coding 'Web dev' Research 'Security lab' Wireless; do
      printf '▶ Start: %s\0icon\x1fpreferences-system-windows\n' "$p"
    done
    printf '✦ Custom layout…\0icon\x1flist-add\n'
    printf '\0message\x1fPick a layout, or Custom to type one like “chrome and 2 terminals”\n'
    ;;
  1)
    if [ "${1:-}" = '✦ Custom layout…' ]; then
      # rofi has closed by now; ask for the layout with the themed input, then launch
      txt=$(printf '' | "$self/menu.sh" 'Custom layout' -l 0 -mesg 'e.g. chrome and 2 terminals · code and terminal') || exit 0
      [ -n "$txt" ] && run "$txt"
    else
      run "${1:-}"
    fi
    ;;
  2) [ -n "${1:-}" ] && run "$1" ;;
esac
