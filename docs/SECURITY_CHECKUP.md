# Security checkup (`security-check`, Security panel)

Open **Security** in the control center (`myos-panel security`) or run `security-check`. Read-only: it never changes
anything. Worst first, each with why it matters and the fix:

| Check | Looks at |
|---|---|
| Firewall | ufw on/off |
| Open to the network | services listening beyond this laptop (expected ones: KDE Connect, mDNS, the VM network, Files' Windows discovery) |
| Disk encryption | whether the disk is encrypted (lost laptop = readable files if not) |
| Secure Boot | on/off (a BIOS setting) |
| Updates | pending security updates, automatic security updates |
| Firmware | BIOS / SSD updates via fwupd (asks the internet at most once a day) |
| SSH key | passphrase or not |
| Admin without a password | membership in docker / lxd (root without a password) |
| Failed logins | last 7 days |
| SSH server, automatic login, screen lock, this Wi-Fi | the rest of the basics |

Fixes: safe ones are buttons that open a terminal with the command (e.g. add an SSH key passphrase); anything that needs
your password is copied for you to paste. The pentest workbench (seclab, Super+H) is separate.

Not to be confused with `scripts/security-check.sh`, which only checks that the pentest workbench's tools are installed.
