#!/usr/bin/env bash
# Run core workstation, Hyprland (+ theme/polish), ROS and AI-desktop phases. Usage: bash bootstrap.sh
# Re-runnable; each phase is idempotent. Log: ~/KadaOS/setup.log
# shellcheck disable=SC2024 # setup.log is user-writable; only the command needs sudo.
cd "$(dirname "$0")" || exit 1
sudo -v || exit 1
sudo DEBIAN_FRONTEND=noninteractive dpkg --configure -a >>../setup.log 2>&1 || {
  echo "Package configuration needs attention; see setup.log."
  exit 1
}
( while true; do sudo -n true; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) 2>/dev/null &
failed=0
for p in phase1-base phase2-dev phase3-docker phase5-security-backup phase6-ai-security-lab phase8-hyprland phase8b-hyprland-polish phase9-ros phase10-ai-desktop phase11-agents install-security; do
  echo ">>> $p"
  if ! bash "./$p.sh"; then
    echo "!!! $p reported errors (see setup.log)"
    failed=1
  fi
done
echo
bash ./terminal-style.sh || echo "!!! terminal-style reported errors"
python3 ./gnome-workflow.py || echo "!!! gnome-workflow reported errors (re-run inside GNOME)"
bash ./postflight.sh || failed=1
echo "Setup finished. Log out/in for group and shell changes; choose Hyprland at login to test it."
echo "Remaining account and HDD steps are listed in docs/HEALTH_REPORT.md and docs/runbooks/POST_INSTALL.md."
exit "$failed"
