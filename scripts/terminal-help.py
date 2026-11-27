#!/usr/bin/env python3
"""Searchable local guide to the workstation's terminal tools and workflows."""
import argparse
import shutil
import subprocess
import sys

TOPICS = {
    "start": ("Start here", [
        ("helpme", "Open this searchable menu; helpme --list shows topics."),
        ("sysinfo", "Show full system, GPU, memory, disk, and battery details."),
        ("command --help", "Inspect a command's options; man command opens its manual."),
        ("Ctrl+C", "Stop a running command; Ctrl+D exits the current shell."),
    ]),
    "navigation": ("Navigation and files", [
        ("z <name>", "Jump to a directory you have visited before (zoxide)."),
        ("zi", "Pick a visited directory interactively."),
        ("ll", "Detailed, human-readable directory listing (eza)."),
        ("tree -L 2", "Show a shallow directory tree."),
        ("bat <file>", "Read a file with syntax highlighting and line numbers."),
        ("cd -", "Return to the previous directory."),
    ]),
    "search": ("Search, completion, and history", [
        ("rg 'pattern' .", "Search file contents recursively."),
        ("fd 'name' .", "Find files by name."),
        ("Ctrl+R", "Search shell command history with fzf."),
        ("Ctrl+T", "Insert a selected file path into the command line."),
        ("Alt+C", "Pick a directory to enter."),
        ("Tab", "Complete commands and paths; use the right arrow to accept a suggestion."),
    ]),
    "git": ("Git and GitHub", [
        ("gs", "Show Git status."),
        ("gl", "Show recent commits in a compact graph."),
        ("lg", "Open lazygit."),
        ("git diff", "Review changed lines before committing."),
        ("gh auth login", "Connect your GitHub account interactively."),
    ]),
    "development": ("Development toolchains", [
        ("uv init / uv run", "Create and run Python projects without a global pip install."),
        ("fnm use / fnm install", "Select and install Node versions."),
        ("pnpm / bun", "JavaScript package and runtime tools."),
        ("cargo / go", "Rust and Go toolchains."),
        ("direnv allow", "Load a project's approved .envrc when entering it."),
        ("code .", "Open the current folder in VS Code."),
    ]),
    "containers": ("Containers", [
        ("docker ps", "List running containers."),
        ("dc up -d", "Start services in a Compose project (dc = docker compose)."),
        ("dps", "Alias for docker ps."),
        ("docker compose logs -f", "Follow service logs."),
        ("lazydocker", "Open the Docker terminal dashboard."),
    ]),
    "ros": ("ROS 2 Lyrical", [
        ("source ~/Scripts/ros-lyrical-env.sh", "Activate ROS only in this shell."),
        ("cd ~/Workspaces/ros2_lyrical", "Enter the native ROS workspace."),
        ("colcon build --symlink-install", "Build packages from src/."),
        ("colcon test && colcon test-result --verbose", "Run and review package tests."),
        ("ros2 doctor --report", "Check the ROS environment."),
    ]),
    "spaceros": ("Space ROS", [
        ("~/Scripts/space-ros-shell.sh", "Open the isolated development container."),
        ("cd ~/Workspaces/space_ros", "Host directory mounted inside that container."),
        ("ros2 --help / colcon --help", "Quick checks once inside the container."),
    ]),
    "security": ("Security and backup", [
        ("tailscale status", "Check private network connection."),
        ("sudo tailscale up", "Sign in to the private network if logged out."),
        ("~/Scripts/backup.sh", "Encrypted backup; requires the mounted external HDD."),
        ("~/Scripts/verify-backups.sh", "Check repository data and restore a sample."),
        ("nmap / tshark / semgrep", "Network, packet, and code inspection tools."),
    ]),
    "desktop": ("Desktop and terminal", [
        ("Super+Space (GNOME)", "Open the app grid."),
        ("Super+Enter (GNOME)", "Open Ptyxis terminal."),
        ("Super+Shift+S (GNOME)", "Open the screenshot tool."),
        ("Super+Enter", "Open a terminal in Hyprland."),
        ("Super+Space", "Open the Hyprland app launcher."),
        ("Super+1…9", "Switch Hyprland workspaces."),
        ("tmux", "Keep terminal sessions running across tabs and connections."),
        ("btop", "Interactive process and resource monitor."),
    ]),
    "clipboard": ("Clipboard history", [
        ("Super+V (GNOME)", "Open Clipboard Indicator after the next GNOME login."),
        ("Super+M (GNOME)", "Open the message tray; moved from Super+V."),
        ("Private mode", "Pause Clipboard Indicator when handling sensitive text."),
        ("Super+Shift+V (Hyprland)", "Pick an item from cliphist."),
        ("wl-copy / wl-paste", "Copy or read text in Wayland terminals."),
    ]),
}


def details(key):
    title, commands = TOPICS[key]
    color = sys.stdout.isatty()
    print(f"\n\033[1;95m{title}\033[0m" if color else f"\n{title}")
    width = max(len(command) for command, _ in commands)
    for command, explanation in commands:
        print(f"  {command:<{width}}  {explanation}")
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", nargs="?", help="show a topic directly")
    parser.add_argument("--list", action="store_true", help="list available topics")
    parser.add_argument("--all", action="store_true", help="show every topic")
    args = parser.parse_args()
    if args.topic:
        key = args.topic.lower().replace(" ", "")
        if key not in TOPICS:
            print(f"Unknown topic: {args.topic}. Run helpme --list.", file=sys.stderr)
            return 2
        details(key)
    elif args.all:
        for key in TOPICS:
            details(key)
    elif args.list or not (sys.stdin.isatty() and sys.stdout.isatty() and shutil.which("fzf")):
        print("Terminal help topics:\n")
        for key, (title, _) in TOPICS.items():
            print(f"  {key:<13} {title}")
        print("\nRun helpme <topic>, or run helpme in a terminal for the searchable menu.")
    else:
        choices = [f"{key:<13} {title}" for key, (title, _) in TOPICS.items()]
        while True:
            result = subprocess.run(
                ["fzf", "--height=70%", "--layout=reverse", "--border=rounded",
                 "--prompt=helpme > ", "--header=Type to search • Enter to view • Esc to close"],
                input="\n".join(choices), text=True, capture_output=True,
            )
            if result.returncode:
                break
            key = result.stdout.split(maxsplit=1)[0]
            details(key)
            try:
                input("Press Enter for the menu, or Ctrl+C to close…")
            except (KeyboardInterrupt, EOFError):
                print()
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
