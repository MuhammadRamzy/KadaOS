"""Offline checks for the shortcuts cheatsheet grouping (no GTK)."""
import importlib.util, sys, unittest
from pathlib import Path

_argv = sys.argv; sys.argv = ['cheatsheet']
try:
    spec = importlib.util.spec_from_file_location('cheat', Path(__file__).resolve().parents[1] / 'config/desktop/cheatsheet.py')
    cheat = importlib.util.module_from_spec(spec); spec.loader.exec_module(cheat)
finally:
    sys.argv = _argv


class Cheatsheet(unittest.TestCase):
    def test_mods_and_keys(self):
        self.assertEqual(cheat.mods_from_mask(64 | 4 | 1), ['Super', 'Ctrl', 'Shift'])
        self.assertEqual(cheat.key_label('slash'), '/')
        self.assertEqual(cheat.key_label('e'), 'E')
        self.assertIsNone(cheat.key_label('mouse:272'))

    def test_categorize(self):
        self.assertEqual(cheat.categorize('App launcher', 'exec'), 'Apps & launch')
        self.assertEqual(cheat.categorize('Go to workspace 1', 'workspace'), 'Workspaces')
        self.assertEqual(cheat.categorize('Focus left', 'movefocus'), 'Windows')
        self.assertEqual(cheat.categorize('Screenshot area', 'exec'), 'Screenshots')
        self.assertEqual(cheat.categorize('Live dictation on/off', 'exec'), 'AI & voice')

    def test_build_groups_dedup_order_and_drops_mouse_and_blank(self):
        binds = [{'modmask': 64, 'key': 'E', 'description': 'File manager', 'dispatcher': 'exec'},
                 {'modmask': 64, 'key': 'E', 'description': 'File manager', 'dispatcher': 'exec'},   # duplicate
                 {'modmask': 64, 'key': '1', 'description': 'Go to workspace 1', 'dispatcher': 'workspace'},
                 {'modmask': 64, 'key': 'mouse:272', 'description': 'drag', 'dispatcher': 'movewindow'},  # pointer
                 {'modmask': 0, 'key': 'x', 'description': '', 'dispatcher': 'exec'}]                 # no description
        groups = dict(cheat.build_groups(binds))
        self.assertEqual(len(groups['Apps & launch']), 1)
        self.assertIn('Workspaces', groups)
        self.assertEqual(list(groups), [c for c in cheat.CATEGORIES if c in groups])


if __name__ == '__main__': unittest.main()
