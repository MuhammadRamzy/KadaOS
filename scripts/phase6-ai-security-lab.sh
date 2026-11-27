#!/usr/bin/env bash
# Phase 6: AI lab, virtualization, networking + security/RE tools (packages via apt / uv tools; no daemons enabled beyond libvirt)
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
log "== phase6 start =="
export PATH="$HOME/.local/bin:$PATH"
# Ollama (vendor script; service left disabled to save RAM - start with: sudo systemctl start ollama)
if ! command -v ollama >/dev/null; then curl -fsSL https://ollama.com/install.sh | sh >>"$LOG" 2>&1; fi
sudo systemctl disable --now ollama >>"$LOG" 2>&1 || true
# Python AI tools in isolated envs
for t in huggingface-hub jupyterlab semgrep impacket frida-tools volatility3; do
  command -v uv >/dev/null && uv tool install "$t" >>"$LOG" 2>&1 && log "uv tool $t" || log "uv tool FAILED $t"
done
# Virtualization
apt_try qemu-system-x86 qemu-utils libvirt-daemon-system libvirt-clients virt-manager ovmf distrobox podman
sudo usermod -aG libvirt,kvm "$USER"
# Networking + security tools
echo "wireshark-common wireshark-common/install-setuid boolean false" | sudo debconf-set-selections
apt_try nmap arp-scan wireshark tshark ffuf gobuster nikto sqlmap hydra john hashcat aircrack-ng \
  bettercap smbclient ldap-utils yara binwalk radare2 python3-scapy ltrace strace \
  libimage-exiftool-perl adb fastboot scrcpy apktool iperf3 httpie python3-yara
# Ubuntu enables Bettercap's root API service when installing the package.
# Keep the CLI available, but start the service manually only for a lab session.
if systemctl list-unit-files bettercap.service --no-legend 2>/dev/null | grep -q '^bettercap.service'; then
  sudo systemctl disable --now bettercap.service >>"$LOG" 2>&1 || log "bettercap service disable FAILED"
fi
# Snaps/flatpak for GUI tools (only if absent)
snap list 2>/dev/null | grep -q '^zaproxy' || sudo snap install zaproxy --classic >>"$LOG" 2>&1 || log "zaproxy FAILED"
snap list 2>/dev/null | grep -q '^ghidra' || sudo snap install ghidra >>"$LOG" 2>&1 || log "ghidra FAILED"
snap list 2>/dev/null | grep -q '^ghostty' || sudo snap install ghostty --classic >>"$LOG" 2>&1 || log "ghostty FAILED (kitty is the fallback)"
# Trivy/Syft/Grype/Metasploit/Burp: fetched from vendors on demand, not auto-installed
[ -e ~/Labs/Notes/LAB_GUIDE.md ] || cat > ~/Labs/Notes/LAB_GUIDE.md <<'M'
# Isolated lab guide
- Targets (Juice Shop, DVWA, Metasploitable-style) run ONLY in VMs/containers on host-only or NAT libvirt networks.
- Never bridge vulnerable targets to the home LAN or expose them to the Internet.
- Only test systems you own or are authorized to assess.
- Snapshot VMs before risky changes. Keep 16GB budget: ~8-10GB for host, small lab VMs.
```mermaid
flowchart LR
  Host[Ubuntu host] --> NAT[libvirt host-only/NAT net]
  NAT --> Kali[Kali operator VM]
  NAT --> Targets[Vulnerable targets]
  Host -. no bridge .- LAN[Home LAN / Internet]
```
Metasploit, Burp Community, Trivy/Syft/Grype: install from vendor when needed.
Juice Shop: docker run --rm -p 127.0.0.1:3001:3000 bkimminich/juice-shop
M
log "== phase6 done =="
