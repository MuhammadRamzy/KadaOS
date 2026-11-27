#!/usr/bin/env bash
# Phase 4: agent rules, project template, Obsidian vault, MarkItDown ingestion, dotfiles repo
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || exit 1
log "== phase4 start =="
export PATH="$HOME/.local/bin:$PATH"
# ---- project template
t=~/Templates/project-base; mkdir -p $t/{docs/{requirements,architecture,decisions,runbooks,ai},scripts,tests}
[ -f "$t/docs/ai/shared-rules.md" ] || cat > "$t/docs/ai/shared-rules.md" <<'M'
# Shared agent rules (single source; CLAUDE.md/AGENTS.md/GEMINI.md/copilot point here)
## Mission
Build, test, document and maintain this repo with minimal unnecessary context.
## Source of truth
Requirements: docs/requirements/ · Architecture: docs/architecture/ · ADRs: docs/decisions/ · Runbooks: docs/runbooks/ · Tasks: docs/STATUS.md
## Rules
1. Inspect before editing (rg/fd/tree; read the index before many files).
2. Small, reversible changes. Do not invent APIs, data models or requirements.
3. Reuse existing utilities before adding dependencies.
4. Update docs when behavior/architecture changes; durable decisions go to docs/decisions/.
5. Run targeted tests before broad suites. Never expose secrets.
6. Don't modify generated/vendor files. Summarize long logs; don't paste them.
7. End non-trivial tasks with: changed files, tests run, risks/follow-ups, docs updated.
M
for f in CLAUDE.md AGENTS.md GEMINI.md; do
  [ -f "$t/$f" ] || echo "Follow @docs/ai/shared-rules.md. Keep this file short; put shared rules there." > "$t/$f"
done
sed -i 's/@docs/docs/' $t/AGENTS.md $t/GEMINI.md
mkdir -p "$t/.github"
[ -f "$t/.github/copilot-instructions.md" ] || echo "Follow docs/ai/shared-rules.md." > "$t/.github/copilot-instructions.md"
[ -f "$t/README.md" ] || printf '# Project\n\n' > "$t/README.md"
[ -f "$t/docs/STATUS.md" ] || printf '# Status\n\n- [ ] \n' > "$t/docs/STATUS.md"
# ---- Claude Code global config (never overwrite existing)
c=~/.claude; mkdir -p $c/{rules,skills,agents,hooks}
[ -f $c/CLAUDE.md ] || cat > $c/CLAUDE.md <<'M'
# Global conventions
- Inspect before modifying; prefer rg/fd/tree; summarize long logs.
- Small reversible changes; run lint/tests after edits; state what you inspected.
- Never commit secrets. Durable decisions -> docs/decisions/.
- Use subagents only when parallelism/specialization helps.
M
for a in flutter backend database devops security research docs uiux; do
  [ -f $c/agents/$a.md ] || cat > $c/agents/$a.md <<M
---
name: $a
description: Specialist for $a work. Use proactively for $a-related tasks.
---
You are a $a specialist. Inspect existing code/docs first, make minimal changes, verify with tests, report concisely.
M
done
for s in plan research implement review test document adr release security-review; do
  mkdir -p $c/skills/fos-$s
  [ -f $c/skills/fos-$s/SKILL.md ] || cat > $c/skills/fos-$s/SKILL.md <<M
