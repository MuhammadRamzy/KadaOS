#!/usr/bin/env bash
# Hyprland polish: extra packages, Nerd Font, and install configs from config/ (backs up existing first).
# Re-runnable. Usage: bash scripts/phase8b-hyprland-polish.sh
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log "== phase8b Hyprland polish start =="
apt_try python3-pil hyprpolkitagent blueman papirus-icon-theme qt6ct nwg-look udiskie jq libnotify-bin \
  fonts-font-awesome fonts-noto-color-emoji wl-clipboard hyprpicker \
  rofi swayosd swappy wtype wayvnc adb hyprland-qtutils wlsunset nwg-displays gnome-system-monitor libsecret-tools \
  ghostscript poppler-utils p7zip-full ffmpeg
# File Actions and the launcher also use: python3-gi gir1.2-gtk-4.0 libadwaita-1-0 gir1.2-nm-1.0 gir1.2-gnomebluetooth-3.0
apt_try python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 gir1.2-nm-1.0 gir1.2-gnomebluetooth-3.0
apt_try build-essential pkg-config libwayland-dev wayland-protocols pipewire-bin

# JetBrainsMono Nerd Font (user-level, no sudo)
if ! fc-list | grep -qi 'JetBrainsMono Nerd'; then
  d=~/.local/share/fonts/JetBrainsMonoNF; mkdir -p "$d"
  curl -fsSL https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.tar.xz | tar xJ -C "$d" \
    && fc-cache -f >/dev/null && log "installed JetBrainsMono Nerd Font" || log "FAILED Nerd Font download"
fi

