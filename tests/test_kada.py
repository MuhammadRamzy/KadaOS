#!/usr/bin/env python3
"""Tests for the ./kada installer menu (dry runs only: nothing is installed, no password asked)."""
import re, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def kada(*args):
    return subprocess.run([str(ROOT / "kada"), *args], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)


def planned(*args):
    return re.findall(r"scripts/(\S+)", kada("--dry-run", *args).stdout)


class Kada(unittest.TestCase):
    def test_every_step_exists(self):
        for s in planned("--order", "sadhya") + planned("--items", "usbguard"):
            self.assertTrue((ROOT / "scripts" / f"{s}.sh").exists() or (ROOT / "scripts" / f"{s}.py").exists(), s)

    def test_dependencies_come_first_once(self):
        steps = planned("--items", "ai")
        self.assertEqual(steps[:2], ["phase1-base", "phase8-hyprland"], "base and the desktop before the AI layer")
        self.assertIn("phase3-docker", steps, "the private web search needs Docker")
        self.assertEqual(len(steps), len(set(steps)))

    def test_orders(self):
        self.assertEqual(planned("--order", "chaya"), ["phase1-base", "phase8-hyprland", "phase8b-hyprland-polish", "terminal-style"])
        self.assertNotIn("phase16-usbguard", planned("--order", "sadhya"), "USB guard needs you at the laptop: à la carte only")
        for o in ("chaya-kadi", "kattan", "porotta", "pazhampori", "omelette"):
            self.assertTrue(planned("--order", o), o)

    def test_bad_input(self):
        self.assertEqual(kada("--items", "nope").returncode, 2)
        self.assertEqual(kada("--order", "biryani").returncode, 2)
        self.assertIn("Full Sadhya", kada("--list").stdout)

    def test_bootstrap_is_the_menu(self):
        self.assertIn("Full Sadhya", subprocess.run([str(ROOT / "bootstrap.sh"), "--list"], capture_output=True, text=True).stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
