# ADR 0001: Hyprland is the main desktop, GNOME the fallback
**Status:** accepted · 2026-09-25

**Context:** the goal is a keyboard-first workflow on the laptop, and Hyprland is new to the user. GNOME must stay usable.

**Decision:**
- Hyprland 0.53 from Ubuntu's own packages runs on the Intel iGPU (`AQ_DRM_DEVICES`), with software cursors (the hybrid GPU showed a ghost cursor).
- Every dotfile lives in `config/` and is installed by `phase8b`, which backs up the old files first.
- GNOME gets the same shortcuts (`gnome-shared-keys.sh`).
- `gnome-sync.sh` applies Ubuntu Settings (mouse, touchpad, keyboard, cursor, wallpaper) to Hyprland live.

**Consequences:**
- Muscle memory works in both desktops, and one Settings app controls both.
- Features that need wlroots protocols (layer-shell pop-ups, wtype, grim) are Hyprland-only.
