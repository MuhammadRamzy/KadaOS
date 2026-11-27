import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, str(ROOT / path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

flow = load('flow', 'config/hypr/scripts/flow.py')
seclab = load('seclab', 'config/security/seclab')
installer = load('installer', 'scripts/install-workbench.py')

class ParserTests(unittest.TestCase):
    def test_counts_aliases_and_order(self):
        self.assertEqual(flow.parse('open 2 terminals and vscode with chrome'), ['code', 'chrome', 'terminal', 'terminal'])
        self.assertEqual(flow.parse('chrome and a couple of terminals'), ['chrome', 'terminal', 'terminal'])
        self.assertEqual(flow.parse('terminal and terminal'), ['terminal', 'terminal'])

    def test_overlap(self):
        self.assertEqual(flow.parse('vscode and vs code'), ['code', 'code'])

    def test_reject_partial_or_shell_input(self):
        for text in ('chrome and spotify', 'chrome; touch /tmp/pwn', '$(chrome)',
                     '0 terminals', '7 terminals', '-2 terminals', '1.5 terminals',
                     'chrome and 6 terminals', '', 'please', 'decode', 'chrome without terminal'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                flow.parse(text)

    def test_profile_labels_do_not_match_app_search(self):
        for label in flow.PROFILES:
            for app in ('chrome', 'code', 'terminal', 'obsidian', 'firefox', 'files', 'btop', 'slack'):
                self.assertNotIn(app, ('▶ Start: ' + label).lower())
            self.assertTrue(flow.parse('▶ Start: ' + label))

    def test_ai_untrusted_json(self):
        for output in ('["chrome; id"]', '["chrome", {}]', '"chrome"', '[]',
                       '["terminal"]'[:-1], json.dumps(['terminal'] * 7)):
            with patch.object(flow.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output)), self.assertRaises(ValueError):
                flow.normalize('arbitrary request')

    def test_ai_json_fence(self):
        output = '```json\n["chrome", "terminal"]\n```'
        with patch.object(flow.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output)):
            self.assertEqual(flow.normalize('browser and shell'), ['chrome', 'terminal'])

class InstallerTests(unittest.TestCase):
    def run_in_home(self, callback):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            conf = home / '.config/hypr/hyprland.conf'
            conf.parent.mkdir(parents=True)
            conf.write_text('bindd = $mod, K, Agents, exec, agent-menu\n')
            with patch.object(installer, 'HOME', home), patch.object(installer, 'BACKUP', home / 'backups'), patch.dict(installer.os.environ, {'HYPRLAND_INSTANCE_SIGNATURE': ''}):
                callback(home, conf)

    def test_install_is_idempotent_and_preserves_config(self):
        def check(home, conf):
            installer.main()
            self.assertIn('bindd = $mod, K, Agents, exec, agent-menu', conf.read_text())
            before = {str(p): p.stat().st_mtime_ns for p in home.rglob('*') if p.is_file()}
            installer.main()
            self.assertEqual(before, {str(p): p.stat().st_mtime_ns for p in home.rglob('*') if p.is_file()})
            self.assertEqual(conf.read_text().count(installer.BIND), 1)
        self.run_in_home(check)

    def test_conflict_makes_no_changes(self):
        def check(home, conf):
            conf.write_text(conf.read_text() + 'bindd = $mod, H, Other app, exec, app\n')
            with self.assertRaises(SystemExit): installer.main()
            self.assertFalse((home / '.local').exists())
        self.run_in_home(check)

    def test_symlink_makes_no_changes(self):
        def check(home, conf):
            target = home / 'real.conf'
            conf.rename(target)
            conf.symlink_to(target)
            with self.assertRaises(SystemExit): installer.main()
            self.assertTrue(conf.is_symlink())
            self.assertFalse((home / '.local').exists())
        self.run_in_home(check)

