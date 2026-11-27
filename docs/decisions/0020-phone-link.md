# 0020 — Phone link: KDE Connect + USB cable + ntfy, hardened on both ends (`phone`)

Date: 2026-11-26 · Status: accepted (laptop side built; phone side not tried live yet)

## Context
The user (Pixel 8, Android, MIUI/HyperOS) wants files, links and clipboard both ways, notifications, and laptop
alerts on the phone. KDE Connect alone stopped working "after certain days" in an earlier try. They want it reliable,
efficient, and with as few apps and places as possible. Away alerts go through ntfy.sh, topic `your-secret-topic` (their choice).

## Decision
- **One tool, `phone`** (`config/phone/phone.py`, stdlib), three channels that cover for each other:
  KDE Connect (home Wi-Fi: share, clipboard, notifications, ring), adb over the USB cable (send, get, scrcpy mirror;
  always works) and ntfy (alerts anywhere). `phone send` tries Wi-Fi, then the cable.
- **Phone side hardened once over adb** during `phone setup`: Doze whitelist, RUN_(ANY_)IN_BACKGROUND, no auto-revoke,
  READ_LOGS + SYSTEM_ALERT_WINDOW for automatic clipboard (Android 10+ blocks background clipboard reads). The MIUI
  Autostart and battery-saver switches can't be set over adb, so setup opens the screen and says what to tap.
- **Laptop side**: kdeconnectd starts at login (exec-once). The 5-minute watcher (`phone _tick`) revives it over D-Bus,
  refreshes discovery, and reports "Phone link is down" after 15 min unreachable on the network it was last seen on.
  The report goes out over ntfy, so the failure of one channel is reported by another.
- **Alerts**: watcher problems are forwarded by `phone _alert`: when the screen is locked (default), always, or off.
  Urgent ones always go. Offline sends queue and retry. ntfy.sh topics are public, so by default only the title is sent.
- Two phone apps at most (KDE Connect, ntfy). Rejected: Syncthing (a third app; folder sync isn't what was asked; can be
  added later for "photos to laptop"), LocalSend (both apps must be open; no clipboard or notifications), a custom app.

## Consequences
- No new resident process beyond kdeconnectd. Watchdog cost: one `kdeconnect-cli -l` every 5 minutes.
- On networks with client isolation only the cable and ntfy work; `phone doctor` says so.
- If MIUI refuses READ_LOGS ("USB debugging (Security settings)" off), phone → laptop clipboard needs one tap.
- Networks that drop broadcast (seen on the user's office Wi-Fi, a /16): the laptop records the phone's IP + MAC per network
  while connected (`ss` on kdeconnectd's TCP link) and, when the link drops, sets KDE Connect's `customDevices` (D-Bus) to that
  address so it announces itself directly, then refreshes. The phone can do the same with "Add devices by IP".
- UI: Phone page in the control center (`myos-panel phone`) and a bar item (`phone _bar`, every 30 s, KDE Connect only, hidden
  until paired).
