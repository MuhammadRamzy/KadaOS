#!/usr/bin/env bash
# Install `board` (SSH + embedded workflow, docs/REMOTE.md). User-level; no sudo.
#   bash scripts/install-remote.sh             install / update (safe to re-run)
#   bash scripts/install-remote.sh --uninstall remove what this installed (keeps your key, devices and known_hosts)
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$root/config/remote"
share="$HOME/.local/share/myos/remote"
scripts="$HOME/.local/share/nautilus/scripts"
zfunc="$HOME/.local/share/zsh/site-functions"
names=("Send to device…" "Copy device path" "Open on device in VS Code" "Device terminal here")

if [ "${1:-}" = "--uninstall" ]; then
  board umount >/dev/null 2>&1 || true
  rm -f "$HOME/.local/bin/board" "$share/board.py" "$zfunc/_board" "$HOME/.ssh/config.d/99-defaults" "$HOME/.ssh/config.d/10-devices"
  for n in "${names[@]}"; do rm -f "$scripts/$n"; done
  sed -i '/^fpath=(~\/.local\/share\/zsh\/site-functions $fpath)  # board$/d' "$HOME/.zshrc" 2>/dev/null || true
  sed -i '/^sftp:\/\/.* · /d' "$HOME/.config/gtk-3.0/bookmarks" 2>/dev/null || true
  for c in "Board USB (shared)" "Board Ethernet (shared)" "Board hotspot"; do nmcli con delete "$c" >/dev/null 2>&1 || true; done
  [ -f "$HOME/.config/Code/User/settings.json.board-backup" ] && \
    cp "$HOME/.config/Code/User/settings.json.board-backup" "$HOME/.config/Code/User/settings.json"
  echo "board removed. Kept: ~/.ssh keys + known_hosts, ~/.config/myos/devices.toml, ~/Embedded. The Include line in ~/.ssh/config is harmless."
  exit 0
fi

install -Dm755 "$src/board.py" "$share/board.py"
mkdir -p "$HOME/.local/bin"; ln -sfn "$share/board.py" "$HOME/.local/bin/board"
mkdir -p -m 700 "$HOME/.ssh" "$HOME/.ssh/config.d" "$HOME/.ssh/sockets"
install -m600 "$src/ssh/99-defaults" "$HOME/.ssh/config.d/99-defaults"
install -Dm644 "$src/_board" "$zfunc/_board"
grep -q 'site-functions $fpath)  # board' "$HOME/.zshrc" 2>/dev/null || {
  cp "$HOME/.zshrc" "$HOME/.zshrc.before-board" 2>/dev/null || true
  # must come before compinit, so it goes on the first line
  printf 'fpath=(~/.local/share/zsh/site-functions $fpath)  # board\n' | cat - "$HOME/.zshrc" > "$HOME/.zshrc.tmp" && mv "$HOME/.zshrc.tmp" "$HOME/.zshrc"
}
mkdir -p "$scripts"
for n in "${names[@]}"; do install -m755 "$src/nautilus-scripts/$n" "$scripts/$n"; done
"$HOME/.local/bin/board" gen >/dev/null                       # ~/.ssh/config Include + device hosts, VS Code, bookmarks
"$HOME/.local/bin/board" usb setup >/dev/null 2>&1 || echo "note: USB-cable network profile not created (run: board usb setup)"
mkdir -p "$HOME/Embedded/logs" "$HOME/Embedded/images" "$HOME/Embedded/backups" "$HOME/Remote"
echo "board installed: board help · board setup (first time) · board doctor"
