#!/usr/bin/env python3
"""Tests for the USB guard notifier (config/desktop/usbguard.py): rule parsing, the BadUSB warning, and picking
'inserted and blocked' out of `usbguard watch` output. USBGuard is never called."""
import importlib.util, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("ug", Path(__file__).resolve().parents[1] / "config/desktop/usbguard.py")
ug = importlib.util.module_from_spec(spec); spec.loader.exec_module(ug)

STICK = 'block id 0781:5581 serial "4C53" name "Ultra" hash "abc=" parent-hash "def=" with-interface 08:06:50 with-connect-type "hotplug"'
BADUSB = 'block id 1234:5678 serial "" name "Flash Disk" hash "x=" with-interface { 08:06:50 03:01:01 } with-connect-type "hotplug"'
WATCH = f"""[IPC] Connected
[device] PresenceChanged: id=17
 event=Insert
 target=block
 device_rule={STICK}
[device] PolicyChanged: id=17
 target_old=block
 target_new=block
 device_rule={STICK}
[device] PresenceChanged: id=3
 event=Insert
 target=allow
 device_rule=allow id 32c2:0018 name "HS6209"
[device] PresenceChanged: id=18
 event=Remove
 target=block
 device_rule={STICK}
""".splitlines(True)


class UsbGuard(unittest.TestCase):
    def test_parse_rule(self):
        d = ug.parse_rule("7: " + STICK)
        self.assertEqual((d["id"], d["target"], d["vid_pid"], d["name"], d["kinds"]), ("7", "block", "0781:5581", "Ultra", ["storage"]))

    def test_badusb_warning(self):
        self.assertIn("It says it's a keyboard", ug.describe(ug.parse_rule(BADUSB)))
        self.assertNotIn("⚠", ug.describe(ug.parse_rule(STICK)))

    def test_only_inserted_and_blocked(self):
        ev = list(ug.events(WATCH))
        self.assertEqual([(d["id"], d["name"]) for d in ev], [("17", "Ultra")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
