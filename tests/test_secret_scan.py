#!/usr/bin/env python3
"""Tests for the leak scan (config/git/secret-scan.py) and the global hook dispatcher (config/git/hooks/dispatch).
Fake keys are built by concatenation so this file doesn't trip the scan. Uses a private GIT_CONFIG_GLOBAL: the real
git config is never read or changed."""
import importlib.util, os, shutil, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ss", ROOT / "config/git/secret-scan.py")
ss = importlib.util.module_from_spec(spec); spec.loader.exec_module(ss)
AWS = "AKIA" + "Q3EXAMPLEZZ7KD2P"          # 16 chars after AKIA
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


class Scan(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(ss.scan_text(f"key = '{AWS}'", "f")[0][2], "AWS access key")
        self.assertEqual(ss.scan_text(f"token: {GH}", "f")[0][2], "GitHub token")
        self.assertEqual(ss.scan_text("-----BEGIN OPENSSH " + "PRIVATE KEY-----", "f")[0][2], "private key")
        self.assertEqual(ss.scan_text('password = "' + "hunter2hunter2!" + '"', "f")[0][2], "hard-coded secret")
        self.assertEqual(ss.scan_text("postgres://app:" + "s3cretpw" + "@db/x", "f")[0][2], "password in a URL")

    def test_no_false_alarms(self):
        for ok in ('password = "your-password-here"', "api_key: ${API_KEY}", 'secret = "<put it in .env>"',
                   f"key = '{AWS}'  # gitleaks:allow", "token = os.environ['TOKEN']", "https://user@example.com/x"):
            self.assertEqual(ss.scan_text(ok, "f"), [], ok)

    def test_bad_files(self):
        for bad in (".env", "app/.env.local", "id_ed25519", "certs/server.key", "credentials.json", "secrets.yaml"):
            self.assertTrue(ss.BAD_FILES.search(bad), bad)
        for ok in (".env.example", "keyboard.py", "docs/keys.md", "public.pem.txt"):
            self.assertFalse(ss.BAD_FILES.search(ok), ok)


class Hook(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="hook-test-")); self.addCleanup(shutil.rmtree, self.t, True)
        hooks = self.t / "hooks"; hooks.mkdir()
        shutil.copy(ROOT / "config/git/hooks/dispatch", hooks / "dispatch")
        for h in ("pre-commit", "post-commit"): (hooks / h).symlink_to("dispatch")
        home = self.t / "home"; (home / ".local/bin").mkdir(parents=True)
        (home / ".local/bin/secret-scan").symlink_to(ROOT / "config/git/secret-scan.py")
        gc = self.t / "gitconfig"
        gc.write_text(f"[core]\n\thooksPath = {hooks}\n[user]\n\tname = t\n\temail = t@x\n")
        self.env = {**os.environ, "HOME": str(home), "GIT_CONFIG_GLOBAL": str(gc), "GIT_CONFIG_NOSYSTEM": "1"}
        self.env.pop("SKIP_SECRET_SCAN", None)
        self.env["SECRET_SCAN_BUILTIN"] = "1"                  # the built-in scan (gitleaks has its own test below)
        self.repo = self.t / "r"; self.repo.mkdir(); self.git("init", "-q", "-b", "main")

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def commit(self, name, text):
        (self.repo / name).write_text(text); self.git("add", name); return self.git("commit", "-qm", "x")

    def test_blocks_secret_and_env_file(self):
        r = self.commit("conf.py", f"KEY = '{AWS}'\n")
        self.assertNotEqual(r.returncode, 0); self.assertIn("conf.py:1  AWS access key", r.stderr)
        self.git("reset", "-q")
        self.assertNotEqual(self.commit(".env", "A=1\n").returncode, 0)
        self.git("reset", "-q"); (self.repo / ".env").unlink()

    def test_clean_commit_and_repo_hook_still_runs(self):
        own = self.repo / ".git/hooks/post-commit"
        own.write_text(f"#!/bin/sh\ntouch '{self.t}/own-hook-ran'\n"); own.chmod(0o755)
        r = self.commit("ok.py", "print('hi')\n")
        self.assertEqual(r.returncode, 0, r.stderr); self.assertTrue((self.t / "own-hook-ran").exists())

    @unittest.skipUnless(shutil.which("gitleaks"), "gitleaks not installed")
    def test_gitleaks_blocks_and_says_where(self):
        self.env.pop("SECRET_SCAN_BUILTIN")
        r = self.commit("conf.py", f"KEY = '{AWS}'\n")
        self.assertNotEqual(r.returncode, 0); self.assertIn("File:        conf.py", r.stderr); self.assertNotIn(AWS, r.stderr)

    def test_skip_once(self):
        self.env["SKIP_SECRET_SCAN"] = "1"
        self.assertEqual(self.commit("conf.py", f"KEY = '{AWS}'\n").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
