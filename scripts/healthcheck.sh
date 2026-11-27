#!/usr/bin/env bash
set -u
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.local/share/fnm:$HOME/.bun/bin:$PATH"
echo "=== OS ==="; lsb_release -ds 2>/dev/null; uname -r
echo "=== GPU ==="; nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true
echo "=== Tools ==="
for t in git gh zsh tmux starship zoxide fzf eza bat fd rg lazygit lazydocker uv node pnpm bun cargo go java clang docker code ollama tailscale restic sops age qemu-system-x86_64 nmap tshark; do
  command -v "$t" >/dev/null || { echo "MISS $t"; continue; }
  case $t in go) f=version;; tmux) f=-V;; restic) f=version;; *) f=--version;; esac
  if v=$(COREPACK_ENABLE_DOWNLOAD_PROMPT=0 timeout 10 "$t" $f 2>&1 | grep -v -i "could not connect" | head -1) && [ -n "$v" ]; then echo "OK   $t: $v"; else echo "FAIL $t: $v"; fi; done
docker compose version 2>/dev/null
echo "=== Firewall ==="; sudo -n ufw status 2>/dev/null || echo "(run with sudo for ufw)"
echo "=== Tailscale ==="; tailscale status 2>&1 | head -3
echo "=== Storage ==="; lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS | grep -v loop; df -h /
echo "=== Failed services ==="; systemctl --failed --no-legend
echo "=== Docker volumes ==="; docker volume ls 2>/dev/null
