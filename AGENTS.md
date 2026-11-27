# Rules for coding agents working on KadaOS

Claude Code reads this through `CLAUDE.md`, Antigravity through `GEMINI.md`, Copilot through `.github/copilot-instructions.md`.

## What this repo is
The scripts and dotfiles that install and maintain the KadaOS workstation (Ubuntu + Hyprland). `kada` is the installer
menu; `scripts/` holds the install phases and user-level installers; `config/` holds every config and the native apps;
`tests/` holds the checks; `docs/` the guides (start at `docs/INDEX.md`).

## Working rules
1. Inspect before editing (`rg`, `fd`, `git status`). Make small, reversible changes. Don't invent APIs or requirements.
2. Never run `sudo` yourself: privileged steps live in `scripts/phase*.sh`; tell the person the exact command to run.
3. Scripts stay idempotent and tolerant, back up configs before replacing them, and log to `setup.log`.
4. Detect hardware; never assume it. Anything machine-specific must skip cleanly on other machines.
5. Theme colours come from `scripts/theme.py`; regenerate instead of editing generated files.
6. Never commit secrets, `.env` files, keys or personal data. `secret-scan` runs before commits.
7. Never open windows or type into the person's live desktop to test; use `tests/ui_audit.py` (off-screen).
8. Run the checks for what you touched before saying "done": `bash tests/run-all.sh --offline` at least; report failures honestly.
9. Durable decisions go in `docs/decisions/NNNN-title.md` (a short ADR).
