#!/usr/bin/env python3
"""Tests for `phone` (config/phone/phone.py). Fake kdeconnect-cli / adb on PATH and a local server in place of ntfy:
nothing touches a real phone, the internet or the live desktop."""
import http.server, importlib.util, json, os, shutil, tempfile, threading, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("phone", ROOT / "config/phone/phone.py")
phone = importlib.util.module_from_spec(spec); spec.loader.exec_module(phone)

KDE_LIST = """- Pixel 8: abc_123 (paired and reachable)
- Pixel: zzz (reachable)
- Old tab: old1 (paired)
2 devices found
"""


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="phone-test-")); self.addCleanup(shutil.rmtree, self.t, True)
        self.bin = self.t / "bin"; self.bin.mkdir(); self.log = self.t / "calls"
        for k, v in {"CFG": self.t / "phone.json", "STATE": self.t / "state.json", "DOWNLOADS": self.t / "dl"}.items():
            old = getattr(phone, k); setattr(phone, k, v); self.addCleanup(setattr, phone, k, old)
        oldpath = os.environ["PATH"]; os.environ["PATH"] = f"{self.bin}:/usr/bin:/bin"
        self.addCleanup(os.environ.__setitem__, "PATH", oldpath)
        self.fake("pgrep", "exit 1")                       # not locked
        self.fake("nmcli", "echo 'yes:HomeWiFi'")

    def fake(self, name, body):
        p = self.bin / name
        p.write_text(f'#!/bin/sh\necho "{name} $*" >> {self.log}\n{body}\n'); p.chmod(0o755)

    def calls(self): return self.log.read_text().splitlines() if self.log.exists() else []


class Parsing(Sandbox):
    def test_kde_list(self):
        devs = phone.parse_kde_list(KDE_LIST)
        self.assertEqual([(d["id"], d["paired"], d["reachable"]) for d in devs],
                         [("abc_123", True, True), ("zzz", False, True), ("old1", True, False)])
        self.assertEqual(phone.kde_phone({"kde_id": ""}, devs), None, "two paired devices and none chosen: don't guess")
        self.assertEqual(phone.kde_phone({"kde_id": "old1"}, devs)["name"], "Old tab")

    def test_adb_pick_never_confuses_the_pad(self):
        devs = [{"serial": "PAD1", "state": "device", "model": "23043RP34G"}, {"serial": "PH1", "state": "device", "model": "2201117TG"}]
        self.assertIsNone(phone.adb_phone({"adb_serial": ""}, devs), "two devices: ask once")
        self.assertEqual(phone.adb_phone({"adb_serial": "PH1"}, devs)["serial"], "PH1")
        self.assertIsNone(phone.adb_phone({"adb_serial": "PH1"}, devs[:1]), "only the Pad plugged in: not the phone")

    def test_privacy_of_alerts(self):
        self.assertEqual(phone.ntfy_message("pi5 is offline", "10.0.0.5 secret", "short"), "pi5 is offline")
        self.assertNotIn("pi5", phone.ntfy_message("pi5 is offline", "x", "private"))
        self.assertIn("10.0.0.5", phone.ntfy_message("pi5 is offline", "10.0.0.5", "full"))

    def test_bar_states(self):
        self.assertEqual(phone.bar_json(None)["text"], "", "not paired: hidden")
        ph = {"name": "Pixel", "id": "a", "paired": True, "reachable": True}
        on = phone.bar_json(ph, 64, False); self.assertEqual((on["text"], on["class"]), (phone.PHONE_ICON, "on"))
        self.assertIn("64%", on["tooltip"])
        low = phone.bar_json(ph, 15, False); self.assertEqual((low["text"], low["class"]), (phone.PHONE_ICON + " 15%", "low"))
        self.assertEqual(phone.bar_json(ph, 15, True)["class"], "on", "charging: not low")
        self.assertEqual(phone.bar_json({**ph, "reachable": False}, seen=0)["class"], "away")

    def test_peer_address_from_ss(self):
        ss = ('ESTAB 0 0 10.100.231.174:1716 10.100.42.9:43210 users:(("kdeconnectd",pid=1,fd=30))\n'
              'ESTAB 0 0 10.100.231.174:22 10.100.1.1:5555 users:(("sshd",pid=2,fd=3))\n')
        self.assertEqual(phone.parse_peer(ss, {"10.100.231.174"}), "10.100.42.9")
        v6 = 'ESTAB 0 0 [::ffff:192.168.1.5]:1716 [::ffff:192.168.1.77]:40000 users:(("kdeconnectd",pid=1,fd=9))'
        self.assertEqual(phone.parse_peer(v6, {"192.168.1.5"}), "192.168.1.77")
        self.assertIsNone(phone.parse_peer('ESTAB 0 0 10.0.0.2:22 10.0.0.3:1 users:(("sshd",pid=2,fd=3))', set()))

    def test_settings(self):
        phone.set_option("push", "always"); self.assertEqual(phone.config()["push"], "always")
        with self.assertRaises(phone.Fail): phone.set_option("push", "sometimes")
        with self.assertRaises(phone.Fail): phone.set_option("topic", "x"), "only alert settings"

    def test_harden_steps(self):
        kde = phone.harden_steps([phone.KDE_PKG]); ntfy = phone.harden_steps([phone.NTFY_PKG])
        self.assertTrue(any("READ_LOGS" in c for _, c in kde)); self.assertFalse(any("READ_LOGS" in c for _, c in ntfy))
        self.assertTrue(all(c.split()[0] in ("dumpsys", "cmd", "pm") for _, c in kde + ntfy), "only adb shell built-ins")

    def test_link_watchdog(self):
        st, now = {}, 100000
        self.assertIsNone(phone.link_problem(True, st, "wifi:Home", now))
        self.assertIsNone(phone.link_problem(False, st, "wifi:Home", now + 600), "short drop: quiet")
        self.assertIsNone(phone.link_problem(False, st, "wifi:Cafe", now + 3600), "other network: expected")
        self.assertEqual(phone.link_problem(False, st, "wifi:Home", now + 3600)[0], "Phone link is down")
        self.assertIsNone(phone.link_problem(False, {}, "wifi:Home", now), "never seen: quiet")


