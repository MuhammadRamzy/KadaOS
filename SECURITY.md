# Security policy

KadaOS configures a workstation: firewall, services, privileged scripts and tools that talk to the network. Security bugs
here can matter, so thank you for looking.

## Reporting a vulnerability

**Please don't open a public issue.** Use GitHub's private reporting instead: the repository's **Security** tab →
**Report a vulnerability**. Include what you found, how to reproduce it, and which order/items were installed
(`./kada --list` names them).

You'll get an acknowledgement within a few days. Fixes land on `main`; the advisory credits you unless you'd rather not.

## In scope
- Scripts in `scripts/` and `kada` doing something unsafe (command injection, unsafe temp files, wrong permissions,
  privilege escalation, downloading without verification).
- Services or listeners KadaOS starts that are reachable from the network when they shouldn't be.
- The launcher, panels or assistant running something you didn't approve.
- Secrets or personal data that end up somewhere they shouldn't (logs, world-readable files, commits).

## Out of scope
- The upstream tools KadaOS installs (report those to their projects), and the security tools' intended behaviour.
- Anything that needs an attacker to already have your user account or physical access with the screen unlocked.

## Using the security workbench responsibly
The workbench (`seclab`) refuses targets outside an engagement's written scope. Only test systems you own or are
authorised to test.
