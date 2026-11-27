#!/usr/bin/env bash
# Same as ./kada (the installer menu). The old fixed list is still there: bash scripts/bootstrap.sh
set -e
exec "$(dirname "${BASH_SOURCE[0]}")/kada" "$@"
