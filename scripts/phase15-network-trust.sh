#!/usr/bin/env bash
# Network trust levels (docs/NETWORK_TRUST.md): the firewall part, as a NetworkManager dispatcher hook. Asks for your password once.
# Undo: sudo rm /etc/NetworkManager/dispatcher.d/90-myos-trust  (and `sudo ufw delete deny in on wlo1` if a rule is left)
# shellcheck disable=SC2024 # setup.log belongs to the invoking user.
set -u
if [ "$(id -u)" = 0 ]; then
  echo "Run this as yourself, without sudo: bash scripts/phase15-network-trust.sh  (it asks for your password when needed)" >&2; exit 1
fi
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
log "== phase15 network trust start =="
sudo -v || { log "phase15 needs sudo"; exit 1; }
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
# root copy: system python in isolated mode (no user site-packages, no imports from the current folder)
sed '1s|.*|#!/usr/bin/python3 -I|' "$root/config/network/trust.py" > "$tmp"
sudo install -m 755 -o root -g root "$tmp" /etc/NetworkManager/dispatcher.d/90-myos-trust && log "installed NetworkManager hook 90-myos-trust"
sudo ufw status 2>/dev/null | grep -q "^Status: active" || log "note: ufw is not active, so Public can't block incoming yet (sudo ufw enable)"
log "== phase15 network trust done =="
echo
echo "Done. Mark your networks: trust home (on your home Wi-Fi), trust work, trust public; or Super + Ctrl + W."
