# Hyprland on the HP OMEN

> **Current guide:** [../HYPRLAND_GUIDE.md](../HYPRLAND_GUIDE.md) (daily use) · decisions in [../decisions/](../decisions/).
> This page keeps the original install notes.

Ubuntu 26.04 provides Hyprland and its desktop portal in its own repository.
The setup script uses those packages and creates a minimal configuration only
when no user configuration exists. GNOME stays installed and selectable at login.
Ubuntu's Dock, AppIndicators, and Tiling Assistant are already enabled. Phase 8
also installs Extension Manager, Workspace Indicator, System Monitor, and Places
Menu from Ubuntu's GNOME 50 compatible packages. It tries to enable the extensions;
check their state in Extension Manager after logging out and back in.

Run `bash scripts/phase8-hyprland.sh` after the core bootstrap has finished.
Log out, choose Hyprland from the session chooser on the login screen, and log
in. Keep GNOME available if the new session fails. Check `hyprctl configerrors`
inside Hyprland and `journalctl --user -b` for session errors. The first login
is the required display, keyboard, audio, and portal smoke test; package presence
alone does not prove a working desktop.

The config does not force the NVIDIA GPU. Hyprland's multi-GPU guidance recommends
an integrated GPU as the laptop's primary renderer for battery life. If display
outputs fail, inspect `/dev/dri/by-path` and the current NVIDIA driver state
before adding a device override. Do not change kernel modules or driver branches
without a reproducible fault and rollback plan.

Useful shortcuts: Super+Enter terminal; Super+Space launcher; Super+1–9
workspace; Super+Shift+1–9 move window; Super+Q close; Super+Shift+E logout;
Super+Shift+S screenshot. Full bindings live in `config/hypr/hyprland.conf`.

Sources: [Ubuntu Hyprland package](https://packages.ubuntu.com/resolute/hyprland),
[Ubuntu Hyprland portal](https://packages.ubuntu.com/resolute/xdg-desktop-portal-hyprland),
[Hyprland multi-GPU guidance](https://wiki.hypr.land/configuring/extra/multi-gpu/).
