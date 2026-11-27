# Remote devices and your network (`board`)

One tool for every device you reach over SSH or a cable: Raspberry Pis, Jetsons, ESP32 / Pico boards, servers, VMs.
Plus a quick look at **everything on the network you're connected to**. Design: plan ·
[ADR 0019](decisions/0019-remote-and-embedded-workflow.md).

## First time

```sh
bash scripts/install-remote.sh          # user-level: board, ssh config, completion, Files scripts
board setup                             # makes your SSH key (asks for a passphrase), VS Code Remote-SSH
! bash scripts/phase12-embedded.sh      # optional, needs your password: serial/mount/network tools, udev, dialout
board doctor                            # explains anything still missing, with the fix
```

Log out and back in once after the phase script, so the `dialout` group (serial ports) applies.

## Shortcuts

| Keys | Does |
|---|---|
| **Super + R** | Remote panel: every device, status, Terminal / VS Code / Files / Serial |
| **Super + Ctrl + R** | Connect to a device (pick it; opens tmux on it) |
| **Super + U** | Serial console (picker, or straight in with one adapter) |
| **Super + Shift + U** | Who is on my network: every IP, name, vendor, open ports |

The launcher (Super + Space) also has "Remote devices", "Who is on my network", "My network info" and "Serial console".

## Your network

| Command | Shows |
|---|---|
| `board net` | Every live device on your network: IP, name, vendor (from the MAC), common open ports, ✓ if it's one of your devices, **new** if it wasn't there last time, router and this laptop marked |
| `board net --fast` | Same without the port check (about 3 s) |
| `board net info` | Your interfaces and IPs, router, DNS servers, Wi-Fi name / signal / channel / speed. `--public` also asks api.ipify.org for your public IP |
| `board net ports HOST` | Open TCP ports on one device (`--ports 22,80,8000-8100`) |
| `board scan` | Devices with SSH or mDNS, and adds the one you pick |

How it finds devices: it pings every address in your subnet (your /24) at once. That fills the ARP table, so phones,
Windows PCs and IoT gadgets that ignore ping still show up. On a bigger Wi-Fi (like a /16) the router and anything you
already talk to are included too. Office, campus and guest Wi-Fi usually hide clients from each other, so you may
only see the router there. At home, on a cable or on `board hotspot` you see everything.

It only ever looks at networks the laptop is on (it refuses outside addresses). It is not a pentest scanner: no
service or version detection. Use the security workbench for that.

Other network tools installed by the phase script: `nmap`, `arp-scan` (needs sudo), `mtr` (live traceroute),
`traceroute`, `iperf3` (speed between two machines), `dig` / `host` (DNS), `whois`, `nc` / `socat`, `tcpdump`,
`ethtool`, `iw`, `wakeonlan`.

## Devices

```sh
board add pi5 pi5.local -u pi          # copies your key (asks the Pi's password once), learns model / arch
board ls                               # status, path used (Wi-Fi / USB cable / Ethernet), latency, temp
board ssh pi5                          # tmux on the Pi; survives Wi-Fi drops
board code pi5                         # VS Code on the Pi's project (sshfs mode on Pi Zero / low RAM)
board files pi5   ·   board mount pi5  # Files over sftp · mount at ~/Remote/pi5
board push pi5 main.py   ·   board pull pi5 logs/
board sync pi5 --run "python3 main.py" # mirror on every save, then run
board run @lab -- uptime               # every device tagged lab
board ports pi5 8080   ·   board share pi5 11434
board logs pi5 --why                   # journal, explained by the local model
board info pi5   ·   board doctor pi5  # throttling / under-voltage in plain words
board forget pi5                       # after reflashing
```

The same names work in `ssh`, `scp`, `rsync`, `git`, VS Code Remote-SSH and Files, because `board` generates
`~/.ssh/config.d/10-devices` from `~/.config/myos/devices.toml`. Your own hosts go in `~/.ssh/config`, which is
never touched.

## Background jobs

Long builds, training runs or downloads keep running on the device after you close the lid or the Wi-Fi drops.
When one ends you get a notification with its exit code and last lines (the assistant's 5-minute watcher checks).

```sh
board job pi5 -- make -j4             # starts in the project folder (--here: home folder); prints the job ID
board job ls                          # running / ✓ done / ✗ exit N / ■ stopped / ✗ lost (the device rebooted)
board job log ID -f                   # follow its output   ·   board job kill ID   ·   board job forget ID
```

Output lives on the device in `~/.board-jobs/ID.log`. A job you stop yourself doesn't notify.

## Alerts

```sh
board watch on pi5                    # notify when pi5 is offline >10 min, under-voltage now, ≥80 °C, disk >90 % full,
                                      # its host key changed, or it refuses your key
board watch on                        # while on your home network: notify when a NEW device joins it
board watch                           # what's watched   ·   board watch off [NAME]
```

Checked every 5 minutes by `myos-watch.timer`, only for devices you turned on, and only on networks you chose (it
recognises a network by its router's MAC, so other Wi-Fi is never swept). Same problem again: one reminder after 6 h.

## Ask the assistant

Super+Z: "are my Pis online?", "why is pi5 slow?", "what's failing on the robot?", "who's on my network?", "run
`df -h` on @lab", "start `python3 train.py` on jetson and tell me when it's done", "show my jobs", "reboot pi5".
Looking is free; running, starting/stopping jobs and rebooting show an approval card first.

## In the field (no Wi-Fi)

- `board usb enable pi5`, then one USB cable to the Pi's USB-C port gives a network link (10.55.0.x).
- `board link on`: direct Ethernet cable, and the device gets the laptop's internet.
- `board hotspot on`: a laptop Wi-Fi hotspot for several devices.
- `board serial`: UART console, logged to `~/Embedded/logs/`.

## New boards

`board flash` writes an SD card with your key, Wi-Fi, UART and USB-cable mode already on (it refuses the system
disk). `board bootstrap pi5` sets up tmux, updates and key-only login. `board backup pi5` images the card over the
network.

## Undo

`bash scripts/install-remote.sh --uninstall`. Your key, `known_hosts`, device list and `~/Embedded` stay.
