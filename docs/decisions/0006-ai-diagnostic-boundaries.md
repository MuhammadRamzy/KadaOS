# 0006 — Validate complete diagnostic commands

Date: 2026-09-25 · Accepted

The local laptop assistant and local-tools MCP share `fai.run_readonly`. The old first-word/deny-list check allowed mutating options on otherwise diagnostic programs and allowed environment dumps.

Validate complete command shapes and options before executing, with no shell and closed stdin. Limit file-content reads to setup documentation, Hyprland configuration, and selected metrics; resolve symlinks before checking boundaries. Refuse unsupported commands and suggest that the user run them manually. In particular, environment dumps, unrestricted container inspection/logs and arbitrary home-file reads are outside this tool's scope.

This intentionally narrows the diagnostics described in ADR 0003. It does not sandbox the entire local process or guarantee that arbitrary service log output contains no sensitive text. Model requests cannot widen the command allow-list. Offline refusal tests must demonstrate that unsafe requests never reach subprocess execution.

Install code with backups and preserve executable permissions. Existing MCP processes load code at startup and must reconnect to pick up revisions.
