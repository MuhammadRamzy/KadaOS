#!/usr/bin/env python3
"""Tests for `profile` (config/desktop/profile.py): what each switch does, and that going back only undoes what the
profile itself changed. Pure planning; nothing is switched on the real laptop."""
import importlib.util, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("profile", Path(__file__).resolve().parents[1] / "config/desktop/profile.py")
prof = importlib.util.module_from_spec(spec); spec.loader.exec_module(prof)
prof.adapt_cfg = lambda: {"ac_profile": "balanced", "battery_profile": "power-saver", "ac_hz": 165, "battery_hz": 60}


class Plan(unittest.TestCase):
    def test_ai(self):
        self.assertEqual(prof.plan("ai", {"name": "auto"}, True), [("power", "performance"), ("hz", 165), ("model", -1)])

    def test_battery_unloads_and_slows_the_screen(self):
        self.assertEqual(prof.plan("battery", {"name": "auto"}, True), [("power", "power-saver"), ("hz", 60), ("model", 0)])

    def test_present_then_auto_undoes_only_its_own_changes(self):
        self.assertEqual(prof.plan("present", {"name": "auto"}, False), [("dnd", True), ("inhibit", None)])
        ours = {"name": "present", "set_dnd": True, "inhibit_pid": 4242}
        self.assertEqual(prof.plan("auto", ours, False),
                         [("release_inhibit", 4242), ("dnd", False), ("power", "power-saver"), ("hz", 60)])
        yours = {"name": "present", "inhibit_pid": 4242}            # DND was already on (you): leave it alone
        self.assertNotIn(("dnd", False), prof.plan("auto", yours, True))

    def test_leaving_ai_lets_the_model_unload_normally(self):
        self.assertIn(("model", "5m"), prof.plan("auto", {"name": "ai", "model": "warm"}, True))
        self.assertNotIn(("model", "5m"), prof.plan("ai", {"name": "ai", "model": "warm"}, True), "staying in AI keeps it warm")

    def test_names(self):
        with self.assertRaises(ValueError): prof.apply("turbo")
        self.assertEqual(set(prof.PROFILES), {"ai", "battery", "present", "auto"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
