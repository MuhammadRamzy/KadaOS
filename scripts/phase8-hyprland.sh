#!/usr/bin/env bash
# Install a second, keyboard-first desktop session. GNOME remains available.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
log "== phase8 Hyprland start =="

# Ubuntu already provides Dock, AppIndicators and Tiling Assistant. Add only
# small extensions that improve navigation and system visibility.
apt_try gnome-shell-extension-manager gnome-shell-extension-workspace-indicator \
  gnome-shell-extension-system-monitor gnome-shell-extension-places-menu
for pkg in gnome-shell-extension-workspace-indicator gnome-shell-extension-system-monitor gnome-shell-extension-places-menu; do
  metadata="$(dpkg -L "$pkg" 2>/dev/null | rg '/metadata.json$' | head -n 1)"
  [ -n "$metadata" ] || continue
  uuid="$(jq -r .uuid "$metadata")"
  if ! gnome-extensions enable "$uuid" >>"$LOG" 2>&1; then
    python3 - "$uuid" <<'PY' || log "GNOME extension $uuid needs enabling after logging in"
import ast
import subprocess
import sys
schema, key = 'org.gnome.shell', 'enabled-extensions'
current = ast.literal_eval(subprocess.check_output(['gsettings', 'get', schema, key], text=True).strip())
if sys.argv[1] not in current:
    subprocess.run(['gsettings', 'set', schema, key, str(current + [sys.argv[1]])], check=True)
PY
    log "GNOME extension $uuid queued for the next login"
  fi
done

# Ubuntu 26.04 packages; avoid external Hyprland installers and GPU overrides.
apt_try hyprland xdg-desktop-portal-hyprland xdg-desktop-portal-gtk xwayland \
  waybar wofi sway-notification-center wlogout cliphist wl-clipboard grim slurp \
  brightnessctl playerctl pavucontrol network-manager-gnome hyprlock hypridle \
  hyprpaper fastfetch zsh-autosuggestions zsh-syntax-highlighting python3-yara
# brightnessctl's udev rule grants backlight writes to the video group.
# Group membership takes effect after the next login.
if getent group video >/dev/null && ! id -nG "$USER" | tr ' ' '\n' | grep -qx video; then
  sudo usermod -aG video "$USER" >>"$LOG" 2>&1 && log "added $USER to video group (re-login needed)" \
    || log "FAILED to add $USER to video group"
fi

install_if_absent() {
  local source="$1" target="$2"
  if [ -e "$target" ]; then
    log "preserved existing $target"
  else
    install -Dm644 "$source" "$target"
    log "created $target"
  fi
}
install_if_absent "$root/config/hypr/hyprland.conf" "$HOME/.config/hypr/hyprland.conf"
install_if_absent "$root/config/waybar/config.jsonc" "$HOME/.config/waybar/config.jsonc"
install_if_absent "$root/config/waybar/style.css" "$HOME/.config/waybar/style.css"

if dpkg -s hyprland >/dev/null 2>&1; then
  log "Hyprland installed; choose it from the login screen after logging out"
else
  log "Hyprland package missing; see setup.log"
  exit 1
fi
log "== phase8 Hyprland done =="