class LaunchTests(unittest.TestCase):
    def test_missing_app_does_not_change_workspace(self):
        with patch.object(flow.shutil, 'which', return_value=None), patch.object(flow, 'ctl') as ctl:
            with self.assertRaises(ValueError): flow.launch(['chrome'])
            ctl.assert_not_called()

    def test_requires_dwindle_layout(self):
        def ctl(*args, **kwargs):
            if args == ('getoption', 'general:layout'): return {'str': 'master'}
        with patch.object(flow.shutil, 'which', return_value='/bin/mock'), patch.object(flow, 'ctl', side_effect=ctl):
            with self.assertRaises(ValueError): flow.launch(['terminal', 'terminal'])

    def test_launches_all_apps_on_empty_workspace_best_effort(self):
        # New model: go to an empty workspace, fire every app with [workspace N silent]; dwindle tiles them.
        # A slow/absent window must NOT abort the rest, so there is no per-window wait or cancel.
        def ctl(*args, **kwargs):
            if args == ('getoption', 'general:layout'): return {'str': 'dwindle'}
            if args == ('activeworkspace',): return {'id': 4}
            if args == ('clients',): return []
        with patch.object(flow.shutil, 'which', return_value='/bin/mock'), \
             patch.object(flow, 'ctl', side_effect=ctl) as mock, \
             patch.object(flow.time, 'sleep'), patch.object(flow.subprocess, 'run'):
            flow.launch(['code', 'terminal', 'terminal'])
            calls = [c.args for c in mock.call_args_list]
            self.assertIn(('dispatch', 'workspace', 'empty'), calls)
            execs = [c for c in calls if c[:2] == ('dispatch', 'exec') and '[workspace 4 silent]' in c[2]]
            self.assertEqual(len(execs), 3)
            # slower apps (code) are launched before the fast terminals
            self.assertIn('code', execs[0][2])

class SecurityTests(unittest.TestCase):
    def test_explicit_args_are_not_shell(self):
        with patch.object(seclab.os, 'execvp') as execute:
            seclab.main(['nmap', '--help', '; touch /tmp/pwn'])
            execute.assert_called_once_with('nmap', ['nmap', '--help', '; touch /tmp/pwn'])

    def test_unknown_tool_rejected(self):
        with self.assertRaises(ValueError): seclab.main(['sh', '-c', 'id'])

    def test_catalogue_unique(self):
        self.assertEqual(len(seclab.BY_NAME), len(seclab.TOOLS))

    def test_scope_matching(self):
        scope = ['10.0.0.0/24', '192.168.1.5', 'lab.example.com']
        ok = ['10.0.0.7', '10.0.0.0/25', '192.168.1.5', 'lab.example.com', 'api.lab.example.com',
              'http://10.0.0.9:8080/login', 'https://www.lab.example.com/']
        bad = ['10.0.1.1', '10.0.0.0/16', '192.168.1.6', 'example.com', 'evillab.example.com',
               'lab.example.com.evil.net', 'http://8.8.8.8/', '', 'http://']
        for t in ok: self.assertTrue(seclab.in_scope(t, scope), t)
        for t in bad: self.assertFalse(seclab.in_scope(t, scope), t)

    def test_engagement_run_refuses_out_of_scope_and_records(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.object(seclab, 'ENG_ROOT', Path(d) / 'eng'), patch.object(seclab, 'ACTIVE', Path(d) / 'state/active'):
            eng = seclab.new_engagement('home lab')
            self.assertEqual(seclab.active(), eng)
            (eng / 'scope.txt').write_text('# comment\n127.0.0.1\n')
            with self.assertRaises(ValueError): seclab.run_recipe('nmap-quick', '127.0.0.2')
            with self.assertRaises(ValueError): seclab.run_recipe('rm-rf', '127.0.0.1')
            with patch.object(seclab.shutil, 'which', return_value='/bin/echo'), \
                 patch.object(seclab, 'build', return_value=['echo', 'scanned']):
                self.assertEqual(seclab.run_recipe('nmap-quick', '127.0.0.1'), 0)
            saved = list((eng / 'scans').glob('*.txt'))
            self.assertEqual(saved[0].read_text(), 'scanned\n')
            self.assertIn('`nmap-quick` on `127.0.0.1` → exit 0', (eng / 'log.md').read_text())

    def test_recipe_argv_has_no_shell_and_maps_urls(self):
        argv = seclab.build('web-dirs', 'http://10.0.0.5:8080/', '/x')
        self.assertEqual(argv[:4], ['gobuster', 'dir', '-u', 'http://10.0.0.5:8080/'])
        self.assertEqual(seclab.build('nmap-quick', 'https://lab.example.com/a', '/o')[3], 'lab.example.com')
        self.assertEqual(seclab.build('web-nikto', '10.0.0.5', '/o')[-1], 'http://10.0.0.5')

if __name__ == '__main__':
    unittest.main()
