#!/usr/bin/env python3
"""Tests for border signals (config/desktop/border_signals.py): look-away timing, battery crossing, the signal
sequence (colour on, back to the theme colour) and quiet times. Nothing is drawn: hyprctl is replaced."""
import importlib.util, sys, tempfile, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("bs", Path(__file__).resolve().parents[1] / "config/desktop/border_signals.py")
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)


class T(unittest.TestCase):
    def test_lookaway(self):
        t = [0.0]; la = bs.LookAway(20, now=lambda: t[0])
        self.assertFalse(la.due(), "not active yet")
        la.active(); t[0] = 19 * 60; self.assertFalse(la.due())
        t[0] = 20 * 60; self.assertTrue(la.due())
        la.shown(); t[0] += 60; self.assertFalse(la.due(), "next one 20 min after the last")
        la.idle(); t[0] += 3600; self.assertFalse(la.due(), "a break resets it")
        la.active(); la.active(); t[0] += 20 * 60 - 1; self.assertFalse(la.due(), "repeated activity doesn't restart the clock")

    def test_battery_once_per_discharge(self):
        b = bs.Battery(15)
        self.assertFalse(b.check(40, True))
        self.assertTrue(b.check(15, True))
        self.assertFalse(b.check(12, True), "only once")
        self.assertFalse(b.check(12, False), "plugged in")
        self.assertTrue(b.check(14, True), "unplugged again below the line: warn again")
        self.assertFalse(b.check(16, True)); self.assertFalse(b.check(15, True), "hysteresis: no flapping at the line")

    def test_signal_returns_to_theme_colour(self):
        calls = []
        with tempfile.TemporaryDirectory() as d:
            colors = Path(d) / "colors.conf"; colors.write_text("general {\n    col.active_border = rgba(5b9cffdd)\n}\n")
            old = (bs.COLORS, bs.LOCK, bs.hyprctl, bs.quiet_now, bs.PENDING)
            bs.COLORS, bs.LOCK, bs.PENDING = colors, Path(d) / "lock", Path(d) / "pending"
            bs.hyprctl = lambda *a: calls.append(a) or ""; bs.quiet_now = lambda: False
            try:
                self.assertTrue(bs.show("lookaway", sleep=lambda s: None))
                kw = [a[2] for a in calls if a[0] == "keyword"]
                self.assertEqual(kw, ["rgba(b48cffff)", "rgba(5b9cffdd)"] * 2, "breathes twice, back to the theme colour")
                calls.clear(); bs.show("attention", address="0xabc", sleep=lambda s: None)
                self.assertEqual([a[-1] for a in calls], ["rgba(ffab4dff)"] * 2 + ["unset"] * 2, "only that window, then unset")
                self.assertTrue(all(a[2] == "address:0xabc" for a in calls))
                self.assertEqual(bs.PENDING.read_text(), "", "finished: nothing left to reset")
                bs.PENDING.write_text("0xdead\n"); calls.clear(); bs.reset_borders()
                self.assertIn(("dispatch", "setprop", "address:0xdead", "active_border_color", "unset"), calls,
                              "a restart clears a window left recoloured by a cut-off signal")
                self.assertFalse(bs.PENDING.exists())
                bs.quiet_now = lambda: True; calls.clear()
                self.assertFalse(bs.show("done", sleep=lambda s: None)); self.assertEqual(calls, [], "quiet: fullscreen or locked")
            finally:
                bs.COLORS, bs.LOCK, bs.hyprctl, bs.quiet_now, bs.PENDING = old

    def test_attention_rules(self):
        opened, last = {"0xnew": 100.0}, {}
        self.assertFalse(bs.attention_wanted("0xnew", opened, 100.5, last, None), "a window that is just opening")
        self.assertFalse(bs.attention_wanted("0xa", opened, 200.0, last, "0xa"), "the focused window")
        self.assertTrue(bs.attention_wanted("0xa", opened, 200.0, last, "0xb"))
        self.assertFalse(bs.attention_wanted("0xa", opened, 230.0, last, "0xb"), "once a minute per window")
        self.assertTrue(bs.attention_wanted("0xa", opened, 261.0, last, "0xb"))

    def test_settings_defaults_and_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            old = bs.SETTINGS; bs.SETTINGS = Path(d) / "s.json"
            try:
                self.assertEqual(bs.settings()["lookaway_minutes"], 20)
                bs.SETTINGS.write_text('{"lookaway_minutes": 30, "battery": false}')
                s = bs.settings(); self.assertEqual((s["lookaway_minutes"], s["battery"], s["attention"]), (30, False, True))
                bs.SETTINGS.write_text("{broken"); self.assertEqual(bs.settings(), bs.DEFAULTS)
            finally:
                bs.SETTINGS = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
