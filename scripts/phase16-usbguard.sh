#!/usr/bin/env bash
# USB guard (docs/USB_GUARD.md): USBGuard with a policy made from what's plugged in now, plus the Allow/Block notifier.
# Be at the laptop. The built-in keyboard and touchpad aren't USB, so they keep working whatever happens.
# Undo: sudo systemctl disable --now usbguard   (every USB device works again immediately)
# shellcheck disable=SC2024 # setup.log belongs to the invoking user.
set -u
if [ "$(id -u)" = 0 ]; then
  echo "Run this as yourself, without sudo: bash scripts/phase16-usbguard.sh  (it asks for your password when needed)" >&2; exit 1
fi
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
echo "Plug in everything you use regularly now (mouse receiver, keyboard, phone cable, probes…): they'll be allowed."
read -r -p "Ready? Enter to continue, Ctrl+C to stop. " _
log "== phase16 usbguard start =="
sudo -v || { log "phase16 needs sudo"; exit 1; }
apt_try usbguard
command -v usbguard >/dev/null || { log "usbguard not available"; exit 1; }
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
# --no-ports-sn: a device without a serial number still works in any port
sudo usbguard generate-policy --no-ports-sn > "$tmp" || { log "couldn't generate a policy"; exit 1; }
echo; echo "Allowed from now on:"; sed -E 's/ hash "[^"]*"//; s/ parent-hash "[^"]*"//; s/ with-interface .*//' "$tmp"; echo
sudo install -m 600 -o root -g root "$tmp" /etc/usbguard/rules.conf
conf=/etc/usbguard/usbguard-daemon.conf
sudo cp -n "$conf" "$conf.myos-backup" 2>/dev/null || true
set_opt() { sudo sed -i -E "s|^#?\s*$1=.*|$1=$2|" "$conf"; grep -q "^$1=" "$conf" || echo "$1=$2" | sudo tee -a "$conf" >/dev/null; }
set_opt ImplicitPolicyTarget block
set_opt PresentDevicePolicy apply-policy
set_opt InsertedDevicePolicy apply-policy
set_opt IPCAllowedUsers "root $USER"
sudo systemctl enable --now usbguard >>"$LOG" 2>&1 && sudo systemctl restart usbguard && log "usbguard on (new devices blocked until allowed)"
install -Dm755 "$root/config/desktop/usbguard.py" ~/.local/share/myos/usbguard.py && ln -sfn ~/.local/share/myos/usbguard.py ~/.local/bin/usb-guard
install -Dm644 "$root/config/systemd/myos-usbguard-notify.service" ~/.config/systemd/user/myos-usbguard-notify.service
systemctl --user daemon-reload && systemctl --user enable --now myos-usbguard-notify.service >>"$LOG" 2>&1 && log "notifier on"
log "== phase16 usbguard done =="
echo
echo "Done. Unplug and replug the mouse receiver: it should keep working. Plug in something new: you'll be asked."
echo "If anything goes wrong: sudo systemctl stop usbguard   (the laptop keyboard always works; docs/USB_GUARD.md)"
