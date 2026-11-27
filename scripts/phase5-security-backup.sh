#!/usr/bin/env bash
# Phase 5: UFW, AppArmor, unattended upgrades, fail2ban, Tailscale, sops/age, restic backup scripts
# shellcheck disable=SC2024 # setup.log is user-writable; only system commands need sudo.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
log "== phase5 start =="
apt_try ufw apparmor apparmor-utils unattended-upgrades fail2ban age gnupg restic
sudo ufw default deny incoming >>"$LOG" 2>&1; sudo ufw default allow outgoing >>"$LOG" 2>&1
sudo ufw allow in on tailscale0 to any port 22 proto tcp >>"$LOG" 2>&1
sudo ufw --force enable >>"$LOG" 2>&1 && log "ufw enabled (deny incoming)"
sudo systemctl enable --now apparmor >>"$LOG" 2>&1
sudo dpkg-reconfigure -f noninteractive unattended-upgrades >>"$LOG" 2>&1
# sops
if ! command -v sops >/dev/null; then
  v=$(curl -fsSL https://api.github.com/repos/getsops/sops/releases/latest | jq -r .tag_name)
  if [ -n "$v" ] && [ "$v" != null ]; then
    tmp_sops=$(mktemp -d)
    sops_name="sops-$v.linux.amd64"
    sops_base="https://github.com/getsops/sops/releases/download/$v"
    if curl -fsSL "$sops_base/$sops_name" -o "$tmp_sops/$sops_name" && \
       curl -fsSL "$sops_base/sops-$v.checksums.txt" -o "$tmp_sops/checksums.txt"; then
      expected=$(awk -v name="$sops_name" '$2 == name || $2 == "*" name { print $1; exit }' "$tmp_sops/checksums.txt")
      actual=$(sha256sum "$tmp_sops/$sops_name" | cut -d' ' -f1)
      if [ -n "$expected" ] && [ "$expected" = "$actual" ]; then
        mkdir -p "$HOME/.local/bin"
        install -m 755 "$tmp_sops/$sops_name" "$HOME/.local/bin/sops"
        log "installed verified sops $v"
      else
        log "sops checksum verification FAILED"
      fi
    else
      log "sops download FAILED"
    fi
    rm -rf "$tmp_sops"
  fi
fi
# Tailscale official repo for this Ubuntu release; authenticate manually.
if ! command -v tailscale >/dev/null; then
  cn=$(. /etc/os-release; echo "$VERSION_CODENAME")
  if curl -fsI "https://pkgs.tailscale.com/stable/ubuntu/$cn.noarmor.gpg" >/dev/null 2>&1; then
    curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/$cn.noarmor.gpg" | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
    curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/$cn.tailscale-keyring.list" | sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null
    sudo apt-get update >>"$LOG" 2>&1; apt_try tailscale
  else
    log "Tailscale vendor repo unavailable for $cn; skipped"
  fi
fi
# zram / swappiness (conservative, reversible: delete the file to undo)
apt_try zram-tools
if [ ! -e /etc/sysctl.d/99-swappiness.conf ]; then
  echo 'vm.swappiness=20' | sudo tee /etc/sysctl.d/99-swappiness.conf >/dev/null
  sudo sysctl --system >>"$LOG" 2>&1
else
  log "preserved existing /etc/sysctl.d/99-swappiness.conf"
fi
sudo systemctl enable --now fstrim.timer >>"$LOG" 2>&1
# ---- backup scripts
mkdir -p "$HOME/Scripts" "$HOME/.config/restic"
for name in backup.sh verify-backups.sh; do
  source="$root/config/backup/$name"
  target="$HOME/Scripts/$name"
  if [ ! -e "$target" ]; then
    install -m 755 "$source" "$target"
    log "created $target"
  elif ! cmp -s "$source" "$target"; then
    proposal="$target.setup-new"
    [ -e "$proposal" ] || install -m 755 "$source" "$proposal"
    log "REVIEW outdated $target against $proposal; existing helper preserved"
  else
    log "backup helper current: $target"
  fi
done
[ -f "$HOME/.config/restic/password" ] || {
  (umask 077; head -c 32 /dev/urandom | base64 > "$HOME/.config/restic/password")
  log "generated restic password at $HOME/.config/restic/password - BACK IT UP in your password manager"
}
log "== phase5 done =="
