# KadaOS guides

New here? Install with `./kada` (see the [README](../README.md)), log in to Hyprland, and press **Super + Space**.
Type `help` there for everything you can type.

## Using it
- [Hyprland guide](HYPRLAND_GUIDE.md): the desktop, the bar, the panels, the one shortcut you need, troubleshooting.
- [Work layouts](WORK_LAYOUTS.md): several apps tiled at once ("chrome and two terminals").
- [AI guide](AI_GUIDE.md): the assistant, AI on selected text, OCR, dictation, file search, terminal helpers.
- [Agents guide](AGENTS_GUIDE.md): Claude Code, Codex, Antigravity and the local model side by side · [Agent tasks](TASKS.md).
- [Per-project environments (`new-project`)](ENVIRONMENTS.md) · [Long jobs (`job`)](JOBS.md).
- [Disk space (`disk`, Storage panel, Downloads tidy)](STORAGE.md) · [Security checkup](SECURITY_CHECKUP.md).
- [Secrets (`secret-scan`, KeePassXC)](SECRETS.md) · [Network trust levels](NETWORK_TRUST.md) · [USB guard](USB_GUARD.md).
- [Security workbench (`seclab`)](SECURITY_LAB.md): engagements, scope, recipes, findings, reports, Wi-Fi, CTF, lab network.
- [Remote devices (`board`)](REMOTE.md): Raspberry Pis and boards over SSH and serial.
- [Phone link (`phone`)](PHONE.md) · [Google Drive in Files](GOOGLE_DRIVE.md) · [Hydration reminders](HYDRATION.md).
- [Obsidian notes](OBSIDIAN.md) (optional).

## Making it yours
- [Adapting KadaOS](ADAPTING.md): colours, shortcuts, launcher entries, the AI model, startup, turning features off.
- [Testing](TESTING.md): `bash tests/run-all.sh`, 1,100+ checks, off-screen and safe while you work.

## Operating and recovering
- [Post-install checks](runbooks/POST_INSTALL.md) · [Rebuild](runbooks/REBUILD.md) · [Backup and recovery](runbooks/BACKUP_RECOVERY.md)
- [Hyprland internals](runbooks/HYPRLAND.md) · [ROS / Space ROS](runbooks/ROS_SPACEROS.md) · [Security lab](runbooks/SECURITY_LAB.md)
- Self-tests: `bash scripts/desktop-check.sh` (does the desktop match the repo?) and `bash scripts/healthcheck.sh` (tool versions).

## Why it's built this way
- [Architecture decisions](decisions/) (short ADRs).

`scripts/` is the executable source of truth; `config/` holds every dotfile and the native apps; `setup.log` (git-ignored)
records what the installer did.
