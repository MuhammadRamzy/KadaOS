# Your phone and the laptop (`phone`)

Pixel 8 (Android) ↔ this laptop: files and links both ways, clipboard, phone notifications on the laptop,
find my phone, and laptop alerts on the phone wherever you are. Why it's built this way: [ADR 0020](decisions/0020-phone-link.md).

## Set up once (about 5 minutes)

1. On the laptop: `! bash scripts/phase13-phone.sh` (KDE Connect + firewall ports).
2. On the phone: Settings → About phone → tap **OS version** 7 times → Additional settings → Developer options →
   **USB debugging** on, and **USB debugging (Security settings)** on (needed for automatic clipboard).
3. Plug the phone into the laptop and run `phone setup`. Tap **Allow** on the phone. Then the laptop:
   - opens KDE Connect and ntfy in the Play Store on the phone (tap Install)
   - stops Android from putting both apps to sleep, and lets KDE Connect see the clipboard
   - subscribes ntfy to your alerts topic (tap Subscribe)
   - opens MIUI's Autostart screen (turn both apps on). Then: long-press KDE Connect → App info → Battery saver → **No restrictions**
   - pairs over Wi-Fi (tap Accept)

After this you never set it up again. Unplug the cable.

## Every day

**One place:** the phone icon in the top bar (between Wi-Fi and volume) opens the **Phone panel**: status and battery,
Send files, Send clipboard, Find phone, Mirror screen, received files and alert settings. Drop files on the panel to send
them. The icon is dim when the phone isn't reachable and shows the phone's battery when it's low.


| You want | Do |
|---|---|
| Laptop → phone: a file | Files: right-click → Scripts → **Send to phone** · or `phone send FILE…` |
| Laptop → phone: a link or text | `phone send https://…` · `phone send -t "text"` |
| Phone → laptop: anything | On the phone: **Share → KDE Connect → laptop**. Files land in `~/Downloads` |
| Copy on one, paste on the other | Nothing to do: the clipboard syncs both ways |
| Phone notifications | Show up on the laptop by themselves |
| Find the phone | `phone find` (rings even on silent) · or ask the assistant |
| See / use the phone screen | `phone mirror` (USB cable; clipboard works both ways there too) |
| Phone's latest downloads, by cable | `phone get 3` → `~/Downloads/Phone` |
| Is it working? | `phone` · `phone doctor` explains anything wrong, with the fix |

Ask the assistant (Super+Z): "send the last screenshot to my phone", "find my phone", "text my phone this address".

## Why it keeps working

- **Three channels**: Wi-Fi (KDE Connect), the USB cable (always works), and ntfy over the internet. `phone send`
  tries Wi-Fi, then the cable.
- **Phone side**: Android and MIUI kill background apps after a few days. Setup turns that off for KDE Connect and
  ntfy (Doze exemption, background allowed, permissions kept, Autostart, no battery restrictions).
- **Laptop side**: KDE Connect starts at login. Every 5 minutes the watcher wakes it if it died and asks for the
  phone again. If the phone stays unreachable for 15 minutes on the Wi-Fi where it usually is, you get a "Phone link
  is down" alert **over ntfy**, which doesn't depend on KDE Connect.
- Alerts that can't be sent (no internet) wait and go out when the laptop is back online.

## Alerts on the phone

Laptop problems (disk full, a failed service, a Pi offline, a `board job` finished, the phone link down) reach the
phone through ntfy, topic `your-secret-topic`. By default only when the **laptop is locked** (you're away); urgent ones
always. Change it in `~/.config/myos/phone.json`:
- `"push"`: `"away"` (default), `"always"` or `"off"`
- `"detail"`: `"short"` (title only, default), `"private"` (just "a new alert") or `"full"` (title + details)

ntfy.sh topics are public: anyone who guesses the name can read or send to it. So only short titles leave the
laptop, never command output, addresses or file names. To lock it, reserve the topic with an ntfy account (or
self-host ntfy) and add a token.

## Office, campus and guest Wi-Fi

These networks often block the broadcast KDE Connect uses to find devices, so the link drops when the phone sleeps.
The laptop remembers the phone's address on each network and calls it directly when the link drops (every 5 minutes,
on the panel's ↻ button, and before every send). For the most solid link there, tell the phone where the laptop is too:
KDE Connect on the phone → ⋮ → **Add devices by IP** → the address the Phone panel shows. If the network hides devices
completely, use your phone's hotspot or the cable.

## Limits (honest)

- Wi-Fi features need the phone and laptop on the **same network**. Guest, campus and office Wi-Fi often block
  devices from seeing each other: use your phone's hotspot or the cable there.
- Automatic phone → laptop clipboard relies on the READ_LOGS grant from setup. If MIUI refused it (setup shows
  "skipped"), copy on the phone and tap **Send clipboard** in KDE Connect's notification.
- `phone mirror` and `phone get` need the cable (USB debugging stays on).

## Undo

`bash scripts/install-phone.sh --uninstall` removes the tool. `sudo apt remove kdeconnect` removes KDE Connect.
Your settings stay in `~/.config/myos/phone.json`.
