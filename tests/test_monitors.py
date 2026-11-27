#!/usr/bin/env python3
"""Tests for `monitors` (config/desktop/monitors.py): set keys, snapshots and the hyprctl rules. hyprctl is never called."""
import importlib.util, tempfile, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("mon", Path(__file__).resolve().parents[1] / "config/desktop/monitors.py")
mon = importlib.util.module_from_spec(spec); spec.loader.exec_module(mon)

LAPTOP = {"name": "eDP-1", "description": "BOE 0x0CF1", "width": 1920, "height": 1200, "refreshRate": 165.0, "x": 0, "y": 0, "scale": 1.0, "transform": 0}
DELL = {"name": "HDMI-A-1", "description": "Dell U2723QE ABC123", "width": 3840, "height": 2160, "refreshRate": 60.0,
        "x": 1920, "y": 0, "scale": 1.5, "transform": 1}


class Monitors(unittest.TestCase):
    def test_key_ignores_port_and_order(self):
        moved = {**DELL, "name": "DP-2"}
        self.assertEqual(mon.key([LAPTOP, DELL]), mon.key([moved, LAPTOP]))
        self.assertNotEqual(mon.key([LAPTOP]), mon.key([LAPTOP, DELL]))

    def test_rules(self):
        rs = mon.rules(mon.snapshot([LAPTOP, DELL, {**LAPTOP, "description": "Old TV", "disabled": True}]))
        self.assertIn("desc:BOE 0x0CF1,1920x1200@165.00,0x0,1", rs)
        self.assertIn("desc:Dell U2723QE ABC123,3840x2160@60.00,1920x0,1.5,transform,1", rs)
        self.assertIn("desc:Old TV,disable", rs)

    def test_apply_only_when_saved(self):
        mon.hypr = lambda *a: self.calls.append(a) or ""
        self.calls = []
        self.assertEqual(mon.apply([LAPTOP, DELL], {}), []); self.assertEqual(self.calls, [])
        saved = {mon.key([LAPTOP, DELL]): mon.snapshot([LAPTOP, DELL])}
        self.assertEqual(len(mon.apply([LAPTOP, DELL], saved)), 2); self.assertEqual(self.calls[0][:2], ("keyword", "monitor"))

    def test_store_roundtrip(self):
        mon.STORE = Path(tempfile.mkdtemp()) / "p.json"
        self.assertEqual(mon.load(), {}); mon.store({"a": {}}); self.assertEqual(mon.load(), {"a": {}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
