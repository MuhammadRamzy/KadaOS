#!/usr/bin/env python3
"""Off-screen UI/UX audit of every native KadaOS app (run through tests/run-all.sh).

  python3 tests/ui_audit.py              # driver: builds the sandbox, runs every scenario
  python3 tests/ui_audit.py app NAME OUT # one scenario, in-process (the driver calls this)

Each app starts normally inside a sandbox: throwaway HOME and runtime dir, GTK broadway (no
screen), a private D-Bus that can't auto-start services, portals off, live-session variables
removed, and stub commands first on PATH. Read-only `hyprctl`/`systemctl` queries pass through so
real shortcuts show; anything that changes the system is blocked and reported. Your clipboard is
replaced by sample data. After the app settles, every window is screenshotted and checked.
"""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DESKTOP, AI = ROOT / "config/desktop", ROOT / "config/ai"

# name: (entry, argv, stdin, settle seconds, steps). Step: (text to type, must see, must not see)
SCENARIOS = {
    "launcher": ("run", ["run.py"], None, 2.0, [
        ("hydration", ["Hydration: drank water"], []),
        ("pad control", ["Pad control: laptop mouse + keyboard on the tablet"], ["Hydration: drank water"]),
        ("wi-fi", ["Wi-Fi networks"], []),
        ("agent", ["Agent tasks: give Claude or Codex a task"], []),
        ("record", ["Record screen (start / stop)"], []),
        ("trust", ["Network trust: Home / Work / Public"], []),
        ("tidy", ["Downloads: tidy (preview)", "Downloads: tidy now"], []),
        ("bluetoth", ["Bluetooth devices"], []),
        ("volume", ["Settings: Sound"], []),
        ("move window left", ["Move window left", "Keyboard shortcut", "Super", "Shift", "←"], []),
        ("best biryani kochi", ["Search Google for “best biryani kochi”", "Ask the assistant: best biryani kochi"], []),
        ("yt lofi", ["Search YouTube for “lofi”"], []),
        ("help", ["Enter on text that matches nothing searches Google in Chrome"], []),
        ("? why is my disk full", ["Ask the assistant: why is my disk full"], ["Search Google"]),
        ("> htop", ["Run in a terminal: htop"], []),
        ("git status", ["Run in a terminal: git status"], []),
        ("make the screen dimmer", ["Search Google for “make the screen dimmer”"], ["Run in a terminal: make the screen dimmer"]),
        ("volume 30", ["Set volume to 30 %"], []),
        ("timer 10 min tea", ["Timer: 10 min · tea"], []),
        ("remind me in 20 min to call Ali", ["Remind me in 20 min: call Ali"], []),
        ("kill 3000", ["Stop what's using port 3000"], []),
        ("volume", ["Type a value: volume 30"], []),
        ("nmap", ["Security tool: nmap", "Security recipe: Quick port scan (top 100)"], []),
        ("ocr", ["Read text from the screen (OCR, copies it)"], []),
        ("ros", ["ROS 2 terminal (Lyrical)"], []),
        ("ring my phone", ["Phone: ring it (find my phone)"], []),
        ("ssh", ["Remote: terminal on a device…"], []),
        ("hyprland", ["Edit: Shortcuts and window rules (Hyprland)"], []),
    ]),
    "cheatsheet": ("cheatsheet", ["cheatsheet.py"], None, 2.0, [
        ("pad control", ["Pad control on/off"], []),
    ]),
    "picker-list": ("pick", ["pick.py", "--list", "--title", "Sample menu"], "Alpha\tfolder-symbolic\tfirst\nBravo\nCharlie\n", 1.5, [
        ("bra", ["Bravo"], ["Alpha", "Charlie"]),
    ]),
    "picker-grid": ("pick", ["pick.py", "--grid", "--title", "Sample grid"],
                    "".join(f"Tile {i}\tfolder-symbolic\n" for i in range(1, 7)), 1.5, [
        ("tile 4", ["Tile 4"], ["Tile 1"]),
    ]),
    "picker-input": ("pick", ["pick.py", "--input", "--title", "Rename file"], None, 1.5, []),
    "panel-wifi": ("panel", ["panel.py", "wifi"], None, 2.5, []),
    "panel-bluetooth": ("panel", ["panel.py", "bluetooth"], None, 2.5, []),
    "panel-clipboard": ("panel", ["panel.py", "clipboard"], None, 2.5, [
        ("example", ["https://example.com"], ["Hello from the sandbox clipboard"]),
    ]),
    "panel-calendar": ("panel", ["panel.py", "calendar"], None, 2.5, []),
    "panel-inbox": ("panel", ["panel.py", "inbox"], None, 2.5, []),
    "panel-remote": ("panel", ["panel.py", "remote"], None, 3.0, [
        ("pi", ["pi5", "pi-zero"], ["jetson"]),
    ]),
    "panel-remote-empty": ("panel", ["panel.py", "remote"], None, 2.5, []),
    "panel-remote-nearby": ("panel", ["panel.py", "remote"], None, 3.5, []),
    "panel-remote-setup": ("panel", ["panel.py", "remote"], None, 2.5, []),
    "panel-remote-add": ("panel", ["panel.py", "remote"], None, 2.5, []),
    "panel-remote-detail": ("panel", ["panel.py", "remote"], None, 3.5, []),
    "panel-remote-edit": ("panel", ["panel.py", "remote"], None, 3.5, []),
    "panel-phone": ("panel", ["panel.py", "phone"], None, 2.5, []),
    "panel-phone-away": ("panel", ["panel.py", "phone"], None, 2.5, []),
    "panel-phone-setup": ("panel", ["panel.py", "phone"], None, 2.5, []),
    "panel-storage": ("panel", ["panel.py", "storage"], None, 2.5, []),
    "panel-security": ("panel", ["panel.py", "security"], None, 2.5, []),
    "panel-battery": ("panel", ["panel.py", "battery"], None, 2.5, []),
    "panel-projects": ("panel", ["panel.py", "projects"], None, 2.5, []),
    "panel-services": ("panel", ["panel.py", "services"], None, 2.5, []),
    "panel-tasks": ("panel", ["panel.py", "tasks"], None, 2.5, []),
    "file-actions": ("fileactions", ["fileactions.py"], None, 2.0, []),
    "chat": ("chat", ["chat.py"], None, 3.5, [
        ("/la", ["/layout"], []),
    ]),
    "chat-sample-conversation": ("chat", ["chat.py"], None, 3.5, []),
    "hydration": ("hydration_panel", ["hydration.py"], None, 1.5, []),
}
# run only when named (python3 tests/ui_audit.py launcher-live-ai): they use the real local AI, whose answers vary
EXTRA_SCENARIOS = {
    "launcher-live-ai": ("run", ["run.py"], None, 8.0, [("make the screen dimmer", ["✦ Brightness down"], ["Run in a terminal: make the screen dimmer"])]),
}
MUST_SEE_ON_OPEN = {
    "launcher": ["Search anything, or just say what you want", "ESSENTIALS", "Clipboard history", "TIP", "Esc close"],
    "picker-list": ["Sample menu", "Alpha", "Bravo"], "picker-grid": ["Sample grid", "Tile 6"],
    "picker-input": ["Rename file"], "panel-clipboard": ["Hello from the sandbox clipboard"],
    "chat": ["What can I do for you?", "Ask anything"], "hydration": ["Reminder service is offline"],
    "chat-sample-conversation": ["Sandbox sample chat", "Show me a table and a command", "rg", "search", "echo hello"],
    "file-actions": ["sample.png"],
    "panel-remote": ["Remote", "pi5", "jetson", "pi-zero", "Raspberry Pi 5", "48 °C", "4 devices · 2 online"],
    "panel-remote-empty": ["No devices yet", "Find devices"],
    "panel-remote-nearby": ["Find devices", "Ethernet cable", "Laptop hotspot", "USB cable", "raspberrypi.local", "Add", "no SSH",
                            "no cable in eno1", "Add by name or IP"],
    "panel-remote-setup": ["Set up", "First, your SSH key", "Create key", "Not installed yet"],
    "panel-remote-add": ["Add a device", "Device password", "Add device"],
    "panel-remote-detail": ["pi5", "Raspberry Pi 5", "via USB cable", "48 °C", "Terminal", "VS Code", "Files", "Serial console",
                            "Mount as a folder", "Send a file", "Open a device port", "Edit details", "Reboot", "Remove"],
    "panel-phone": ["Phone", "Pixel 8", "Connected over Wi-Fi · 64% · charging", "Send files", "Send clipboard", "Find phone",
                    "Mirror screen", "Received files", "Copy the phone's latest download", "Send alerts", "When the laptop is locked"],
    "panel-phone-away": ["Pixel 8", "Not reachable", "Open KDE Connect on the phone", "Add devices by IP → 192.168.1.20"],
    "panel-phone-setup": ["Set up your phone", "Set up"],
    "panel-battery": ["Battery", "92%", "Good · holds 64.5 of 70.1 Wh it had when new", "Right now", "Charge cycles", "312",
                      "about 4.1 years until 80 %", "Make it last"],
    "panel-projects": ["Projects", "4 repos · 2 need attention", "Needs attention", "webshop", "main · 3 changed · ↑2 to push · 2 h ago",
                       "api-server", "CI failing", "Up to date", "notes"],
    "panel-services": ["Services", "Listening", ":3000  node", "vite --port 3000", "local only", ":11434  ollama", "local AI models",
                       "Docker", "webshop", "all 2 running", "searxng"],
    "panel-tasks": ["Agent tasks", "New task", "Project", "webshop", "Agent", "claude", "What should it do?", "Start",
                    "Add a dark mode toggle", "Ready to review · claude · webshop · 3 files changed", "Fix the flaky login test",
                    "Working · codex · api-server", "Done", "Rename the config loader"],
    "panel-security": ["Security", "1 thing to fix soon", "10 good · 2 worth fixing · 1 fix soon", "To look at", "Disk encryption",
                       "Admin without a password", "Looking good", "Firewall", "SSH key"],
    "panel-storage": ["Storage", "26.8 GB free", "Free up 13.8 GB", "Docker build cache", "npm download cache",
                      "Chrome's disk cache", "Needs your password", "Downloaded system packages", "Big files in Downloads",
                      "Find duplicate files"],
    "panel-remote-edit": ["Edit pi5", "Address (name.local or IP)", "Project folder on the device", "Save"],
}

