#!/usr/bin/env bash
# Install `phone` (Android phone ↔ laptop, docs/PHONE.md). User-level; no sudo.
#   bash scripts/install-phone.sh             install / update (safe to re-run)
#   bash scripts/install-phone.sh --uninstall remove it (keeps ~/.config/myos/phone.json and KDE Connect's pairing)
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$root/config/phone"
share="$HOME/.local/share/myos/phone"
scripts="$HOME/.local/share/nautilus/scripts"
if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$HOME/.local/bin/phone" "$share/phone.py" "$scripts/Send to phone"
  echo "phone removed. Kept: ~/.config/myos/phone.json, KDE Connect and its pairing (sudo apt remove kdeconnect to drop it)."
  exit 0
fi
install -Dm755 "$src/phone.py" "$share/phone.py"
mkdir -p "$HOME/.local/bin"; ln -sfn "$share/phone.py" "$HOME/.local/bin/phone"
install -Dm755 "$src/nautilus-scripts/Send to phone" "$scripts/Send to phone"
echo "phone installed. Next: phone setup   (with the phone on a USB cable)"