# Adwaita Sans/Mono (the Graphite UI font), user-level, no sudo — from the GNOME release tarball.
if ! fc-list | grep -qi 'Adwaita Sans'; then
  d=~/.local/share/fonts/AdwaitaFonts; mkdir -p "$d"; t=$(mktemp -d)
  if curl -fsSL "https://download.gnome.org/sources/adwaita-fonts/50/adwaita-fonts-50.0.tar.xz" -o "$t/a.tar.xz" \
     && tar -xf "$t/a.tar.xz" -C "$t"; then
    cp "$t"/adwaita-fonts-*/sans/*.ttf "$t"/adwaita-fonts-*/mono/*.ttf "$d"/ 2>/dev/null \
      && fc-cache -f >/dev/null 2>&1 && log "installed Adwaita fonts" || log "FAILED Adwaita font copy"
  else log "FAILED Adwaita font download"; fi
  rm -rf "$t"
fi

# Regenerate theme files (icons, colours, wlogout PNGs) before copying
python3 "$root/scripts/theme.py" >>"$LOG" 2>&1

# Configs: back up whatever exists, then install ours
bk=~/.config/setup-backups/$(date +%Y%m%d-%H%M%S); mkdir -p "$bk"
for app in hypr waybar wofi rofi swaync swayosd wlogout kitty; do
  [ -e ~/.config/$app ] && cp -a ~/.config/$app "$bk/"
  mkdir -p ~/.config/$app && cp -a "$root/config/$app/." ~/.config/$app/
done
chmod +x ~/.config/hypr/scripts/*.sh ~/.config/hypr/scripts/*.py
# Hybrid laptops (Intel iGPU + NVIDIA): stable GPU symlinks for AQ_DRM_DEVICES so the iGPU renders and NVIDIA drives
# external ports. Detected by vendor, never assumed; any other machine gets Hyprland's own GPU choice.
igpu=""; dgpu=""
for c in /sys/class/drm/card[0-9]*; do
  [ -e "$c/device/vendor" ] || continue
  case "$(cat "$c/device/vendor")" in
    0x8086) igpu="$(basename "$(readlink -f "$c/device")")";;
    0x10de) dgpu="$(basename "$(readlink -f "$c/device")")";;
  esac
done
if [ -n "$igpu" ] && [ -n "$dgpu" ] && [ -e "/dev/dri/by-path/pci-$igpu-card" ] && [ -e "/dev/dri/by-path/pci-$dgpu-card" ]; then
  ln -sfn "/dev/dri/by-path/pci-$igpu-card" ~/.config/hypr/gpu-intel
  ln -sfn "/dev/dri/by-path/pci-$dgpu-card" ~/.config/hypr/gpu-nvidia
  log "hybrid GPUs: Intel $igpu renders, NVIDIA $dgpu for external ports"
else
  rm -f ~/.config/hypr/gpu-intel ~/.config/hypr/gpu-nvidia
  sed -i '/^env = AQ_DRM_DEVICES/d' ~/.config/hypr/hyprland.conf
  log "not an Intel+NVIDIA hybrid: Hyprland picks the GPU itself"
fi
install -Dm755 "$root/config/bin/nvrun" ~/.local/bin/nvrun
mkdir -p ~/.local/share/org.gnome.Ptyxis/palettes && cp "$root/config/ptyxis/Graphite.palette" ~/.local/share/org.gnome.Ptyxis/palettes/
[ -f ~/.config/hypr/wallpaper-mode ] || echo black > ~/.config/hypr/wallpaper-mode
# portable home paths: generated files may contain the original user's home
grep -rlI "/home/USER" ~/.config/hypr ~/.config/waybar ~/.config/rofi ~/.config/swaync ~/.config/wlogout ~/.config/kitty ~/.config/qt6ct 2>/dev/null \
  | xargs -r sed -i "s#/home/USER#$HOME#g"   # portable home
# terminal: Graphite palette on the default Ptyxis profile
pid=$(gsettings get org.gnome.Ptyxis default-profile-uuid 2>/dev/null | tr -d "'")
[ -n "$pid" ] && dconf write "/org/gnome/Ptyxis/Profiles/$pid/palette" "'Graphite'" 2>/dev/null
log "configs installed; previous versions in $bk"

# Native desktop apps (Quick Settings panels, launcher, pickers, file actions, cheatsheet)
bash "$root/scripts/install-panels.sh" | tee -a "$LOG" || log "install-panels failed"
bash "$root/scripts/install-browsers.sh" | tee -a "$LOG" || log "install-browsers failed"
bash "$root/scripts/install-hydration.sh" | tee -a "$LOG" || log "install-hydration failed"

# swaync: systemd-managed, Hyprland-only
mkdir -p ~/.config/systemd/user/swaync.service.d
cp "$root/config/systemd/swaync.service.d/hyprland-only.conf" ~/.config/systemd/user/swaync.service.d/
mkdir -p ~/.config/systemd/user/hyprpolkitagent.service.d
cp "$root/config/systemd/hyprpolkitagent.service.d/hyprland-only.conf" ~/.config/systemd/user/hyprpolkitagent.service.d/
# Ubuntu enables these as user services too; Hyprland starts them itself (exec-once) → mask the duplicates
systemctl --user mask waybar.service hypridle.service hyprpaper.service >/dev/null 2>&1
systemctl --user daemon-reload

# Blueman: manage devices only. Its PowerManager/KillSwitch plugins restore a saved "off" state and rfkill-block
# the adapter; power is handled by the bar / control center / Ubuntu instead.
gsettings set org.blueman.general plugin-list "['!PowerManager', '!KillSwitch', '!StatusIcon', '!StatusNotifierItem']" 2>/dev/null

# GTK dark + icons (applies to GTK apps under Hyprland too)
gsettings set org.gnome.desktop.interface color-scheme prefer-dark 2>/dev/null

# Same shortcuts in Ubuntu/GNOME
bash "$root/scripts/gnome-shared-keys.sh" | tee -a "$LOG"

# Apply live if running inside Hyprland
if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
  hyprctl reload >/dev/null
  pkill waybar; pkill -x swaync-client; pkill hyprpaper; pkill hypridle; sleep 0.5
  pkill -f gnome-sync.sh; pkill swayosd-server
  systemctl --user restart swaync
  for p in waybar hyprpaper hypridle swayosd-server ~/.config/hypr/scripts/gnome-sync.sh; do setsid -f $p >/dev/null 2>&1; done
  systemctl --user start hyprpolkitagent 2>/dev/null || true
  notify-send "Hyprland updated" "Press Super+/ for all shortcuts" 2>/dev/null
fi
rm -f "$XDG_RUNTIME_DIR"/hypr/*/hyprland.log.old 2>/dev/null
log "== phase8b done =="
