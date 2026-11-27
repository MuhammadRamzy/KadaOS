# Testing the whole setup

```sh
bash tests/run-all.sh            # everything (~2 min, includes one small local-model answer)
bash tests/run-all.sh --quick    # skip the AI/model and agent live checks
bash tests/run-all.sh --offline  # repo + sandbox only; nothing reads the live session
```

It's safe while you work: nothing opens on your screen, nothing is typed, no setting changes. Apps run
off-screen (GTK broadway) in throwaway sandboxes with a private D-Bus that can't auto-start services, no
portals, and stub commands that block anything state-changing (`hyprctl dispatch`, `systemctl start`,
`nmcli`, notifications…). Read-only queries pass through, so the cheatsheet shows your real shortcuts.

| Section | What it proves |
| --- | --- |
| 1 · Syntax and wiring (`tests/setup_static.py`) | Every Python/shell/JSON/TOML file, the Hyprland config, systemd units and desktop entries are valid; every shortcut, bar module, notification-centre button, Super+Space action and actions-menu entry points at something that exists; no two shortcuts share keys; every shortcut has a cheatsheet description; themed configs match a fresh `theme.py` regen; doc links resolve. |
| 2 · Unit tests (`tests/test_*.py`) | Assistant, launcher, pickers, panels, file actions, workbench, vault copy, hydration logic. |
| 3 · Hydration suite (`tests/hydration_suite.sh`) | The service and notification buttons on a private bus, every panel control and dialog, installer sandbox. See [HYDRATION.md](HYDRATION.md). |
| 4 · Every native app (`tests/ui_audit.py`) | Launcher, cheatsheet, all picker modes, all four Quick Settings pages, File Actions, the assistant (home and a sample conversation with a table/code/link) and Hydration: opens without errors, dark Graphite surface, **all text readable** (WCAG contrast measured against what's really behind it; glass windows are composited over your blurred wallpaper the way Hyprland draws them), fits its window, icon-only buttons are named, Tab never gets stuck, search/typing shows the right results, opening it changes nothing on the system. |
| 5 · This laptop, live (`scripts/desktop-check.sh`) | Read-only: deployed files match the repo, services running, shortcuts loaded, AI models and agents wired. |
| 6 · Security tools (`scripts/security-check.sh`) | All 67 workbench commands present. |

Screenshots of every screen land in `$XDG_RUNTIME_DIR/myos-ui-shots/` (and `hydration-shots/`), plus crops
of the lowest-contrast text so you can judge them. Run one app: `python3 tests/ui_audit.py chat`.
Adding a new app: add a line to `SCENARIOS` in `tests/ui_audit.py` (what to type, what must appear).
