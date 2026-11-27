#!/usr/bin/env bash
# Connect Google Drive so it shows in Files, open/save dialogs and every app, at ~/GoogleDrive.
# GNOME 50 removed its built-in Drive support; rclone's shared Google client stops working in 2026,
# so a one-time personal "Desktop app" OAuth client is required: https://rclone.org/drive/#making-your-own-client-id
#   bash scripts/drive-connect.sh            sign in (once) and start the mount
#   bash scripts/drive-connect.sh --off      stop and disable the mount (sign-in kept)
set -euo pipefail
R=~/.local/bin/rclone; unit=google-drive.service
[ -x "$R" ] || { echo "rclone missing at $R (needs v1.75+)"; exit 1; }
if [ "${1:-}" = --off ]; then systemctl --user disable --now "$unit"; echo "Drive unmounted."; exit 0; fi
if ! "$R" listremotes | grep -qx 'gdrive:'; then
  echo "1) In Google Cloud Console: enable Drive API, OAuth consent screen (External, add yourself as test user"
  echo "   or publish), Credentials → Create OAuth client → Desktop app.  Guide: https://rclone.org/drive/#making-your-own-client-id"
  read -rp "Client ID: " id; read -rsp "Client secret (hidden): " sec; echo
  echo "2) A browser opens for Google sign-in..."
  "$R" config create gdrive drive client_id="$id" client_secret="$sec" scope=drive >/dev/null
fi
"$R" lsd gdrive: --max-depth 1 >/dev/null || { echo "Sign-in check failed. Retry: $R config reconnect gdrive:"; exit 1; }
install -Dm644 "$(dirname "$0")/../config/systemd/$unit" ~/.config/systemd/user/$unit
systemctl --user daemon-reload
systemctl --user enable --now "$unit"
bm=~/.config/gtk-3.0/bookmarks
grep -q "GoogleDrive" "$bm" 2>/dev/null || echo "file://$HOME/GoogleDrive Google Drive" >> "$bm"
sleep 2; mountpoint -q ~/GoogleDrive && echo "Google Drive is at ~/GoogleDrive (sidebar: Google Drive)." \
  || { echo "Mount did not start:"; journalctl --user -u "$unit" -n 20 --no-pager; exit 1; }