BLOCK = ("notify-send wtype ydotool xdg-open gtk-launch gio gnome-control-center nautilus zenity rofi setsid "
         "swaync-client brightnessctl wpctl pactl playerctl pkexec sudo loginctl rfkill nmcli bluetoothctl docker "
         "ollama adb scrcpy tailscale kitty ptyxis code xdg-mime blueman-manager hyprpicker grim slurp swappy "
         "powerprofilesctl wl-copy shutdown reboot poweroff").split()


# ───────────────────────────── driver ─────────────────────────────
def build_sandbox(base):
    home, run, stub = base / "home", base / "run", base / "bin"
    for d in (home / ".config", home / ".local/share", home / ".local/bin", stub):
        d.mkdir(parents=True)
    run.mkdir(mode=0o700)
    real = Path.home()
    for name in ("gtk-4.0", "gtk-3.0", "dconf"):  # copies, so nothing can write back to your settings
        if (real / ".config" / name).exists():
            shutil.copytree(real / ".config" / name, home / ".config" / name, dirs_exist_ok=True)
    if (real / ".local/share/fonts").exists():
        (home / ".local/share/fonts").symlink_to(real / ".local/share/fonts")
    shutil.copytree(ROOT / "config/hypr", home / ".config/hypr", ignore=shutil.ignore_patterns("__pycache__"))
    (home / ".config/local-ai").mkdir()
    cfg = real / ".config/local-ai/config.json"
    if cfg.exists():
        shutil.copy(cfg, home / ".config/local-ai/config.json")
    chats = home / ".local/share/local-ai/chats"
    chats.mkdir(parents=True)
    now = time.time()
    (chats / "sample.json").write_text(json.dumps({"id": "sample", "title": "Sandbox sample chat", "created": now - 60,
        "updated": now, "messages": [
            {"role": "user", "content": "Show me a table and a command", "time": now - 50},
            {"role": "assistant", "time": now - 40, "content":
             "| Tool | Use |\n|---|---|\n| rg | search |\n| fd | find |\n\n```sh\necho hello\n```\n\nSee https://example.com"}]}))
    (home / ".local/bin/myos-hydration").write_text("#!/bin/sh\nexit 1\n")
    (home / ".local/bin/myos-hydration").chmod(0o755)
    (base / "sample.png").write_bytes(subprocess.run([sys.executable, "-c",
        "import io,PIL.Image as I,sys;b=io.BytesIO();I.new('RGB',(64,64),(40,90,200)).save(b,'PNG');sys.stdout.buffer.write(b.getvalue())"],
        capture_output=True, check=True).stdout)
    log = base / "calls.log"
    real_run = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    def write(name, body):
        (stub / name).write_text("#!/bin/sh\n" + body)
        (stub / name).chmod(0o755)
    for name in BLOCK:
        write(name, f'echo "BLOCKED {name} $*" >> "{log}"\nexit 0\n')
    # the security catalogue + recipes the launcher lists (read-only)
    (home / ".local/share/security-workbench").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "config/security/tools.json", home / ".local/share/security-workbench/tools.json")
    write("seclab", f'[ "$1" = recipes ] && exec python3 "{ROOT / "config/security/seclab"}" recipes; echo "BLOCKED seclab $*" >> "{log}"\n')
    (home / ".local/bin/seclab").write_text(f'#!/bin/sh\nexec "{stub}/seclab" "$@"\n'); (home / ".local/bin/seclab").chmod(0o755)
    # read-only state queries the launcher shows ("Do not disturb: on now", "Connected: <Wi-Fi>"): canned, not blocked
    write("swaync-client", f'case " $* " in *" -D "*) echo false;; *) echo "BLOCKED swaync-client $*" >> "{log}";; esac\n')
    write("nmcli", f'case " $* " in *" con show --active "*) echo "Sample Wi-Fi:802-11-wireless";; *) echo "BLOCKED nmcli $*" >> "{log}";; esac\n')
    write("hyprctl", f'''case " $* " in
  *" dispatch "*|*" keyword "*|*" reload "*|*" kill "*|*" output "*|*" setcursor "*|*" switchxkblayout "*|*" notify "*|*" plugin "*|*" setprop "*|*--batch*)
    echo "BLOCKED hyprctl $*" >> "{log}"; echo ok; exit 0;;
esac
HYPRLAND_INSTANCE_SIGNATURE="{sig}" XDG_RUNTIME_DIR="{real_run}" exec /usr/bin/hyprctl "$@"
''')
    write("systemctl", f'''case " $* " in
  *" is-active "*|*" is-enabled "*|*" status "*|*" show "*|*" list-units "*|*" list-timers "*|*" cat "*)
    XDG_RUNTIME_DIR="{real_run}" exec /usr/bin/systemctl "$@";;
esac
echo "BLOCKED systemctl $*" >> "{log}"; exit 0
''')
    write("cliphist", f'''case "$1" in
  list) printf '3\\tHello from the sandbox clipboard\\n2\\thttps://example.com\\n1\\tsudo apt update\\n';;
  decode) cat >/dev/null; printf 'Hello from the sandbox clipboard';;
  *) echo "BLOCKED cliphist $*" >> "{log}";;
esac
''')
    write("wl-paste", 'printf ""\n')
    # board: canned devices for the Remote panel (BOARD_FAKE=empty → none)
    write("board", f'''[ "$BOARD_FAKE" = empty ] && [ "$2" != links ] && {{ echo '{{}}'; exit 0; }}
case "$1 $2" in
  "json devices") cat <<'J'
{{"pi5": {{"host": "pi5.local", "user": "pi", "kind": "pi", "model": "Raspberry Pi 5 Model B Rev 1.0", "tags": ["lab"]}},
 "jetson": {{"host": "10.0.0.20", "kind": "jetson", "model": "NVIDIA Jetson Orin Nano"}},
 "pi-zero": {{"host": "pi-zero.local", "kind": "pi", "model": "Raspberry Pi Zero 2 W"}},
 "esp-weather": {{"kind": "mcu", "serial": "/dev/serial/by-id/usb-Silicon_Labs_CP2102-if00"}}}}
J
  ;;
  "json status") cat <<'J'
{{"pi5": {{"state": "online", "via": "USB cable", "ms": 2, "temp_c": 48.2, "load": 0.3, "disk_free_kb": 22020096, "disk_total_kb": 30408704,
          "mem_total_kb": 8191000, "mem_avail_kb": 6100000, "uptime_s": 11000, "os": "Debian GNU/Linux 12 (bookworm)", "arch": "aarch64", "throttled": ["under-voltage now"]}},
 "jetson": {{"state": "online", "via": "Wi-Fi", "ms": 6, "temp_c": 51, "load": 1.2, "disk_free_kb": 104857600, "throttled": []}},
 "pi-zero": {{"state": "hostkey"}},
 "esp-weather": {{"state": "serial", "serial_present": false}}}}
J
  ;;
  "json links") if [ "$BOARD_FAKE" = nokey ]; then k=false; else k=true; fi; cat <<J
{{"key": $k, "key_path": "", "missing": ["tio", "sshfs"], "dialout": false,
 "eth": {{"iface": "eno1", "cable": false, "on": false}}, "usb": {{"ready": true, "connected": []}},
 "hotspot": {{"iface": "wlo1", "on": false, "ssid": "omen-lab", "password": ""}}}}
J
  ;;
  "json net") cat <<'J'
[{{"ip": "192.168.1.1", "name": "_gateway", "mac": "c8:4f:86:94:50:38", "vendor": "TP-Link", "role": "router", "ports": [53, 80], "known": "", "new": false, "via": "Wi-Fi"}},
 {{"ip": "192.168.1.23", "name": "raspberrypi.local", "mac": "dc:a6:32:01:02:03", "vendor": "Raspberry Pi", "role": "", "ports": [22], "known": "", "new": true, "via": "Wi-Fi"}},
 {{"ip": "192.168.1.40", "name": "", "mac": "de:ad:be:ef:00:01", "vendor": "random MAC (phone/laptop privacy)", "role": "", "ports": [], "known": "", "new": false, "via": "Wi-Fi"}},
 {{"ip": "192.168.1.50", "name": "pi5.local", "mac": "2c:cf:67:00:00:01", "vendor": "Raspberry Pi", "role": "", "ports": [22], "known": "pi5", "new": false, "via": "Wi-Fi"}}]
J
  ;;
  *) echo "BLOCKED board $*" >> "{log}";;
esac
''')
    # battery-health: canned report for the Battery panel (json.dumps: no hand-escaped braces)
    bat = {"health": 92.0, "verdict": "Good", "full_wh": 64.5, "design_wh": 70.1, "now_wh": 40.0, "power_w": 9.8, "percent": 62,
           "status": "Discharging", "cycles": 312, "maker": "HP", "tech": "Li-ion", "hours_left": 4.1, "years_to_worn": 4.1,
           "trend": {"per_year": 2.9, "per_100_cycles": 2.7, "days": 300},
           "history": [{"day": f"2026-{m:02d}-01", "health": round(100 - (m - 1) * 0.8, 1), "cycles": m * 30} for m in range(1, 12)]}
    (base / "battery.json").write_text(json.dumps(bat))
    write("battery-health", f'cat "{base / "battery.json"}"\n')
    # projects: canned repos for the Projects panel (sample names only)
    prj = [{"name": "webshop", "path": "/tmp/webshop", "branch": "main", "changed": 3, "ahead": 2, "behind": 0, "ci": "pass",
            "summary": "main · 3 changed · ↑2 to push · 2 h ago"},
           {"name": "api-server", "path": "/tmp/api", "branch": "dev", "changed": 0, "ahead": 0, "behind": 0, "ci": "fail",
            "prs": [{"number": 4}], "summary": "dev · CI failing · 1 PR · 1 d ago"},
           {"name": "notes", "path": "/tmp/notes", "branch": "main", "changed": 0, "summary": "main · 1 w ago"},
           {"name": "dotfiles", "path": "/tmp/dot", "branch": "main", "changed": 0, "summary": "main · 1 mo ago"}]
    (base / "projects.json").write_text(json.dumps(prj))
    write("projects", f'cat "{base / "projects.json"}"\n')
    # services: canned ports + containers for the Services panel (sample names only)
    web = [{"name": "webshop-db-1", "image": "postgres:16", "state": "running", "status": "Up 2 hours", "ports": "5432/tcp", "project": "webshop",
            "service": "db", "folder": "~/Projects/webshop"},
           {"name": "webshop-web-1", "image": "nginx:alpine", "state": "running", "status": "Up 2 hours", "ports": "0.0.0.0:8080->80/tcp",
            "project": "webshop", "service": "web", "folder": "~/Projects/webshop"}]
    one = [{"name": "searxng", "image": "searxng/searxng", "state": "exited", "status": "Exited (0) 2 weeks ago", "ports": "", "project": "",
            "service": "", "folder": ""}]
    svc = {"ports": [{"port": 3000, "addr": "127.0.0.1", "name": "node", "pid": 4242, "cmd": "node vite --port 3000", "cwd": "~/Projects/webshop",
                      "local": True, "what": "", "protected": False},
                     {"port": 11434, "addr": "127.0.0.1", "name": "ollama", "pid": 99, "cmd": "ollama serve", "cwd": "~", "local": True,
                      "what": "local AI models", "protected": True}],
           "containers": web + one, "stacks": {"webshop": web, "": one}}
    (base / "services.json").write_text(json.dumps(svc))
    write("services", f'[ "$1" = --json ] && cat "{base / "services.json"}" || echo "BLOCKED services $*" >> "{log}"\n')
    # tasks: canned agent tasks for the Agent tasks panel (sample names only)
    tsk = [{"id": "t261126-100000", "task": "Add a dark mode toggle", "agent": "claude", "name": "webshop", "state": "review",
            "stat": "3 files changed", "base": "main", "branch": "agent/claude-add-a-dark-mode-100000"},
           {"id": "t261126-090000", "task": "Fix the flaky login test", "agent": "codex", "name": "api-server", "state": "running"},
           {"id": "t261125-090000", "task": "Rename the config loader", "agent": "claude", "name": "notes", "state": "merged"}]
    (base / "tasks.json").write_text(json.dumps(tsk))
    write("tasks", f'[ "$1 $2" = "ls --json" ] && cat "{base / "tasks.json"}" || echo "BLOCKED tasks $*" >> "{log}"\n')
    # security-check: canned checkup for the Security panel
    write("security-check", '''cat <<'J'
{"summary": {"good": 10, "warn": 2, "bad": 1, "info": 0}, "t": 0, "checks": [
 {"id": "encryption", "title": "Disk encryption", "state": "bad", "detail": "Not encrypted: if the laptop is lost or stolen, every file can be read.", "why": "A login password doesn't protect the disk.", "fix": {"cmd": "", "root": false, "label": "Plan"}},
 {"id": "groups", "title": "Admin without a password", "state": "warn", "detail": "You're in the Docker group.", "why": "Common for developers.", "fix": {"cmd": "sudo gpasswd -d me docker", "root": true, "label": "Remove"}},
 {"id": "secureboot", "title": "Secure Boot", "state": "warn", "detail": "Off.", "why": "A BIOS setting.", "fix": null},
 {"id": "firewall", "title": "Firewall", "state": "ok", "detail": "On: nothing can connect in unless allowed.", "why": "", "fix": null},
 {"id": "ssh-key", "title": "SSH key", "state": "ok", "detail": "Protected by a passphrase.", "why": "", "fix": null}]}
J
''')
    # disk: canned report for the Storage panel
    write("disk", f'''case "$1" in
  --json) cat <<'J'
{{"disk": {{"free": 26800000000, "total": 267200000000, "used_pct": 85}}, "safe_total": 17400000000, "items": [
 {{"id": "docker-build", "title": "Docker build cache", "why": "Rebuilt when you build an image again.", "size": 9300000000, "root": false}},
 {{"id": "chrome-cache", "title": "Chrome's disk cache", "why": "Close Chrome first.", "size": 3600000000, "root": false}},
 {{"id": "npm", "title": "npm download cache", "why": "Downloaded again when needed.", "size": 3500000000, "root": false}},
 {{"id": "pip", "title": "pip cache", "why": "Re-downloaded on the next install.", "size": 1000000000, "root": false}},
 {{"id": "apt", "title": "Downloaded system packages", "why": "Already installed.", "size": 700000000, "root": true, "cmd": "sudo apt clean"}}]}}
J
  ;;
  *) echo "BLOCKED disk $*" >> "{log}";;
esac
''')
    # phone: canned status for the Phone panel (PHONE_FAKE = on | away | setup)
    write("phone", f'''case "$1 $2" in
  "status --json") case "$PHONE_FAKE" in
    setup) echo '{{"kdeconnect": true, "phone": null, "battery": null, "charging": null, "cable": null, "alerts": {{"topic": "", "rule": "away", "detail": "short", "queued": 0, "last": {{}}}}, "seen": null}}';;
    away) echo '{{"kdeconnect": true, "phone": {{"name": "Pixel 8", "id": "x1", "paired": true, "reachable": false}}, "battery": null, "charging": null, "cable": null, "alerts": {{"topic": "your-secret-topic", "rule": "away", "detail": "short", "queued": 1, "last": {{}}}}, "seen": 1764150000, "laptop_ip": "192.168.1.20"}}';;
    *) echo '{{"kdeconnect": true, "phone": {{"name": "Pixel 8", "id": "x1", "paired": true, "reachable": true}}, "battery": 64, "charging": true, "cable": {{"serial": "d7", "state": "device", "model": "2201117TG"}}, "alerts": {{"topic": "your-secret-topic", "rule": "away", "detail": "short", "queued": 0, "last": {{}}}}, "seen": 1764150000}}';;
  esac;;
  *) echo "BLOCKED phone $*" >> "{log}";;
esac
''')
    (base / "dbus.conf").write_text(f"""<busconfig><type>session</type><listen>unix:dir={run}</listen>
<auth>EXTERNAL</auth><policy context="default"><allow send_destination="*" eavesdrop="true"/>
<allow eavesdrop="true"/><allow own="*"/></policy></busconfig>""")  # no <servicedir>: nothing auto-starts
    return home, run, stub, log


