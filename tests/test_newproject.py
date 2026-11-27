#!/usr/bin/env python3
"""Tests for `new-project` (config/desktop/newproject.py) in a temp folder: files per language, ROS extras, git, no overwrite."""
import importlib.util, shutil, subprocess, tempfile, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("np", Path(__file__).resolve().parents[1] / "config/desktop/newproject.py")
np_ = importlib.util.module_from_spec(spec); spec.loader.exec_module(np_)


class NewProject(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="np-test-")); self.addCleanup(shutil.rmtree, self.t, True)

    def test_files_per_language(self):
        f = np_.files("x", "node", False)
        self.assertIn('node = "lts"', f["mise.toml"]); self.assertIn("node_modules/", f[".gitignore"])
        self.assertIn(".env", f[".gitignore"].splitlines()); self.assertNotIn("distrobox.ini", f)
        self.assertNotIn("mise.toml", np_.files("x", "none", False))
        r = np_.files("x", "python", True)
        self.assertIn("source .venv/bin/activate", r[".envrc"]); self.assertIn("/opt/ros/lyrical/setup.bash", r[".envrc"])
        self.assertIn("[x-ros]", r["distrobox.ini"]); self.assertIn("install/", r[".gitignore"])

    def test_create_commits_and_never_overwrites(self):
        d = np_.create("demo", "go", base=self.t)
        self.assertTrue((d / "AGENTS.md").exists()); self.assertEqual((d / "CLAUDE.md").read_text(), "Read AGENTS.md and follow it.\n")
        log = subprocess.run(["git", "log", "--oneline"], cwd=d, capture_output=True, text=True).stdout
        self.assertIn("Start the project", log)
        with self.assertRaises(ValueError): np_.create("demo", base=self.t)
        with self.assertRaises(ValueError): np_.create("../evil", base=self.t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
