# Network trust levels (`trust`, Super + Ctrl + W)

Tell the laptop how much to trust the network you're on. It's remembered per network (on the network's own NetworkManager
profile), so the next time you join that Wi-Fi the same rules apply.

| Level | What changes |
|---|---|
| **Home** | Nothing: devices here can find you (phone link, file sharing, dev servers you expose) |
| **Work** | A random MAC address that stays the same for this network; encrypted DNS (DNS-over-TLS) when the server supports it; no LLMNR |
| **Public** | A new random MAC every time you connect; encrypted DNS when possible; no mDNS/LLMNR (the laptop doesn't announce itself); **the firewall blocks everything coming in** on that network |

- **Open Wi-Fi** (no password) you haven't marked counts as Public. Secured networks you haven't marked are left as they are.
- **Setup once:** `! bash scripts/phase15-network-trust.sh` installs the small root hook that adds/removes the firewall rule
  when you join or leave a Public network. Everything else needs no password.
- MAC and DNS changes apply when you **reconnect** (turn Wi-Fi off and on, or pick the network again).
- **Captive portals** (hotel/café login pages) still work: DNS-over-TLS is "opportunistic", not strict.
- **No VPN yet** (your choice). When you add one, Public is the place to bring it up automatically.

Terminal: `trust` (current network and level) · `trust home | work | public` · `trust public "Cafe Wi-Fi"` (another saved network).
Undo the hook: `sudo rm /etc/NetworkManager/dispatcher.d/90-myos-trust`.
