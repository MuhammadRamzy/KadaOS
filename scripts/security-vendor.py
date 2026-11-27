#!/usr/bin/env python3
"""Install pinned vendor releases into the user's security directory."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def install(name):
    manifest = json.loads((ROOT / 'config/security/releases.json').read_text())
    release = manifest[name]
    if platform.machine() != 'x86_64':
        raise ValueError('These release pins are for x86_64 only.')
    base = Path.home() / '.local/share/security'
    bindir = Path.home() / '.local/bin'
    base.mkdir(parents=True, exist_ok=True)
    bindir.mkdir(parents=True, exist_ok=True)
    final = base / (name + '-' + release['version'])
    if not final.exists():
        with tempfile.TemporaryDirectory(dir=base, prefix='.download-') as tmp:
            tmp = Path(tmp)
            archive = tmp / 'asset'
            with urllib.request.urlopen(release['url'], timeout=120) as response, archive.open('wb') as out:
                shutil.copyfileobj(response, out)
            with archive.open('rb') as downloaded:
                if hashlib.file_digest(downloaded, 'sha256').hexdigest() != release['sha256']:
                    raise ValueError('Release checksum mismatch; refusing installation.')
            unpack = tmp / 'unpacked'
            unpack.mkdir()
            if name == 'jadx':
                with zipfile.ZipFile(archive) as z:
                    for info in z.infolist():
                        dest = (unpack / info.filename).resolve()
                        if not dest.is_relative_to(unpack.resolve()):
                            raise ValueError('Unsafe archive member')
                    z.extractall(unpack)
                for binary in ('jadx', 'jadx-gui'):
                    (unpack / 'bin' / binary).chmod(0o755)
            elif name == 'enum4linux-ng':
                shutil.copy2(archive, unpack / 'enum4linux-ng.py')
                # Build at its permanent location; venv shebangs contain absolute paths.
            elif name == 'cutter':
                shutil.copy2(archive, unpack / 'cutter')
                (unpack / 'cutter').chmod(0o755)
            else:
                with tarfile.open(archive) as tar:
                    member = next((m for m in tar if m.name in (name, './' + name) and m.isfile()), None)
                    if member is None:
                        raise ValueError('Binary not found in release archive')
                    with tar.extractfile(member) as src, (unpack / name).open('wb') as out:
                        shutil.copyfileobj(src, out)
                (unpack / name).chmod(0o755)
            unpack.rename(final)
    if name == 'enum4linux-ng':
        if not (final / 'venv/bin/python').exists():
            subprocess.run(['uv', 'venv', str(final / 'venv')], check=True)
        subprocess.run(['uv', 'pip', 'install', '--python', str(final / 'venv/bin/python'),
                        'impacket==0.13.1', 'ldap3==2.9.1', 'PyYAML==6.0.3'], check=True)
        commands = {name: [str(final / 'venv/bin/python'), str(final / 'enum4linux-ng.py')]}
    elif name == 'jadx':
        commands = {n: [str(final / 'bin' / n)] for n in ('jadx', 'jadx-gui')}
    else:
        commands = {name: [str(final / name)]}
    for binary, argv in commands.items():
        target = bindir / binary
        content = '#!/bin/sh\nexec ' + shlex.join(argv) + ' "$@"\n'
        if target.exists() or target.is_symlink():
            if target.is_file() and target.read_text(errors='replace') == content:
                continue
            raise ValueError(f'{target} exists; refusing to replace it.')
        with tempfile.NamedTemporaryFile(mode='w', dir=bindir, delete=False) as out:
            out.write(content)
            temporary = Path(out.name)
        temporary.chmod(0o755)
        os.replace(temporary, target)
    print(f'Installed {name} {release["version"]}; SHA-256 matched repo pin.')

if __name__ == '__main__':
    try:
        install(sys.argv[1])
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
