#!/usr/bin/env python3
"""Tests for `projects` (config/desktop/projects.py) on throwaway git repos: discovery, changes, ahead/behind, summary, CI state.
GitHub is never called."""
import importlib.util, os, shutil, subprocess, tempfile, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("prj", Path(__file__).resolve().parents[1] / "config/desktop/projects.py")
prj = importlib.util.module_from_spec(spec); spec.loader.exec_module(prj)
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def git(cwd, *a): subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, env=ENV, stdin=subprocess.DEVNULL)


class Projects(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="prj-test-")); self.addCleanup(shutil.rmtree, self.t, True)
        prj.ROOTS, prj.EXTRA = [self.t / "Projects"], []
        origin = self.t / "origin.git"; git(self.t, "init", "-q", "--bare", str(origin))
        self.repo = self.t / "Projects/app"; self.repo.mkdir(parents=True)
        git(self.repo, "init", "-q", "-b", "main"); (self.repo / "a").write_text("1"); git(self.repo, "add", "a")
        git(self.repo, "commit", "-qm", "first"); git(self.repo, "remote", "add", "origin", str(origin)); git(self.repo, "push", "-qu", "origin", "main")
        (self.t / "Projects/not-a-repo").mkdir()

    def test_discovery_and_info(self):
        self.assertEqual([p.name for p in prj.repos()], ["app"])
        (self.repo / "b").write_text("x"); git(self.repo, "commit", "-qam", "second", "--allow-empty")
        i = prj.info(self.repo)
        self.assertEqual((i["branch"], i["changed"], i["ahead"], i["behind"], i["last_msg"]), ("main", 1, 1, 0, "second"))
        self.assertIn("1 changed", prj.summary(i)); self.assertIn("↑1 to push", prj.summary(i))

    def test_counts_and_ci(self):
        self.assertEqual(prj.parse_counts("2\t5\n"), (5, 2)); self.assertEqual(prj.parse_counts(""), (None, None))
        self.assertEqual(prj.ci_state({"status": "completed", "conclusion": "failure"}), "fail")
        self.assertEqual(prj.ci_state({"status": "in_progress"}), "running")
        self.assertEqual(prj.ci_state({"status": "completed", "conclusion": "success"}), "pass")
        self.assertIsNone(prj.ci_state(None))

    def test_scan_has_summary_and_open_rejects_quotes(self):
        self.assertTrue(prj.scan()[0]["summary"].startswith("main"))
        self.assertEqual(prj.main(["open", "/tmp/it's"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