---
name: fos-$s
description: KadaOS $s workflow. Use when the user asks to $s.
---
Perform the "$s" workflow: inspect first, keep context small, record durable outcomes in docs/, end with a short summary (changed files, tests, risks).
M
done
[ -f $c/hooks/secret-check.sh ] || cat > $c/hooks/secret-check.sh <<'H'
#!/usr/bin/env bash
# Blocks staged secrets (uses gitleaks if present, else a simple regex)
if command -v gitleaks >/dev/null; then gitleaks protect --staged -q; exit $?; fi
git diff --cached -U0 2>/dev/null | grep -EnI '(AKIA[0-9A-Z]{16}|-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|ghp_[A-Za-z0-9]{36}|sk-[A-Za-z0-9]{20,})' && { echo "possible secret staged"; exit 1; }
exit 0
H
chmod +x $c/hooks/secret-check.sh
log "claude config in ~/.claude (settings.json untouched)"
# ---- Obsidian vault
v=~/DocsVault
mkdir -p $v/{"00 Dashboard","01 Projects","02 AI/Claude","02 AI/Codex","02 AI/Gemini","02 AI/Reviews","03 Research","04 Architecture","05 Decisions","06 Meetings","07 Learning","08 Security","09 Prompts","10 Templates",Attachments}
tp="$v/10 Templates"
[ -f "$tp/Daily.md" ] || {
printf -- '---\ntype: daily\ncreated: {{date}}\ntags: [daily]\n---\n# {{date}}\n## Focus\n## Log\n## Decisions\n' > "$tp/Daily.md"
printf -- '---\ntype: adr\nstatus: proposed\nproject:\ncreated: {{date}}\n---\n# ADR: \n## Context\n## Decision\n## Consequences\n' > "$tp/ADR.md"
printf -- '---\ntype: research\nsource:\ncreated: {{date}}\ntags: []\n---\n# \n## Summary\n## Key findings\n## Links\n' > "$tp/Research.md"
printf -- '---\ntype: ai-session\nagent:\nproject:\ncreated: {{date}}\n---\n# Session\n## Goal\n## Outcome\n## Follow-ups\n' > "$tp/AI Session.md"
printf -- '---\ntype: meeting\ncreated: {{date}}\n---\n# Meeting\n## Attendees\n## Notes\n## Actions\n' > "$tp/Meeting.md"
printf -- '---\ntype: project\nstatus: active\ncreated: {{date}}\n---\n# Project\n## Goal\n## Links\n' > "$tp/Project.md"
printf '# Conventions\n- Mermaid for version-controlled diagrams; Canvas/Excalidraw for visual maps.\n- AI transcripts = raw evidence; curated Decision/Summary notes = truth.\n' > "$tp/Conventions.md"; }
# ---- MarkItDown in isolated uv env
if command -v uv >/dev/null && [ ! -x ~/Tools/markitdown/.venv/bin/markitdown ]; then
  uv venv ~/Tools/markitdown/.venv --python 3.12 >>"$LOG" 2>&1 && \
  uv pip install --python ~/Tools/markitdown/.venv/bin/python 'markitdown[all]' >>"$LOG" 2>&1 && log "markitdown installed"
fi
mkdir -p "$HOME/Scripts"
for name in ingest_to_obsidian.py sync_ai_docs_to_obsidian.py; do
  source="$root/config/automation/$name"
  target="$HOME/Scripts/$name"
  if [ ! -e "$target" ]; then
    install -m 755 "$source" "$target"
    log "created $target"
  elif ! cmp -s "$source" "$target"; then
    proposal="$target.setup-new"
    [ -e "$proposal" ] || install -m 755 "$source" "$proposal"
    log "REVIEW outdated $target against $proposal; existing script preserved"
  fi
done
# ---- dotfiles repo (stow layout, non-destructive: copies, doesn't replace)
d=~/dotfiles; mkdir -p $d/{zsh,git,tmux,starship/.config,vscode/.config/Code/User}
[ -f ~/.zshrc ] && cp -n ~/.zshrc $d/zsh/.zshrc
[ -f ~/.gitconfig ] && cp -n ~/.gitconfig $d/git/.gitconfig
[ -f ~/.tmux.conf ] || printf 'set -g mouse on\nset -g history-limit 50000\nset -g default-terminal "tmux-256color"\nset -g base-index 1\n' > ~/.tmux.conf
cp -n ~/.tmux.conf $d/tmux/.tmux.conf
[ -d $d/.git ] || git -C $d init -q
log "== phase4 done =="
