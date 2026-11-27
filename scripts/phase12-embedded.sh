#!/usr/bin/env bash
# Embedded / SSH tools for `board` (docs/REMOTE.md). Asks for your password once (apt, udev, groups).
#   bash scripts/phase12-embedded.sh          core + cross-compilers + MCU tools + logic analysers
#   bash scripts/phase12-embedded.sh --core   only what board itself uses (+ network tools)
# shellcheck disable=SC2024 # setup.log belongs to the invoking user.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
log "== phase12 embedded start =="
sudo -v || { log "phase12 needs sudo"; exit 1; }
sudo apt-get update -q >>"$LOG" 2>&1 || log "apt update had problems (continuing)"

# board itself: serial console, mounts, roaming shell, mDNS browsing, remote GUI, file watching
apt_try tio picocom sshfs mosh avahi-utils waypipe inotify-tools zstd mpv
# network: discovery, ports, path, speed, DNS, raw sockets (board net uses nmap/avahi when present)
apt_try nmap arp-scan mtr-tiny traceroute iperf3 bind9-dnsutils whois netcat-openbsd socat tcpdump ethtool iw wakeonlan
if [ "${1:-}" != "--core" ]; then
  # build on the laptop, run on the Pi / Jetson (and arm64 Docker images)
  apt_try gcc-aarch64-linux-gnu g++-aarch64-linux-gnu gdb-multiarch qemu-user-static binfmt-support cmake ninja-build
  # microcontrollers: STM32 / RP2040 / ESP32 / Arduino
  apt_try gcc-arm-none-eabi libnewlib-arm-none-eabi openocd esptool dfu-util   # picotool comes with the Pico VS Code extension
  # buses and logic analysers
  apt_try sigrok-cli pulseview can-utils i2c-tools
fi

sudo install -m644 "$root/config/remote/udev/60-myos-embedded.rules" /etc/udev/rules.d/60-myos-embedded.rules \
  && sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=tty --subsystem-match=usb \
  && log "udev rules for serial ports, Pico, ST-Link, CMSIS-DAP, J-Link, ESP32 installed"
for g in dialout plugdev; do
  id -nG "$USER" | grep -qw "$g" || { sudo usermod -aG "$g" "$USER" && log "added $USER to $g (log out and back in once)"; }
done
bash "$root/scripts/install-remote.sh" | tee -a "$LOG"
log "== phase12 embedded done =="
echo
echo "Done. Serial ports work now (udev); the dialout group applies after your next login."
echo "Next: board setup   (SSH key + VS Code)   ·   board doctor"
