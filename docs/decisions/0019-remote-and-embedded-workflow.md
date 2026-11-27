# 0019 — Remote devices, embedded workflow and network discovery (`board`)

Date: 2026-11-26 · Status: accepted

## Context
The user works with Raspberry Pis, MCU boards and servers, at a desk and in the field with only a cable. There was no
SSH key, no ssh config, no serial setup and no way to see what was on the network. Plan:
plans/ssh-embedded-workflow.md.

## Decision
- One stdlib Python CLI, `board` (`config/remote/board.py`). The device registry is `~/.config/myos/devices.toml`.
  `~/.ssh/config.d/10-devices` is generated from it, so ssh, rsync, git, VS Code and Files all share the names.
  `99-defaults` (ControlMaster, keepalives) comes last, so the user's own config always wins.
- Path selection runs as a `ProxyCommand` (`board _proxy`): it tries the registry host, `NAME.local`, the last IP,
  and USB-cable / direct-Ethernet neighbours at the same time. ssh drops a ProxyCommand's stderr when ControlPersist
  is on, so the proxy also saves its reason to `$XDG_RUNTIME_DIR/board-proxy-NAME.err`.
- **Network discovery** (`board net`): a parallel ping sweep of each interface's /24, then the ARP table (REACHABLE
  / DELAY / PROBE), so devices that drop ping still count. Routers and fresh neighbours on the interface's real subnet
  are included too. Plain TCP connects to about 30 common ports. Names come from reverse DNS and mDNS, vendors from
  the nmap OUI list. A "new" mark comes from MACs seen before (state file). It refuses networks the laptop isn't on.
- Shortcuts: Super+R panel, Super+Ctrl+R connect, Super+U serial, Super+Shift+U network. Packages, udev rules and
  `dialout` come from one sudo phase (`scripts/phase12-embedded.sh`), which the user runs.

## Consequences
- No daemon. Status is polled only while the panel is open.
- Client-isolated Wi-Fi shows only the router. That is a limit of the network, and the tool says so.
- `board net` is not a security scanner (no version detection); the security workbench keeps its own scope.
