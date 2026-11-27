# Obsidian: every project's docs in one place

**Vault:** `~/DocsVault`. Open it with **Super + O**.

## How it's built
- **Independent copies:** `Projects/<name>/docs`, `README.md` and `AGENTS.md` are copied from each project. Editing or deleting a vault copy does not change the project original. The sync copies new and updated project files, preserves vault edits, and saves conflicting project revisions as `.incoming-<hash>` files. It never deletes project files or vault notes.
- **Home page:** `00 Home.md` is generated with each project's README, status, docs index and handoff, its latest commit, and the recent reviews and ADRs.
- **Your notes:** `Inbox/` is for quick capture (new notes go here by default) and `Notes/` is for keeping. The sync never touches either folder.
- **Graph view** (Ctrl + G): each project has its own colour (this setup is gold), so you can see how the docs link to each other.
- **Diagrams:** Mermaid diagrams in the docs render natively.

## Keeping it fresh
`scripts/vault-sync.sh` runs every hour (the `docs-vault-sync.timer` user timer), whenever `proj-init` creates a project, and whenever you run it yourself. A project appears in the vault once it has a `docs/` folder, a README or an AGENTS.md.

## Install
- **App:** `sudo snap install obsidian --classic` (the official snap, published by Obsidian).
- **First launch:** Super + O opens the vault directly. If Obsidian asks, choose "Trust author" and keep the default settings.
- **Settings:** the vault's settings (dark theme with a gold accent, Ubuntu Sans and JetBrains Mono fonts, graph colours) come from `config/obsidian/` and are installed on the first sync.
