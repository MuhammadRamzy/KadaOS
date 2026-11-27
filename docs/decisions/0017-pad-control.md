# 0017 — Pad control: laptop mouse + keyboard on the Android tablet

Date: 2026-11-20 · Status: accepted, deployed (Android side not yet tried live)

## Decision

- Super+F12 (and the control-centre toggle and bar icon) now runs **Pad control** instead of the extended screen,
  which moves to Super+Shift+F12. Only one of the two runs at a time.
- Android only accepts outside input through adb, so the input comes from scrcpy 3.3.4 with video off and
  `--mouse=uhid --keyboard=uhid` (a real HID mouse pointer on the Pad). There's nothing to install on the Pad.
- Edge crossing: scrcpy's input window is an invisible 3 px strip on the right edge (Hyprland window rules match
  the title "Pad control"). A watcher polls Hyprland IPC at 20 Hz, only while control is on. When the pointer is on the
  strip **and** the strip has focus, it sends one lone Super tap (`wtype`), which is scrcpy's capture toggle. It
  re-arms only after the pointer leaves the strip, so coming back with Super never bounces back to the Pad.
- Rejected: lan-mouse, Deskflow and Input Leap have no Android client; Android can't take injected input without adb or root.

## Consequences

- Returning is a lone Super tap, not an edge crossing, because scrcpy doesn't report the Pad's pointer position.
- Using a Super+key combo while on the Pad can release capture, because scrcpy sees a lone Super release.
- Unverified until the Pad is plugged in: the empty scrcpy input window under these rules, and auto-capture by the
  Super tap. Fallback: clicking the strip also captures.
