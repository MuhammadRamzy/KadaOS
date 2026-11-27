# Google Drive in Files

Your Drive appears at `~/GoogleDrive`, with **Google Drive** in the Files sidebar and in every open/save dialog.
It's streamed, not synced: a file downloads when you open it and stays cached (up to 10 GB, kept 3 days, and never when
the disk has less than 15 GB free); what you save uploads in the background. Offline, cached files still open; the mount
reconnects by itself when the network comes back. It isn't a backup.

## Connect (once)
GNOME 50 dropped its built-in Drive support and rclone's shared Google sign-in stops working in 2026, so Google needs a
personal "Desktop app" client (free, ~5 minutes, guide: https://rclone.org/drive/#making-your-own-client-id):
1. Google Cloud Console → new project → enable the **Google Drive API**.
2. OAuth consent screen → External → add yourself as a test user.
3. Credentials → Create OAuth client → **Desktop app** → copy the client ID and secret.
4. `bash scripts/drive-connect.sh` → paste them → sign in in the browser that opens.

Stop it: `bash scripts/drive-connect.sh --off` (the sign-in is kept). Status: `systemctl --user status google-drive`.
