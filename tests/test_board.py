#!/usr/bin/env python3
"""Tests for `board` (config/remote/board.py).

Unit tests use a throwaway HOME. The integration tests talk real SSH to a throwaway device: a tiny Alpine container
running sshd on 127.0.0.1 (skipped with a reason if Docker isn't usable). Nothing touches ~/.ssh or the live desktop.
"""
import importlib.util, ipaddress, json, os, shutil, socket, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "config/remote/board.py"
spec = importlib.util.spec_from_file_location("board", SRC)
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)

IMAGE = "myos-board-test-device:1"
DOCKERFILE = """FROM alpine:3
RUN apk add --no-cache openssh-server openssh-sftp-server tmux rsync bash sudo python3 && ssh-keygen -A \\
 && adduser -D -s /bin/bash dev && passwd -u dev && echo 'dev ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/dev \\
 && mkdir -p /home/dev/.ssh && chmod 700 /home/dev/.ssh && chown -R dev /home/dev/.ssh \\
 && sed -i 's/^#\\?AllowTcpForwarding.*/AllowTcpForwarding yes/' /etc/ssh/sshd_config
CMD ["/usr/sbin/sshd", "-D", "-e"]
"""


def sandbox(test):
    """Point every board path at a temp HOME (module constants are computed at import)."""
    t = Path(tempfile.mkdtemp(prefix="board-test-"))
    test.addCleanup(shutil.rmtree, t, True)
    saved = {}
    for k, v in {"HOME": t, "CFG_DIR": t / ".config/myos", "REG": t / ".config/myos/devices.toml", "SSH": t / ".ssh",
                 "GEN": t / ".ssh/config.d/10-devices", "STATE": t / "state.json", "CACHE": t / "cache.json",
                 "LOGS": t / "logs", "IMAGES": t / "images", "MOUNTS": t / "Remote",
                 "VSCODE_SETTINGS": t / "Code/settings.json", "BOOKMARKS": t / "bookmarks"}.items():
        saved[k] = getattr(board, k); setattr(board, k, v)
    test.addCleanup(lambda: [setattr(board, k, v) for k, v in saved.items()])
    return t


class Registry(unittest.TestCase):
    def setUp(self): self.t = sandbox(self)

    def test_round_trip_keeps_every_type(self):
        reg = {"defaults": {"user": "me", "baud": 115200},
               "pi5": {"host": "pi5.local", "user": "pi", "port": 2222, "tags": ["lab", "robot"], "agent": True,
                       "notes": 'quote " and \\ and ünïcode', "forward": ["8080", "5000:5000"]}}
        board.save_registry(reg)
        back = board.load_registry()
        self.assertEqual(back, reg)
        self.assertEqual(oct(board.REG.stat().st_mode & 0o777), "0o600")

    def test_validation_blocks_config_injection(self):
        bad = {"host": "pi\n  ProxyCommand evil", "user": "a b", "port": 70000, "kind": "toaster", "mac": "zz",
               "jump": "a b", "options": ["no-value"], "forward": ["x:y:z:w"], "colour": "red"}
        problems = board.validate_device("pi5", bad)
        for word in ("host", "user", "port", "kind", "mac", "jump", "options", "forward", "unknown field", "line breaks"):
            self.assertTrue(any(word in p for p in problems), f"{word} not flagged: {problems}")
        self.assertTrue(board.validate_device("bad.name", {}))
        self.assertTrue(board.validate_device("defaults", {}))
        with self.assertRaises(board.Fail):
            board.save_registry({"x": {"host": "a b"}})
        self.assertFalse(board.REG.exists(), "invalid registry must not be written")

    def test_any_username_and_ipv6(self):
        for user in ("pi", "pi", "ubuntu", "first.last", "DOMAIN\\user", "x_y-z"):
            self.assertEqual(board.validate_device("d", {"user": user, "host": "fe80::1%eth0"}), [], user)

    def test_backups_kept(self):
        for i in range(3): board.save_registry({"a": {"notes": str(i)}})
        self.assertGreaterEqual(len(list((board.CFG_DIR / "backups").glob("*.toml"))), 1)


