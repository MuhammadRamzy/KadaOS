#!/usr/bin/env python3
"""Tests for config/brand/greeter-settings.py (edits GDM's keyfile): our values win under GLib's own parser
even when the file already sets those keys, apply is idempotent, and undo restores the file byte for byte."""
import importlib.util, unittest
from pathlib import Path
import gi
from gi.repository import GLib

spec = importlib.util.spec_from_file_location("gs", Path(__file__).resolve().parents[1] / "config/brand/greeter-settings.py")
gs = importlib.util.module_from_spec(spec); spec.loader.exec_module(gs)

ORIG = """# GDM configuration
[org/gnome/login-screen]
logo='/usr/share/plymouth/ubuntu-logo.png'
disable-user-list=false

[org/gnome/desktop/interface]
# accent-color='blue'
accent-color='orange'
clock-format='12h'

[org/gnome/settings-daemon/plugins/power]
sleep-inactive-ac-timeout=0
"""


def value(text, group, key):
    k = GLib.KeyFile(); k.load_from_data(text, len(text.encode()), GLib.KeyFileFlags.KEEP_COMMENTS)
    return k.get_value(group, key)


class T(unittest.TestCase):
    def test_ours_win_and_undo_restores(self):
        a = gs.apply(ORIG)
        self.assertEqual(value(a, "org/gnome/desktop/interface", "accent-color"), "'blue'", "GLib takes ours")
        self.assertEqual(value(a, "org/gnome/login-screen", "logo"), "''")
        self.assertEqual(value(a, "org/gnome/desktop/interface", "color-scheme"), "'prefer-dark'")
        self.assertEqual(value(a, "org/gnome/desktop/interface", "clock-format"), "'12h'", "other keys untouched")
        self.assertEqual(value(a, "org/gnome/settings-daemon/plugins/power", "sleep-inactive-ac-timeout"), "0")
        self.assertEqual(gs.apply(a), a, "idempotent")
        self.assertEqual(gs.undo(a), ORIG, "undo restores byte for byte")

    def test_missing_sections_are_added_and_removed(self):
        a = gs.apply("[other]\nx=1\n")
        self.assertEqual(value(a, "org/gnome/login-screen", "logo"), "''")
        self.assertEqual(value(gs.undo(a), "other", "x"), "1")

    def test_old_unmarked_logo_is_cleaned(self):
        old = ORIG.replace("logo='/usr/share/plymouth/ubuntu-logo.png'\n", gs.OLD_LOGO + "\n")
        self.assertNotIn(gs.OLD_LOGO, gs.undo(old))


if __name__ == "__main__":
    unittest.main(verbosity=2)
