#!/usr/bin/env bash
# Optional per-need tools. Usage: phase7-optional.sh flutter|cloud|k8s|nix|all
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
export PATH="$HOME/.local/bin:$PATH"
flutter(){ sudo snap install flutter --classic >>"$LOG" 2>&1 && log "flutter (snap)"; apt_try adb; }  # no Android Studio; add cmdline-tools manually if needed
cloud(){ sudo snap install terraform --classic >>"$LOG" 2>&1; pipx install ansible >>"$LOG" 2>&1; npm i -g wrangler supabase firebase-tools vercel >>"$LOG" 2>&1; log cloud-done; }
k8s(){ sudo snap install kubectl helm --classic >>"$LOG" 2>&1; sudo snap install k9s >>"$LOG" 2>&1; log k8s-done; }
nix(){ curl -fsSL https://install.determinate.systems/nix | sh -s -- install >>"$LOG" 2>&1; }
case "${1:-}" in flutter) flutter;; cloud) cloud;; k8s) k8s;; nix) nix;; all) flutter; cloud; k8s;; *) echo "usage: $0 flutter|cloud|k8s|nix|all";; esac
