"""Regression: restarting the activity helper must not close the new helper's pipe (double-close bug)."""
import gc
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "config/desktop"
sys.path.insert(0, str(SOURCE))
import hydration  # noqa: E402


class IdleRestart(unittest.TestCase):
    def test_restart_keeps_new_pipe_open(self):
        tmp = Path(tempfile.mkdtemp())
        helper = tmp / "hydration-idle"
        helper.write_text("#!/bin/sh\necho ready\nexec sleep 30\n")
        helper.chmod(helper.stat().st_mode | stat.S_IEXEC)
        hydration.HERE = tmp
        svc = object.__new__(hydration.Service)   # no D-Bus / desktop: only the idle-helper plumbing
        svc.Gio, svc.GLib = hydration.gi_modules()
        svc.engine = hydration.Engine()
        svc.ctx = {}
        svc.idle_process = svc.idle_channel = svc.idle_source = None
        try:
            for _ in range(5):                       # each restart replaces (and frees) the previous Popen
                svc.start_idle()
                gc.collect()
                os.fstat(svc.idle_process.stdout.fileno())   # OSError(EBADF) with the old shutdown() code
            self.assertEqual(svc.idle_process.stdout.readline().strip(), b"ready")
        finally:
            if svc.idle_source:
                svc.GLib.source_remove(svc.idle_source)
            if svc.idle_process:
                svc.idle_process.kill(); svc.idle_process.wait(); svc.idle_process.stdout.close()


if __name__ == "__main__":
    unittest.main()
