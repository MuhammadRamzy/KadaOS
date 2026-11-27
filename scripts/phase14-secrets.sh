#!/usr/bin/env bash
# Secrets (docs/SECRETS.md): KeePassXC vault, gitleaks, and the leak scan before every commit. Asks for your password once.
# shellcheck disable=SC2024 # setup.log belongs to the invoking user.
set -u
if [ "$(id -u)" = 0 ]; then
  echo "Run this as yourself, without sudo: bash scripts/phase14-secrets.sh  (it asks for your password when needed)" >&2; exit 1
fi
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
log "== phase14 secrets start =="
sudo -v || { log "phase14 needs sudo"; exit 1; }
sudo apt-get update -q >>"$LOG" 2>&1 || log "apt update had problems (continuing)"
apt_try keepassxc
apt_try gitleaks
bash "$root/scripts/install-git-hooks.sh" | tee -a "$LOG"
log "== phase14 secrets done =="
echo
echo "Done. Open KeePassXC with Super + Ctrl + K and create your database (docs/SECRETS.md)."
