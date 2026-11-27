#!/usr/bin/env python3
"""Install security menu and work layouts without replacing unrelated desktop config."""
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
BACKUP = HOME / '.local/state/setup/workbench-backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
BIND = 'bindd = $mod, H, Security lab, exec, ~/.local/bin/seclab menu'

def put(target, content, mode):
    if target.is_symlink():
        raise ValueError(f'Refusing to replace symlink: {target}')
    if target.exists() and target.read_bytes() == content and target.stat().st_mode & 0o777 == mode:
        return
    if target.exists() or target.is_symlink():
        backup = BACKUP / target.relative_to(HOME)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup, follow_symlinks=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
        out.write(content)
        temp = Path(out.name)
    temp.chmod(mode)
    os.replace(temp, target)


def main():
    conf = HOME / '.config/hypr/hyprland.conf'
    targets = [conf, HOME / '.local/bin/seclab']
    targets += [HOME / '.local/share/security-workbench' / n for n in ('seclab', 'tools.json')]
    targets += [HOME / '.config/hypr/scripts' / n for n in ('launcher.sh', 'flow-modi.sh', 'flow.py')]
    for target in targets:
        if target.is_symlink():
            raise SystemExit(f'Refusing to replace symlink: {target}; no files changed.')
    text = conf.read_text()
    bindings = [line.strip() for line in text.splitlines() if re.match(r'\s*bind\w*\s*=\s*(?:\$mod|SUPER)\s*,\s*H\s*,', line, re.I)]
    if bindings and bindings != [BIND]:
        raise SystemExit('Super+H is already assigned; no files changed.')
    # Source of truth is config/hypr/hyprland.conf. This migration adds only its new binding.
    # Canonical placement also makes the migration byte-identical on an unmodified setup.
    lines = [line for line in text.splitlines() if line.strip() != BIND]
    anchor = next((i for i, line in enumerate(lines) if line.startswith('bindd = $mod, K,')), None)
    if anchor is None:
        raise SystemExit('Agent keybind anchor missing; no files changed.')
    while lines and not lines[-1]:
        lines.pop()
    lines.insert(anchor, BIND)
    text = '\n'.join(lines) + '\n'
    for name in ('seclab', 'tools.json'):
        source = ROOT / 'config/security' / name
        put(HOME / '.local/share/security-workbench' / name, source.read_bytes(), 0o755 if name == 'seclab' else 0o644)
    put(HOME / '.local/bin/seclab', b'#!/bin/sh\nexec "$HOME/.local/share/security-workbench/seclab" "$@"\n', 0o755)
    for name in ('launcher.sh', 'flow-modi.sh', 'flow.py'):
        put(HOME / '.config/hypr/scripts' / name, (ROOT / 'config/hypr/scripts' / name).read_bytes(), 0o755)
    put(conf, text.encode(), conf.stat().st_mode & 0o777)
    print(f'Installed workbench. Changed-file backups: {BACKUP}')
    if os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        subprocess.run(['hyprctl', 'reload'], check=True)
        errors = subprocess.check_output(['hyprctl', 'configerrors'], text=True).strip()
        if errors:
            raise SystemExit('Hyprland reported configuration errors: ' + errors)

if __name__ == '__main__':
    main()
