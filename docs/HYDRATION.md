# Hydration reminders

Quiet water-break reminders that count **active screen time**, not wall-clock time.
Everything runs locally: no AI model, no network, no microphone audio.

## Using it

- **Open:** Super+Space → "Hydration", or the Hydration button in the notification
  centre. The panel shows the state, the reason for any wait, today's confirmed
  breaks, and the settings.
- **Reminder buttons:** *Drank water* (logs it and starts a fresh interval),
  *Snooze 10 min* (10 **active** minutes), *Pause today* (until the next start
  time, e.g. pausing at 01:00 resumes at 09:00 the same morning).
- **Terminal:** `myos-hydration status | drank | snooze | pause | resume | undo | clear`.

## How it decides (defaults, all adjustable in the panel)

| Rule | Default |
| --- | --- |
| Reminder after active use | 45 min |
| Reminder hours | 09:00–22:00 |
| Idle (no keyboard/mouse) stops counting | after 180 s |
| Long break resets the interval | 15 min idle, or a suspend of 15 min or more |
| Waits during | lock screen, Do Not Disturb, fullscreen apps, microphone in use |
| Unanswered reminder | one retry after 15 active min, then every 60 active min |

Long breaks are matched to this laptop's hypridle settings: dim at 2.5 min, lock at 5 min,
suspend at 20 min. A 30-minute "away" timer would never fire, because the laptop is already asleep by then.
The microphone is checked (`pw-dump`, metadata only) only in the last minute before a
reminder, so there is no constant process spawning on battery.

## Status messages

| Panel says | Meaning / fix |
| --- | --- |
| Waiting: activity observer unavailable | The idle helper isn't running. It retries automatically; if it persists, reinstall. |
| Waiting: notification state unavailable | swaync isn't running: `systemctl --user restart swaync`. |
| Waiting: compositor unavailable | The service started outside Hyprland. Log out and back in. |
| Settings/state need repair | `~/.config/myos/hydration.json` or the state file is malformed. The file is kept untouched; fix or delete it, then restart. |
| Reminder service is offline | Click *Start reminders*, or `systemctl --user start myos-hydration`. |

Logs: `journalctl --user -u myos-hydration -n 50`.

## Files

- Code: `~/.local/share/myos/hydration*.py`, helper `hydration-idle` (built from `config/desktop/hydration_idle.c`).
- Settings: `~/.config/myos/hydration.json` · State/history: `~/.local/state/myos/hydration/state.json`
  (confirmed drinks only, kept 30 days, mode 600).
- Unit: `~/.config/systemd/user/myos-hydration.service` (restarted by Hyprland at login when enabled).

## Install, update, remove

```sh
bash scripts/install-hydration.sh              # install or update (idempotent; backups in ~/.local/state/myos/hydration-backups/)
bash scripts/install-hydration.sh --uninstall  # remove; settings and history are kept
```

Build dependencies (already on this laptop): `build-essential pkg-config libwayland-dev wayland-protocols pipewire-bin`.
Turning off **Start after login** in the panel disables the unit; reinstalling respects that.

## Testing

```sh
bash tests/hydration_suite.sh            # everything (~1 min), safe while you work
bash tests/hydration_suite.sh --offline  # skip the read-only checks of the live install
```

About 190 checks: engine logic; the service over a private D-Bus with a fake notification server;
**every panel screen** (offline, connected, paused, settings) and **every control** (each button, spin row,
time entry, switch, the Clear dialog's buttons and Esc, toasts, Esc to close, Tab order, 360 px layout);
the notification popup (text, all three buttons, silence, dismiss/stale clicks); theme pixels (dark Graphite
surface, blue accent, red-tinted destructive button, 12-hour times) and theme-regen drift; Super+Space, the
desktop entry and the notification-centre button; install, reinstall and uninstall in a sandbox HOME. The UI runs
off-screen (GTK broadway, no portals, live-session variables removed) and `systemctl` is stubbed, so nothing
touches your desktop. Screenshots of every screen land in `$XDG_RUNTIME_DIR/hydration-shots/`.