def wallpaper():
    """The wallpaper Hyprland shows (hyprpaper in image mode), else "" for the plain black default."""
    home = Path.home()
    try:
        if (home / ".config/hypr/wallpaper-mode").read_text().strip() == "image":
            m = re.search(r"path\s*=\s*(\S+)", (home / ".config/hypr/hyprpaper.conf").read_text())
            return os.path.expanduser(m.group(1)) if m else ""
    except OSError:
        pass
    return ""


def driver():
    shots = Path(os.environ.get("UI_SHOTS", Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "myos-ui-shots"))
    shutil.rmtree(shots, ignore_errors=True)
    shots.mkdir(parents=True)
    base = Path(tempfile.mkdtemp(prefix="myos-ui-"))
    failures = total = 0
    broadway = None
    try:
        home, run, stub, log = build_sandbox(base)
        display = f":{40 + os.getpid() % 40}"
        clean = {k: v for k, v in os.environ.items() if k not in (
            "WAYLAND_DISPLAY", "DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DBUS_SESSION_BUS_ADDRESS",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CURRENT_DESKTOP")}
        env = clean | {"HOME": str(home), "XDG_RUNTIME_DIR": str(run), "PATH": f"{stub}:{home}/.local/bin:/usr/bin:/bin",
                       "GDK_BACKEND": "broadway", "BROADWAY_DISPLAY": display, "GDK_DEBUG": "no-portals",
                       "GTK_USE_PORTAL": "0", "MYOS_UI_SANDBOX": str(base), "MYOS_REAL_HOME": str(Path.home()), "UI_SHOTS": str(shots), "NO_AT_BRIDGE": "1",
                       "WALLPAPER": wallpaper()}
        import socket as _socket
        for _try in range(5):                     # wait until it's really listening; another number if this one is taken
            broadway = subprocess.Popen(["gtk4-broadwayd", "--address", "127.0.0.1", display], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _w in range(30):
                if broadway.poll() is not None: break
                try:
                    _socket.create_connection(("127.0.0.1", 8080 + int(display[1:])), timeout=0.2).close(); break
                except OSError: time.sleep(0.1)
            if broadway.poll() is None: break
            display = f":{40 + (int(display[1:]) - 40 + 7) % 40}"; env["BROADWAY_DISPLAY"] = display
        names = sys.argv[1:] or list(SCENARIOS)
        for name in names:
            print(f"\n{name}", flush=True)
            out = base / f"{name}.json"
            calls_before = log.read_text().splitlines() if log.exists() else []
            for attempt in (1, 2):           # a scenario that produced no result at all gets one retry (slow first start)
                p = subprocess.run(["dbus-run-session", f"--config-file={base / 'dbus.conf'}", "--", sys.executable,
                                    str(Path(__file__).resolve()), "app", name, str(out)],
                                   env=env, cwd=base, capture_output=True, text=True, timeout=120)
                if out.exists(): break
            results = json.loads(out.read_text()) if out.exists() else [[f"{name}: app started and was audited", False,
                                                                        (p.stderr or p.stdout)[-600:]]]
            blocked = [c for c in (log.read_text().splitlines() if log.exists() else [])[len(calls_before):]
                       if c.startswith("BLOCKED") and not re.search(r"hyprctl dispatch \S+ .*class:\^\(org\\\.myos\\\.", c)]
            # (an app placing its own window, e.g. the panel under the bar, is expected)
            results.append(["opening it changes nothing on the system", not blocked, blocked[:5]])
            tb = [l for l in p.stderr.splitlines() if "Traceback" in l or "Error:" in l and "Gtk-" not in l]
            results.append(["no Python errors in the log", not tb, "\n".join(p.stderr.splitlines()[-12:]) if tb else ""])
            for check, ok, detail in results:
                total += 1
                failures += not ok
                print(f"  {'PASS' if ok else 'FAIL'} {check}{'' if ok else '  -> ' + str(detail)[:600]}", flush=True)
    finally:
        if broadway:
            broadway.terminate()
        shutil.rmtree(base, ignore_errors=True)
    print(f"\nUI audit: {total - failures}/{total} passed. Screenshots: {shots}")
    return 1 if failures else 0


# ───────────────────────────── in-process audit ─────────────────────────────
def app(name, out):
    assert os.environ.get("MYOS_UI_SANDBOX") and os.environ.get("GDK_BACKEND") == "broadway", "sandbox only"
    assert "WAYLAND_DISPLAY" not in os.environ and "HYPRLAND_INSTANCE_SIGNATURE" not in os.environ
    entry, argv, stdin, settle, steps = SCENARIOS.get(name) or EXTRA_SCENARIOS[name]
    if "live-ai" not in name:
        os.environ["MYOS_RUN_NO_AI"] = "1"      # the launcher's local-AI suggestions aren't deterministic; checked live instead
    else:                                        # opt-in: uses the real local models (reuse their cache: no cold start)
        cache = Path(os.environ["MYOS_REAL_HOME"]) / ".cache/myos/run-embed.json" if os.environ.get("MYOS_REAL_HOME") else None
        if cache and cache.exists():
            (Path.home() / ".cache/myos").mkdir(parents=True, exist_ok=True); shutil.copy(cache, Path.home() / ".cache/myos/run-embed.json")
    if name.endswith("-empty"): os.environ["BOARD_FAKE"] = "empty"
    if name.startswith("panel-phone"): os.environ["PHONE_FAKE"] = name.removeprefix("panel-phone").lstrip("-") or "on"
    if name.startswith("panel-remote-") and not name.endswith("-empty"):
        os.environ["MYOS_REMOTE_VIEW"] = name.rsplit("-", 1)[1]
        if name.endswith("-setup"): os.environ["BOARD_FAKE"] = "nokey"
    sys.path[:0] = [str(DESKTOP), str(AI)]
    sys.argv = argv
    errors = []
    sys.excepthook = lambda t, v, tb: errors.append(f"{t.__name__}: {v}") or sys.__excepthook__(t, v, tb)
    import io
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("Graphene", "1.0")
    from gi.repository import Adw, GLib, Graphene, Gtk
    shots = Path(os.environ["UI_SHOTS"])
    results = []

    def check(text, ok, detail=""):
        results.append([text, bool(ok), detail if not ok else ""])

    def pump(seconds):
        ctx = GLib.MainContext.default()
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            while ctx.pending():
                ctx.iteration(False)
            time.sleep(0.01)

    def walk(w):
        yield w
        c = w.get_first_child()
        while c:
            yield from walk(c)
            c = c.get_next_sibling()

    def windows():
        return [w for w in Gtk.Window.list_toplevels() if w.get_visible() and w.get_width() > 120]

    def texts():
        found = []
        for win in windows():
            for w in walk(win):
                if not w.get_mapped():
                    continue
                if isinstance(w, Gtk.Label) and w.get_text():
                    found.append(w.get_text())
                elif isinstance(w, Adw.PreferencesRow) and w.get_title():
                    found.append(w.get_title())
                elif isinstance(w, Adw.WindowTitle):
                    found.append(w.get_title())
            found.append(win.get_title() or "")
        return found

    def sees(s):
        return any(s.lower() in t.lower() for t in texts())

    def render(win, path):
        for _ in range(30):
            snap = Gtk.Snapshot()
            Gtk.WidgetPaintable.new(win).snapshot(snap, win.get_width(), win.get_height())
            node = snap.to_node()
            if node:
                tex = win.get_native().get_renderer().render_texture(node, None)
                tex.save_to_png(str(path))
                return path
            pump(0.1)
        return None

    def dark_ratio(path):
        from PIL import Image, ImageFilter
        img = Image.open(path).convert("RGBA")
        alpha = img.getchannel("A")  # interior only: rounded corners are always transparent
        inner = sorted(alpha.getpixel((int(img.width * x / 10), int(img.height * y / 10))) for x in range(1, 10) for y in range(1, 10))
        glass = inner[len(inner) // 2] < 250
        if glass:  # glass window: Hyprland blurs what's behind it
            wall = os.environ.get("WALLPAPER")
            back = Image.new("RGBA", img.size, (0, 0, 0, 255))
            if wall and Path(wall).exists():
                src = Image.open(wall).convert("RGBA")
                scale = max(img.width / src.width, img.height / src.height)
                src = src.resize((int(src.width * scale) + 1, int(src.height * scale) + 1))
                back = src.crop((0, 0, img.width, img.height)).filter(ImageFilter.GaussianBlur(12))
            img = Image.alpha_composite(back, img)
            img.save(path)  # the screenshot now shows what you actually see
        img = img.convert("RGB")
        w, h = img.size
        pts = [img.getpixel((int(w * x / 10), int(h * y / 10))) for x in range(1, 10) for y in range(1, 10)]
        return sum(0.2126 * r + 0.7152 * g + 0.0722 * b < 90 for r, g, b in pts) / len(pts), glass, img

    def lum(rgb):  # WCAG relative luminance
        def c(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = rgb[:3]
        return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b)

    def worst_contrast(win, img):
        """Lowest WCAG contrast of any visible text against what's actually behind it (lightest/darkest glyph core)."""
        rows = []
        for w in walk(win):
            if not (isinstance(w, Gtk.Label) and w.get_mapped() and w.get_text().strip()):
                continue
            if "other-month" in w.get_css_classes():  # calendar days outside this month are dimmed on purpose
                continue
            ok, rect = w.compute_bounds(win)
            if not ok or rect.get_width() < 4 or rect.get_height() < 6:
                continue
            clipped = False  # skip text scrolled out of view (it isn't on screen to read)
            sw = w.get_ancestor(Gtk.ScrolledWindow)
            while sw and not clipped:
                ok2, r2 = w.compute_bounds(sw)
                clipped = not ok2 or r2.get_y() < 0 or r2.get_y() + r2.get_height() > sw.get_height() + 1 \
                    or r2.get_x() < 0 or r2.get_x() + r2.get_width() > sw.get_width() + 1
                sw = sw.get_parent().get_ancestor(Gtk.ScrolledWindow) if sw.get_parent() else None
            if clipped:
                continue
            x, y = int(rect.get_x()), int(rect.get_y())
            box = (max(0, x), max(0, y), min(img.width, x + int(rect.get_width())), min(img.height, y + int(rect.get_height())))
            if box[2] - box[0] < 4 or box[3] - box[1] < 6:
                continue
            crop = img.crop(box)
            ls = sorted(lum(px) for px in crop.getdata())
            bg = ls[len(ls) // 2]                     # most of a label's box is background
            c = w.get_color()                         # the text colour CSS actually resolved to
            alpha = c.alpha
            a = w
            while a is not None and a is not win:     # dim-label etc. fade text via opacity
                alpha *= a.get_opacity()
                a = a.get_parent()
            if alpha < 0.05:                          # fully faded (e.g. Adw.EntryRow's spare title used for its animation)
                continue
            bgpx = sorted(crop.getdata(), key=lum)[len(ls) // 2]
            fg_rgb = [255 * ch * alpha + b * (1 - alpha) for ch, b in zip((c.red, c.green, c.blue), bgpx[:3])]
            fg = lum(fg_rgb)
            ratio = (max(bg, fg) + 0.05) / (min(bg, fg) + 0.05)
            rows.append((round(ratio, 2), w.get_text()[:40], box))
        rows.sort()
        for i, (_, _, box) in enumerate(rows[:3]):  # keep the worst crops so a person can judge
            img.crop(box).save(shots / f"{name}-lowest-contrast-{i}.png")
        return [r[:2] for r in rows]

    def editable():
        for win in windows():
            for w in walk(win):
                if w.get_mapped() and w.get_sensitive() and isinstance(w, (Gtk.Editable, Gtk.TextView)):
                    if isinstance(w, Gtk.Text) and isinstance(w.get_parent(), (Gtk.SearchEntry, Gtk.Entry, Gtk.PasswordEntry)):
                        continue  # use the outer entry
                    return w
        return None

    def audit():
        try:
            if name == "chat-sample-conversation":  # open the seeded chat: table, code block, link
                from gi.repository import Gio
                sample = Path.home() / ".local/share/local-ai/chats/sample.json"
                Gio.Application.get_default().win.open_chat(json.loads(sample.read_text()))
                pump(1.5)
            wins = windows()
            check("opens a window", wins, [w.get_title() for w in Gtk.Window.list_toplevels()])
            for i, win in enumerate(wins):
                tag = f"[{win.get_title() or type(win).__name__}]"
                shot = render(win, shots / f"{name}-{i}.png")
                check(f"{tag} renders", shot)
                if shot:
                    ratio, glass, img = dark_ratio(shot)
                    if not glass:
                        check(f"{tag} dark Graphite surface", ratio > 0.6, f"only {ratio:.0%} of samples dark")
                    rows = worst_contrast(win, img)
                    weak = [r for r in rows if r[0] < 3.0]
                    check(f"{tag} all text readable{' on the glass over your wallpaper' if glass else ''} (contrast ≥ 3:1)",
                          not weak, weak[:6])
                minimum = win.get_child().measure(Gtk.Orientation.HORIZONTAL, -1)[0] if win.get_child() else 0
                check(f"{tag} content fits the window width", minimum <= win.get_width() + 1, (minimum, win.get_width()))
                bad = []
                for w in walk(win):
                    internal = (w.get_ancestor(Gtk.WindowControls) or w.get_ancestor(Gtk.MenuButton)
                                or w.get_ancestor(Gtk.DropDown) or "back" in w.get_css_classes())
                    if (isinstance(w, Gtk.Button) and w.get_mapped() and not internal
                            and not w.get_tooltip_text() and not (w.get_label() or "").strip()
                            and not any(isinstance(c, Gtk.Label) and c.get_text().strip() for c in walk(w))
                            and w.get_accessible_role() != Gtk.AccessibleRole.SPIN_BUTTON
                            and not (isinstance(w.get_parent(), Gtk.Widget) and type(w.get_parent()).__name__ == "SpinButton")):
                        bad.append(f"{w.get_icon_name() or type(w).__name__} {w.get_css_classes()}")
                check(f"{tag} every icon-only button has a tooltip (name for screen readers)", not bad, bad[:8])
                focusables = [w for w in walk(win) if w.get_mapped() and w.get_sensitive() and w.get_focusable()
                              and isinstance(w, (Gtk.Button, Gtk.Editable, Gtk.Switch, Gtk.CheckButton, Gtk.ListBoxRow, Gtk.TextView))]
                if len(focusables) > 1:
                    win.set_focus(None)
                    seen, stuck, last, repeat = [], False, None, 0
                    for _ in range(40):
                        win.emit("move-focus", Gtk.DirectionType.TAB_FORWARD)
                        pump(0.02)
                        f = win.get_focus()
                        repeat = repeat + 1 if f is last else 0
                        stuck = stuck or (repeat >= 3)
                        last = f
                        if f is not None and f not in seen:
                            seen.append(f)
                    check(f"{tag} Tab moves between controls (no keyboard trap)", not stuck and len(seen) > 1,
                          f"stuck on {type(last).__name__}" if stuck else f"{len(seen)} stops")
            for s in MUST_SEE_ON_OPEN.get(name, []):
                check(f"shows '{s}'", sees(s), texts()[:15])
            for typed, must, mustnt in steps:
                field = editable()
                if not field:
                    check(f"has a text field to type '{typed}'", False)
                    continue
                if isinstance(field, Gtk.TextView):
                    field.get_buffer().set_text(typed)
                else:
                    field.set_text(typed)
                pump(3.0 if "live-ai" in name else 0.8)
                for s in must:
                    check(f"typing '{typed}' shows '{s}'", sees(s), [t for t in texts() if t][:15])
                for s in mustnt:
                    check(f"typing '{typed}' hides '{s}'", not sees(s))
                for i, win in enumerate(windows()):
                    render(win, shots / f"{name}-typed-{typed.strip('/').replace(' ', '_')}-{i}.png")
            check("no Python exceptions while open", not errors, errors[:3])
        except Exception as error:  # an audit crash is a failure, never a hang
            import traceback
            check("audit completed", False, traceback.format_exc()[-600:])
        Path(out).write_text(json.dumps(results))
        sys.stdout.flush()
        os._exit(0)

    # Broadway's frame clock barely ticks with no browser attached, so animations would stall
    # mid-way (half-revealed rows, stale pages). Jump straight to the end state instead.
    Gtk.init()
    Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
    GLib.timeout_add(int(settle * 1000), lambda: audit() or False)
    if entry == "panel":
        import panel
        panel.App().run(sys.argv)
    elif entry == "pick":
        import pick
        pick.main()
    elif entry == "fileactions":
        import fileactions
        fileactions.run_gui([str(Path(os.environ["MYOS_UI_SANDBOX"]) / "sample.png")])
    elif entry == "hydration_panel":
        import hydration_panel
        hydration_panel.run()
    else:
        __import__(entry).run_app()
    # Some apps exit their loop early (e.g. nothing to show); still report.
    pump(settle)
    audit()


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "app":
        app(sys.argv[2], sys.argv[3])
    else:
        sys.exit(driver())
