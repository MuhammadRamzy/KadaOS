"""Offline checks for the myos-run launcher providers (calc / hash / base / exec). No GTK."""
import importlib.util, sys, unittest
from pathlib import Path

_a = sys.argv; sys.argv = ['run']
try:
    spec = importlib.util.spec_from_file_location('run', Path(__file__).resolve().parents[1] / 'config/desktop/run.py')
    run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
finally:
    sys.argv = _a


class Calc(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(run.calc('2+2*3'), '= 8')
        self.assertEqual(run.calc('(2+2)*3'), '= 12')
        self.assertEqual(run.calc('2^10'), '= 1,024')
        self.assertEqual(run.calc('10/4'), '= 2.5')
        self.assertEqual(run.calc('1500*15/100'), '= 225')

    def test_functions_and_constants(self):
        self.assertTrue(run.calc('sqrt(2)').startswith('= 1.414'))
        self.assertEqual(run.calc('abs(-5)'), '= 5')

    def test_rejects_non_math(self):
        for q in ('hello', '42', 'firefox', '', 'ls -la', 'import os'):
            self.assertIsNone(run.calc(q), q)

    def test_safe_no_code_execution(self):
        for q in ('__import__("os")', 'open("x")', '[].__class__'):
            self.assertIsNone(run.calc(q), q)


class HashAndBase(unittest.TestCase):
    def test_hash(self):
        self.assertEqual(run.hash_q('md5 abc'), ('md5', '900150983cd24fb0d6963f7d28e17f72'))
        self.assertEqual(run.hash_q('SHA1 abc')[0], 'sha1')
        self.assertIsNone(run.hash_q('abc'))
        self.assertIsNone(run.hash_q('crc32 abc'))

    def test_base(self):
        self.assertEqual(run.base_q('255 to hex'), '0xff')
        self.assertEqual(run.base_q('0x1f to dec'), '31')
        self.assertEqual(run.base_q('10 to bin'), '0b1010')
        self.assertEqual(run.base_q('0b1010 to oct'), '0o12')
        self.assertIsNone(run.base_q('hello to hex'))
        self.assertIsNone(run.base_q('255'))


class Units(unittest.TestCase):
    def test_conversions(self):
        self.assertEqual(run.unit_q('100 c to f'), '212 °F')
        self.assertEqual(run.unit_q('0 c to k'), '273.15 °K')
        self.assertEqual(run.unit_q('1 gb to mb'), '1,024 mb')
        self.assertEqual(run.unit_q('2 hours to min'), '120 min')
        self.assertTrue(run.unit_q('10 km to mi').startswith('6.21'))

    def test_rejects_non_units(self):
        self.assertIsNone(run.unit_q('255 to hex'))   # base_q's job, not units
        self.assertIsNone(run.unit_q('hello to mi'))
        self.assertIsNone(run.unit_q('5 kg to ft'))   # cross-category


class Emoji(unittest.TestCase):
    def test_search(self):
        self.assertEqual(run.emoji_search(':fire:')[0], ('🔥', 'Fire'))
        self.assertTrue(any(ch == '🚀' for ch, _ in run.emoji_search('emoji rocket')))
        self.assertTrue(any('heart' in name.lower() for _, name in run.emoji_search('emoji heart')))

    def test_only_on_prefix(self):
        self.assertEqual(run.emoji_search('firefox'), [])
        self.assertEqual(run.emoji_search('emoji'), [])


class Exec(unittest.TestCase):
    def test_strips_field_codes(self):
        self.assertEqual(run.clean_exec('firefox %u'), ['firefox'])
        self.assertEqual(run.clean_exec('kitty --class x %U -e foo'), ['kitty', '--class', 'x', '-e', 'foo'])
        self.assertEqual(run.clean_exec('app -f %F --icon %i'), ['app', '-f', '--icon'])



class Actions(unittest.TestCase):
    def test_every_action_command_is_installed_by_the_setup(self):
        """Each {B}/NAME the launcher runs is created by some install script (no dead entries after a rename)."""
        import re
        root = Path(__file__).resolve().parents[1]
        run = (root / "config/desktop/run.py").read_text()
        names = set(re.findall(r"\{B\}/([\w.-]+)", run))
        installers = "\n".join(p.read_text(errors="ignore") for p in (root / "scripts").glob("*") if p.is_file())
        installers += "\n".join("bin/" + p.name for d in ("agents", "ai", "desktop") for p in (root / "config" / d / "bin").glob("*"))  # copied as folders
        missing = sorted(n for n in names if not re.search(rf"(\.local/bin/{re.escape(n)}\b|bin/{re.escape(n)}\b)", installers))
        self.assertEqual(missing, [])


class Universal(unittest.TestCase):
    CONF = """$mod = SUPER
bindd = $mod CTRL, G, Projects: every repo · CI and PRs, exec, ~/.local/bin/myos-panel projects
bindd = $mod, Space, App launcher, exec, $launcher
bind = $mod, Q, killactive
binddm = $mod, mouse:272, Move window, movewindow
bindd = $mod SHIFT, left, Move window left, movewindow, l
"""

    def test_parse_binds(self):
        b = run.parse_binds(self.CONF)
        self.assertEqual([x["desc"] for x in b], ["Projects: every repo · CI and PRs", "App launcher", "Move window left"])
        self.assertEqual(b[0]["combo"], "Super + Ctrl + G"); self.assertEqual(b[0]["dispatcher"], "exec")
        self.assertEqual((b[2]["combo"], b[2]["dispatcher"], b[2]["arg"]), ("Super + Shift + ←", "movewindow", "l"))
        self.assertEqual(run.combo_label("", "XF86AudioRaiseVolume"), "Volume Up key")
        self.assertEqual(run.combo_label("", "XF86MonBrightnessDown"), "Screen Brightness Down key")

    def test_parse_the_real_config(self):
        conf = (Path(__file__).resolve().parents[1] / "config/hypr/hyprland.conf").read_text()
        binds = run.parse_binds(conf)
        self.assertGreater(len(binds), 80, "every described shortcut becomes searchable")
        self.assertTrue(all(b["dispatcher"] and " " not in b["dispatcher"] for b in binds))

    def test_score(self):
        self.assertGreater(run.score("blu", "Bluetooth devices"), run.score("blu", "Settings: Bluetooth"))
        self.assertIsNotNone(run.score("bluetoth", "Bluetooth devices"), "typo still finds it")
        self.assertIsNotNone(run.score("volume", "Settings: Sound", "volume audio"), "keywords count")
        self.assertIsNone(run.score("zzz", "Bluetooth devices"))
        self.assertGreater(run.score("lock", "Lock screen"), run.score("lock", "Clock"))

    def test_frecency(self):
        h = {}
        for _ in range(5): run.bump(h, "a:Lock screen", now=1000.0)
        self.assertGreater(run.frecency_boost(h["a:Lock screen"], now=1000.0), 15)
        self.assertLess(run.frecency_boost(h["a:Lock screen"], now=1000.0 + 86400 * 60), 2, "fades when unused")
        self.assertEqual(run.frecency_boost(None), 0.0)

    def test_web_search(self):
        self.assertEqual(run.web_search("best biryani kochi")[:2], ("Google", "https://www.google.com/search?q=best+biryani+kochi"))
        self.assertEqual(run.web_search("yt lofi beats")[0], "YouTube")
        self.assertEqual(run.web_search("gh")[0], "Google", "an engine word alone is just a search")
        self.assertTrue(run.looks_like_url("github.com/foo")); self.assertTrue(run.looks_like_url("https://x.y/z"))
        self.assertFalse(run.looks_like_url("hello world")); self.assertFalse(run.looks_like_url("file.txt"))

    def test_recent_files(self):
        x = """<bookmark href="file:///home/u/a%20b.pdf" added="x" modified="2026-11-02T10:00:00Z"/>
<bookmark href="file:///home/u/new.png" added="x" modified="2026-11-20T10:00:00Z"/>
<bookmark href="https://example.com" added="x" modified="2026-11-21T10:00:00Z"/>"""
        self.assertEqual(run.recent_files(x), ["/home/u/new.png", "/home/u/a b.pdf"])


class Alive(unittest.TestCase):
    def test_commands(self):
        self.assertIn("set-volume @DEFAULT_AUDIO_SINK@ 30%", run.parse_command("volume 30")[2])
        self.assertIn("brightnessctl -q set 70%", run.parse_command("brightness 70%")[2])
        t = run.parse_command("timer 10 min tea"); self.assertEqual(t[0], "Timer: 10 min · tea"); self.assertIn("--on-active=600s", t[2])
        self.assertIn("--on-active=90s", run.parse_command("timer 90 s")[2])
        r = run.parse_command("remind me in 2 hours to stretch"); self.assertIn("--on-active=7200s", r[2]); self.assertIn("stretch", r[2])
        import time as T
        noon = T.mktime((2026, 11, 26, 12, 0, 0, 0, 0, -1))
        self.assertEqual(run.parse_command("remind me at 6:30 pm to call Ali", now=noon)[1], "Today")
        self.assertIn("--on-active=23400s", run.parse_command("remind me at 18:30 to x", now=noon)[2])
        self.assertEqual(run.parse_command("remind me at 9:00 to x", now=noon)[1], "Tomorrow")
        self.assertEqual(run.parse_command("wifi off")[2], "nmcli radio wifi off")
        self.assertIn("stop-port 3000", run.parse_command("kill :3000")[2])
        self.assertIsNone(run.parse_command("volume of a sphere")); self.assertIsNone(run.parse_command("best biryani"))
        self.assertIn("'call Ali; rm -rf ~'", run.parse_command("remind me in 1 min to call Ali; rm -rf ~")[2], "text is quoted, never run")

    def test_live_state(self):
        st = {"night": True, "dnd": False, "profile": "present", "wifi": "Home", "battery": (41, "Discharging"), "disk_free": 12e9}
        self.assertEqual(run.live_sub("Night light: toggle", st), "On now · Enter turns it off")
        self.assertEqual(run.live_sub("Do not disturb: toggle", st), "Off now · Enter turns it on")
        self.assertEqual(run.live_sub("Profile: Presenting (no notifications, no sleep)", st), "● Current profile")
        self.assertIsNone(run.live_sub("Profile: AI work", st))
        self.assertEqual(run.live_sub("Wi-Fi networks", st), "Connected: Home")
        self.assertEqual(run.live_sub("Battery health", st), "41 % · discharging")
        self.assertIsNone(run.live_sub("Lock screen", st))

    def test_suggestions(self):
        st = {"disk_free": 9e9, "battery": (18, "Discharging"), "profile": "auto", "night": False, "review": 2}
        got = [t for t, _ in run.suggestions(st, hour=22)]
        self.assertEqual(got[:2], ["Agent tasks: give Claude or Codex a task", "Storage: free up space"])
        self.assertIn("Profile: Battery saver", got); self.assertIn("Night light: toggle", got)
        self.assertEqual(run.suggestions({"disk_free": 90e9}, hour=14), [], "nothing to say: nothing shown")

    def test_chrome_profile(self):
        ls = '{"profile": {"last_used": "Profile 3", "info_cache": {"Default": {"name": "Alex"}, "Profile 3": {"name": "Work"}}}}'
        self.assertEqual(run.chrome_profile(ls), "Profile 3")
        self.assertEqual(run.chrome_profile(ls, "Alex"), "Default", "pick by name")
        self.assertEqual(run.chrome_profile(ls.replace("Profile 3\", \"info", "Gone\", \"info"), ""), "Default", "last used gone: first known")
        self.assertEqual(run.chrome_profile("not json"), "Default")

    def test_ai_helpers(self):
        self.assertEqual(run.parse_pick('{"pick": 2}', 5), 1); self.assertIsNone(run.parse_pick('{"pick": 0}', 5))
        self.assertIsNone(run.parse_pick('{"pick": 9}', 5)); self.assertIsNone(run.parse_pick("sorry", 5))
        self.assertTrue(run.looks_like_sentence("make the screen dimmer")); self.assertFalse(run.looks_like_sentence("12 * 7 + 3"))
        self.assertFalse(run.looks_like_sentence("chrome")); self.assertFalse(run.looks_like_sentence("> ls -la /tmp"))
        self.assertAlmostEqual(run.cosine([1, 0], [1, 0]), 1.0); self.assertAlmostEqual(run.cosine([1, 0], [0, 1]), 0.0)
        self.assertIn('User: "dim it"', run.intent_prompt("dim it", ["A", "B"]))


class Coverage(unittest.TestCase):
    """Everything the setup offers is one search away in Super+Space (directly, or through a keyboard shortcut it lists)."""
    INTERNAL = {"agent-notify": "agent hook", "agent-status": "bar helper", "ai-status": "bar helper", "myos-pick": "picker used by menus",
                "myos-panel": "opens pages (each page checked)", "nvrun": "prefix for GPU commands", "sops": "used by scripts",
                "rclone": "used by Drive", "fd": "used by the launcher", "bat": "used by agent-review"}

    def setUp(self):
        import re
        root = Path(__file__).resolve().parents[1]
        self.run = (root / "config/desktop/run.py").read_text()
        self.reach = self.run + (root / "config/hypr/hyprland.conf").read_text()
        self.root, self.re = root, re

    def reachable(self, needle):
        return self.re.search(rf"(?<![\w-]){self.re.escape(needle)}(?![\w-])", self.reach) is not None

    def test_every_panel_page(self):
        import ast
        src = (self.root / "config/desktop/panel.py").read_text()
        pages = ast.literal_eval(self.re.search(r"^PAGES = (\(.*?\))", src, self.re.M).group(1))
        self.assertEqual([p for p in pages if not self.reachable(f"myos-panel {p}")], [])

    def test_every_command_the_setup_installs(self):
        names = {p.name for d in ("agents", "ai", "desktop") for p in (self.root / "config" / d / "bin").glob("*") if not p.name.startswith("_")}
        for sh_ in (self.root / "scripts").glob("install-*.sh"):
            names |= set(self.re.findall(r"ln -sfn \S+ ~/\.local/bin/([\w.-]+)", sh_.read_text()))
        missing = sorted(n for n in names - {"__pycache__"} if n not in self.INTERNAL and not self.reachable(n))
        self.assertEqual(missing, [])

    def test_subcommands_of_the_big_tools(self):
        want = {"seclab": "new scope run finding findings report wifi ctf lab ai menu", "board": "ls ssh code files info doctor serial net",
                "phone": "send clip find mirror get push doctor", "fai": "cmd rag status unload index", "tasks": "",
                "profile": "ai battery present auto", "tidy": "--apply", "monitors": "save", "services": "who stop-port"}
        missing = [f"{tool} {sub}" for tool, subs in want.items() for sub in (subs.split() or [""])
                   if not self.re.search(rf"{self.re.escape(tool)}\b[^\n]{{0,6}}{self.re.escape(sub)}", self.run)]
        self.assertEqual(missing, [])

    def test_every_layout_and_script_folder(self):
        for script in ("backup.sh", "verify-backups.sh", "ros-lyrical-env.sh", "space-ros-shell.sh", "drive-connect.sh", "desktop-check.sh"):
            self.assertIn(script, self.run)

if __name__ == '__main__':
    unittest.main()
