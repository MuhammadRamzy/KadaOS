"""Deterministic scheduling regressions; no desktop or notification side effects."""
import copy
from datetime import datetime, timedelta
import importlib.util
import sys
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "config/desktop"
spec = importlib.util.spec_from_file_location("hydration_engine", SOURCE / "hydration_engine.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
Engine, settings, in_hours = module.Engine, module.settings, module.in_hours
NOW = datetime(2026, 11, 19, 12)
CONTEXT = dict(active_session=True, locked=False, idle=False, away=False,
               dnd=False, fullscreen=False, call=False, error="")


class Hydration(unittest.TestCase):
    def setUp(self):
        self.e = Engine()
        self.ctx = CONTEXT.copy()
        self.now = NOW
        self.step(0)

    def step(self, seconds=5, **context):
        self.ctx.update(context)
        self.now += timedelta(seconds=seconds)
        return self.e.tick(seconds, self.now, self.ctx, "boot:session")

    def advance(self, seconds, **context):
        alerts = 0
        for _ in range(seconds // 5):
            alerts += self.step(5, **context)
        return alerts

    def due(self):
        self.e.s.update(remaining=0, grace=0, due_wait=300)

    def test_active_interval_and_quiet_window(self):
        self.assertEqual(self.advance(45 * 60), 0)
        self.assertEqual(self.advance(5 * 60), 1)
        self.assertEqual(self.e.s["attempts"], 1)

    def test_idle_freezes_time(self):
        self.advance(100)
        before = self.e.s["remaining"]
        self.advance(500, idle=True)
        self.assertEqual(self.e.s["remaining"], before)

    def test_lock_freezes_and_closes_notification(self):
        self.due()
        self.assertTrue(self.step())
        before = self.e.s["remaining"]
        self.step(locked=True)
        self.assertFalse(self.e.s["notice"])
        self.assertEqual(self.e.s["remaining"], before)

    def test_dnd_counts_activity_but_never_alerts(self):
        self.e.s["remaining"] = 10
        self.assertEqual(self.advance(300, dnd=True), 0)
        self.assertEqual(self.e.s["remaining"], 0)
        self.assertFalse(self.step(dnd=False))
        self.assertEqual(self.advance(115), 0)
        self.assertEqual(self.advance(5), 1)

    def test_overlapping_suppression(self):
        self.due()
        self.assertEqual(self.advance(300, dnd=True, call=True, fullscreen=True), 0)
        self.assertEqual(self.advance(300, dnd=False), 0)
        self.assertEqual(self.advance(300, call=False), 0)
        self.assertEqual(self.advance(300, fullscreen=False), 1)

    def test_context_switches_can_be_disabled(self):
        self.e.cfg.update(calls=False, fullscreen=False)
        self.due()
        self.assertTrue(self.step(call=True, fullscreen=True))

    def test_missing_essential_signal_suppresses(self):
        self.due()
        self.assertEqual(self.advance(600, error="DND unavailable"), 0)
        self.assertIn("DND unavailable", self.e.status(self.now)["reason"])

    def test_snooze_is_active_time(self):
        self.e.action("snooze", self.now)
        self.advance(600, idle=True)
        self.assertEqual(self.e.s["remaining"], 600)
        self.assertEqual(self.advance(605, idle=False), 1)

    def test_unanswered_retry_then_backoff(self):
        self.due()
        self.assertTrue(self.step())
        self.assertEqual(self.e.s["remaining"], 900)
        self.assertEqual(self.advance(900), 1)
        self.assertEqual(self.e.s["remaining"], 3600)
        self.assertEqual(self.e.s["history"], [])
        self.assertEqual(self.advance(3600), 1)

    def test_manual_log_resets_backoff(self):
        self.e.s["attempts"] = 5
        self.e.action("drank", self.now)
        self.assertEqual(self.e.s["attempts"], 0)
        self.assertEqual(self.e.s["remaining"], 2700)
        self.assertEqual(self.e.status(self.now)["today"], 1)

    def test_undo_restores_prior_progress(self):
        self.advance(300)
        before = self.e.s["remaining"]
        self.e.action("drank", self.now)
        self.e.action("undo", self.now)
        self.assertEqual(self.e.s["remaining"], before)
        self.assertEqual(self.e.s["history"], [])

    def test_pause_survives_restart_until_next_start(self):
        self.e.action("pause", self.now)
        self.e = Engine(state=copy.deepcopy(self.e.s))
        self.assertEqual(self.advance(600), 0)
        self.now = NOW.replace(day=20, hour=8)
        self.step()
        self.assertTrue(self.e.s["paused_until"])
        self.now = NOW.replace(day=20, hour=9)
        self.step()
        self.assertIsNone(self.e.s["paused_until"])

    def test_pause_before_start_resumes_same_day(self):
        self.e.action("pause", NOW.replace(hour=1))
        self.assertEqual(self.e.s["paused_until"], "2026-11-19T09:00:00")

    def test_resume_starts_fresh(self):
        self.e.action("pause", self.now)
        self.e.action("resume", self.now)
        self.assertFalse(self.e.s["paused_until"])
        self.assertEqual(self.e.s["remaining"], 2700)

    def test_undo_cannot_cancel_a_later_pause_or_snooze(self):
        for action in ("pause", "snooze", "resume"):
            self.e.action("drank", self.now)
            self.e.action(action, self.now)
            before = copy.deepcopy(self.e.s)
            self.e.action("undo", self.now)
            self.assertEqual(self.e.s, before)

    def test_long_absence_resets_without_logging(self):
        self.due()
        self.step(idle=True, away=True)
        self.step(idle=False, away=False)
        self.assertEqual(self.e.s["remaining"], 2695)
        self.assertEqual(self.e.s["history"], [])

    def test_large_sampling_gap_does_not_count(self):
        before = self.e.s["remaining"]
        self.step(3600)
        self.assertEqual(self.e.s["remaining"], before)
        self.assertEqual(self.e.s["grace"], 120)

    def test_restart_preserves_progress_and_excludes_downtime(self):
        self.advance(600)
        before = self.e.s["remaining"]
        self.e = Engine(state=copy.deepcopy(self.e.s))
        self.step(3600)
        self.assertEqual(self.e.s["remaining"], before)

    def test_new_session_resets_progress(self):
        self.advance(600)
        self.e.tick(0, self.now, self.ctx, "new-boot:new-session")
        self.assertEqual(self.e.s["remaining"], 2700)

    def test_stale_and_duplicate_notification_actions(self):
        self.due()
        self.step()
        token = self.e.s["generation"]
        self.assertTrue(self.e.action("drank", self.now, token))
        self.assertFalse(self.e.action("drank", self.now, token))
        self.assertEqual(len(self.e.s["history"]), 1)

    def test_old_action_cannot_override_pause(self):
        self.due()
        self.step()
        token = self.e.s["generation"]
        self.e.action("pause", self.now)
        self.assertFalse(self.e.action("snooze", self.now, token))
        self.assertTrue(self.e.s["paused_until"])

    def test_outside_hours_never_delivers_but_manual_logging_works(self):
        self.now = NOW.replace(hour=23)
        self.due()
        self.assertFalse(self.step())
        self.e.action("drank", self.now)
        self.assertEqual(self.e.status(self.now)["today"], 1)

    def test_midnight_hours_and_clock_changes(self):
        cfg = settings(dict(start="22:00", end="06:00"))
        self.assertTrue(in_hours(NOW.replace(hour=23), cfg))
        self.assertTrue(in_hours(NOW.replace(hour=3), cfg))
        self.assertFalse(in_hours(NOW, cfg))
        before = self.e.s["remaining"]
        self.now -= timedelta(hours=1)
        self.step()
        self.assertEqual(self.e.s["remaining"], before - 5)

    def test_history_retention_clear_and_empty_status(self):
        self.e.s["history"] = [self.now.timestamp() - 31 * 86400, self.now.timestamp()]
        self.step()
        self.assertEqual(len(self.e.s["history"]), 1)
        self.e.action("clear", self.now)
        self.assertIsNone(self.e.status(self.now)["last"])
        self.assertFalse(self.e.status(self.now)["undo"])

    def test_invalid_settings_and_corrupt_state(self):
        for cfg in ({"interval": 0}, {"idle": True}, {"start": "25:00"},
                    {"start": "9:00"}, {"start": "22:00", "end": "22:00"},
                    {"calls": "false"}, {"unknown": 1}):
            with self.assertRaises(ValueError, msg=cfg):
                settings(cfg)
        for state in ({"remaining": -5}, {"remaining": float("nan")},
                      {"history": ["bad"]}, {"paused_until": "bad"}):
            with self.assertRaises(ValueError, msg=state):
                Engine(state=state)


if __name__ == "__main__":
    unittest.main()
