"""popup-dismiss.sh: a click outside a popup closes it; inside it, on the bar, or with no popup, nothing happens."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "config/hypr/scripts/popup-dismiss.sh"
FAKE = """#!/bin/sh
case "$*" in
  "-j activewindow") printf '{"class":"%s","at":[1510,40],"size":[400,640],"address":"0xabc"}' "$CLS";;
  cursorpos) echo "$POS";;
  "-j layers") echo '{"eDP-1":{"levels":{"2":[{"x":0,"y":0,"w":1920,"h":32,"namespace":"waybar"}]}}}';;
  *) echo "CALLED: $*";;
esac
"""


class PopupDismiss(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = tempfile.mkdtemp()
        fake = Path(cls.bin, "hyprctl"); fake.write_text(FAKE); fake.chmod(0o755)

    def closes(self, cls_, pos):
        env = dict(os.environ, CLS=cls_, POS=pos, PATH=f"{self.bin}:{os.environ['PATH']}")
        out = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10).stdout
        return "closewindow address:0xabc" in out

    def test_cases(self):
        for cls_, pos, want in [("org.myos.Panel", "100, 500", True), ("org.myos.Run", "100, 500", True),
                                ("org.myos.Pick", "100, 500", True), ("org.myos.Panel", "1600, 300", False),
                                ("org.myos.Panel", "1700, 10", False), ("org.myos.Chat", "100, 500", False),
                                ("kitty", "100, 500", False)]:
            with self.subTest(cls_=cls_, pos=pos):
                self.assertEqual(self.closes(cls_, pos), want)


if __name__ == "__main__":
    unittest.main()
