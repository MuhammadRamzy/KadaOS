# 0011 — Phase 1 repairs and Google Drive through rclone mount

Date: 2026-11-04 · Status: accepted (Claude, user-authorized implementation)

**Duplicate Files launch (DESK-01).** Root cause reproduced. rofi 2.0 gives D-Bus activation 1500 ms
([source](https://github.com/davatorium/rofi/blob/2.0.0/source/modes/drun.c), `exec_dbus_entry`). If no reply
arrives in time, it also runs the entry's `Exec`. Both requests open a window when Nautilus answers slowly, for
example on a cold start after login. Pausing the Nautilus service for 2.5 s reproduced two windows every time.
`configuration { drun { DBusActivatable: false; } }` in the generated rofi config makes rofi always use `Exec`
only. Afterwards, the same slow-start reproduction gave one window.

**Diagnostics (AI-02/03).** `system_status()` treats nonzero exit codes, missing tools and timeouts as
*unavailable/unknown*, with the reason. It no longer reports them as idle or healthy. `desktop-check.sh` now runs
the function instead of only listing the MCP tools.

**Dictation (DESK-09).** Typing is bound to the window that was focused when dictation started. When focus
changes or the screen locks, text is held on the clipboard instead of being typed.

**Agent sessions (WORK-01).** tmux session name = sanitized basename + first 6 hex characters of the SHA-1 of the
full path.

**Backup (REC-02/04).** The installed helper is synced to source (`DocsVault`). `Workspaces` and `Documents` are
added. `Downloads` is deliberately excluded.

**Google Drive (CLOUD-01/02).** GNOME 50 removed its Drive integration. Signing in to Google again in Online
Accounts does not restore it. Choice: the official rclone build (v1.75.2) in `~/.local/bin`, plus a user unit
`google-drive.service` that mounts at `~/GoogleDrive` with a Files bookmark. The mount streams files; it does not
sync them. It uses a full VFS cache capped at 10 GB, with a 15 GB free-space floor. It is not a backup and does
not give offline access to the whole drive. The rclone docs say a personal Desktop OAuth client is required in
2026, so `scripts/drive-connect.sh` asks for one and runs the browser sign-in. Google-native Docs appear as
exported docx/xlsx/pptx; edit them in the browser. Rollback: `bash scripts/drive-connect.sh --off`. Distro rclone
1.60 was left installed and is shadowed by `~/.local/bin`.

Backups of the replaced live files are in `~/.local/share/local-ai/backups-2026-11-04/`.
