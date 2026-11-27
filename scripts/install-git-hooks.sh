#!/usr/bin/env bash
# Leak scan before every commit, in every repo: global git hooks folder + secret-scan. User-level; no sudo.
# Undo: git config --global --unset core.hooksPath
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hooks="$HOME/.config/git/hooks"
install -Dm755 "$root/config/git/secret-scan.py" ~/.local/share/myos/secret-scan.py
ln -sfn ~/.local/share/myos/secret-scan.py ~/.local/bin/secret-scan
install -Dm755 "$root/config/git/hooks/dispatch" "$hooks/dispatch"
for h in applypatch-msg pre-applypatch post-applypatch pre-commit pre-merge-commit prepare-commit-msg commit-msg \
         post-commit pre-rebase post-checkout post-merge pre-push post-rewrite push-to-checkout; do
  ln -sfn dispatch "$hooks/$h"
done
cur="$(git config --global --get core.hooksPath || true)"
if [ -n "$cur" ] && [ "$cur" != "$hooks" ]; then
  echo "core.hooksPath is already set to $cur; not changing it. Point it at $hooks yourself if you want the scan."; exit 1
fi
git config --global core.hooksPath "$hooks"
command -v gitleaks >/dev/null || echo "Built-in scan active. For the full rule set: ! sudo apt install gitleaks"
echo "secret scan before every commit: on ($hooks)"
