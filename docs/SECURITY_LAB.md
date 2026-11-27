# Security workbench

**Super+H** opens the security menu. Choose a GUI to open it, or a command-line tool to read its help in a terminal. The menu never supplies a target or starts a scan for you. `seclab list` shows the catalogue; `seclab check` reports missing commands. A presence check does not prove every tool works.

```sh
seclab ai "Explain the difference between a SYN scan and a connect scan"
seclab why 'a command that failed' --code 1
seclab rag "Where is the lab isolation guide?"
seclab wifi                    # list local wireless interfaces, without changing them
seclab nmap --help              # explicit tool arguments pass through unchanged
```

AI uses the existing local `fai` helper. It explains and drafts; it does not execute its suggestions. `why` also accepts piped error output. Review commands before running them. Use targets you own or are authorized to test; keep vulnerable targets in isolated VMs or containers, never bridged onto the home LAN.

## Engagements (scope + saved results)

Keep each authorized job in `~/Engagements/NAME/` (`scope.txt`, `notes.md`, `log.md`, `scans/`, `loot/`).
Super+H → **Start an engagement** / **Run a recipe**, or from a terminal:

```sh
seclab new home-lab            # creates the folder and makes it active
seclab scope add 192.168.56.0/24 lab.example.com
seclab recipes                 # nmap-quick, nmap-services, nmap-full, web-fingerprint, web-dirs, web-nikto, smb-shares
seclab run nmap-services 192.168.56.10
```

`seclab run` **refuses any target outside the active scope** (IP inside a listed CIDR, an exact host, or a
subdomain of a listed domain). Output is saved to `scans/<time>-<recipe>-<target>.txt` (nmap also writes
`-oA` files), and each run appends a line to `log.md` for the report timeline. Recipes are fixed argv
lists, never a shell. List only targets you are authorized to test.

## Findings and the report

```sh
seclab finding "Default credentials on the admin panel" -s high -t 10.66.0.12   # findings/001-….md (opens $EDITOR)
seclab findings                # every finding, worst first
seclab report                  # report.md + report.html + report.pdf in the engagement folder
```
Each finding is one Markdown file with `title`, `severity` (critical/high/medium/low/info), `target` and `status` at the
top and Description / Evidence / Impact / Remediation below. The report has: authorization, window and rules (from
`notes.md`), a summary table by severity, the scope, every finding worst first, the timeline from `log.md` and the list of
saved scan files. The PDF is printed by headless Chrome; `seclab report --md` writes only the Markdown.

## Wireless, CTF, lab network

- `seclab wifi`: every Wi-Fi radio, built-in card or USB adapter, and whether it does monitor mode. Wireless testing wants a
  **USB adapter**: monitor mode on the built-in card (Realtek rtw89) disconnects your Wi-Fi. `seclab wifi layout` (or the
  **Wireless** layout in Super + Space) opens the adapter report and two terminals on an empty workspace.
- `seclab ctf NAME`: `~/CTF/NAME/` with a challenge table in `notes.md`, `files/`, `exploits/`, `loot/`, then VS Code, two
  terminals and a browser on an empty workspace (`--no-open` to only make the folder).
- `seclab lab up`: an **isolated** libvirt network `seclab-lab` (10.66.0.0/24, DHCP .100–.200, no forwarding: VMs reach each
  other and this laptop, never the LAN or the Internet). Pick it in virt-manager for vulnerable target VMs and add
  `10.66.0.0/24` to the engagement scope. It doesn't start at boot. `seclab lab` shows it and the VMs' addresses;
  `seclab lab down` stops it, `seclab lab remove` deletes it. With the firewall on, the VMs can reach only the laptop ports you opened for every network (e.g. the phone link's 1714–1764).

## Install and rebuild

```sh
bash scripts/install-security.sh           # menu, Super+H, and Super+Space layouts; no sudo
bash scripts/phase6b-security-extras.sh --user re
bash scripts/phase6b-security-extras.sh all # run in your terminal; includes sudo prompts
bash scripts/security-check.sh             # exit status = missing commands (capped at 125)
```

The core bootstrap also installs the workbench after the desktop and AI phases. Extra packages remain an explicit category installation.

Categories: `wireless`, `recon`, `web`, `re`, `forensics`, `cloud`, `frameworks`, `wordlists`, `all`. `--user` skips privileged packages. Existing commands are preserved. APT failures are logged and installation continues; the final catalogue check returns failure for missing commands. `setup.log` records actions. SecLists is an explicit `wordlists`/`all` download and can be large. Optional debugger extensions such as pwndbg are not auto-injected into GDB.

JADX, Cutter and cloud binaries use versioned upstream downloads with SHA-256 pins in `config/security/releases.json`. enum4linux-ng uses pinned upstream source and an isolated Python environment; its direct dependencies are pinned, but transitive dependencies are resolved by uv. These checks detect changed downloads; they are not independent vendor signature verification. Release URLs come from the official [JADX releases](https://github.com/skylot/jadx/releases), [Cutter releases](https://github.com/rizinorg/cutter/releases), and [enum4linux-ng repository](https://github.com/ParrotSec/enum4linux-ng). Update pins deliberately when upgrading.

Metasploit installation expects the Rapid7 repository to be configured already (as it is on this laptop); a fresh machine needs the vendor repository first. Ghidra and ZAP use the existing snap route. Core tools remain the responsibility of `phase6-ai-security-lab.sh`. The extras script does not enable services or modify wireless interfaces.

## Current verification — 2026-09-26

The catalogue contains 67 commands. Initially four were missing; enum4linux-ng, JADX 1.5.6 and Cutter 2.5.0 were installed and verified with help/version commands. Stegseek was subsequently installed in the user terminal and its 0.6 version check passed. **All 67 commands are now present.** Cutter's bundled Qt backend uses XWayland on this laptop; its version check succeeds despite a Wayland-plugin warning. Tools already present were preserved, not reinstalled. Full per-tool functional validation against lab targets has not been performed.

## Restore desktop changes

Changed-file backups are under `~/.local/state/setup/workbench-backups/<timestamp>/`, with paths relative to your home. Restore only the files listed there, then run `hyprctl reload`. The installer checks for a conflicting Super+H binding before changing anything; it atomically replaces files and preserves unrelated desktop settings. A second identical install makes no file changes. Vendor tools live under `~/.local/share/security/`, with launchers under `~/.local/bin/`.
