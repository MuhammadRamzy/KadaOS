#!/usr/bin/env bash
# The KadaOS mark on the boot screen and the login screen (system-wide, so it asks for your password).
#   Boot (Plymouth): your laptop maker's logo and the spinner stay; the KadaOS wordmark replaces the Ubuntu one at the
#   bottom. Login (GDM): the KadaOS wordmark under the user list. Both are static PNGs: no effect on boot or login time.
#   bash scripts/phase17-brand.sh          apply          bash scripts/phase17-brand.sh undo     back to Ubuntu's
# shellcheck disable=SC2024 # setup.log belongs to the invoking user.
set -u
if [ "$(id -u)" = 0 ]; then
  echo "Run this as yourself, without sudo: bash scripts/phase17-brand.sh  (it asks for your password when needed)" >&2; exit 1
fi
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
T=/usr/share/plymouth/themes; THEME="$T/kadaos"; GREETER=/etc/gdm3/greeter.dconf-defaults; LOGIN_PNG=/usr/share/pixmaps/kadaos-login.png
sudo -v || { log "phase17 needs sudo"; exit 1; }

# GDM keeps its settings in a keyfile; set or clear `logo` in its [org/gnome/login-screen] section, keeping the rest
greeter_logo() {
  [ -f "$GREETER" ] || return 0
  [ -e "$GREETER.myos-backup" ] || sudo cp "$GREETER" "$GREETER.myos-backup"   # the original, once
  sudo python3 -I - "$GREETER" "$1" <<'PY'
import re, sys
path, logo = sys.argv[1], sys.argv[2]
t = open(path).read()
t = re.sub(r"(?m)^logo=.*\n", "", t)                                       # ours, from an earlier run
if logo:
    if "[org/gnome/login-screen]" not in t: t += "\n[org/gnome/login-screen]\n"
    t = t.replace("[org/gnome/login-screen]\n", f"[org/gnome/login-screen]\nlogo='{logo}'\n", 1)
open(path, "w").write(t)
PY
  [ -x /usr/share/gdm/generate-config ] && sudo /usr/share/gdm/generate-config >/dev/null 2>&1
  return 0
}

if [ "${1:-}" = undo ]; then
  log "== phase17 brand undo =="
  if [ -e "$THEME/kadaos.plymouth" ]; then
    sudo update-alternatives --remove default.plymouth "$THEME/kadaos.plymouth" >/dev/null 2>&1
    sudo rm -rf "${THEME:?}"
    echo "Rebuilding the boot image (a minute)…"; sudo update-initramfs -u >>"$LOG" 2>&1
  fi
  greeter_logo ""; sudo rm -f "$LOGIN_PNG"
  log "phase17: Ubuntu's boot and login screens are back"; exit 0
fi

log "== phase17 brand start =="
# ── boot: a copy of Ubuntu's own theme (BGRT = firmware logo + spinner; plain spinner on machines without it)
base="$T/bgrt/bgrt.plymouth"; [ -f "$base" ] || base="$T/spinner/spinner.plymouth"
if [ -f "$base" ] && command -v update-initramfs >/dev/null; then
  sudo install -d "$THEME"
  sudo cp -L "$T"/spinner/*.png "$THEME"/                                   # spinner frames, lock and entry images
  sudo install -m 644 "$root/config/brand/kadaos-boot.png" "$THEME/watermark.png"
  sed -e '/^Name\[/d' -e 's|^Name=.*|Name=KadaOS|' \
      -e 's|^Description=.*|Description=KadaOS: the firmware logo, a spinner and the KadaOS wordmark|' \
      -e "s|^ImageDir=.*|ImageDir=$THEME|" "$base" | sudo tee "$THEME/kadaos.plymouth" >/dev/null
  sudo update-alternatives --install "$T/default.plymouth" default.plymouth "$THEME/kadaos.plymouth" 150 >/dev/null
  sudo update-alternatives --set default.plymouth "$THEME/kadaos.plymouth" >/dev/null
  echo "Rebuilding the boot image (a minute)…"
  if sudo update-initramfs -u >>"$LOG" 2>&1; then log "phase17: boot screen set"; else log "phase17: update-initramfs failed (see setup.log)"; fi
else
  log "phase17: no Plymouth here; boot screen skipped"
fi

# ── login: GDM's own logo slot
if [ -f "$GREETER" ]; then
  sudo install -m 644 "$root/config/brand/kadaos-login.png" "$LOGIN_PNG"
  greeter_logo "$LOGIN_PNG"; log "phase17: login screen set (you'll see it next time you log in)"
else
  log "phase17: not GDM; login screen skipped"
fi
log "== phase17 brand done =="
