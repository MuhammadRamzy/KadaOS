# Adapting KadaOS

KadaOS is one person's workflow, written to be changed. After any edit in the repo, apply it with the installer step that
owns the file (shown below), then `bash scripts/desktop-check.sh` to confirm the desktop matches.

## Colours and look
Everything is generated from one palette at the top of [`scripts/theme.py`](../scripts/theme.py) (`P = dict(…)`: surfaces,
the accent, red/green/orange). Change it, then `python3 scripts/theme.py` and `bash scripts/phase8b-hyprland-polish.sh`.
Fonts: Adwaita Sans for the interface, JetBrains Mono for code. Wallpaper: Super + Space → "Change wallpaper".
The KadaOS mark sits on the bar's apps button, beside the Super + Space search box and in a corner of the lock screen.
Its sources are in [`config/brand/`](../config/brand); `python3 config/brand/render.py` remakes the PNGs (app icon sizes,
boot and login images) after you change an SVG. The boot and login screens are optional: `./kada --items brand`.

## Shortcuts
They're in [`config/hypr/hyprland.conf`](../config/hypr/hyprland.conf) as `bindd = MODS, KEY, Description, dispatcher, args`.
Keep commas out of the description (Hyprland splits on them; a test checks this). Super + Space and the Super + / cheat
sheet pick up new shortcuts by themselves. Apply: copy the file to `~/.config/hypr/` (Hyprland reloads it).

## Super + Space
- **Your own entries**: add a line to `ACTIONS` or `TOOLS` in [`config/desktop/run.py`](../config/desktop/run.py)
  (title, command, icon, search words), then `bash scripts/install-panels.sh`.
- **Browser profile** for web searches: Super + Space → "Edit: Launcher settings" (`~/.config/myos/launcher.json`).
- **Plain-language understanding** uses the models in `~/.config/local-ai/config.json` (`model`, `embed_model`); it does
  nothing if Ollama isn't running, and stays off while the Battery profile is on.

## The assistant and local AI
Models, voice and dictation language: `~/.config/local-ai/config.json`. Any Ollama model works; smaller ones answer faster
on modest hardware. `fai unload` frees the GPU now.

## What runs at login
`exec-once` lines in `hyprland.conf` and the user services in `config/systemd/` and `config/ai/systemd/`.
Turn a service off: `systemctl --user disable --now NAME`.

## Turning features off
| Feature | Off |
|---|---|
| Hydration reminders | Super + Space → "Hydration: pause today", or `systemctl --user disable --now myos-hydration` |
| Leak scan before commits | `git config --global --unset core.hooksPath` |
| Network trust (firewall part) | `sudo rm /etc/NetworkManager/dispatcher.d/90-myos-trust` |
| USB guard | `sudo systemctl disable --now usbguard` |
| KadaOS boot and login screens | `bash scripts/phase17-brand.sh undo` (Ubuntu's come back) |
| Downloads tidy | `tidy off` (it's off until you turn it on) |
| Work profile | `profile auto` |
| Top bar | Super + Space → "Top bar: hide" / "auto-hide" |

## Machine-specific parts
Detected at install time and skipped when they don't apply: hybrid Intel + NVIDIA rendering (`AQ_DRM_DEVICES`), the
panel's refresh rates (fastest on AC, 60 Hz on battery), NVIDIA video encoding for recordings, battery health, Wi-Fi
monitor mode. If something assumed your hardware wrongly, please [open an issue](https://github.com/MuhammadRamzy/KadaOS/issues).

## Internal names
Commands keep plain technical names (`board`, `phone`, `job`, `disk`, `tasks`…), and the native apps use the `org.myos.*`
IDs and `~/.config/myos/` settings folder from before the project was called KadaOS. They're stable; renaming them would
break existing installs.
