# Changelog

## 1.1.1 · 2026-11-27 · Fixing the shop front

- **Login**: GNOME's top bar is back to its normal size (the big clock had stretched it, and the system menu with it);
  the chosen name sits on a glass row. The glass backdrop stays.
- **Boot**: the splash is the mark as glass with its cursor glowing and breathing, matching the login; the extra
  wordmark is gone.
- **No more splash flicker**: the boot screen used to appear, go dark and appear again when the graphics driver took
  over. `phase17-brand.sh` now loads the display's driver (Intel or AMD) inside the boot image (early KMS) so it shows once.
  Rerun `bash scripts/phase17-brand.sh` to get it; `undo` removes it too.

## 1.1 · 2026-11-27 · The front of the shop

New screens, a quieter way to get your attention, and a lot less CPU.

- **Lock and login screens**: the KadaOS backdrop (the mark drawn as glass, its cursor glowing), a big 12-hour clock,
  and the same input as Super + Space. The login (GDM) has no avatar cards; the boot screen is a new graphite splash with
  a softly blinking cursor. Optional and fully reversible: `bash scripts/phase17-brand.sh` (`undo` restores the theme
  that was selected before).
- **Border signals** (`border-signal`): the window outline as a quiet signal. A look-away reminder after 20 minutes at
  the screen, an amber flash on a window that needs you, a low-battery breath, and `border-signal done|fail` for your
  scripts and agents. Never while fullscreen or locked.
- **Browsers**: Chrome tuned through `~/.config/chrome-flags.conf` (touchpad swipes, hardware video decoding), plus Zen
  for tab-heavy work (checksum-verified install, Super + Alt + B, import from one Chrome profile).
- **Top bar** (auto-hide): slides in after the cursor rests at the edge; its watcher went from ~40% of a CPU core to 0.4%.
- Fixes: Super + Space now always takes typing after reopening; the Storage panel's clean-up reports real results.

## 1.0 · 2026-11-27 · Opening day

The first public serving.

- `./kada`: the installer menu with seven orders and à la carte, dependency-aware, dry-run and unattended modes.
- **Super + Space**: one search for everything: apps, every feature and shortcut (keys shown), settings, config files,
  projects, files, clipboard history, commands with values, plain-language understanding through the local AI, and a web
  search in the browser you already have open. Learns what you pick.
- Desktop: Hyprland with the Graphite theme, native GTK4 panels (Wi-Fi, Bluetooth, clipboard, calendar, inbox, storage,
  security, battery, projects, services, agent tasks, remote devices, phone), screen recording, work profiles, monitor
  layouts, hydration reminders, Downloads tidy.
- Development: `new-project`, `job`, services view, work layouts; coding agents with the task board and `agent-review`.
- Security: hardening, `secret-scan` + gitleaks, KeePassXC, network trust levels, USB guard, `seclab` engagements with
  scope, recipes, findings and PDF reports, Wi-Fi adapter detection, CTF workspaces, an isolated lab network.
- Local AI: assistant, dictation, OCR, search by meaning, private metasearch.
- Embedded and robotics: `board` (SSH devices, serial, health, jobs, alerts), ROS 2 Lyrical, Space ROS.
- Phone link: KDE Connect, USB cable fallback, ntfy alerts.
- The KadaOS mark: bar, Super + Space, lock screen, app icon, and (optional) the boot and login screens.
- 1,100+ automated checks, including every app rendered off-screen.
