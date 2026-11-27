#!/usr/bin/env python3
"""Bounded app layouts; natural language is data, never a shell command."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

APPS = {
    'chrome': (['google-chrome-stable', '--new-window'], r'(?i)google-chrome.*'),
    'firefox': (['firefox', '--new-window'], r'(?i)firefox'),
    'code': (['code', '--new-window'], r'(?i)code'),
    'obsidian': (['obsidian', 'obsidian://open?path=' + str(Path.home() / 'DocsVault')], r'(?i)obsidian'),
    'files': (['nautilus', '--new-window'], r'(?i)org.gnome.nautilus'),
    'slack': (['slack'], r'(?i)slack'),
    'terminal': (['ptyxis', '--new-window'], r'(?i)org.gnome.ptyxis'),
    'btop': (['kitty', '--class', 'flow-btop', '-e', 'btop'], r'flow-btop'),
    'seclab': (['kitty', '--class', 'flow-seclab', '--hold', '-e', str(Path.home() / '.local/bin/seclab'), 'list'], r'flow-seclab'),
    'wifi': (['kitty', '--class', 'flow-wifi', '--hold', '-e', str(Path.home() / '.local/bin/seclab'), 'wifi'], r'flow-wifi'),
}
PROFILES = {'Coding': ['code', 'terminal', 'terminal'],
            'Web dev': ['chrome', 'code', 'terminal'],
            'Research': ['chrome', 'files', 'terminal'],
            'Security lab': ['chrome', 'seclab', 'terminal'],
            'Wireless': ['wifi', 'terminal', 'terminal']}
ALIASES = {'google chrome': 'chrome', 'browser': 'chrome', 'chrome': 'chrome',
           'firefox': 'firefox', 'vs code': 'code', 'vscode': 'code', 'editor': 'code',
           'code': 'code', 'obsidian': 'obsidian', 'notes': 'obsidian',
           'file manager': 'files', 'files': 'files', 'nautilus': 'files',
           'slack': 'slack', 'terminals': 'terminal', 'terminal': 'terminal',
           'ptyxis': 'terminal', 'btop': 'btop', 'seclab': 'seclab',
           'wifi': 'wifi', 'wireless': 'wifi'}
COUNTS = {'a': 1, 'an': 1, 'one': 1, 'two': 2, 'a couple of': 2,
          'a couple': 2, 'couple of': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}

def validate(apps):
    if not isinstance(apps, list) or not 1 <= len(apps) <= 6:
        raise ValueError('Choose between one and six windows.')
    if any(not isinstance(x, str) or x not in APPS for x in apps):
        raise ValueError('Unknown app in layout.')
    return sorted(apps, key=lambda x: x in ('terminal', 'btop', 'seclab', 'wifi'))

def parse(text):
    text = text.strip()
    if text.removeprefix('▶ Start: ') in PROFILES:
        return validate(PROFILES[text.removeprefix('▶ Start: ')].copy())
    aliases = '|'.join(re.escape(x) for x in sorted(ALIASES, key=len, reverse=True))
    counts = '|'.join(re.escape(x) for x in sorted(COUNTS, key=len, reverse=True))
    pattern = rf'(?<!\w)(?:(?P<count>\d+|{counts})\s+)?(?P<app>{aliases})(?!\w)'
    apps, end = [], 0
    filler = re.compile(r'^(?:\s|,|\+|\band\b|\bwith\b|\bopen\b|\bstart\b|\blaunch\b|\bplease\b)*$', re.I)
    for match in re.finditer(pattern, text, re.I):
        if not filler.fullmatch(text[end:match.start()]):
            raise ValueError('Unrecognized layout text; use app names and counts.')
        count = (match['count'] or 'one').lower()
        count = int(count) if count.isdigit() else COUNTS[count]
        if not 1 <= count <= 6:
            raise ValueError('Each app count must be between one and six.')
        apps.extend([ALIASES[match['app'].lower()]] * count)
        end = match.end()
    if not filler.fullmatch(text[end:]):
        raise ValueError('Unrecognized layout text; use app names and counts.')
    return validate(apps)

def normalize(text):
    prompt = ('Convert the request to a JSON array of app names only. Allowed: '
              + ', '.join(APPS) + '. Maximum six windows. Do not invent apps. '
              'If unsupported return []. Request: ' + text)
    result = subprocess.run(['fai', 'ask', '--', prompt], capture_output=True, text=True,
                            check=True, timeout=45)
    answer = result.stdout.strip()
    fence = re.fullmatch(r'```(?:json)?\s*(\[.*\])\s*```', answer, re.S)
    if fence:
        answer = fence[1]
    return validate(json.loads(answer))

def ctl(*args, json_result=False):
    out = subprocess.check_output(['hyprctl', *(['-j'] if json_result else []), *args], text=True, timeout=5)
    if json_result:
        return json.loads(out)
    if out.strip() != 'ok':
        raise RuntimeError(out.strip())

def launch(apps):
    for app in apps:
        if not shutil.which(APPS[app][0][0]):
            raise ValueError(f'{app} is not installed.')
        if app in ('btop', 'seclab', 'wifi') and not shutil.which(str(Path.home() / '.local/bin/seclab') if app in ('seclab', 'wifi') else app):
            raise ValueError(f'{app} is not installed.')
    if ctl('getoption', 'general:layout', json_result=True)['str'] != 'dwindle':
        raise ValueError('Work layouts currently require the dwindle layout.')
    existing = ctl('clients', json_result=True)
    for app in set(apps) & {'obsidian', 'slack'}:
        if any(re.fullmatch(APPS[app][1], c['class']) for c in existing):
            raise ValueError(f'{app} is already open and may reuse its window. Open it with the regular app launcher.')
    # Move to an empty workspace, then launch everything onto it; dwindle tiles the windows as they appear.
    # Launching all up front (instead of waiting for each window) is what makes this reliable: a slow
    # cold-starting app like VS Code no longer blocks or cancels the rest of the layout.
    ctl('dispatch', 'workspace', 'empty')
    workspace = ctl('activeworkspace', json_result=True)['id']
    # Open the slower apps first so they have a head start while the fast terminals follow.
    order = sorted(apps, key=lambda a: a not in ('code', 'obsidian', 'slack', 'chrome', 'firefox'))
    for i, app in enumerate(order):
        command, _cls = APPS[app]
        ctl('dispatch', 'exec', f'[workspace {workspace} silent] ' + shlex.join(command))
        if i < len(order) - 1:
            time.sleep(0.6)   # stagger so dwindle tiles them in a stable order
    subprocess.run(['notify-send', '-t', '3000', 'Work layout',
                    f"Opening {len(apps)} window(s) on this workspace…"], check=False)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--ai', action='store_true', help='Allow local AI normalization on parser failure')
    parser.add_argument('request', nargs='+')
    args = parser.parse_args()
    text = ' '.join(args.request)
    try:
        try:
            apps = parse(text)
        except ValueError:
            if not args.ai:
                raise
            apps = normalize(text)
            if args.dry_run:
                print(json.dumps(apps))
                return
            # Model interpretation is displayed for approval before opening apps.
            choice = subprocess.run(['rofi', '-dmenu', '-p', 'Open interpreted layout?', '-no-custom'],
                                    input='Open: ' + ', '.join(apps) + '\nCancel\n', text=True,
                                    capture_output=True, check=False)
            if choice.returncode or not choice.stdout.startswith('Open: '):
                return
        if args.dry_run:
            print(json.dumps(apps))
            return
        runtime = Path(os.environ['XDG_RUNTIME_DIR'])
        with (runtime / 'myos-flow.lock').open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('A layout is already opening.') from None
            launch(apps)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f'Layout: {error}', file=sys.stderr)
        subprocess.run(['notify-send', 'Work layout', str(error)], check=False)
        sys.exit(1)

if __name__ == '__main__':
    main()
