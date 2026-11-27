# 0016 — Hydration reminders: active-time scheduling in a user service

Date: 2026-11-20 · Status: accepted, deployed

## Decision

- A pure-Python engine (`hydration_engine.py`) and a GLib user service (`hydration.py`) with a
  D-Bus control API (`org.myos.Hydration`), plus a libadwaita panel. No LLM, no network.
- Idle and return come from a tiny C client of Wayland `ext_idle_notifier_v1` **v2**
  (`get_input_idle_notification`, which ignores idle inhibitors, so a video playing with no input still counts as idle).
  Verified on Hyprland 0.53.3: the helper reports `ready`, and the status shows `observer: true`.
- Context comes from logind (LockedHint, plus a hyprlock process check), swaync `GetDnd`, the Hyprland
  `activewindow` fullscreen flag, and PipeWire input streams (metadata only, checked only near delivery).
- The long-break threshold is 15 min, and a suspend of 15 min or more also resets the interval. This laptop's hypridle suspends at
  20 min, so the plan's 30 min would never fire.
- Missing essential signals pause delivery with a visible reason, never a silent fixed timer.

## Consequences

- Hyprland must restart the unit at login (exec-once), so the service gets the current
  `WAYLAND_DISPLAY`/`HYPRLAND_INSTANCE_SIGNATURE`. The first start at `default.target` is skipped by
  `ConditionEnvironment`, which is expected.
- Day rollover happens at local midnight, so a schedule that spans midnight (e.g. 22:00–06:00) restarts its interval at 00:00.
  This is accepted for now.

See [the guide](../HYDRATION.md) and the plan.
