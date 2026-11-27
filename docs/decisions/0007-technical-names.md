# 0007 — Technical names, no "owner"

Date: 2026-09-25 · Accepted (user decision)

"Owner" was only the setup's working name. Nothing new may use it. Everything is named for what it does:

| Was | Now |
|---|---|
| `~/OwnerVault` | `~/DocsVault` |
| MCP server `owner` | `local-tools` (`mcp-local-tools.py`) |
| `~/.local/share`, `~/.config`, `~/.cache` `/owner-ai` | `.../local-ai` |
| `owner-ollama`, `owner-whisper`, `owner-index`, `owner-vault`, `owner-adapt` | `ollama-local`, `whisper-server`, `docs-index`, `docs-vault-sync`, `system-adapt` |
| `~/.config/owneros-backup`, `~/.local/state/owner{,os}`, `~/.cache/owner` | `~/.config/setup-backups`, `~/.local/state/setup`, `~/.cache/setup` |
| `OWNEROS_*` backup variables, `.owneros-new` | `BACKUP_*`, `.setup-new` |
| "KadaOS" in text | "KadaOS" (the GitHub repo name) |

Not renamed yet: the repo folder `~/KadaOS` (hard-coded in agent configs and units), the HDD mount `/mnt/backup-hdd`
and `/etc/sysctl.d/99-owner.conf` (both need sudo), and the original source documents' text in `docs/reference/`.
`scripts/migrate-names.sh` moves a live install from the old names (one-time, re-runnable).
