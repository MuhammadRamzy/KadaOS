"""Top-bar smart items: they stay empty until they matter, and always print valid JSON."""
import json, subprocess, sys, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "config/hypr/scripts/bar-status.py"


class BarStatus(unittest.TestCase):
    def test_next_event_rules(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "test"], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.stdout.strip(), "ok", r.stderr)

    def test_probes_print_json(self):
        for probe in ("system", "privacy"):
            r = subprocess.run([sys.executable, str(SCRIPT), probe], capture_output=True, text=True, timeout=20)
            d = json.loads(r.stdout)
            self.assertIn("class", d, probe)


class BarClock(unittest.TestCase):
    """Right click (toggle) flips short <-> long date and redraws at once; left click is only the calendar."""
    def test_toggle_redraws_immediately(self):
        import os, tempfile, time
        clock = Path(__file__).resolve().parents[1] / "config/hypr/scripts/bar-clock.sh"
        with tempfile.TemporaryDirectory() as rt:
            env = dict(os.environ, XDG_RUNTIME_DIR=rt)
            p = subprocess.Popen([str(clock)], env=env, stdout=subprocess.PIPE, text=True)
            try:
                first = json.loads(p.stdout.readline())
                self.assertEqual(first["class"], "short")
                time.sleep(0.2)
                subprocess.run([str(clock), "toggle"], env=env, check=True)
                t0 = time.time(); second = json.loads(p.stdout.readline())
                self.assertEqual(second["class"], "long")
                self.assertLess(time.time() - t0, 0.8)
                self.assertIn(str(time.localtime().tm_year), second["text"])
            finally:
                p.kill()

    def test_bar_wires_clicks(self):
        cfg = json.loads((Path(__file__).resolve().parents[1] / "config/waybar/config.jsonc").read_text())
        c = cfg["custom/clock"]
        self.assertIn("myos-panel calendar", c["on-click"])
        self.assertTrue(c["on-click-right"].endswith("bar-clock.sh toggle"))
        self.assertNotIn("format-alt", c)


class AgentNotify(unittest.TestCase):
    """agent-notify: summaries are plain one-liners and the session state follows prompt -> finished -> needs you."""
    NOTIFY = Path(__file__).resolve().parents[1] / "config/agents/bin/agent-notify"

    def test_self_check(self):
        r = subprocess.run([sys.executable, str(self.NOTIFY), "test"], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.stdout.strip(), "ok", r.stderr)

    def test_state_flow_without_popups(self):
        import os, tempfile
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, MYOS_AGENT_STATE=f"{d}/state.json", HOME=d, MYOS_NO_AI="1")   # no popup helper, no AI rewrite
            run = lambda ev, payload: subprocess.run([sys.executable, str(self.NOTIFY), "claude", ev], input=json.dumps(payload),
                                                     env=env, text=True, capture_output=True, timeout=20)
            base = {"session_id": "s", "cwd": "/w/KadaOS"}
            run("Prompt", base)
            st = lambda: json.loads(Path(f"{d}/state.json").read_text())["s"]
            self.assertEqual(st()["state"], "working")
            run("Stop", dict(base, last_assistant_message="## Done\nFixed the clock click so it opens the calendar."))
            self.assertIn(st()["state"], ("done", "seen"))
            self.assertTrue(st()["summary"].startswith("Done Fixed the clock"))
            run("Notification", dict(base, notification_type="idle_prompt", message="idle"))
            self.assertIn(st()["state"], ("done", "seen"))          # idle nag ignored
            run("Notification", dict(base, notification_type="permission_prompt", message="Needs permission to use Bash"))
            self.assertIn(st()["state"], ("needs", "seen"))
            self.assertEqual(st()["proj"], "KadaOS")


if __name__ == "__main__":
    unittest.main()
