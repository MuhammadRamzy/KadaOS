"""Secretary: notification sorting, inbox, digest, and quiet mode (DND only when we set it; digest when it ends)."""
import importlib.util, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Secretary(unittest.TestCase):
    def test_self_check(self):
        r = subprocess.run([sys.executable, str(ROOT / "config/ai/secretary.py"), "test"], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.stdout.strip(), "ok", r.stderr)


class QuietMode(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("sa", ROOT / "config/ai/system-adapt.py")
        self.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)
        self.dnd, self.calls = False, []
        m = self

        class R:
            def __init__(self, out=""): self.stdout = out

        def sh(*a, **k):
            m.calls.append(a)
            if a[:2] == ("swaync-client", "-D"): return R("true" if m.dnd else "false")
            if a[:2] == ("swaync-client", "-dn"): m.dnd = True
            if a[:2] == ("swaync-client", "-df"): m.dnd = False
            return R()
        self.m.sh = sh

    def test_on_then_off_with_digest(self):
        self.m.QUIET.update(fullscreen=False, call=True); self.m.reconcile()
        self.assertTrue(self.dnd)
        self.m.QUIET.update(call=False); self.m.reconcile()
        self.assertFalse(self.dnd)

    def test_respects_your_own_dnd(self):
        self.dnd = True                                  # you turned DND on yourself
        self.m.QUIET.update(fullscreen=True, call=False); self.m.reconcile()
        self.m.QUIET.update(fullscreen=False); self.m.reconcile()
        self.assertTrue(self.dnd, "must not switch off DND it didn't switch on")

    def test_you_switching_off_wins(self):
        self.m.QUIET.update(fullscreen=False, call=True); self.m.reconcile(); self.assertTrue(self.dnd)
        self.dnd = False; self.m.reconcile()             # you turned it off during the call
        self.m.reconcile(); self.m.reconcile()           # later checks while the call goes on
        self.assertFalse(self.dnd, "must not force it back on")
        self.m.QUIET.update(call=False); self.m.reconcile()
        self.m.QUIET.update(call=True); self.m.reconcile()   # a new call later: quiet again
        self.assertTrue(self.dnd)



class RefreshRate(unittest.TestCase):
    """system-adapt picks a refresh rate the panel really has (any laptop, not just a 165 Hz one)."""
    def setUp(self):
        spec = importlib.util.spec_from_file_location("sa2", ROOT / "config/ai/system-adapt.py")
        self.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)

    def test_best_hz(self):
        omen = ["1920x1200@165.00Hz", "1920x1200@60.00Hz"]
        self.assertEqual(self.m.best_hz(omen, 1920, 1200, True), 165)
        self.assertEqual(self.m.best_hz(omen, 1920, 1200, False), 60)
        plain = ["1920x1080@60.01Hz", "1280x720@60.00Hz"]
        self.assertEqual(self.m.best_hz(plain, 1920, 1080, True), 60, "a 60 Hz panel stays at 60")
        self.assertEqual(self.m.best_hz(["2560x1600@120.00Hz", "2560x1600@90.00Hz"], 2560, 1600, False), 90, "lowest >= 60")
        self.assertEqual(self.m.best_hz([], 1920, 1200, True), self.m.CFG["ac_hz"], "no mode list: the configured value")

if __name__ == "__main__":
    unittest.main()
