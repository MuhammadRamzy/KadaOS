#!/usr/bin/env python3
"""Tests for `disk` (config/desktop/disk.py): Docker size parsing, big files, duplicates, cleanup bookkeeping and the
report shape. Temp folders and fake cleanup items only: never touches real caches or the real Trash."""
import importlib.util, os, shutil, tempfile, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("disk", Path(__file__).resolve().parents[1] / "config/desktop/disk.py")
disk = importlib.util.module_from_spec(spec); spec.loader.exec_module(disk)


class Disk(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="disk-test-")); self.addCleanup(shutil.rmtree, self.t, True)

    def test_docker_sizes(self):
        self.assertEqual(disk.parse_docker_size("9.271GB"), 9271000000)
        self.assertEqual(disk.parse_docker_size("350.1MB (4%)"), 350100000)
        self.assertEqual(disk.parse_docker_size("0B"), 0); self.assertEqual(disk.parse_docker_size(""), 0)

    def test_big_files_and_duplicates(self):
        a = self.t / "Downloads"; (a / "sub").mkdir(parents=True); (self.t / "Documents").mkdir()
        (a / "big.iso").write_bytes(b"x" * 3000); (a / "small.txt").write_bytes(b"x" * 10)
        self.assertEqual([Path(f["path"]).name for f in disk.big_files(a, min_size=1000)], ["big.iso"])
        same = os.urandom(5000)
        (a / "photo.jpg").write_bytes(same); (a / "sub/photo (1).jpg").write_bytes(same); (self.t / "Documents/photo.jpg").write_bytes(same)
        (a / "other.jpg").write_bytes(os.urandom(5000))                       # same size, different content
        (a / ".hidden").mkdir(); (a / ".hidden/photo.jpg").write_bytes(same)    # hidden folders are skipped
        g = disk.duplicates([a, self.t / "Documents"], min_size=1000)
        self.assertEqual(len(g), 1); self.assertEqual(len(g[0]["paths"]), 3)
        self.assertEqual(Path(g[0]["paths"][0]).name, "photo.jpg", "keeps the shortest path first")
        self.assertFalse(any(".hidden" in p for p in g[0]["paths"]))

    def test_same_start_different_end_is_not_a_duplicate(self):
        d = self.t / "D"; d.mkdir(); head = os.urandom(1 << 16)
        (d / "a.bin").write_bytes(head + b"A" * 9000); (d / "b.bin").write_bytes(head + b"B" * 9000)
        (d / "c.bin").write_bytes(head + b"A" * 9000)
        g = disk.duplicates([d], min_size=1000)
        self.assertEqual([sorted(Path(p).name for p in x["paths"]) for x in g], [["a.bin", "c.bin"]])

    def test_wipe_keeps_the_folder(self):
        c = self.t / "cache"; (c / "d").mkdir(parents=True); (c / "f").write_text("x"); (c / "d/g").write_text("y")
        disk.wipe(c); self.assertTrue(c.is_dir()); self.assertEqual(list(c.iterdir()), [])

    def test_clean_bookkeeping(self):
        done = []
        its = [{"id": "a", "title": "A", "why": "", "size": 5, "how": lambda: done.append("a")},
               {"id": "b", "title": "B", "why": "", "size": 5, "how": lambda: (_ for _ in ()).throw(RuntimeError("close Chrome first"))},
               {"id": "r", "title": "R", "why": "", "size": 5, "how": None, "cmd": "sudo apt clean"}]
        res = {i: (ok, m) for i, ok, m in disk.clean(["a", "b", "r", "zz"], its)}
        self.assertEqual(done, ["a"]); self.assertTrue(res["a"][0])
        self.assertEqual(res["b"], (False, "close Chrome first"))
        self.assertIn("! sudo apt clean", res["r"][1], "root items are never run: the command is shown")
        self.assertEqual(res["zz"], (False, "unknown item"))

    def test_report_shape(self):
        r = disk.report(dock={})
        self.assertEqual(set(r), {"disk", "items", "safe_total"})
        self.assertTrue(all("how" not in i and "root" in i for i in r["items"]), "the report is plain JSON")
        self.assertTrue(any(i["root"] and i["cmd"].startswith("sudo") for i in r["items"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
