# 0008 — Security workbench and bounded app layouts

Date: 2026-09-26 · Status: accepted

The security catalogue is shared by the menu and command-presence checker. Menu selections open GUI tools or terminal help; targets require explicit CLI input. Local AI explains and drafts through the existing `fai`; it cannot execute suggested commands. Vendor releases are versioned and hash-pinned; existing installations are preserved.

Super+Space combines app-free profile labels with drun. Layout parsing accepts a fixed app vocabulary, complete phrases and bounded counts. A model fallback emits validated JSON and requires a preview confirmation. Only fixed argv templates reach Hyprland's shell-based exec dispatcher. Layout runs are serialized; new window addresses, classes and workspace IDs identify candidates. Timeouts stop further launches without touching existing windows.

Source configs remain authoritative. The user installer applies the new source binding in canonical position, detects conflicts, and atomically installs changed files with backups outside the loaded config tree. It does not regenerate or replace unrelated desktop settings. Kernel/backlight experiments and privileged package installation remain separate user actions.

Limitations: same-app concurrent launches from outside the layout can still race window matching; single-instance apps may reuse a window and time out. Live validation covers terminal geometry, not every application's startup behavior. Checksums are pinned from official release metadata, not separately authenticated signatures.
