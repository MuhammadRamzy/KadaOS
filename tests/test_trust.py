#!/usr/bin/env python3
"""Tests for network trust levels (config/network/trust.py): effective level, NetworkManager settings, the firewall plan
the root hook follows. Nothing is changed on the real network or firewall."""
import importlib.util, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("trust", Path(__file__).resolve().parents[1] / "config/network/trust.py")
tr = importlib.util.module_from_spec(spec); spec.loader.exec_module(tr)


class Trust(unittest.TestCase):
    def test_level(self):
        self.assertEqual(tr.level_of("work", "wpa-psk", True), "work")
        self.assertEqual(tr.level_of("", "", True), "public", "open Wi-Fi you haven't marked counts as public")
        self.assertIsNone(tr.level_of("", "wpa-psk", True), "secured and unmarked: left alone")
        self.assertIsNone(tr.level_of("", "", False), "wired and unmarked: left alone")
        self.assertIsNone(tr.level_of("trusted", "", False), "a firewalld zone we don't use")

    def test_settings(self):
        s = tr.nm_settings("public")
        self.assertEqual((s["802-11-wireless.cloned-mac-address"], s["connection.mdns"], s["connection.zone"]), ("random", "no", "public"))
        self.assertEqual(tr.nm_settings("home")["802-11-wireless.cloned-mac-address"], "preserve")
        self.assertEqual(tr.nm_settings("work")["connection.dns-over-tls"], "opportunistic")

    def test_firewall_plan(self):
        add = [["ufw", "prepend", "deny", "in", "on", "wlo1", "comment", tr.RULE_COMMENT]]
        rm = [["ufw", "delete", "deny", "in", "on", "wlo1"]]
        self.assertEqual(tr.firewall_plan("public", "wlo1", "up", False), add)
        self.assertEqual(tr.firewall_plan("public", "wlo1", "up", True), [], "already there")
        self.assertEqual(tr.firewall_plan("public", "wlo1", "down", True), rm)
        self.assertEqual(tr.firewall_plan("home", "wlo1", "up", True), rm, "left over from a public network on the same card")
        self.assertEqual(tr.firewall_plan(None, "wlo1", "up", False), [])
        self.assertEqual(tr.firewall_plan("public", "wlo1", "hostname", False), [], "events we don't act on")
        self.assertEqual(tr.firewall_plan("public", "lo", "up", False), [])

    def test_has_rule(self):
        status = "Status: active\n\nTo   Action   From\nAnywhere on wlo1   DENY IN   Anywhere   # myos-trust public\n1714:1764/tcp  ALLOW IN  Anywhere"
        self.assertTrue(tr.has_rule(status, "wlo1")); self.assertFalse(tr.has_rule(status, "eno1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