class Ntfy(Sandbox):
    def setUp(self):
        super().setUp()
        got = self.got = []
        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(s):
                got.append(json.loads(s.rfile.read(int(s.headers["Content-Length"])))); s.send_response(200); s.end_headers()
            def log_message(s, *a): pass
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.addCleanup(self.srv.shutdown)
        self.cfg = {**phone.DEFAULTS, "server": f"http://127.0.0.1:{self.srv.server_port}", "topic": "your-secret-topic"}
        phone.save(phone.CFG, self.cfg)

    def test_push_queue_and_flush(self):
        self.assertEqual(phone.push("✓ Job finished on pi5"), "sent")
        self.assertEqual(self.got[0], {"topic": "your-secret-topic", "message": "✓ Job finished on pi5", "priority": 3, "tags": []})
        offline = {**self.cfg, "server": "http://127.0.0.1:9"}
        self.assertEqual(phone.push("later", cfg=offline), "queued")
        self.assertEqual(len(phone.state()["queue"]), 1)
        self.assertEqual(phone.flush(offline), 0); self.assertEqual(phone.flush(self.cfg), 1)
        self.assertEqual(self.got[-1]["message"], "later"); self.assertEqual(phone.state()["queue"], [])
        self.assertEqual(oct(phone.STATE.stat().st_mode & 0o777), "0o600")

    def test_alert_rules(self):
        self.assertEqual(phone.alert("Disk almost full", "x", is_away=False), "here", "at the laptop: desktop only")
        self.assertEqual(phone.alert("Disk almost full", "x", is_away=True), "sent")
        self.assertEqual(phone.alert("Host key changed", "x", urgent=True, is_away=False), "sent", "urgent always goes")
        self.assertEqual(self.got[-1]["priority"], 4)
        self.assertEqual(phone.alert("x", cfg={**self.cfg, "push": "off"}, is_away=True), "off")
        self.assertEqual(phone.alert("x", cfg={**self.cfg, "push": "always"}, is_away=False), "sent")


class Send(Sandbox):
    def test_wifi_then_cable_then_explain(self):
        f = self.t / "a b.pdf"; f.write_text("x")
        self.fake("kdeconnect-cli", f"[ \"$1\" = -l ] && printf '%s' '{KDE_LIST.splitlines()[0]}'; exit 0")
        self.assertEqual(phone.main(["send", str(f), "https://example.org"]), 0)
        self.assertIn(f"kdeconnect-cli -d abc_123 --share {f}", self.calls())
        self.assertIn("kdeconnect-cli -d abc_123 --share https://example.org", self.calls())
        self.log.unlink()
        self.fake("kdeconnect-cli", "[ \"$1\" = -l ] && echo '- Pixel 8: abc_123 (paired)'; exit 0")   # not reachable
        self.fake("adb", 'case "$*" in "devices -l") printf "List\\nPH1 device usb:1 model:2201117TG\\n";; esac; exit 0')
        self.assertEqual(phone.main(["send", str(f)]), 0)
        self.assertIn(f"adb -s PH1 push {f} /sdcard/Download/", self.calls())
        self.fake("adb", 'printf "List\\n"')
        self.assertEqual(phone.main(["send", str(f)]), 1, "no path to the phone: a clear error")
        self.assertEqual(phone.main(["send", str(self.t / "missing")]), 2)


wspec = importlib.util.spec_from_file_location("watch", ROOT / "config/ai/watch.py")
watch = importlib.util.module_from_spec(wspec); wspec.loader.exec_module(watch)
cspec = importlib.util.spec_from_file_location("chat", ROOT / "config/ai/chat.py")
chat = importlib.util.module_from_spec(cspec); cspec.loader.exec_module(chat)


class Integration(Sandbox):
    def test_watcher_reads_the_phone_link(self):
        self.fake("phone", 'echo \'{"phone-link:abc": ["Phone link is down", "Open KDE Connect"]}\'')
        got = watch.remote_problems(board=self.t / "no-board", phone=self.bin / "phone")
        self.assertEqual(got, {"phone-link:abc": ("Phone link is down", "Open KDE Connect")})

    def test_assistant_tool(self):
        f = self.t / "x.png"; f.write_text("x")
        self.assertEqual(chat.phone_argv("send", [str(f)], phone="P"), ["P", "send", str(f)])
        for bad in [("send", []), ("send", [str(self.t / "nope")]), ("text", [], " "), ("format", [])]:
            with self.assertRaises(ValueError): chat.phone_argv(*bad, phone="P")
        (self.t / ".local/bin").mkdir(parents=True)
        self.fake("phone", "echo ok"); shutil.copy(self.bin / "phone", self.t / ".local/bin/phone")
        old = chat.HOME; chat.HOME = self.t; self.addCleanup(setattr, chat, "HOME", old)
        self.assertIn("declined", chat.run_agent_tool("phone", {"action": "send", "items": [str(f)]})[0])
        self.assertEqual(chat.run_agent_tool("phone", {"action": "find"}), ("ok", True))
        self.assertEqual(chat.run_agent_tool("phone", {"action": "send", "items": [str(f)]}, confirm=lambda *a: True), ("ok", True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
