#!/usr/bin/env python3
"""Tests for seclab findings and the engagement report (config/security/seclab) in a temp engagement folder.
No tool is run; the PDF step is skipped (--md path) except for one Markdown → HTML check."""
import importlib.machinery, importlib.util, os, shutil, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_loader("seclab_r", importlib.machinery.SourceFileLoader("seclab_r", str(ROOT / "config/security/seclab")))
sl = importlib.util.module_from_spec(spec); spec.loader.exec_module(sl)


class Report(unittest.TestCase):
    def setUp(self):
        t = Path(tempfile.mkdtemp(prefix="seclab-test-")); self.addCleanup(shutil.rmtree, t, True)
        sl.ENG_ROOT, sl.ACTIVE = t / "eng", t / "state/active"
        self.eng = sl.new_engagement("client-q4")
        (self.eng / "scope.txt").write_text("10.0.0.0/24\nexample.test\n")
        n = (self.eng / "notes.md").read_text().replace("- Window:", "- Window: 1–5 Dec 2026")
        (self.eng / "notes.md").write_text(n)
        (self.eng / "log.md").write_text("- 2026-12-01 10:00 AM · `ports` on `10.0.0.5` → exit 0 · scans/x.txt\n")

    def test_findings_sorted_worst_first(self):
        sl.add_finding(self.eng, "Banner shows version", "low", "10.0.0.5")
        sl.add_finding(self.eng, "SQL injection in login", "critical", "example.test")
        sl.add_finding(self.eng, "Missing HSTS", "medium")
        self.assertEqual([m["title"] for m, _, _ in sl.findings(self.eng)], ["SQL injection in login", "Missing HSTS", "Banner shows version"])
        with self.assertRaises(ValueError): sl.add_finding(self.eng, "x", "urgent")

    def test_bad_severity_in_file_counts_as_info(self):
        (self.eng / "findings").mkdir(exist_ok=True)
        (self.eng / "findings/009-x.md").write_text("---\ntitle: Odd\nseverity: severe\n---\nbody")
        self.assertEqual(sl.findings(self.eng)[0][0]["severity"], "info")

    def test_report_contents(self):
        sl.add_finding(self.eng, "SQL injection in login", "critical", "example.test")
        md = sl.report_md(self.eng, today="2026-12-06")
        self.assertIn("# Security assessment: client-q4", md)
        self.assertIn("**Window:** 1–5 Dec 2026", md)
        self.assertNotIn("**Rules of engagement:** ##", md, "an empty notes field doesn't swallow the next line")
        self.assertIn("| Critical | 1 |", md); self.assertIn("rated **critical**", md)
        self.assertIn("- `10.0.0.0/24`", md); self.assertIn("### 1. SQL injection in login", md)
        self.assertIn("#### Remediation", md, "finding sections nest under the finding")
        self.assertIn("`ports` on `10.0.0.5`", md)

    def test_write_md_only(self):
        made = sl.write_report(self.eng, pdf=False)
        self.assertEqual([p.name for p in made], ["report.md"])


class Kit(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="seclab-kit-")); self.addCleanup(shutil.rmtree, self.t, True)

    def phy(self, name, bus, driver, iface):
        dev = self.t / "devices" / name; (dev / "net" / iface).mkdir(parents=True)
        for kind, target in (("subsystem", bus), ("driver", driver)):
            (self.t / kind / target).mkdir(parents=True, exist_ok=True); (dev / kind).symlink_to(self.t / kind / target)
        p = self.t / "ieee80211" / name; p.mkdir(parents=True); (p / "device").symlink_to(dev)

    def test_wifi_adapters(self):
        self.phy("phy0", "pci", "rtw89_8852bte", "wlo1"); self.phy("phy1", "usb", "mt7921u", "wlx00c0")
        info = {"phy0": "Supported interface modes:\n * managed\n * monitor\nBand 1:", "phy1": "Supported interface modes:\n * monitor\nBand 1:"}
        ads = sl.wifi_adapters(self.t / "ieee80211", info.get)
        self.assertEqual([(a["iface"], a["internal"], a["monitor"]) for a in ads], [("wlo1", True, True), ("wlx00c0", False, True)])
        self.assertTrue(ads[1]["injection_hint"])

    def test_ctf_folder(self):
        sl.CTF_ROOT = self.t / "CTF"
        d = sl.new_ctf("Kerala CTF 2026")
        self.assertTrue((d / "exploits").is_dir()); self.assertIn("| Challenge |", (d / "notes.md").read_text())
        (d / "notes.md").write_text("mine"); sl.new_ctf("Kerala CTF 2026")
        self.assertEqual((d / "notes.md").read_text(), "mine", "never overwrites your notes")

    def test_lab_network_is_isolated(self):
        self.assertNotIn("<forward", sl.LAB_XML.split("-->", 1)[1], "no forward: no LAN, no Internet")
        self.assertIn("10.66.0.1", sl.LAB_XML)


if __name__ == "__main__":
    unittest.main(verbosity=2)
