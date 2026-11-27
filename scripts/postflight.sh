#!/usr/bin/env bash
# Read-only workstation audit. Run after bootstrap has exited.
# shellcheck disable=SC2016 # Literal Markdown and quoted bash -c scripts are intentional.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
HEALTH="$ROOT/docs/HEALTH_REPORT.md"
MANIFEST="$ROOT/docs/INSTALL_MANIFEST.md"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.local/share/fnm:$HOME/.bun/bin:$PATH"
docker_cmd=(docker)
if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
  docker_cmd=(sudo -n docker)
fi

section() { printf '\n## %s\n\n' "$1"; }
block() {
  printf '```text\n'
  timeout 15s "$@" 2>&1 || true
  printf '```\n'
}
tool() {
  local name="$1"; shift
  if ! command -v "$name" >/dev/null 2>&1; then
    printf '| %s | missing |\n' "$name"
    return
  fi
  local version
  version="$(timeout 8s "$name" "$@" 2>&1 | head -n 1)"
  version="${version//|/\\|}"
  printf '| %s | %s |\n' "$name" "${version:-installed (version unavailable)}"
}

{
  printf '# Workstation health report\n\nGenerated: %s\n' "$(date -Is)"
  section 'OS and GPU'
  block bash -c 'source /etc/os-release; printf "%s\n" "$PRETTY_NAME"; uname -r; nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader'
  section 'Storage and mounts'
  block lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS
  block df -h / "$HOME"
  block du -sh "$HOME/.cache" "$HOME/.local/share/containers" "$HOME/.local/share/uv" 2>/dev/null
  if mountpoint -q /mnt/backup-hdd; then
    printf 'External HDD: mounted at `/mnt/backup-hdd`.\n'
  else
    printf 'External HDD: **not mounted** at `/mnt/backup-hdd`.\n'
  fi
  section 'Security and services'
  block systemctl --failed --no-legend
  if command -v ufw >/dev/null 2>&1; then
    if sudo -n true 2>/dev/null; then block sudo -n ufw status; else printf 'UFW status: requires sudo in an interactive terminal.\n'; fi
  fi
  if command -v tailscale >/dev/null 2>&1; then block tailscale status; fi
  section 'Desktop and robotics'
  block gnome-shell --version
  if dpkg -s hyprland >/dev/null 2>&1; then
    printf 'Hyprland package: installed; a login-session smoke test is still required.\n'
  else
    printf 'Hyprland package: missing.\n'
  fi
  if [ -f /opt/ros/lyrical/setup.bash ]; then
    printf 'ROS 2 Lyrical setup: present at `/opt/ros/lyrical/setup.bash`.\n'
  else
    printf 'ROS 2 Lyrical setup: missing.\n'
  fi
  if command -v docker >/dev/null 2>&1; then
    block "${docker_cmd[@]}" image inspect osrf/space-ros:jazzy-2026.07.0-dev --format '{{.Id}}'
  fi
  section 'Containers'
  if command -v docker >/dev/null 2>&1; then
    block "${docker_cmd[@]}" info --format '{{.ServerVersion}}'
    block "${docker_cmd[@]}" compose version
    block "${docker_cmd[@]}" volume ls
  else
    printf 'Docker command unavailable.\n'
  fi
  section 'Recent setup failures'
  if [ -f "$ROOT/setup.log" ]; then
    block bash -c 'rg -n "(^E:|^Err:|\[[0-9]{2}:[0-9]{2}:[0-9]{2}\].*(FAILED|unavailable|needs attention))" "$1" | tail -80' _ "$ROOT/setup.log"
  else
    printf 'No setup log found.\n'
  fi
  section 'Backup readiness'
  if [ -f "$HOME/.config/restic/password" ]; then
    printf 'Restic password file: present. Keep a separate copy in the password manager.\n'
  else
    printf 'Restic password file: missing.\n'
  fi
  if [ -d /mnt/backup-hdd/07-Backups/restic/keys ]; then
    printf 'Restic repository: initialized on external HDD.\n'
  else
    printf 'Restic repository: not initialized on external HDD.\n'
  fi
  for name in backup.sh verify-backups.sh; do
    if [ -e "$HOME/Scripts/$name.setup-new" ]; then
      printf 'Backup helper review pending: `%s`.\n' "$HOME/Scripts/$name.setup-new"
    fi
  done
} > "$HEALTH"

{
  printf '# Install manifest\n\nGenerated: %s\n\n' "$(date -Is)"
  printf '| Tool | Detected version or state |\n| --- | --- |\n'
  tool git --version
  tool gh --version
  tool zsh --version
  tool tmux -V
  tool starship --version
  tool zoxide --version
  tool fzf --version
  tool rg --version
  tool uv --version
  tool node --version
  tool pnpm --version
  tool bun --version
  tool cargo --version
  tool go version
  tool java -version
  tool clang --version
  tool docker --version
  tool code --version
  tool ollama --version
  tool tailscale version
  tool restic version
  tool sops --version
  tool age --version
  tool nmap --version
  tool flutter --version
  tool Hyprland --version
  tool waybar --version
  tool fastfetch --version
  tool gnome-shell --version
  printf '\nThe table records command availability; service health and setup failures are in [HEALTH_REPORT.md](HEALTH_REPORT.md). Optional phase 7 tools may be intentionally absent.\n'
} > "$MANIFEST"

printf 'Wrote %s and %s\n' "$HEALTH" "$MANIFEST"