class SshConfig(unittest.TestCase):
    def setUp(self): self.t = sandbox(self)

    def test_render(self):
        reg = {"pi5": {"host": "10.0.0.5", "user": "pi", "port": 2200, "agent": True, "options": ["Compression yes"]},
               "far": {"jump": "bastion", "user": "u"}, "esp": {"kind": "mcu", "serial": "/dev/ttyUSB0"},
               "plain": {"host": "srv", "proxy": False}}
        text = board.render_ssh_config(reg)
        self.assertIn("Host pi5\n  HostName 10.0.0.5\n  User pi\n  Port 2200\n  HostKeyAlias pi5", text)
        self.assertIn("_proxy pi5 %p", text)
        self.assertIn("ForwardAgent yes", text); self.assertIn("  Compression yes", text)
        far = text.split("Host far")[1].split("Host ")[0]
        self.assertIn("HostName far.local", far); self.assertIn("ProxyJump bastion", far); self.assertNotIn("ProxyCommand", far)
        self.assertNotIn("Host esp", text, "serial-only boards have no ssh host")
        self.assertNotIn("ProxyCommand", text.split("Host plain")[1])

    def test_include_added_once_with_backup(self):
        board.SSH.mkdir(mode=0o700)
        (board.SSH / "config").write_text("Host work\n  HostName w\n")
        board.ensure_ssh_layout(); board.ensure_ssh_layout()
        text = (board.SSH / "config").read_text()
        self.assertTrue(text.startswith("Include ~/.ssh/config.d/*"))
        self.assertEqual(text.count("Include"), 1); self.assertIn("Host work", text)
        self.assertEqual(len(list(board.SSH.glob("config.backup-*"))), 1)

    def test_defaults_file_is_last_and_valid(self):
        f = ROOT / "config/remote/ssh/99-defaults"
        self.assertIn("ControlMaster auto", f.read_text())
        r = subprocess.run(["ssh", "-G", "-F", str(f), "example.local"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("controlpersist 600", r.stdout)


class Helpers(unittest.TestCase):
    def test_port_specs(self):
        self.assertEqual(board.parse_port_spec("8080"), (8080, "localhost", 8080))
        self.assertEqual(board.parse_port_spec("9000:80"), (9000, "localhost", 80))
        self.assertEqual(board.parse_port_spec("5432:db:5432"), (5432, "db", 5432))
        for bad in ("abc", "0", "1:2:3:4", "70000"):
            with self.assertRaises(board.Fail): board.parse_port_spec(bad)

    def test_throttled(self):
        self.assertEqual(board.decode_throttled("0x0"), [])
        self.assertEqual(board.decode_throttled("0x50005"), ["under-voltage now", "throttled now",
                                                              "under-voltage since boot", "throttled since boot"])
        self.assertEqual(board.decode_throttled(""), [])

    def test_probe_parsing(self):
        f = board.parse_probe("model=Raspberry Pi 5 Model B Rev 1.0\narch=aarch64\ntemp=48312\nload=0.31\nuptime=12345.6\n"
                              "disk_free=1000\nmem_total=8000000\nthrottled=0x0\ntmux=yes\nsudo=no\nhome=/home/pi\n")
        self.assertEqual(f["temp_c"], 48.3); self.assertEqual(f["arch"], "aarch64"); self.assertTrue(f["tmux"])
        self.assertFalse(f["sudo"]); self.assertEqual(f["throttled"], []); self.assertEqual(f["home"], "/home/pi")

    def test_ssh_errors(self):
        c = board.classify_ssh_error
        self.assertEqual(c("@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@", 255), "hostkey-changed")
        self.assertEqual(c("Host key verification failed.", 255), "hostkey-unknown")
        self.assertEqual(c("pi@x: Permission denied (publickey).", 255), "auth")
        self.assertEqual(c("board: pi5 is not reachable (tried ...)", 255), "offline")
        self.assertEqual(c("ssh: Could not resolve hostname x", 255), "offline")
        self.assertEqual(c("", 0), "ok"); self.assertEqual(c("", 1), "remote")

    def test_scan_nets_never_scans_a_slash_16(self):
        nets = board.scan_nets([("wlo1", ipaddress.ip_interface("10.100.231.174/16")),
                                ("usb0", ipaddress.ip_interface("10.55.0.1/24"))])
        self.assertEqual([str(n) for _, n in nets], ["10.100.231.0/24", "10.55.0.0/24"])

    def test_usb_macs(self):
        h, d = board.usb_macs("pi5")
        self.assertEqual(board.usb_macs("pi5"), (h, d))
        self.assertTrue(h.startswith("02:b0:") and d.startswith("02:b1:")); self.assertEqual(h[6:], d[6:])
        self.assertNotEqual(board.usb_macs("pi4"), (h, d))
        self.assertRegex(d, board.MAC_RE)

    def test_vendor(self):
        self.assertIn("Raspberry", board.vendor("dc:a6:32:01:02:03"))
        self.assertIn("random", board.vendor("de:ad:be:ef:00:01"))
        self.assertEqual(board.vendor(board.usb_macs("x")[1]), "board USB cable")

    def test_iface_kind(self):
        self.assertEqual(board.iface_kind("wlo1"), "Wi-Fi")
        self.assertEqual(board.iface_kind("enx02b0aabbccdd"), "USB cable")
        self.assertEqual(board.iface_kind("lo"), "this laptop")

    def test_safe_disks_never_offers_the_system_disk(self):
        data = [
            {"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "size": 512 << 30, "rm": False, "tran": "nvme",
             "children": [{"mountpoints": ["/"]}]},
            {"name": "sda", "path": "/dev/sda", "type": "disk", "size": 1 << 40, "rm": False, "tran": "sata", "hotplug": False,
             "children": [{"mountpoints": ["/home"]}]},
            {"name": "sdb", "path": "/dev/sdb", "type": "disk", "size": 32 << 30, "rm": True, "tran": "usb", "model": "SD Reader",
             "children": [{"mountpoints": ["/media/u/bootfs"]}]},
            {"name": "mmcblk0", "path": "/dev/mmcblk0", "type": "disk", "size": 64 << 30, "rm": False, "tran": None},
            {"name": "sdc", "path": "/dev/sdc", "type": "disk", "size": 4 << 40, "rm": True, "tran": "usb"},     # 4 TB backup disk
            {"name": "sdd", "path": "/dev/sdd", "type": "disk", "size": 32 << 30, "rm": True, "tran": "usb",
             "children": [{"mountpoints": ["/"]}]},                                                          # live-USB root
        ]
        self.assertEqual([d["path"] for d in board.safe_disks(data)], ["/dev/sdb", "/dev/mmcblk0"])

    def test_cloud_init(self):
        ud, nc = board.cloud_init_files("pi5", "pi", "ssh-ed25519 AAAA me", "Asia/Kolkata",
                                        [('My "Wifi"', "p@ss:word")], "IN")
        self.assertIn("name: pi", ud); self.assertIn("lock_passwd: true", ud); self.assertIn("ssh-ed25519 AAAA me", ud)
        self.assertIn("ssh_pwauth: false", ud); self.assertIn('"My \\"Wifi\\""', nc); self.assertIn('"p@ss:word"', nc)
        self.assertIn("regulatory-domain: IN", nc)

    def test_customize_boot(self):
        t = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, t)
        (t / "config.txt").write_text("[all]\n"); (t / "cmdline.txt").write_text("console=serial0 root=PARTUUID=1 rootwait\n")
        (t / "user-data").write_text("#cloud-config\n")
        done, legacy = board.customize_boot(t, "pi5", "u", "ssh-ed25519 K", [], "IN", uart=True, gadget=True)
        self.assertFalse(legacy); self.assertTrue((t / "ssh").exists())
        self.assertIn("enable_uart=1", (t / "config.txt").read_text())
        self.assertIn("dtoverlay=dwc2", (t / "config.txt").read_text())
        cmd = (t / "cmdline.txt").read_text()
        self.assertEqual(cmd.count("\n"), 1, "cmdline.txt must stay one line")
        self.assertIn(f"g_ether.dev_addr={board.usb_macs('pi5')[1]}", cmd)
        board.customize_boot(t, "pi5", "u", "ssh-ed25519 K", [], "IN", uart=True, gadget=True)
        self.assertEqual((t / "cmdline.txt").read_text().count("g_ether.dev_addr"), 1, "idempotent")

    def test_gadget_script_is_valid_sh(self):
        for en in (True, False):
            r = subprocess.run(["sh", "-n"], input=board.gadget_script("02:b0:1:2:3:4", "02:b1:1:2:3:4", en), text=True,
                               capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_probe_script_is_valid_sh(self):
        self.assertEqual(subprocess.run(["sh", "-n"], input=board.PROBE, text=True).returncode, 0)
        r = subprocess.run(["sh", "-s"], input=board.PROBE, text=True, capture_output=True)
        f = board.parse_probe(r.stdout)
        self.assertTrue(f["arch"]); self.assertTrue(f["home"])


class Hotplug(unittest.TestCase):
    def setUp(self):
        self.t = sandbox(self)
        board.save_registry({"pi5": {"host": "pi5.local", "usb_mac": board.usb_macs("pi5")[1]},
                             "esp": {"kind": "mcu", "serial": "/dev/serial/by-id/usb-Silicon_Labs_CP2102-if00-port0"}})

    def test_pico_bootsel(self):
        ev = board.classify_usb_event({"ACTION": "add", "SUBSYSTEM": "usb", "DEVTYPE": "usb_device",
                                       "ID_VENDOR_ID": "2e8a", "ID_MODEL_ID": "0003"})
        self.assertEqual(ev[0], "Pico ready to flash")

    def test_serial_adapter(self):
        ev = board.classify_usb_event({"ACTION": "add", "SUBSYSTEM": "tty", "DEVNAME": "/dev/ttyUSB0",
                                       "ID_VENDOR_ID": "10c4", "ID_MODEL_ID": "ea60", "DEVLINKS": "/dev/serial/by-id/x"})
        self.assertIn("CP210x", ev[0]); self.assertEqual(ev[2][0][0], "open")

    def test_board_on_usb_cable_is_named(self):
        mac = board.usb_macs("pi5")[0].replace(":", "")
        ev = board.classify_usb_event({"ACTION": "add", "SUBSYSTEM": "net", "INTERFACE": f"enx{mac}", "ID_NET_NAME_MAC": f"enx{mac}"})
        self.assertEqual(ev[0], "pi5 on USB cable"); self.assertEqual([a[0] for a in ev[2]], ["ssh", "code", "files"])

    def test_ignores_noise(self):
        self.assertIsNone(board.classify_usb_event({"ACTION": "remove", "SUBSYSTEM": "tty"}))
        self.assertIsNone(board.classify_usb_event({"ACTION": "add", "SUBSYSTEM": "usb", "DEVTYPE": "usb_device",
                                                    "ID_VENDOR_ID": "046d", "ID_MODEL_ID": "c52b"}))   # a mouse


class JobsAndWatch(unittest.TestCase):
    def setUp(self): self.t = sandbox(self)

    def test_job_args(self):
        a = board.parse_job_args(["pi5", "--here", "--", "make", "-j4"])
        self.assertEqual((a.action, a.target, a.cmd, a.here), ("start", "pi5", ["make", "-j4"], True))
        a = board.parse_job_args(["log", "0101-x", "-f", "-n", "5"])
        self.assertEqual((a.action, a.target, a.follow, a.lines), ("log", "0101-x", True, 5))
        self.assertEqual(board.parse_job_args([]).action, "ls")

    def test_job_scripts_run_detached_and_report(self):
        """Run the real device-side shell locally (HOME = temp): exit code, log tail, quoting, running state, kill."""
        env = dict(os.environ, HOME=str(self.t))
        sh = lambda script: subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=10)
        self.assertIn("started", sh(board.job_start_script("0101-000000-aaaa", "echo 'it''s'; echo two; exit 3")).stdout)
        self.assertIn("started", sh(board.job_start_script("0101-000000-bbbb", "sleep 30", cd=str(self.t))).stdout)
        for _ in range(50):
            st = board.parse_job_status(sh(board.job_status_script(["0101-000000-aaaa", "0101-000000-bbbb", "0101-000000-cccc", "x;rm -rf ~"])).stdout)
            if st.get("0101-000000-aaaa", {}).get("state") == "done": break
            time.sleep(0.1)
        self.assertEqual(st["0101-000000-aaaa"], {"state": "done", "rc": 3, "tail": ["its", "two"]})
        self.assertEqual(st["0101-000000-bbbb"]["state"], "running")
        self.assertEqual(st["0101-000000-cccc"]["state"], "lost")
        self.assertEqual(len(st), 3, "an invalid ID never reaches the shell")
        pid = (self.t / ".board-jobs/0101-000000-bbbb.pid").read_text().strip()
        kill = next(l for l in board.SELF.read_text().splitlines() if "kill -TERM -$P" in l)
        self.assertNotIn("kill -TERM --", kill, "dash rejects `kill --`")
        sh(f"kill -TERM -{pid}")
        time.sleep(0.3)
        self.assertFalse(Path(f"/proc/{pid}").exists() and "sleep" in Path(f"/proc/{pid}/cmdline").read_text(errors="ignore"))

    def test_device_problems(self):
        now = 100000
        self.assertEqual(board.device_problems("pi", {"state": "offline"}, now - 60, now), {}, "brief drop: quiet")
        self.assertEqual(board.device_problems("pi", {"state": "offline"}, None, now), {}, "never seen: quiet")
        self.assertIn("dev-offline:pi", board.device_problems("pi", {"state": "offline"}, now - 3600, now))
        self.assertIn("dev-hostkey:pi", board.device_problems("pi", {"state": "hostkey"}, now, now))
        bad = board.device_problems("pi", {"state": "online", "temp_c": 83.0, "disk_free_kb": 5, "disk_total_kb": 100,
                                           "throttled": ["under-voltage now", "throttled since boot"]}, now, now)
        self.assertEqual(set(bad), {"dev-power:pi", "dev-hot:pi", "dev-disk:pi"})
        self.assertNotIn("since boot", bad["dev-power:pi"][0], "only problems happening now")
        self.assertEqual(board.device_problems("pi", {"state": "online", "temp_c": 50, "throttled": ["throttled since boot"]}, now, now), {})

    def test_watch_settings_round_trip(self):
        board.save_registry({"defaults": {"watch_nets": ["aa:bb:cc:dd:ee:ff Home Wi-Fi"]}, "pi": {"host": "pi.local", "alerts": True}})
        reg = board.load_registry()
        self.assertEqual(board.watch_nets(reg), {"aa:bb:cc:dd:ee:ff": "Home Wi-Fi"})
        self.assertTrue(reg["pi"]["alerts"])
        self.assertTrue(board.validate_device("pi", {"alerts": "yes"}))


class Network(unittest.TestCase):
    def test_only_own_networks(self):
        nets = [("wlo1", ipaddress.ip_interface("10.100.231.174/16"))]
        orig = board.local_nets
        board.local_nets = lambda: nets
        try:
            self.assertTrue(board.local_net_ok(ipaddress.ip_address("10.100.1.1")))
            self.assertTrue(board.local_net_ok(ipaddress.ip_network("10.100.231.0/24")))
            self.assertFalse(board.local_net_ok(ipaddress.ip_address("8.8.8.8")))
            self.assertFalse(board.local_net_ok(ipaddress.ip_network("1.1.1.0/24")))
        finally: board.local_nets = orig

    def test_port_lists_are_validated_before_expanding(self):
        self.assertEqual(board.parse_ports("22, 80,8000-8002,80"), [22, 80, 8000, 8001, 8002])
        for bad in ("100-1", "80-", "0", "1-1000000000", "x", ""):
            with self.assertRaises(board.Fail, msg=bad): board.parse_ports(bad)
        self.assertEqual(board.probe_ports("127.0.0.1", []), [])

    def test_custom_net_stays_inside_it(self):
        """--net 192.168.7.0/29: a VPN neighbour on another interface must not leak in; huge ranges are refused."""
        net = ipaddress.ip_network("192.168.7.0/29")
        saved = board.ping, board.neigh_states, board.local_nets, board.time.sleep
        board.ping = lambda ip, wait=1: False
        board.neigh_states = lambda: {"192.168.7.3": ("aa:bb:cc:00:00:03", ["REACHABLE"]),
                                      "10.9.0.99": ("aa:bb:cc:00:00:09", ["REACHABLE"]),
                                      "192.168.7.5": ("aa:bb:cc:00:00:05", ["PERMANENT"])}
        board.local_nets = lambda: [("wg0", ipaddress.ip_interface("10.9.0.1/24"))]
        board.time.sleep = lambda s: None
        try:
            self.assertEqual(board.live_hosts([("custom", net)], wide=False)[0], {"192.168.7.3"})
            self.assertIn("10.9.0.99", board.live_hosts([("custom", net)], wide=True)[0])
            with self.assertRaises(board.Fail): board.live_hosts([("custom", ipaddress.ip_network("10.0.0.0/16"))])
        finally: board.ping, board.neigh_states, board.local_nets, board.time.sleep = saved

    def test_probe_ports_finds_listener(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(); port = s.getsockname()[1]
        try: self.assertEqual(board.probe_ports("127.0.0.1", [port, 1]), [port])
        finally: s.close()

    def test_live_hosts_counts_arp_only_devices(self):
        """A phone that drops ping but answers ARP still counts; stale/failed entries don't."""
        net = ipaddress.ip_network("192.168.7.0/29")
        saved = board.ping, board.neigh_states, board.local_nets, board.time.sleep
        board.ping = lambda ip, wait=1: ip == "192.168.7.2"
        board.neigh_states = lambda: {"192.168.7.3": ("aa:bb:cc:00:00:03", ["REACHABLE"]),
                                      "192.168.7.4": ("aa:bb:cc:00:00:04", ["STALE"]),
                                      "10.9.9.9": ("aa:bb:cc:00:00:09", ["REACHABLE"])}
        board.local_nets = lambda: []
        board.time.sleep = lambda s: None
        try:
            alive, _ = board.live_hosts([("eth", net)])
            self.assertEqual(alive, {"192.168.7.2", "192.168.7.3"})
        finally: board.ping, board.neigh_states, board.local_nets, board.time.sleep = saved


class PathRace(unittest.TestCase):
    def listener(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(8); self.addCleanup(s.close)
        return s.getsockname()[1]

    def test_prefers_first_reachable_and_skips_dead(self):
        port = self.listener()
        host, s = board.race(["192.0.2.1", "127.0.0.1"], port, grace=0.3, timeout=2)   # TEST-NET-1 never answers
        self.assertEqual(host, "127.0.0.1"); s.close()

    def test_nothing_reachable(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        self.assertEqual(board.race(["127.0.0.1"], port, timeout=1), (None, None))


# ───────────────────────────── integration: real ssh to a throwaway device ─────────────────────────────
def docker_ok():
    if not shutil.which("docker"): return "docker not installed"
    if subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode != 0: return "docker not running"
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        r = subprocess.run(["docker", "build", "-q", "-t", IMAGE, "-"], input=DOCKERFILE, text=True, capture_output=True, timeout=300)
        if r.returncode != 0: return "couldn't build the test device image (offline?): " + r.stderr[-200:]
    return ""


SKIP = os.environ.get("BOARD_SKIP_DOCKER") and "BOARD_SKIP_DOCKER set" or docker_ok()


@unittest.skipIf(SKIP, SKIP)
class RealDevice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = Path(tempfile.mkdtemp(prefix="board-it-"))
        t = cls.t
        (t / ".ssh/config.d").mkdir(parents=True); os.chmod(t / ".ssh", 0o700)
        (t / "s").mkdir(mode=0o700)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(t / ".ssh/id_ed25519")], check=True)
        cls.cid = subprocess.run(["docker", "run", "-d", "--rm", "-p", "127.0.0.1::22", IMAGE], capture_output=True,
                                 text=True, check=True).stdout.strip()
        cls.port = int(subprocess.run(["docker", "port", cls.cid, "22"], capture_output=True, text=True).stdout.split(":")[-1])
        pub = (t / ".ssh/id_ed25519.pub").read_text()
        cls.dexec("sh", "-c", f"echo '{pub.strip()}' > /home/dev/.ssh/authorized_keys && chown dev /home/dev/.ssh/authorized_keys "
                              "&& chmod 600 /home/dev/.ssh/authorized_keys")
        (t / "sshcfg").write_text(f"Include {t}/.ssh/config.d/*\nHost *\n  IdentityFile {t}/.ssh/id_ed25519\n  IdentitiesOnly yes\n"
                                  f"  UserKnownHostsFile {t}/.ssh/known_hosts\n  ControlMaster auto\n  ControlPath {t}/s/%C\n"
                                  "  ControlPersist 60\n  ConnectTimeout 8\n")
        cls.env = dict(os.environ, HOME=str(t), BOARD_SSH_CONFIG=str(t / "sshcfg"), SSH_AUTH_SOCK="",
                       XDG_RUNTIME_DIR=str(t), PATH=os.environ["PATH"])
        for _ in range(50):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", cls.port)) == 0: break
            time.sleep(0.1)
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["ssh", "-F", str(cls.t / "sshcfg"), "-O", "exit", "dev1"], capture_output=True)
        subprocess.run(["docker", "rm", "-f", cls.cid], capture_output=True)
        shutil.rmtree(cls.t, True)

    @classmethod
    def dexec(cls, *a): return subprocess.run(["docker", "exec", cls.cid, *a], capture_output=True, text=True, check=True)

    def b(self, *a, input=None, timeout=60):
        return subprocess.run([sys.executable, str(SRC), *a], env=self.env, capture_output=True, text=True,
                              input=input, timeout=timeout)

    def test_1_add_learns_facts_via_proxy(self):
        r = self.b("add", "dev1", "127.0.0.1", "-u", "dev", "-p", str(self.port), "--project", "~/proj", "--tag", "lab", "-y")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("connected via", r.stdout)
        reg = json.loads(self.b("json", "devices").stdout)["dev1"]
        self.assertEqual(reg["home"], "/home/dev"); self.assertTrue(reg["arch"]); self.assertEqual(reg["kind"], "linux")
        self.assertIn("ProxyCommand", (self.t / ".ssh/config.d/10-devices").read_text())

    def test_2_run_in_project_and_tag(self):
        self.dexec("su", "dev", "-c", "mkdir -p /home/dev/proj")
        r = self.b("run", "dev1", "--", "pwd")
        self.assertEqual(r.stdout.strip(), "/home/dev/proj", r.stderr)
        r = self.b("run", "@lab", "--", "echo", "hi")
        self.assertIn("dev1", r.stdout); self.assertIn("hi", r.stdout); self.assertEqual(r.returncode, 0)

    def test_3_push_pull_sync(self):
        src = self.t / "work"; (src / "pkg").mkdir(parents=True)
        (src / "main.py").write_text("print('from device')\n"); (src / "pkg/a.txt").write_text("a")
        (src / "__pycache__").mkdir(); (src / "__pycache__/x.pyc").write_text("junk")
        r = self.b("sync", "dev1", "--local", str(src), "--once", "--run", "python3 main.py")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ls = self.dexec("ls", "-R", "/home/dev/proj").stdout
        self.assertIn("main.py", ls); self.assertIn("a.txt", ls); self.assertNotIn("__pycache__", ls, "ignores honoured")
        out = self.t / "back"; out.mkdir()
        r = self.b("pull", "dev1", "main.py", "--to", str(out))
        self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual((out / "main.py").read_text(), "print('from device')\n")
        r = self.b("push", "dev1", str(src / "pkg"), "--to", "~/elsewhere")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a.txt", self.dexec("ls", "/home/dev/elsewhere/pkg").stdout)

    def test_4_ports(self):
        self.dexec("sh", "-c", "cd /tmp && (python3 -m http.server 8765 >/dev/null 2>&1 &)")
        time.sleep(1)
        s = socket.socket(); s.bind(("127.0.0.1", 0)); lp = s.getsockname()[1]; s.close()
        r = self.b("ports", "dev1", f"{lp}:8765")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        import urllib.request
        body = urllib.request.urlopen(f"http://127.0.0.1:{lp}/", timeout=5).read()
        self.assertIn(b"Directory listing", body)
        self.assertIn("dev1", self.b("ports", "--list").stdout)
        self.assertEqual(self.b("ports", "dev1", "--close").returncode, 0)

    def test_5_info_and_ls(self):
        r = self.b("info", "dev1", "--json")
        self.assertEqual(json.loads(r.stdout)["status"]["state"], "online")
        r = self.b("ls")
        self.assertIn("dev1", r.stdout); self.assertIn("ms", r.stdout)

    def test_6_host_key_change_is_detected_and_forgettable(self):
        subprocess.run(["ssh", "-F", str(self.t / "sshcfg"), "-O", "exit", "dev1"], capture_output=True)
        self.dexec("sh", "-c", "rm /etc/ssh/ssh_host_* && ssh-keygen -A >/dev/null && kill -HUP 1")
        time.sleep(1)
        r = self.b("run", "dev1", "--", "true")
        self.assertEqual(r.returncode, board.HOSTKEY, r.stdout + r.stderr)
        self.assertIn("forget", r.stderr)
        self.assertEqual(self.b("forget", "dev1").returncode, 0)
        r = self.b("info", "dev1")     # interactive-less: trusts on first use again only via ensure_connected tty path
        r = subprocess.run(["ssh", "-F", str(self.t / "sshcfg"), "-o", "StrictHostKeyChecking=accept-new", "dev1", "true"],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_7_unreachable_is_explained(self):
        self.b("add", "ghost", "192.0.2.77", "-u", "x", "--offline")
        r = self.b("run", "ghost", "--", "true", timeout=40)
        self.assertEqual(r.returncode, board.OFFLINE, r.stderr)
        self.assertIn("not reachable", r.stderr)

    def test_8_init_project(self):
        proj = self.t / "app"; proj.mkdir(); (proj / "main.py").write_text("print(1)\n")
        r = self.b("init-project", str(proj), "--device", "dev1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tasks = json.loads((proj / ".vscode/tasks.json").read_text())
        self.assertIn("Deploy + run", [t["label"] for t in tasks["tasks"]])
        launch = json.loads((proj / ".vscode/launch.json").read_text())
        self.assertEqual(launch["configurations"][0]["type"], "debugpy")
        self.assertTrue((proj / ".boardignore").exists())
        r = self.b("init-project", str(proj), "--device", "dev1")       # again: merged, not duplicated
        tasks2 = json.loads((proj / ".vscode/tasks.json").read_text())
        self.assertEqual(len(tasks2["tasks"]), len(tasks["tasks"]))


    def test_8_trust_after_reflash(self):
        subprocess.run(["ssh", "-F", str(self.t / "sshcfg"), "-O", "exit", "dev1"], capture_output=True)
        self.dexec("sh", "-c", "rm /etc/ssh/ssh_host_* && ssh-keygen -A >/dev/null && kill -HUP 1")
        time.sleep(1)
        self.assertEqual(self.b("run", "dev1", "--", "true").returncode, board.HOSTKEY)
        chk = json.loads(self.b("trust", "dev1", "--check").stdout)
        self.assertTrue(chk["fingerprints"] and chk["fingerprints"][0].startswith("SHA256:"), chk)
        r = self.b("trust", "dev1", "-y")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.b("run", "dev1", "--", "true").returncode, 0)

    def test_8b_rename_keeps_trusted_key(self):
        r = self.b("mv", "dev1", "devx")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.b("run", "devx", "--", "echo", "ok")      # no terminal: an untrusted key would fail with HOSTKEY
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ok"), r.stderr)
        self.assertNotIn("Host dev1\n", (self.t / ".ssh/config.d/10-devices").read_text())
        self.assertEqual(self.b("mv", "devx", "dev1").returncode, 0)
        self.assertIn("already", self.b("mv", "dev1", "dev1").stderr)

    def test_8c_add_with_password_like_the_panel(self):
        """The Remote panel's add form: password via SSH_ASKPASS, key copied, then key login works."""
        try:
            spec = importlib.util.spec_from_file_location("panel", ROOT / "config/desktop/panel.py")
            panel = importlib.util.module_from_spec(spec); spec.loader.exec_module(panel)
        except Exception as e: self.skipTest(f"panel needs GTK: {e}")
        self.dexec("sh", "-c", "echo 'dev:s3cret-pw' | chpasswd && cp /home/dev/.ssh/authorized_keys /tmp/ak && : > /home/dev/.ssh/authorized_keys")
        subprocess.run(["ssh", "-F", str(self.t / "sshcfg"), "-O", "exit", "dev1"], capture_output=True)  # same box: no reused login
        env = dict(self.env); os_env = os.environ.copy()
        try:
            os.environ.clear(); os.environ.update(env)
            e2 = panel.askpass_env("s3cret-pw")
        finally:
            os.environ.clear(); os.environ.update(os_env)
        r = subprocess.run([sys.executable, str(SRC), "add", "dev3", "127.0.0.1", "-u", "dev", "-p", str(self.port), "--update", "-y"],
                           env=e2, capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ssh-ed25519", self.dexec("cat", "/home/dev/.ssh/authorized_keys").stdout)
        self.assertEqual(self.b("run", "dev3", "--", "true").returncode, 0)
        r = self.b("rm", "dev3", "-y", "--forget")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("dev3", self.b("json", "names").stdout)


    def test_9_background_job(self):
        r = self.b("job", "dev1", "--", "echo out; sleep 1; echo done; exit 2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        jid = r.stdout.split("job ")[1].split()[0]
        self.assertEqual(json.loads(self.b("job", "ls", "--json").stdout)[jid]["state"], "running")
        time.sleep(2)
        fresh = json.loads(self.b("job", "check").stdout)
        self.assertEqual((fresh[jid]["state"], fresh[jid]["rc"], fresh[jid]["tail"]), ("done", 2, ["out", "done"]))
        self.assertEqual(json.loads(self.b("job", "check").stdout), {}, "reported once")
        self.assertIn("out", self.b("job", "log", jid).stdout)
        r = self.b("job", "dev1", "sleep", "60"); jid2 = r.stdout.split("job ")[1].split()[0]
        self.assertEqual(self.b("job", "kill", jid2).returncode, 0)
        time.sleep(0.5)
        self.assertEqual(json.loads(self.b("job", "ls", "--json").stdout)[jid2]["state"], "stopped")
        self.assertEqual(json.loads(self.b("job", "check").stdout), {}, "a job you stopped doesn't notify")
        self.assertEqual(self.b("job", "forget", jid).returncode, 0)
        self.assertNotIn(jid, json.loads(self.b("job", "ls", "--json").stdout))

    def test_9b_watch_alerts(self):
        self.assertEqual(self.b("watch", "on", "dev1").returncode, 0)
        alerts = json.loads(self.b("watch", "check").stdout)
        du = shutil.disk_usage(str(Path.home()))         # the test "device" is this laptop: its real disk can be < 10 % free
        if du.free / du.total < 0.1: alerts.pop("dev-disk:dev1", None)
        self.assertEqual(alerts, {}, "healthy device: no alerts")
        self.assertTrue(json.loads(self.b("json", "devices").stdout)["dev1"]["alerts"])
        self.b("watch", "off", "dev1")
        self.assertNotIn("alerts", json.loads(self.b("json", "devices").stdout)["dev1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
