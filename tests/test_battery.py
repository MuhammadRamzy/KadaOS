#!/usr/bin/env python3
"""Tests for battery-health (config/desktop/battery.py) with fake /sys battery folders (energy- and charge-based),
the once-a-day sample, trend and projection. No real battery state is read or changed."""
import importlib.util, os, shutil, tempfile, time, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("bat", Path(__file__).resolve().parents[1] / "config/desktop/battery.py")
bat = importlib.util.module_from_spec(spec); spec.loader.exec_module(bat)


class Battery(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="bat-test-")); self.addCleanup(shutil.rmtree, self.t, True)
        bat.LOG = self.t / "battery.jsonl"

    def fake(self, **files):
        b = self.t / "sys/BAT0"; b.mkdir(parents=True, exist_ok=True)
        for k, v in {"type": "Battery", **files}.items(): (b / k).write_text(str(v))
        return b

    def test_energy_based(self):
        b = self.fake(energy_full=63000000, energy_full_design=70000000, energy_now=31500000, power_now=9000000,
                      cycle_count=210, capacity=50, status="Discharging")
        r = bat.read(b)
        self.assertEqual((r["health"], r["cycles"], r["percent"]), (90.0, 210, 50))
        self.assertAlmostEqual(r["power_w"], 9.0)

    def test_charge_based(self):
        b = self.fake(charge_full=4000000, charge_full_design=5000000, charge_now=2000000, current_now=1000000,
                      voltage_min_design=11400000, voltage_now=11400000, capacity=50, status="Charging")
        self.assertEqual(bat.read(b)["health"], 80.0)

    def test_missing_design_is_no_reading(self):
        self.assertIsNone(bat.read(self.fake(capacity=50)))

    def test_one_sample_a_day(self):
        r = {"health": 99.0, "cycles": 10, "full_wh": 69.3}
        day1 = time.mktime((2026, 1, 1, 12, 0, 0, 0, 0, -1))
        self.assertTrue(bat.sample(day1, r)); self.assertFalse(bat.sample(day1 + 3600, r), "same day: kept once")
        self.assertTrue(bat.sample(day1 + 86400, r)); self.assertEqual(len(bat.history()), 2)

    def test_trend_and_projection(self):
        h = [{"day": "2026-01-01", "health": 100.0, "cycles": 0}, {"day": "2026-12-31", "health": 96.0, "cycles": 200}]
        t = bat.trend(h)
        self.assertAlmostEqual(t["per_year"], 4.0, delta=0.1); self.assertAlmostEqual(t["per_100_cycles"], 2.0)
        self.assertAlmostEqual(bat.projection(96.0, t), 4.0, delta=0.2)
        self.assertIsNone(bat.trend(h[:1]), "one sample: no trend yet")
        self.assertEqual(bat.trend([h[0], {"day": "2026-01-10", "health": 99.0, "cycles": 5}])["per_year"], 0.0, "under 30 days: too early")
        self.assertIsNone(bat.projection(78.0, t), "already worn")
        self.assertEqual(bat.verdict(97), "Like new"); self.assertTrue(bat.verdict(70).startswith("Worn"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
