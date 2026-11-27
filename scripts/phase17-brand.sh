#!/usr/bin/env bash
# The KadaOS mark on the boot screen and the login screen (system-wide, so it asks for your password).
#   Boot (Plymouth): graphite, the KadaOS mark with its cursor blinking, the wordmark at the bottom.
#   Login (GDM): a copy of Ubuntu's login theme on the KadaOS backdrop (the mark as glass), names without avatar cards,
#   chosen through Ubuntu's own gdm-theme.gresource switch. Rerun after a big Ubuntu upgrade to refresh the copy.
#   bash scripts/phase17-brand.sh          apply          bash scripts/phase17-brand.sh undo     back to Ubuntu's
# shellcheck disable=SC2024 # setup.log belongs to the invoking user.
set -u
if [ "$(id -u)" = 0 ]; then
  echo "Run this as yourself, without sudo: bash scripts/phase17-brand.sh  (it asks for your password when needed)" >&2; exit 1
fi
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
T=/usr/share/plymouth/themes; THEME="$T/kadaos"; GREETER=/etc/gdm3/greeter.dconf-defaults
BACKDROP=/usr/share/pixmaps/kadaos-backdrop.jpg; GTHEME=/usr/share/gnome-shell/theme/KadaOS
YARU=/usr/share/gnome-shell/theme/Yaru/gnome-shell-theme.gresource
sudo -v || { log "phase17 needs sudo"; exit 1; }

STATE=/var/lib/kadaos   # what was selected before us, so undo can put it back

# GDM's settings keyfile: our keys under a marker; same-named keys commented out and restored on undo
greeter_settings() {
  [ -f "$GREETER" ] || return 0
  [ -e "$GREETER.myos-backup" ] || sudo cp "$GREETER" "$GREETER.myos-backup"   # the original, once
  sudo python3 -I "$root/config/brand/greeter-settings.py" "$GREETER" "$1" || { log "phase17: GDM settings not changed"; return 1; }
  [ -x /usr/share/gdm/generate-config ] && sudo /usr/share/gdm/generate-config >/dev/null 2>&1
  return 0
}

# alt_select NAME LINK PATH PRIORITY: register PATH and select it, remembering the previous selection (once)
alt_select() {
  if [ ! -e "$STATE/$1.previous" ]; then
    sudo install -d "$STATE"
    update-alternatives --query "$1" 2>/dev/null | awk '/^Status:/{s=$2} /^Value:/{v=$2} END{print s, v}' | sudo tee "$STATE/$1.previous" >/dev/null
  fi
  sudo update-alternatives --install "$2" "$1" "$3" "$4" >/dev/null && sudo update-alternatives --set "$1" "$3" >/dev/null
}

# alt_restore NAME PATH: unregister PATH and bring back the previous selection. Succeeds only if nothing
# points at PATH any more, so the caller can delete it safely.
alt_restore() {
  local prev status value
  prev="$(cat "$STATE/$1.previous" 2>/dev/null)"; status="${prev%% *}"; value="${prev#* }"
  sudo update-alternatives --remove "$1" "$2" >/dev/null 2>&1
  if [ "$status" = manual ] && [ -e "$value" ] && [ "$value" != "$2" ]; then sudo update-alternatives --set "$1" "$value" >/dev/null 2>&1
  else sudo update-alternatives --auto "$1" >/dev/null 2>&1; fi
  if update-alternatives --query "$1" 2>/dev/null | grep -qxF "Value: $2"; then
    log "phase17: $1 still points at $2; left in place"; return 1
  fi
  sudo rm -f "$STATE/$1.previous"
}

if [ "${1:-}" = undo ]; then
  log "== phase17 brand undo =="
  if [ -e "$THEME/kadaos.plymouth" ] && alt_restore default.plymouth "$THEME/kadaos.plymouth"; then
    sudo rm -rf "${THEME:?}"
    echo "Rebuilding the boot image (a minute)…"; sudo update-initramfs -u >>"$LOG" 2>&1
  fi
  greeter_settings undo; sudo rm -f "$BACKDROP" /usr/share/pixmaps/kadaos-login.png
  if [ -e "$GTHEME/gnome-shell-theme.gresource" ] && alt_restore gdm-theme.gresource "$GTHEME/gnome-shell-theme.gresource"; then
    sudo rm -rf "${GTHEME:?}"
  fi
  log "phase17: Ubuntu's boot and login screens are back"; exit 0
fi

log "== phase17 brand start =="
# ── boot: our own script theme (no firmware logo, no spinner)
if [ -d "$T" ] && command -v update-initramfs >/dev/null; then
  sudo rm -rf "${THEME:?}"; sudo install -d "$THEME"
  sudo install -m 644 "$root"/config/brand/plymouth/{mark.png,cursor.png,word.png,kadaos.script,kadaos.plymouth} "$THEME"/
  alt_select default.plymouth "$T/default.plymouth" "$THEME/kadaos.plymouth" 150
  echo "Rebuilding the boot image (a minute)…"
  if sudo update-initramfs -u >>"$LOG" 2>&1; then log "phase17: boot screen set"; else log "phase17: update-initramfs failed (see setup.log)"; fi
else
  log "phase17: no Plymouth here; boot screen skipped"
fi

# ── login: the backdrop, our styles on a copy of Ubuntu's login theme, the blue accent
if [ -f "$GREETER" ]; then
  sudo rm -f /usr/share/pixmaps/kadaos-login.png             # the wordmark logo of earlier versions: the backdrop is the mark now
  greeter_settings apply
  # build the theme, validate it, then swap it in atomically (a truncated resource would break the greeter)
  if [ -f "$YARU" ] && command -v glib-compile-resources >/dev/null && \
     out="$(bash "$root/config/brand/gdm-theme.sh" "$YARU" "$root/config/brand/gdm-kadaos.css")" && \
     gresource list "$out" | grep -q /org/gnome/shell/theme/gdm.css; then
    if sudo install -m 644 "$root/config/brand/kadaos-backdrop-login.jpg" "$BACKDROP" && sudo install -d "$GTHEME" && \
       sudo install -m 644 "$out" "$GTHEME/.new.gresource" && sudo gresource list "$GTHEME/.new.gresource" >/dev/null && \
       sudo mv -f "$GTHEME/.new.gresource" "$GTHEME/gnome-shell-theme.gresource" && \
       alt_select gdm-theme.gresource /usr/share/gnome-shell/gdm-theme.gresource "$GTHEME/gnome-shell-theme.gresource" 20; then
      :
    else
      sudo rm -f "$GTHEME/.new.gresource"; log "phase17: installing the login theme failed; GDM keeps its current theme"
    fi
    rm -rf "${out%/*}"
  else
    log "phase17: couldn't build the login theme; only the accent is set"
  fi
  log "phase17: login screen set (you'll see it next time you log in)"
else
  log "phase17: not GDM; login screen skipped"
fi
log "== phase17 brand done =="
