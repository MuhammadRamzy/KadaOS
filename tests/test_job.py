#!/usr/bin/env python3
"""Tests for `job` (config/desktop/job.py): sizes, options, outcome messages, and real runs as transient systemd user
services (memory cap, out-of-memory stop, stop). Uses a temp state folder and no notifications."""
import importlib.util, json, os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "config/desktop/job.py"
spec = importlib.util.spec_from_file_location("job", SRC); job = importlib.util.module_from_spec(spec); spec.loader.exec_module(job)


class Pure(unittest.TestCase):
    def test_sizes_and_args(self):
        self.assertEqual(job.parse_size("6G"), 6 << 30); self.assertEqual(job.parse_size("512M"), 512 << 20)
        self.assertAlmostEqual(job.parse_size("50%"), job.total_mem() // 2, delta=1)
        with self.assertRaises(ValueError): job.parse_size("lots")
        self.assertEqual(job.limits(None), int(job.total_mem() * 0.70))
        o = job.parse_args(["--mem", "2G", "--plugged", "--", "make", "-j8"])
        self.assertEqual((o["mem"], o["plugged"], o["cmd"]), ("2G", True, ["make", "-j8"]))
        with self.assertRaises(ValueError): job.parse_args(["--bogus", "x"])

    def test_outcomes(self):
        s = {"cmd": "make -j8", "label": "make -j8", "started": time.time() - 75, "max": 6 << 30}
        self.assertEqual(job.outcome(s, "success", "0"), ("✓ make -j8 finished (1m 15s)", False))
        self.assertTrue(job.outcome(s, "oom-kill", "9")[1], "out of memory is urgent")
        self.assertIn("6.0G", job.outcome(s, "oom-kill", "9")[0])
        self.assertIn("exit 2", job.outcome(s, "exit-code", "2")[0])
        self.assertEqual(job.outcome({**s, "stopped": True}, "signal", "TERM"), ("", False), "you stopped it: quiet")


@unittest.skipUnless(shutil.which("systemd-run") and subprocess.run(["systemctl", "--user", "is-system-running"],
                     capture_output=True).returncode in (0, 1), "no systemd user manager")
class Real(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="job-test-")); self.addCleanup(shutil.rmtree, self.d, True)
        self.env = dict(os.environ, JOB_DIR=str(self.d), JOB_QUIET="1")

    def run_job(self, *a):
        return subprocess.run([sys.executable, str(SRC), *a], env=self.env, capture_output=True, text=True, cwd=self.d, timeout=30)

    def wait(self, jid, secs=20):
        for _ in range(secs * 10):
            s = json.loads((self.d / f"{jid}.json").read_text())
            if "result" in s: return s
            time.sleep(0.1)
        self.fail(f"{jid} never finished")

    def jid(self, r): return r.stdout.split("job ")[1].split()[0]

    def test_runs_in_background_with_a_cap(self):
        r = self.run_job("--mem", "200M", "--", "echo out; pwd; exit 3")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.wait(self.jid(r))
        self.assertEqual((s["result"], s["status"]), ("exit-code", "3"))
        self.assertEqual((self.d / f"{s['id']}.log").read_text().split(), ["out", str(self.d)], "runs where you started it")

    def test_runaway_memory_is_stopped_not_frozen(self):
        r = self.run_job("--mem", "100M", "--", sys.executable + " -c 'b=bytearray(400*1024*1024)'")
        self.assertEqual(self.wait(self.jid(r), 15)["result"], "oom-kill")

    def test_unbalanced_quote_is_bashs_problem_not_a_crash(self):
        r = self.run_job("--", "echo 'oops")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.wait(self.jid(r))["result"], "exit-code")

    def test_prune_keeps_newest(self):
        for i in range(5): (self.d / f"0101-00000{i}.json").write_text('{"result": "success"}'); (self.d / f"0101-00000{i}.log").write_text("x")
        old = job.DIR; job.DIR = self.d
        try: job.prune(keep=2)
        finally: job.DIR = old
        self.assertEqual(len(list(self.d.glob("*.json"))), 2); self.assertEqual(len(list(self.d.glob("*.log"))), 2)

    def test_stop(self):
        r = self.run_job("--", "sleep 60"); jid = self.jid(r); time.sleep(1)
        self.assertEqual(self.run_job("stop", jid).returncode, 0)
        s = self.wait(jid)
        self.assertTrue(s["stopped"]); self.assertEqual(job.outcome(s, s["result"], s["status"])[0], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
