#!/usr/bin/env python3
"""Install/uninstall KadaOS Hydration, preserving existing user configuration."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
SHARE = HOME / ".local/share/myos"
UNITS = HOME / ".config/systemd/user"
BACKUP = HOME / ".local/state/myos/hydration-backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
FILES = [(ROOT / "config/desktop" / f, SHARE / f, 0o644)
         for f in ("hydration.py", "hydration_engine.py", "hydration_panel.py")]
FILES += [(ROOT / "config/desktop/bin/myos-hydration", HOME / ".local/bin/myos-hydration", 0o755),
          (ROOT / "config/desktop/org.myos.Hydration.desktop", HOME / ".local/share/applications/org.myos.Hydration.desktop", 0o644),
          (ROOT / "config/systemd/myos-hydration.service", UNITS / "myos-hydration.service", 0o644)]
HYPR_LINE = next(line for line in (ROOT / "config/hypr/hyprland.conf").read_text().splitlines()
                 if line.startswith("exec-once") and "myos-hydration.service" in line)


def command(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def backup(path):
    if path.exists():
        target = BACKUP / path.relative_to(HOME)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def deploy(source, target, mode):
    if target.exists() and target.read_bytes() == source.read_bytes():
        return
    backup(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write beside, then rename: overwriting a running binary in place fails with ETXTBSY.
    temp = target.with_name(target.name + ".new")
    shutil.copyfile(source, temp)
    temp.chmod(mode)
    temp.replace(target)


def integrate(remove=False):
    hypr = HOME / ".config/hypr/hyprland.conf"
    if hypr.exists():
        text = hypr.read_text()
        new = "\n".join(line for line in text.splitlines()
                        if not (line.startswith("exec-once") and "myos-hydration.service" in line)) + "\n"
        if not remove:
            # Keep source order when the live file otherwise matches the repository.
            repo = (ROOT / "config/hypr/hyprland.conf").read_text()
            without = "\n".join(line for line in repo.splitlines() if line != HYPR_LINE) + "\n"
            new = repo if new == without else new + HYPR_LINE + "\n"
        if new != text:
            backup(hypr)
            hypr.write_text(new)
    config = HOME / ".config/swaync/config.json"
    if config.exists():
        data = json.loads(config.read_text())
        actions = data["widget-config"]["buttons-grid"]["actions"]
        actions[:] = [a for a in actions if "myos-hydration" not in a.get("command", "")]
        if not remove:
            actions.insert(max(0, len(actions) - 2), dict(label="\U000F058C   Hydration",
                command="sh -c 'swaync-client -cp; sleep 0.3; ~/.local/bin/myos-hydration panel'"))
        new = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        if new != config.read_text():
            backup(config)
            config.write_text(new)


def main():
    if sys.argv[1:] not in ([], ["--uninstall"]):
        raise SystemExit("Usage: bash scripts/install-hydration.sh [--uninstall]")
    remove = sys.argv[1:] == ["--uninstall"]
    if remove:
        subprocess.run(["systemctl", "--user", "disable", "--now", "myos-hydration.service"], check=False)
        integrate(True)
        for _, target, _ in FILES:
            if target.exists():
                backup(target)
                target.unlink()
        helper = SHARE / "hydration-idle"
        if helper.exists():
            backup(helper)
            helper.unlink()
        print("Hydration removed. Settings, history and backups preserved.")
    else:
        first_install = not (UNITS / "myos-hydration.service").exists()
        was_running = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "myos-hydration.service"]).returncode == 0
        was_enabled = subprocess.run(["systemctl", "--user", "is-enabled", "--quiet", "myos-hydration.service"],
                                     stderr=subprocess.DEVNULL).returncode == 0
        for tool in ("cc", "wayland-scanner", "pkg-config", "pw-dump", "systemctl"):
            if not shutil.which(tool):
                raise SystemExit(f"Missing dependency: {tool}. See docs/HYDRATION.md.")
        command("python3", "-c", "import gi; gi.require_version('Adw', '1'); from gi.repository import Adw, Gio")
        protocol = Path("/usr/share/wayland-protocols/staging/ext-idle-notify/ext-idle-notify-v1.xml")
        # Build successfully before touching any installed files.
        with tempfile.TemporaryDirectory(prefix="myos-hydration-") as temp:
            build = Path(temp)
            command("wayland-scanner", "client-header", str(protocol), str(build / "idle-protocol.h"))
            command("wayland-scanner", "private-code", str(protocol), str(build / "idle-protocol.c"))
            flags = subprocess.check_output(["pkg-config", "--cflags", "--libs", "wayland-client"], text=True).split()
            command("cc", "-O2", "-Wall", "-Wextra", "-Werror", "-I" + temp,
                    str(ROOT / "config/desktop/hydration_idle.c"), str(build / "idle-protocol.c"),
                    "-o", str(build / "hydration-idle"), *flags)
            for source, target, mode in FILES:
                deploy(source, target, mode)
            deploy(build / "hydration-idle", SHARE / "hydration-idle", 0o755)
        # Same as install-panels.sh, which also deploys run.py as-is; deploy() keeps a backup.
        if (SHARE / "run.py").exists():
            deploy(ROOT / "config/desktop/run.py", SHARE / "run.py", 0o755)
        integrate()
        command("systemctl", "--user", "daemon-reload")
        for key in ("WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP", "HYPRLAND_INSTANCE_SIGNATURE"):
            if os.environ.get(key):
                command("systemctl", "--user", "import-environment", key)
        if first_install:
            command("systemctl", "--user", "enable", "myos-hydration.service")
        if first_install or was_running or was_enabled:
            command("systemctl", "--user", "restart", "myos-hydration.service")
        print("Hydration installed. Open Super+Space → Hydration. Backups:", BACKUP)
    if remove:
        command("systemctl", "--user", "daemon-reload")
    subprocess.run(["update-desktop-database", str(HOME / ".local/share/applications")], check=False)
    subprocess.run(["swaync-client", "--reload-config"], check=False)
    with (ROOT / "setup.log").open("a") as stream:
        stream.write(f"{datetime.now().isoformat()} hydration {'uninstalled' if remove else 'installed'}; backups {BACKUP}\n")


if __name__ == "__main__":
    main()
