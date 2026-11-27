#!/usr/bin/env bash
# Install KadaOS native panels (Quick Settings: Wi-Fi, Bluetooth, Clipboard). User-level; no sudo.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install -Dm755 "$root/config/desktop/panel.py" ~/.local/share/myos/panel.py
install -Dm755 "$root/config/desktop/bin/myos-panel" ~/.local/bin/myos-panel
install -Dm755 "$root/config/desktop/cheatsheet.py" ~/.local/share/myos/cheatsheet.py
install -Dm755 "$root/config/desktop/fileactions.py" ~/.local/share/myos/fileactions.py
install -Dm755 "$root/config/desktop/pick.py" ~/.local/share/myos/pick.py
install -Dm755 "$root/config/desktop/run.py" ~/.local/share/myos/run.py
install -Dm644 "$root/config/brand/kadaos-mark-small.svg" ~/.local/share/myos/kadaos-mark.svg
install -Dm644 "$root/config/brand/kadaos-backdrop.jpg" ~/.local/share/myos/kadaos-backdrop.jpg   # lock screen background
# the KadaOS app icon (icon name "kadaos"): fixed sizes for crisp small icons, plus the scalable one
for n in 16 24 32 48 64 128 256 512; do install -Dm644 "$root/config/brand/icons/$n.png" ~/.local/share/icons/hicolor/${n}x${n}/apps/kadaos.png; done
install -Dm644 "$root/config/brand/kadaos-icon.svg" ~/.local/share/icons/hicolor/scalable/apps/kadaos.svg
install -Dm755 "$root/config/desktop/bin/myos-pick" ~/.local/bin/myos-pick
install -Dm755 "$root/config/desktop/job.py" ~/.local/share/myos/job.py && ln -sfn ~/.local/share/myos/job.py ~/.local/bin/job
install -Dm755 "$root/config/desktop/disk.py" ~/.local/share/myos/disk.py && ln -sfn ~/.local/share/myos/disk.py ~/.local/bin/disk
install -Dm755 "$root/config/desktop/security.py" ~/.local/share/myos/security.py && ln -sfn ~/.local/share/myos/security.py ~/.local/bin/security-check
install -Dm755 "$root/config/desktop/profile.py" ~/.local/share/myos/profile.py && ln -sfn ~/.local/share/myos/profile.py ~/.local/bin/profile
install -Dm755 "$root/config/desktop/battery.py" ~/.local/share/myos/battery.py && ln -sfn ~/.local/share/myos/battery.py ~/.local/bin/battery-health
install -Dm755 "$root/config/desktop/monitors.py" ~/.local/share/myos/monitors.py && ln -sfn ~/.local/share/myos/monitors.py ~/.local/bin/monitors
install -Dm755 "$root/config/desktop/projects.py" ~/.local/share/myos/projects.py && ln -sfn ~/.local/share/myos/projects.py ~/.local/bin/projects
install -Dm755 "$root/config/desktop/services.py" ~/.local/share/myos/services.py && ln -sfn ~/.local/share/myos/services.py ~/.local/bin/services
install -Dm755 "$root/config/desktop/newproject.py" ~/.local/share/myos/newproject.py && ln -sfn ~/.local/share/myos/newproject.py ~/.local/bin/new-project
install -Dm755 "$root/config/desktop/tasks.py" ~/.local/share/myos/tasks.py && ln -sfn ~/.local/share/myos/tasks.py ~/.local/bin/tasks
install -Dm755 "$root/config/network/trust.py" ~/.local/share/myos/trust.py && ln -sfn ~/.local/share/myos/trust.py ~/.local/bin/trust
install -Dm755 "$root/config/desktop/usbguard.py" ~/.local/share/myos/usbguard.py && ln -sfn ~/.local/share/myos/usbguard.py ~/.local/bin/usb-guard
install -Dm755 "$root/config/desktop/tidy.py" ~/.local/share/myos/tidy.py && ln -sfn ~/.local/share/myos/tidy.py ~/.local/bin/tidy
install -Dm755 "$root/config/desktop/nautilus-scripts/Convert & more…" "$HOME/.local/share/nautilus/scripts/Convert & more…"
rm -f "$HOME/.local/share/nautilus/scripts/✦ Actions…"   # old name
# Files shortcut: select files, press Ctrl+Shift+X
mkdir -p ~/.config/nautilus; touch ~/.config/nautilus/scripts-accels
grep -q 'Convert & more' ~/.config/nautilus/scripts-accels || printf '<Control><Shift>x Convert & more…\n' >> ~/.config/nautilus/scripts-accels
install -Dm755 "$root/config/desktop/nautilus-scripts/Open Terminal Here" "$HOME/.local/share/nautilus/scripts/Open Terminal Here"
# border signals: the window outline as a quiet signal channel (look-away reminder, attention, battery, `border-signal done`)
install -Dm755 "$root/config/desktop/border_signals.py" ~/.local/share/myos/border_signals.py && ln -sfn ~/.local/share/myos/border_signals.py ~/.local/bin/border-signal
install -Dm644 "$root/config/systemd/myos-border-signals.service" ~/.config/systemd/user/myos-border-signals.service
systemctl --user daemon-reload 2>/dev/null && systemctl --user enable myos-border-signals.service >/dev/null 2>&1 \
  && { systemctl --user is-active --quiet myos-border-signals.service && systemctl --user restart myos-border-signals.service || systemctl --user start myos-border-signals.service; } || true
# restart a running panel so the new code loads
gdbus call --session --dest org.myos.Panel --object-path /org/myos/Panel --method org.gtk.Application.Activate '{}' >/dev/null 2>&1 \
  && pkill -f "share/myos/panel.py" || true
echo "panels installed: myos-panel wifi | bluetooth | clipboard"
