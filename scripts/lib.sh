#!/usr/bin/env bash
# shared helpers: logging + tolerant apt install
# shellcheck disable=SC2024 # setup.log is user-writable; only apt needs sudo.
LOG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/setup.log"   # next to wherever the repo was cloned
log(){ echo "[$(date +%T)] $*" | tee -a "$LOG"; }
apt_try(){ # install each package separately so one missing pkg doesn't abort
  for p in "$@"; do
    if dpkg -s "$p" >/dev/null 2>&1; then log "have $p"; continue; fi
    if sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$p" >>"$LOG" 2>&1; then
      log "installed $p"
    else
      log "FAILED/unavailable: $p"
    fi
  done
}
