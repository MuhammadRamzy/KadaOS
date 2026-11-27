#!/usr/bin/env bash
# User-level installer; backs up changed files and uses atomic replacement.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$root/scripts/install-workbench.py" "$@"
