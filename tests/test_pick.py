"""Offline checks for myos-pick item parsing, filtering, and layout choice (no GTK)."""
import importlib.util, sys, unittest
from pathlib import Path

_a = sys.argv; sys.argv = ['pick']
try:
    spec = importlib.util.spec_from_file_location('pick', Path(__file__).resolve().parents[1] / 'config/desktop/pick.py')
    pick = importlib.util.module_from_spec(spec); spec.loader.exec_module(pick)
finally:
    sys.argv = _a


class Pick(unittest.TestCase):
    def test_parse_plain_rich_and_blank(self):
        items = pick.parse_items(['Area\n', 'Window\tview-restore-symbolic\tpick a window', '', 'Full\ticon\t'])
        self.assertEqual(items[0], ('Area', None, None))
        self.assertEqual(items[1], ('Window', 'view-restore-symbolic', 'pick a window'))
        self.assertEqual(items[2], ('Full', 'icon', None))   # empty subtitle -> None
        self.assertEqual(len(items), 3)                      # blank line dropped

    def test_matches_all_fields_and_words(self):
        it = ('Convert image', 'image-x', 'to webp or png')
        self.assertTrue(pick.matches(it, 'webp'))
        self.assertTrue(pick.matches(it, 'convert png'))     # every word must hit
        self.assertFalse(pick.matches(it, 'convert zip'))
        self.assertTrue(pick.matches(it, ''))

    def test_layout_choice(self):
        self.assertEqual(pick.choose_layout(5, False, False), 'grid')
        self.assertEqual(pick.choose_layout(30, False, False), 'list')
        self.assertEqual(pick.choose_layout(30, True, False), 'grid')   # forced grid
        self.assertEqual(pick.choose_layout(3, False, True), 'list')    # forced list

    def test_grid_navigation_clamps_and_keeps_rows(self):
        # 7 tiles in 3 columns: rows [0 1 2] [3 4 5] [6]
        self.assertEqual(pick.nav(0, 'right', 7, 3), 1)
        self.assertEqual(pick.nav(2, 'right', 7, 3), 2)      # no jumping to the next row
        self.assertEqual(pick.nav(3, 'left', 7, 3), 3)
        self.assertEqual(pick.nav(1, 'down', 7, 3), 4)
        self.assertEqual(pick.nav(4, 'down', 7, 3), 6)       # clamps into the short last row
        self.assertEqual(pick.nav(1, 'up', 7, 3), 0)
        self.assertEqual(pick.nav(0, 'down', 5, 1), 1)       # list = one column
        self.assertEqual(pick.nav(0, 'down', 0, 3), 0)       # nothing visible


if __name__ == '__main__':
    unittest.main()
