#!/usr/bin/env python3
"""Fast centered greeting for local interactive terminals."""
from datetime import datetime
from pathlib import Path
import os
import platform
import shutil
import sys

ART = (
    r" ___    _   __  __ ______   __",
    r"| _ \  /_\ |  \/  |_  /\ \ / /",
    r"|   / / _ \| |\/| |/ /  \ V / ",
    r"|_|_\/_/ \_\_|  |_/___|  |_|  ",
)


def mem_usage():
    entries = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in {"MemTotal", "MemAvailable"}:
            entries[key] = int(value.strip().split()[0])
    total = entries["MemTotal"] / 1048576
    used = (entries["MemTotal"] - entries["MemAvailable"]) / 1048576
    return f"RAM {used:.1f}/{total:.1f}G"


def battery():
    for path in Path("/sys/class/power_supply").glob("BAT*/capacity"):
        value = path.read_text().strip()
        if value.isdigit():
            return f"BAT {value}%"
    return ""


def os_name():
    for line in Path("/etc/os-release").read_text().splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return platform.system()


def uptime():
    seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    return f"{days}d {hours}h" if days else f"{hours}h {minutes}m"


def main():
    if not sys.stdout.isatty() or os.environ.get("TERM") == "dumb":
        return
    width = shutil.get_terminal_size((80, 24)).columns
    use_color = "NO_COLOR" not in os.environ

    def show(value, color):
        value = value.rstrip()
        if len(value) > width:
            value = value[:width]
        pad = " " * max(0, (width - len(value)) // 2)
        tone = f"\033[{color}m" if use_color else ""
        reset = "\033[0m" if use_color else ""
        print(f"{pad}{tone}{value}{reset}")

    if width >= 38:
        art_width = max(len(line.rstrip()) for line in ART)
        left = " " * max(0, (width - art_width) // 2)
        tone = "\033[1;95m" if use_color else ""
        reset = "\033[0m" if use_color else ""
        for line in ART:
            print(f"{left}{tone}{line.rstrip():<{art_width}}{reset}")
    else:
        show("KADAOS", "1;95")
    disk = shutil.disk_usage("/")
    summary = f"{os_name()}  ·  up {uptime()}  ·  {datetime.now():%a %H:%M}"
    resources = "  ·  ".join(item for item in (mem_usage(), f"Disk {disk.used / disk.total:.0%}", battery()) if item)
    show(summary, "96")
    show(resources, "96")
    show("helpme: tools & shortcuts   ·   sysinfo: full system details", "2;95")
    print()


if __name__ == "__main__":
    main()
