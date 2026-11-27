#!/usr/bin/env python3
"""Tests for record.sh (screen recording) with a fake wf-recorder: start → bar timer → stop finalises the file → GIF.
Nothing on the real screen is captured; notifications and clipboard are stubbed."""
import json, os, shutil, subprocess, tempfile, time, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "config/hypr/scripts/record.sh"


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg missing")
class Record(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="rec-test-")); self.addCleanup(shutil.rmtree, self.t, True)
        # never leave a fake recorder behind, even when a test fails (argv list: pkill can't match a shell's own line)
        self.addCleanup(subprocess.run, ["pkill", "-f", f"{self.t}/bin/wf-recorder"], capture_output=True)
        b = self.t / "bin"; b.mkdir(); (self.t / "run").mkdir(); (self.t / "videos").mkdir()
        self.log = self.t / "calls"
        def fake(name, body): (b / name).write_text(f"#!/bin/bash\necho \"{name} $*\" >> {self.log}\n{body}\n"); (b / name).chmod(0o755)
        # fake recorder: makes a real 1 s video at -f, then waits for SIGINT like wf-recorder does
        # fake recorder: on SIGINT it "finishes" for 2 s (like flushing a long recording), then writes a real video
        fake("wf-recorder", 'f=""; while [ $# -gt 0 ]; do [ "$1" = -f ] && f=$2; shift; done\n'
                            'fin() { sleep 2; ffmpeg -loglevel error -f lavfi -i testsrc=size=320x240:rate=10 -t 1 -pix_fmt yuv420p -y "$f"; exit 0; }\n'
                            'trap fin INT; while :; do sleep 0.1; done')
        fake("hyprctl", "echo '[{\"name\": \"eDP-1\", \"focused\": true}]'")
        fake("xdg-user-dir", f"echo {self.t / 'videos'}")
        fake("wl-copy", "cat >/dev/null")                      # the script pipes the file path into it
        for n in ("notify-send", "pkill"): fake(n, "true")      # must not read stdin: it may never close
        hypr = self.t / "home/.config/hypr/scripts"; hypr.mkdir(parents=True)
        (hypr / "notify-action.py").write_text("#!/bin/sh\necho none\n"); (hypr / "notify-action.py").chmod(0o755)
        self.env = dict(os.environ, PATH=f"{b}:/usr/bin:/bin", XDG_RUNTIME_DIR=str(self.t / "run"), HOME=str(self.t / "home"))

    def rec(self, *a): return subprocess.run(["bash", str(SCRIPT), *a], env=self.env, capture_output=True, text=True, timeout=90,
                                             stdin=subprocess.DEVNULL)

    def test_start_timer_stop_gif(self):
        self.assertEqual(json.loads(self.rec("status").stdout)["text"], "", "idle: the bar item is empty")
        self.assertEqual(self.rec("full", "--gif").returncode, 0)
        st = json.loads(self.rec("status").stdout)
        self.assertEqual(st["class"], "rec"); self.assertTrue(st["text"].startswith("● 0:0"))
        time.sleep(1.5)
        self.assertEqual(self.rec("stop").returncode, 0)
        out = sorted(p.suffix for p in (self.t / "videos/Recordings").iterdir())
        self.assertEqual(out, [".gif", ".mp4"], "the video (only used once the recorder exited), and the GIF")
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(next((self.t / "videos/Recordings").glob("*.mp4")))], capture_output=True, text=True)
        self.assertGreater(float(probe.stdout.strip() or 0), 0.5, "a complete, playable video")
        self.assertFalse((self.t / "run/myos-record.pid").exists())
        self.assertEqual(json.loads(self.rec("status").stdout)["text"], "")
        self.assertIn("-o eDP-1", self.log.read_text(), "full screen records the focused monitor")

    def test_stop_when_idle_is_harmless(self):
        self.assertEqual(self.rec("stop").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
