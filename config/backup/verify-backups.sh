#!/usr/bin/env bash
set -euo pipefail
base="${BACKUP_BASE_HOME:-$HOME}"
export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-/mnt/backup-hdd/07-Backups/restic}"
export RESTIC_PASSWORD_FILE="${RESTIC_PASSWORD_FILE:-$base/.config/restic/password}"
restic snapshots
restic check --read-data-subset=10%
snapshot_id="$(restic snapshots --json | jq -r \
  --arg setup "$base/KadaOS" --arg scripts "$base/Scripts" \
  '[.[] | select((.paths | index($setup)) and (.paths | index($scripts)))] | sort_by(.time) | last | .id // empty')"
[ -n "$snapshot_id" ] || { echo "no snapshot contains KadaOS and Scripts"; exit 1; }
t=$(mktemp -d)
trap 'rm -rf "$t"' EXIT
restic restore "$snapshot_id" --target "$t" \
  --include "$base/Scripts/backup.sh" \
  --include "$base/KadaOS/README.md" >/dev/null
test -s "$t$base/Scripts/backup.sh"
test -s "$t$base/KadaOS/README.md"
bash -n "$t$base/Scripts/backup.sh"
echo "restore drill OK: backup script and KadaOS README restored from $snapshot_id"
