# Secrets: no keys in git

## Leak scan before every commit (`secret-scan`)
A global git hook checks what you're about to commit, in every repo, and stops the commit if it finds a secret:
private keys, AWS / GitHub / Slack / Google / OpenAI / Anthropic / Stripe tokens, passwords in URLs, hard-coded
`password = "…"`, and files that usually hold secrets (`.env`, `id_ed25519`, `*.pem`, `*.key`, `credentials.json`…).
Placeholders (`your-password-here`, `${API_KEY}`, `<…>`) don't count.

**Turn it on** (user-level, no password; it sets `git config --global core.hooksPath`):
`! bash scripts/install-git-hooks.sh`. Undo: `git config --global --unset core.hooksPath`.

- With **gitleaks** installed (`! sudo apt install gitleaks`) it uses gitleaks' full rule set; until then the built-in scan.
- The repo's own hooks still run after the scan (git-lfs, the pre-commit framework…). A repo that sets its own
  `core.hooksPath` (e.g. husky) keeps its hooks and skips this scan.
- A line that's fine: add `gitleaks:allow` to it. Skip once: `git commit --no-verify`.
- Before publishing a repo: `secret-scan --all` (tracked files) and `secret-scan --history` (every commit; needs gitleaks).

## Vault: KeePassXC (Super + Ctrl + K)
**Install:** `! bash scripts/phase14-secrets.sh` (KeePassXC + gitleaks, and turns on the leak scan above).

1. Super + Ctrl + K → *Create new database*. Save it as `~/Documents/Vault.kdbx`, pick a long master passphrase, and keep a
   copy of the file somewhere off the laptop (it's encrypted; the file alone is useless without the passphrase).
2. Put API keys and passwords in it, one entry each (folders per project help).
3. **Use a secret in a project** without writing it to disk: in the project's `.envrc`
   `export OPENAI_API_KEY="$(keepassxc-cli show -s -a password ~/Documents/Vault.kdbx myproject/openai)"`
   (asks for the master passphrase when you `cd` in). Or keep a git-ignored `.env`, which `new-project` already sets up.
4. On the phone: KeePassDX opens the same file (sync it with the phone link: `phone send ~/Documents/Vault.kdbx`).

GNOME Keyring stays as it is (Wi-Fi, the SSH key passphrase, app logins); KeePassXC's own Secret Service is left off so
the two don't fight over the same D-Bus name.
