#!/usr/bin/env bash
# Full test suite for the whole laptop setup. Safe to run while you work: nothing opens on your
# screen, nothing is typed, and no setting is changed (sandboxes, private D-Bus, off-screen GTK).
#
#   bash tests/run-all.sh            # everything (~3–4 min, includes one small local-model answer)
#   bash tests/run-all.sh --quick    # skip the AI/model and agent live checks (~2 min)
#   bash tests/run-all.sh --offline  # repo + sandbox only; nothing that reads the live session
#
# Sections: 1 syntax + wiring of every file · 2 unit tests · 3 Hydration feature suite ·
# 4 every native app off-screen (UI/UX/theme/readability) · 5 live laptop checks (read-only) ·
# 6 security tool catalogue. Screenshots of every screen: $XDG_RUNTIME_DIR/myos-ui-shots/
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root" || exit 1
mode="${1:-full}"
case "$mode" in full|--quick|--offline) ;; *) sed -n '2,12p' "$0"; exit 2;; esac
log="$(mktemp -d)"; trap 'rm -rf "$log"' EXIT
declare -a names=() states=() counts=()
start=$(date +%s)

bold() { printf '\n\033[1m%s\033[0m\n' "$1"; }
# section <title> <command...>: show PASS/FAIL lines live, keep the rest in a log
section() {
  local title="$1"; shift
  bold "$title"
  local t0; t0=$(date +%s)
  "$@" >"$log/raw" 2>&1; local rc=$?
  sed -E 's/\x1b\[[0-9;]*m//g' "$log/raw" >"$log/out"   # drop colour codes before counting
  grep -E "^\s*(PASS|FAIL)|^[0-9a-z\[][^ ]*$|^\S.*(PASS|FAIL)$" "$log/out" | grep -v -iE "^(dbus-daemon|\(|Gtk-|  self\.)" || true
  local p f; p=$(grep -cE "(^|\s)PASS(\s|$)" "$log/out"); f=$(grep -cE "(^|\s)FAIL(\s|$)" "$log/out")
  if [ "$rc" -ne 0 ] && [ "$f" -eq 0 ]; then  # crashed or a non-PASS/FAIL tool failed: show why
    echo "  FAIL (exit $rc)"; tail -15 "$log/out" | sed 's/^/    /'; f=1
  fi
  names+=("$title"); counts+=("$p passed, $f failed, $(( $(date +%s) - t0 ))s")
  if [ "$f" -eq 0 ] && [ "$rc" -eq 0 ]; then states+=("PASS"); else states+=("FAIL"); fi
}

unit_tests() {
  python3 -m unittest discover -s tests -p 'test_*.py' -v 2>&1 | sed -E 's/^(test\S+) \(([^)]+)\).*\.\.\. ok$/  PASS \2.\1/; s/^(test\S+) \(([^)]+)\).*\.\.\. (FAIL|ERROR)$/  FAIL \2.\1/'
  return "${PIPESTATUS[0]}"
}

section "1 · Syntax and wiring of every file in the setup" python3 tests/setup_static.py
section "2 · Unit tests (assistant, launcher, pickers, panels, files, hydration…)" unit_tests
section "3 · Hydration feature suite (service, every control, popup, installer)" bash tests/hydration_suite.sh --offline
section "4 · Every native app, off-screen: UI/UX, theme, readability, keyboard" python3 tests/ui_audit.py

if [ "$mode" != --offline ]; then
  if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
    if [ "$mode" = --quick ]; then
      section "5 · This laptop, live (read-only; AI/agent checks skipped)" bash scripts/desktop-check.sh --ui
    else
      section "5 · This laptop, live (read-only)" bash scripts/desktop-check.sh
    fi
  else
    bold "5 · This laptop, live"; echo "  (skipped: run inside the Hyprland session)"
  fi
  section "6 · Security workbench tool catalogue (presence only)" bash scripts/security-check.sh
fi

bold "Summary ($(( $(date +%s) - start ))s)"
failed=0
for i in "${!names[@]}"; do
  printf '  %-4s %-72s %s\n' "${states[$i]}" "${names[$i]}" "${counts[$i]}"
  [ "${states[$i]}" = PASS ] || failed=$((failed + 1))
done
echo "  Screenshots of every screen: ${XDG_RUNTIME_DIR:-/tmp}/myos-ui-shots/ and ${XDG_RUNTIME_DIR:-/tmp}/hydration-shots/"
[ "$failed" -eq 0 ] && echo "  All sections passed." || echo "  $failed section(s) failed."
exit "$failed"
