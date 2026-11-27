# Border signals, and the two browsers

## Border signals (`border-signal`)
The outline around the focused window is in the corner of your eye all day, so it carries quiet signals: no popup,
no sound, nothing to dismiss. The colour says what; the motion says how urgent (a slow breath means "when you get a
chance", a quick flash means "look now"). It always returns to the theme colour.

| Signal | Looks like | When |
|---|---|---|
| Look away | violet, breathes twice | 20 minutes of continuous activity (20-20-20 rule: look 20 ft away for 20 s). A minute away from the keyboard resets it. |
| Attention | amber flash on *that* window | an app asks for attention (a build finished, a message). Not for windows that are just opening, at most once a minute per window. |
| Done | green, breathes once | `border-signal done`, e.g. `make; border-signal done`, or at the end of an agent task |
| Fail | red, two quick flashes | `border-signal fail` |
| Battery | orange, breathes once | battery at 15% while unplugged (once per discharge) |

Never while a window is fullscreen or the screen is locked. Try them all: Super+Space → "Border signals: show them
all", or `border-signal test`.

Settings (optional), re-read every 30 s: Super+Space → "Border signals settings", or `~/.config/myos/border-signals.json`:

```json
{"lookaway": true, "lookaway_minutes": 20, "attention": true, "battery": true, "battery_percent": 15}
```

It runs as the user service `myos-border-signals` (`systemctl --user status myos-border-signals`). It reuses Hydration's
input-only idle observer (it never sees what you type).

## Browsers
- **Chrome** stays the default (Super+B) with all your profiles. Every way of opening it goes through
  `~/.local/bin/google-chrome-stable`, which adds the flags in `~/.config/chrome-flags.conf`: two-finger swipe for
  back/forward, and hardware video decoding on the Intel GPU (better battery for YouTube and Meet). Decoding needs
  Intel's driver once: `! sudo apt install intel-media-va-driver-non-free`. Check at `chrome://gpu`.
- **Zen** (Super+Alt+B, `zen`) is for work with many tabs: workspaces, vertical tabs, split view. It lives in
  `~/.local/opt/zen` and updates itself. To bring over one Chrome profile (bookmarks, history, passwords):
  Super+Space → "Zen: import from Chrome", then pick the profile. Chrome keeps everything.
- Reinstall or repair both: `bash scripts/install-browsers.sh`.
