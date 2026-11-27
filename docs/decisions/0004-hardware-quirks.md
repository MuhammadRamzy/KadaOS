# ADR 0004: Workarounds for hardware and package quirks
**Status:** accepted · 2026-09-25

| Quirk | Workaround |
|---|---|
| HP firmware reports the charger offline and the battery "Discharging" at 0 W while on AC | Decide AC from real battery drain (`system-adapt`, `fai status`) |
| Fn+P emits no event on Linux (checked with `scripts/capture-key.py`) | The power mode is on Super+Shift+P |
| Ubuntu enables swaync, waybar, hypridle and hyprpaper as user services, which duplicates Hyprland's `exec-once` | swaync is systemd-only with a Hyprland-only drop-in; the other three are masked |
| libnotify 0.8.8's `notify-send -A` fails here | `config/hypr/scripts/notify-action.py` talks to D-Bus directly |
| Hyprland 0.53 config: no `;` separators; window rule `size` needs absolute pixels | Documented in HANDOFF, and checked by `desktop-check.sh` |
| GNOME Settings' Bluetooth page reports "no adapter" under Hyprland (needs gnome-settings-daemon); Blueman's PowerManager/KillSwitch plugins soft-blocked the adapter | Bluetooth clicks open Blueman in Hyprland; those two Blueman plugins are disabled |
