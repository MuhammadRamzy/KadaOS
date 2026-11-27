#!/usr/bin/env bash
# vault-sync — copy project docs into ~/DocsVault without changing source files.
#   00 Home.md               → generated dashboard (projects, status, latest handoff/review notes)
# Safe to re-run (a user timer runs it hourly). Your own notes live in Inbox/ and Notes/ and are never touched.
set -u
V=${DOCS_VAULT:-$HOME/DocsVault}; root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$V/Projects" "$V/Inbox" "$V/Notes" "$V/.obsidian"
# first run: install the vault settings (graph colours, core plugins, dark theme) from the repo
[ -f "$V/.obsidian/app.json" ] || cp -rn "$root/config/obsidian/." "$V/.obsidian/"
# register the vault with Obsidian, or obsidian://open?path=… (Super+O) fails with "Vault not found"
python3 - "$V" <<'PY' || true
import json, os, secrets, sys, time
v = os.path.realpath(sys.argv[1]); cfg = os.path.expanduser("~/.config/obsidian/obsidian.json")
try: data = json.load(open(cfg))
except (OSError, ValueError): data = {}
vaults = data.setdefault("vaults", {})
if all(e.get("path") != v for e in vaults.values()):
    vaults[secrets.token_hex(8)] = {"path": v, "ts": int(time.time() * 1000)}
    os.makedirs(os.path.dirname(cfg), exist_ok=True); tmp = cfg + ".tmp"
    json.dump(data, open(tmp, "w")); os.replace(tmp, cfg); print("vault registered with Obsidian")
PY

projects=()
for d in "$HOME"/Projects/* "$HOME"/Workspaces/* "$HOME/KadaOS"; do
  [ -d "$d" ] || continue
  [ -d "$d/docs" ] || [ -f "$d/README.md" ] || [ -f "$d/AGENTS.md" ] || continue
  projects+=("$d")
done

for d in "${projects[@]}"; do
  n=$(basename "$d"); t="$V/Projects/$n"
  python3 "$root/scripts/vault-copy.py" "$d" "$t" || exit 1
done

# dashboard
{
  echo "---"; echo "tags: [dashboard]"; echo "updated: $(date '+%Y-%m-%d %H:%M')"; echo "---"
  echo "# Home"; echo
  echo "Copied project docs. Edits here stay in the vault; project files stay in their repos."; echo
  echo "## Projects"
  for d in "${projects[@]}"; do
    n=$(basename "$d"); line="- **$n**"
    [ -f "$d/README.md" ] && line+=" · [[Projects/$n/README|README]]"
    [ -f "$d/docs/STATUS.md" ] && line+=" · [[Projects/$n/docs/STATUS|Status]]"
    [ -f "$d/docs/INDEX.md" ] && line+=" · [[Projects/$n/docs/INDEX|Docs index]]"
    [ -f "$d/docs/HANDOFF.md" ] && line+=" · [[Projects/$n/docs/HANDOFF|Handoff]]"
    [ -f "$d/docs/ai/HANDOFF.md" ] && line+=" · [[Projects/$n/docs/ai/HANDOFF|Handoff]]"
    c=$(git -C "$d" log -1 --format='%cr: %s' 2>/dev/null | cut -c1-70); [ -n "$c" ] && line+="  _(last commit ${c})_"
    echo "$line"
  done
  echo; echo "## Recent reviews and decisions"
  find "${projects[@]/%//docs}" -path '*/docs/reviews/*.md' -o -path '*/docs/decisions/*.md' 2>/dev/null \
    | xargs -r ls -t 2>/dev/null | head -12 | while read -r f; do
      for d in "${projects[@]}"; do case "$f" in "$d"/*) rel="Projects/$(basename "$d")/${f#"$d"/}"; echo "- [[${rel%.md}|$(basename "$d") · $(basename "${f%.md}")]]";; esac; done
    done
  echo; echo "## Your notes"; echo "- Capture ideas in **Inbox/** and keep long-lived notes in **Notes/**. The sync never touches either folder."
} > "$V/00 Home.md"
echo "vault: $V (${#projects[@]} projects)"
