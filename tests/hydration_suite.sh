#!/usr/bin/env bash
# Full Hydration test suite: logic, service, notification popup, every panel page/button/dialog,
# theme, launcher/menus, installer, and (read-only) the live install.
#   bash tests/hydration_suite.sh            # everything
#   bash tests/hydration_suite.sh --offline  # skip the read-only live-install checks
# Safe to run while you work: private D-Bus, off-screen GTK (broadway), sandbox HOMEs, stubbed systemctl.
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root" || exit 1
offline=0; [ "${1:-}" = "--offline" ] && offline=1
shots="${HYDRATION_SHOTS:-${XDG_RUNTIME_DIR:-/tmp}/hydration-shots}"
rm -rf "$shots"; mkdir -p "$shots"
log="$(mktemp -d)"
failed=(); passed=0

run() {  # run <name> <command...>: quiet unless it fails
  local name="$1"; shift
  printf '%-58s' "$name"
  if "$@" >"$log/out" 2>&1; then
    echo "PASS"; passed=$((passed + 1))
  else
    echo "FAIL"; failed+=("$name"); grep -E "FAIL|Error|error|Traceback|assert" "$log/out" | head -15 | sed 's/^/    /'
  fi
}
section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

section "1 · Static checks"
run "Python compiles" python3 -m py_compile config/desktop/hydration.py config/desktop/hydration_engine.py \
  config/desktop/hydration_panel.py scripts/install-hydration.py tests/hydration_ui.py tests/hydration_config.py
run "Shell scripts parse" bash -n scripts/install-hydration.sh config/desktop/bin/myos-hydration tests/hydration_suite.sh
# shellcheck disable=SC2046  # pkg-config flags must word-split
c_build() {
  local t; t="$(mktemp -d)"; local p=/usr/share/wayland-protocols/staging/ext-idle-notify/ext-idle-notify-v1.xml
  wayland-scanner client-header "$p" "$t/idle-protocol.h" && wayland-scanner private-code "$p" "$t/idle-protocol.c" &&
  cc -O2 -Wall -Wextra -Werror -I"$t" config/desktop/hydration_idle.c "$t/idle-protocol.c" -o "$t/h" \
    $(pkg-config --cflags --libs wayland-client); local rc=$?; rm -rf "$t"; return $rc
}
run "Idle helper compiles with -Werror" c_build
unit_ok() { ! systemd-analyze --user verify config/systemd/myos-hydration.service 2>&1 | grep -i "myos-hydration"; }
run "systemd unit verifies" unit_ok

section "2 · Scheduling logic (engine)"
run "Engine unit tests" python3 -m unittest tests/test_hydration.py

section "3 · Service + notification actions (private D-Bus)"
run "Integration test" timeout 120 dbus-run-session -- python3 tests/hydration_integration.py

section "4 · Theme, launcher, menus, installer (sandbox)"
python3 tests/hydration_config.py >"$log/config" 2>&1; rc=$?
grep -E "^(  PASS|  FAIL|[A-Z])" "$log/config"
passed=$((passed + $(grep -c "^  PASS" "$log/config")))
[ $rc -eq 0 ] || failed+=("config/installer suite")

section "5 · UI/UX: every page, button, dialog, toast, popup (off-screen)"
# off-screen display: start it, wait until it's really listening (port 8080+N), pick another number if that one is taken
for _try in 1 2 3 4 5; do
  n=$((90 + RANDOM % 9)); display=":$n"
  gtk4-broadwayd --address 127.0.0.1 "$display" >/dev/null 2>&1 & bpid=$!   # localhost only: never expose test windows to the network
  for _w in $(seq 30); do
    kill -0 "$bpid" 2>/dev/null || break
    (exec 3<>"/dev/tcp/127.0.0.1/$((8080 + n))") 2>/dev/null && break 2
    sleep 0.1
  done
  kill "$bpid" 2>/dev/null
done
env -u WAYLAND_DISPLAY -u DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE GDK_BACKEND=broadway BROADWAY_DISPLAY="$display" \
  HYDRATION_SHOTS="$shots" timeout 300 dbus-run-session -- python3 tests/hydration_ui.py >"$log/ui" 2>&1; rc=$?
kill "$bpid" 2>/dev/null
grep -E "^(  PASS|  FAIL|[A-Z][a-z])|Traceback|Error" "$log/ui" | grep -v -iE "warning|dbus-daemon|portal"
passed=$((passed + $(grep -c "^  PASS" "$log/ui")))
[ $rc -eq 0 ] || failed+=("UI suite")

if [ $offline -eq 0 ]; then
  section "6 · Live install on this laptop (read-only)"
  if systemctl --user is-enabled --quiet myos-hydration.service; then
    run "service active" systemctl --user is-active --quiet myos-hydration.service
    run "activity observer ready (idle protocol works)" sh -c \
      'myos-hydration status | python3 -c "import json,sys; d=json.load(sys.stdin); assert d[\"observer\"] and d[\"service\"]"'
    for f in hydration.py hydration_engine.py hydration_panel.py; do
      run "deployed $f matches repo" cmp -s "config/desktop/$f" "$HOME/.local/share/myos/$f"
    done
    run "deployed unit matches repo" cmp -s config/systemd/myos-hydration.service ~/.config/systemd/user/myos-hydration.service
    run "deployed launcher matches repo" cmp -s config/desktop/run.py ~/.local/share/myos/run.py
    run "idle helper running" pgrep -u "$USER" -x hydration-idle
    mem_ok() { [ "$(systemctl --user show -p MemoryCurrent --value myos-hydration)" -lt $((40 * 1024 * 1024)) ]; }
    run "service memory under 40 MB" mem_ok
    run "notification server supports buttons" sh -c 'gdbus call --session --dest org.freedesktop.Notifications \
      --object-path /org/freedesktop/Notifications --method org.freedesktop.Notifications.GetCapabilities | grep -q actions'
    run "state file is private (600)" sh -c '[ ! -e ~/.local/state/myos/hydration/state.json ] || [ "$(stat -c %a ~/.local/state/myos/hydration/state.json)" = 600 ]'
  else
    echo "  (service not enabled: live checks skipped)"
  fi
fi

rm -rf "$log"
echo
echo "Passed: $passed   Failed: ${#failed[@]}"
for f in "${failed[@]}"; do echo "  FAILED: $f"; done
echo "Screenshots of every screen: $shots"
[ ${#failed[@]} -eq 0 ]
