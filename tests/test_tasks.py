#!/usr/bin/env python3
"""Tests for the agent task board (config/desktop/tasks.py) with a fake agent on a throwaway repo: worktree + branch,
leftover commit, review → merge, discard, refusals. No real agent or job is started."""
import importlib.util, os, shutil, subprocess, tempfile, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("tasks", Path(__file__).resolve().parents[1] / "config/desktop/tasks.py")
tk = importlib.util.module_from_spec(spec); spec.loader.exec_module(tk)
ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def git(cwd, *a): return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout


class Tasks(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="tasks-test-")); self.addCleanup(shutil.rmtree, self.t, True)
        self.old = {k: os.environ.get(k) for k in [*ENV, "TASKS_FAKE_AGENT"]}; os.environ.update(ENV)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in self.old.items()])
        tk.DIR, tk.TREES = self.t / "state", self.t / "trees"
        self.repo = self.t / "app"; self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main"); (self.repo / "a.txt").write_text("1\n"); git(self.repo, "add", "-A"); git(self.repo, "commit", "-qm", "init")
        self.agent = self.t / "agent.sh"

    def fake(self, body):
        self.agent.write_text("#!/bin/sh\n" + body); self.agent.chmod(0o755); os.environ["TASKS_FAKE_AGENT"] = str(self.agent)

    def test_run_review_merge(self):
        self.fake('echo "$1" | head -1; echo 2 >> a.txt\n')          # changes a file but doesn't commit: leftover gets committed
        t = tk.add(str(self.repo), "Add a second line", "codex")
        self.assertEqual((t["state"], t["base"]), ("queued", "main")); self.assertTrue(t["branch"].startswith("agent/codex-add-a-second-line-"))
        tk.start(t["id"], via_job=False)
        t = tk.load(t["id"])
        self.assertEqual((t["state"], t["commits"]), ("review", 1)); self.assertIn("1 file changed", t["stat"])
        self.assertIn("working alone", (tk.DIR / f"{t['id']}.log").read_text())
        self.assertEqual((self.repo / "a.txt").read_text(), "1\n", "your checkout is untouched until you merge")
        (self.repo / "a.txt").write_text("dirty\n")
        with self.assertRaises(ValueError): tk.merge(t["id"])                # uncommitted changes in the repo
        git(self.repo, "checkout", "-q", "--", "a.txt")
        tk.merge(t["id"])
        self.assertEqual((self.repo / "a.txt").read_text(), "1\n2\n"); self.assertEqual(tk.load(t["id"])["state"], "merged")
        self.assertFalse(Path(t["tree"]).exists())

    def test_no_changes_fails_and_discard(self):
        self.fake("exit 3\n")
        t = tk.add(str(self.repo), "Do nothing", "claude"); tk.start(t["id"], via_job=False)
        t = tk.load(t["id"]); self.assertEqual(t["state"], "failed"); self.assertIn("no changes (exit 3)", t["error"])
        tk.discard(t["id"])
        self.assertNotIn(t["branch"], git(self.repo, "branch")); self.assertFalse(Path(t["tree"]).exists())

    def test_refusals(self):
        with self.assertRaises(ValueError): tk.add(str(self.repo), "x", "agy")
        with self.assertRaises(ValueError): tk.add(str(self.repo), "   ", "claude")
        with self.assertRaises(ValueError): tk.add(str(self.t), "x", "claude")       # not a repo
        t = tk.add(str(self.repo), "x", "claude")
        with self.assertRaises(ValueError): tk.merge(t["id"])                         # still queued


if __name__ == "__main__":
    unittest.main(verbosity=2)
