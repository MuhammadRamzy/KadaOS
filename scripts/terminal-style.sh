#!/usr/bin/env bash
# Apply a readable Ptyxis profile, centered greeting, and terminal help menu.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$HOME/.config" "$HOME/.local/bin" "$HOME/.config/setup-snapshots"
[ -f "$HOME/.zshrc" ] || touch "$HOME/.zshrc"
[ -f "$HOME/.config/setup-snapshots/zshrc-before-workflow" ] || \
  cp "$HOME/.zshrc" "$HOME/.config/setup-snapshots/zshrc-before-workflow"
if [ ! -e "$HOME/.config/starship.toml" ]; then
  install -m 644 "$root/config/terminal/retro-neon.toml" "$HOME/.config/starship.toml"
fi
if [ ! -e "$HOME/.config/terminal-greeting.py" ]; then
  install -m 644 "$root/config/terminal/greeting.py" "$HOME/.config/terminal-greeting.py"
fi
if [ ! -e "$HOME/.local/bin/helpme" ]; then
  install -m 755 "$root/scripts/terminal-help.py" "$HOME/.local/bin/helpme"
fi
if [ ! -e "$HOME/.local/bin/sysinfo" ]; then
cat > "$HOME/.local/bin/sysinfo" <<'SYS'
#!/usr/bin/env bash
exec fastfetch --logo none "$@"
SYS
  chmod 755 "$HOME/.local/bin/sysinfo"
fi
python3 - "$root/config/terminal/zsh-block.txt" <<'PY'
from pathlib import Path
import sys
path = Path.home() / '.zshrc'
content = path.read_text()
if '# terminal workflow start' not in content:
    start_marker, end_marker = '# retro terminal start', '# retro terminal end'
    start = content.find(start_marker)
    if start >= 0:
        end = content.find(end_marker, start)
        if end < 0:
            raise SystemExit(f'Missing {end_marker} in .zshrc')
        content = content[:start].rstrip() + '\n' + content[end + len(end_marker):].lstrip('\n')
    block = Path(sys.argv[1]).read_text()
    path.write_text(content.rstrip() + '\n\n' + block)
PY
python3 - <<'PY'
import json
import os
from pathlib import Path
import subprocess


def get(schema, key):
    return subprocess.check_output(['gsettings', 'get', schema, key], text=True).strip()


def set_value(schema, key, value):
    subprocess.run(['gsettings', 'set', schema, key, value], check=True)

schema = 'org.gnome.Ptyxis'
profile_uuid = get(schema, 'default-profile-uuid').strip("'")
profile = f'org.gnome.Ptyxis.Profile:/org/gnome/Ptyxis/Profiles/{profile_uuid}/'
backup = Path.home() / '.config/setup-snapshots/ptyxis-before.json'
if not backup.exists():
    keys = {
        schema: ['font-name', 'use-system-font', 'cursor-shape', 'audible-bell'],
        profile: ['palette', 'cell-height-scale'],
    }
    backup.write_text(json.dumps({item: {key: get(item, key) for key in names} for item, names in keys.items()}, indent=2) + '\n')
    os.chmod(backup, 0o600)
    set_value(schema, 'use-system-font', 'false')
    set_value(schema, 'font-name', "'JetBrains Mono 12'")
    set_value(schema, 'cursor-shape', "'ibeam'")
    set_value(schema, 'audible-bell', 'false')
    set_value(profile, 'palette', "'Odyssey'")
    set_value(profile, 'cell-height-scale', '1.1')
PY
printf 'Terminal workflow applied. Run helpme for the menu or sysinfo for system details.\n'
