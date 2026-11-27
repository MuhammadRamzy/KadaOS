#!/usr/bin/env bash
# Native user-session hydration reminders. No root access; preserves backups.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$root/scripts/install-hydration.py" "$@"
