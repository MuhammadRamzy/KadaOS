#!/usr/bin/env python3
"""Tests for security-check (config/desktop/security.py): the check rules on canned input. Read-only tool; no live changes."""
import importlib.util, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("sec", Path(__file__).resolve().parents[1] / "config/desktop/security.py")
sec = importlib.util.module_from_spec(spec); spec.loader.exec_module(sec)


class Checks(unittest.TestCase):
    def test_listeners(self):
        ss = ('tcp LISTEN 0 10 127.0.0.1:11434 0.0.0.0:* users:(("ollama",pid=1,fd=3))\n'
              'tcp LISTEN 0 50 *:1716 *:* users:(("kdeconnectd",pid=2,fd=9))\n'
              'udp UNCONN 0 0 0.0.0.0:52019 0.0.0.0:* users:(("chrome",pid=3,fd=1))\n'
              'udp UNCONN 0 0 192.168.122.1:53 0.0.0.0:*\n')
        self.assertEqual(sec.listeners_check(ss)["state"], "ok", "loopback, KDE Connect, client UDP and the VM DNS are fine")
        bad = sec.listeners_check(ss + 'tcp LISTEN 0 10 *:8154 *:* users:(("gtk4-broadwayd",pid=4,fd=3))\n')
        self.assertEqual(bad["state"], "warn"); self.assertIn("8154 (gtk4-broadwayd)", bad["detail"])
        v6 = sec.parse_listeners('tcp LISTEN 0 4 [::1]:631 [::]:*\ntcp LISTEN 0 4 [::]:22 [::]:*\n')
        self.assertEqual([p for _, _, p, _ in v6], [22])

    def test_ssh_key(self):
        self.assertEqual(sec.ssh_key_check({})["state"], "info")
        c = sec.ssh_key_check({"/home/x/.ssh/id_ed25519": False})
        self.assertEqual(c["state"], "bad"); self.assertFalse(c["fix"]["root"]); self.assertIn("ssh-keygen -p", c["fix"]["cmd"])
        self.assertEqual(sec.ssh_key_check({"/home/x/.ssh/id_ed25519": True})["state"], "ok")

    def test_groups(self):
        self.assertEqual(sec.groups_check(["adm", "sudo"])["state"], "ok")
        c = sec.groups_check(["docker", "lxd", "sudo"])
        self.assertEqual(c["state"], "warn"); self.assertTrue(c["fix"]["root"]); self.assertIn("gpasswd -d", c["fix"]["cmd"])

    def test_updates_and_logins(self):
        sec_txt = "5 updates can be applied immediately.\n2 of these updates are standard security updates."
        self.assertEqual(sec.updates_check(sec_txt, True)["state"], "bad")
        self.assertEqual(sec.updates_check("0 updates can be applied immediately.", True)["state"], "ok")
        self.assertEqual(sec.updates_check("3 updates can be applied immediately.", False)["state"], "warn")
        self.assertEqual(sec.updates_check("garbage", True)["state"], "info")
        self.assertEqual(sec.failed_logins_check("")["state"], "ok")
        self.assertEqual(sec.failed_logins_check("x\n" * 6)["state"], "warn")

    def test_firmware(self):
        self.assertEqual(sec.firmware_check('{"Devices": []}', 1)["state"], "ok")
        self.assertEqual(sec.firmware_check('{"Devices": [{"Name": "System Firmware"}]}', 1)["state"], "warn")
        self.assertEqual(sec.firmware_check("", 0)["state"], "info")


if __name__ == "__main__":
    unittest.main(verbosity=2)
