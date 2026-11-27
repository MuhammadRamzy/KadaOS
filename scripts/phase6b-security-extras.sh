#!/usr/bin/env bash
# Run yourself: privileged packages use the shared apt helper; --user never uses sudo.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib.sh
. "$root/scripts/lib.sh"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
mode=all
if [[ ${1:-} == --user ]]; then mode=user; shift; fi
category=${1:-all}
case "$category" in wireless|recon|web|re|forensics|cloud|frameworks|wordlists|all) ;; *) echo "Unknown category: $category" >&2; exit 2;; esac
failed=0
run(){ if "$@" >>"$LOG" 2>&1; then log "OK: $*"; else log "FAILED: $*"; failed=1; fi; }
uv_tool(){ command -v "$1" >/dev/null && return; local binary=$1; shift; run uv tool install "$@"; command -v "$binary" >/dev/null || failed=1; }
wanted(){ [[ $category == all || $category == "$1" ]]; }
log "== security extras: $category ($mode) =="
if [[ $mode == all ]]; then
  wanted recon && apt_try masscan dnsrecon nbtscan onesixtyone smbclient ldap-utils
  wanted web && apt_try whatweb dirb ruby ruby-dev build-essential libcurl4-openssl-dev
  if wanted wireless; then
    printf 'macchanger macchanger/automatically_run boolean false\n' | sudo debconf-set-selections
    apt_try bully hcxtools hcxdumptool mdk4 macchanger dsniff pixiewps cowpatty
  fi
  if wanted re; then
    apt_try default-jdk gdb binutils libfuse2t64
    command -v ghidra >/dev/null || run sudo snap install ghidra
  fi
  wanted forensics && apt_try foremost scalpel sleuthkit autopsy steghide stegseek ruby ruby-dev
  if wanted frameworks; then
    command -v msfconsole >/dev/null || apt_try metasploit-framework
    command -v zaproxy >/dev/null || run sudo snap install zaproxy --classic
  fi
fi
if wanted recon; then
  uv_tool nxc git+https://github.com/Pennyw0rth/NetExec.git
  command -v enum4linux-ng >/dev/null || run python3 "$root/scripts/security-vendor.py" enum4linux-ng
fi
if wanted web; then
  command -v feroxbuster >/dev/null || run cargo install feroxbuster --locked
  if ! command -v wpscan >/dev/null; then
    run gem install --user-install --no-document --bindir "$HOME/.local/bin" wpscan
  fi
fi
if wanted re; then
  uv_tool objection objection
  uv_tool ropper ropper
  for tool in jadx cutter; do
    command -v "$tool" >/dev/null || run python3 "$root/scripts/security-vendor.py" "$tool"
  done
fi
if wanted forensics; then
  uv_tool unblob unblob
  command -v zsteg >/dev/null || run gem install --user-install --no-document --bindir "$HOME/.local/bin" zsteg
fi
if wanted cloud; then
  for tool in trivy syft grype; do
    command -v "$tool" >/dev/null || run python3 "$root/scripts/security-vendor.py" "$tool"
  done
fi
if wanted wordlists; then
  target="$HOME/Labs/Wordlists/SecLists"
  if [[ ! -d $target ]]; then
    mkdir -p "$(dirname "$target")"
    run git clone --depth 1 https://github.com/danielmiessler/SecLists.git "$target"
  fi
fi
# Presence is the final truth even when apt_try tolerates individual failures.
if [[ $category == all ]]; then
  bash "$root/scripts/security-check.sh" || failed=1
elif [[ $category != wordlists ]]; then
  bash "$root/scripts/security-check.sh" "$category" || failed=1
fi
log "== security extras finished; failures=$failed (see setup.log) =="
exit "$failed"
