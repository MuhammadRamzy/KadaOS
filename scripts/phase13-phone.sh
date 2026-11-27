#!/usr/bin/env bash
# Phone link (docs/PHONE.md): KDE Connect + firewall ports. Asks for your password once.
# shellcheck disable=SC2024 # setup.log belongs to the invoking user.
set -u
if [ "$(id -u)" = 0 ]; then
  echo "Run this as yourself, without sudo: bash scripts/phase13-phone.sh  (it asks for your password when needed)" >&2; exit 1
fi
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
log "== phase13 phone start =="
sudo -v || { log "phase13 needs sudo"; exit 1; }
sudo apt-get update -q >>"$LOG" 2>&1 || log "apt update had problems (continuing)"
apt_try kdeconnect
# KDE Connect finds and talks to the phone on 1714-1764 (TCP + UDP). Pairing is TLS with a key you accept on both sides.
if sudo ufw status 2>/dev/null | grep -q "^Status: active"; then
  sudo ufw allow 1714:1764/udp comment "KDE Connect" >>"$LOG" 2>&1 && sudo ufw allow 1714:1764/tcp comment "KDE Connect" >>"$LOG" 2>&1 \
    && log "firewall: KDE Connect ports 1714-1764 open"
fi
bash "$root/scripts/install-phone.sh" | tee -a "$LOG"
log "== phase13 phone done =="
echo
echo "Done. Next: plug the phone in with a USB cable and run: phone setup"
