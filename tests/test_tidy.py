#!/usr/bin/env python3
"""Tests for Downloads tidy (config/desktop/tidy.py) in a temp folder: rules, age, unfinished downloads, name clashes,
off by default, once a day. The Trash is never used (installer trashing is off in these runs)."""
import importlib.util, json, os, shutil, tempfile, time, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("tidy", Path(__file__).resolve().parents[1] / "config/desktop/tidy.py")
td = importlib.util.module_from_spec(spec); spec.loader.exec_module(td)


class Tidy(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="tidy-test-")); self.addCleanup(shutil.rmtree, self.t, True)
        td.CONF, td.STATE = self.t / "tidy.json", self.t / "state.json"
        self.dl = self.t / "Downloads"; self.dl.mkdir()
        self.c = {**td.DEFAULT, "folder": str(self.dl)}

    def f(self, name, hours_old=48):
        p = self.dl / name; p.write_text("x"); t = time.time() - hours_old * 3600; os.utime(p, (t, t)); return p

    def test_plan(self):
        self.f("photo.JPG"); self.f("paper.pdf"); self.f("src.tar.gz"); self.f("new.pdf", hours_old=1)
        self.f("big.iso.crdownload"); self.f("movie.mp4"); self.f("movie.mp4.part"); self.f(".hidden.png"); self.f("notes.xyz")
        (self.dl / "folder.pdf").mkdir()
        got = {s.name: d.parent.name for a, s, d in td.plan(self.c)}
        self.assertEqual(got, {"photo.JPG": "Images", "paper.pdf": "Documents", "src.tar.gz": "Archives"})

    def test_apply_name_clash(self):
        (self.dl / "Images").mkdir(); (self.dl / "Images/a.png").write_text("old"); self.f("a.png")
        td.apply(td.plan(self.c))
        self.assertEqual(sorted(p.name for p in (self.dl / "Images").iterdir()), ["a (2).png", "a.png"])
        self.assertEqual((self.dl / "Images/a.png").read_text(), "old", "never overwrites")

    def test_off_by_default_and_once_a_day(self):
        self.assertFalse(td.load()["enabled"]); self.assertTrue(td.CONF.exists(), "defaults written on first use")
        self.f("paper.pdf")
        td.CONF.write_text(json.dumps({**self.c, "enabled": False})); self.assertEqual(td.daily(), "")
        td.CONF.write_text(json.dumps({**self.c, "enabled": True}))
        self.assertEqual(td.daily(), "1 → Documents")
        self.f("second.pdf"); self.assertEqual(td.daily(), "", "already ran today")


if __name__ == "__main__":
    unittest.main(verbosity=2)
