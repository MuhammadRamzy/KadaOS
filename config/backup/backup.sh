#!/usr/bin/env bash
# Usage: backup.sh   (repo defaults to external HDD; override with RESTIC_REPOSITORY)
set -euo pipefail
base="${BACKUP_BASE_HOME:-$HOME}"
export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-/mnt/backup-hdd/07-Backups/restic}"
export RESTIC_PASSWORD_FILE="${RESTIC_PASSWORD_FILE:-$base/.config/restic/password}"
confirmation="${RESTIC_CONFIRMATION_FILE:-$base/.config/restic/password-backed-up}"
case "$RESTIC_REPOSITORY" in
  /mnt/backup-hdd/*)
    mountpoint -q /mnt/backup-hdd || { echo "external HDD is not mounted"; exit 1; }
    uuid_file="${BACKUP_HDD_UUID_FILE:-$base/.config/setup/hdd-uuid}"
    [ -s "$uuid_file" ] || { echo "expected HDD UUID file is missing: $uuid_file"; exit 1; }
    read -r expected_uuid < "$uuid_file"
    actual_uuid="$(findmnt -n -o UUID --target /mnt/backup-hdd)"
    [ "$actual_uuid" = "$expected_uuid" ] || { echo "mounted HDD UUID does not match $uuid_file"; exit 1; }
    ;;
  *)
    [ "${BACKUP_ALLOW_LOCAL_REPO:-0}" = 1 ] || {
      echo "non-HDD repository requires BACKUP_ALLOW_LOCAL_REPO=1"; exit 1;
    }
    ;;
esac
[ -f "$RESTIC_PASSWORD_FILE" ] || { echo "restic password file is missing"; exit 1; }
[ -f "$confirmation" ] || { echo "save the restic password outside this machine, then create $confirmation"; exit 1; }
mkdir -p "$RESTIC_REPOSITORY"
[ -d "$RESTIC_REPOSITORY/keys" ] || restic init
paths=()
for path in "$base/Projects" "$base/Workspaces" "$base/Documents" "$base/Scripts" "$base/KadaOS" "$base/DocsVault" \
  "$base/dotfiles" "$base/Labs/Networks" "$base/Labs/Notes" "$base/Containers" \
  "$base/.ssh" "$base/.config/age" "$base/.config/sops" \
  "$base/.config/hypr" "$base/.config/waybar" "$base/.config/Code/User"; do
  if [ -e "$path" ]; then paths+=("$path"); else printf 'skip missing: %s\n' "$path"; fi
done
[ "${#paths[@]}" -gt 0 ] || { echo "no backup paths exist"; exit 1; }
restic backup "${paths[@]}" --exclude node_modules --exclude .venv
restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
mkdir -p "$HOME/.local/state/setup" && touch "$HOME/.local/state/setup/last-backup"   # read by system-adapt (backup-overdue reminder)
