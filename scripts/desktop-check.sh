#!/usr/bin/env bash
# Hyprland desktop self-test. Run inside the Hyprland session:  bash scripts/desktop-check.sh
# Use --ui to check the desktop without running AI/model or agent checks.
# Prints PASS/FAIL per check; exit code = number of failures.
case "${1:-}" in ""|--ui) ;; *) echo "Usage: $0 [--ui]"; exit 2;; esac
ui_only=${1:-}
root="$(cd "$(dirname "$0")/.." && pwd)"; S=~/.config/hypr/scripts; fail=0
ok(){ printf '  \e[32mPASS\e[0m %s\n' "$1"; }; bad(){ printf '  \e[31mFAIL\e[0m %s\n' "$1"; fail=$((fail+1)); }
chk(){ if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] || { echo "Run this inside Hyprland."; exit 1; }
echo "Config"
chk "hyprland.conf valid"                 'Hyprland --verify-config 2>&1 | grep -q "config ok"'
chk "no runtime config errors"            '[ -z "$(hyprctl configerrors | tr -d "[:space:]")" ]'
chk "config loaded in session (key binds)" '[ "$(hyprctl binds -j | jq length)" -gt 50 ]'   # file can match while Hyprland runs on defaults
mirror_matches(){
  python3 - "$1" "$2" <<'PYTHON'
from pathlib import Path
import filecmp, sys
source, target = map(Path, sys.argv[1:])
files = [p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
def same(a, b):   # repo configs say /home/USER where yours has your home folder
    x, y = a.read_bytes(), b.read_bytes()
    return x == y or x.replace(b'/home/USER', str(Path.home()).encode()) == y
sys.exit(0 if files and all((target / p.relative_to(source)).is_file() and
    same(p, target / p.relative_to(source)) for p in files) else 1)
PYTHON
}
for a in hypr waybar rofi wofi swaync wlogout kitty; do
  chk "~/.config/$a matches repo"         "mirror_matches '$root/config/$a' '$HOME/.config/$a'"
done
chk "waybar json"                         'python3 -c "import json;json.load(open(\"$HOME/.config/waybar/config.jsonc\"))"'
chk "swaync json"                         'python3 -c "import json;json.load(open(\"$HOME/.config/swaync/config.json\"))"'
echo "Services"
chk "exactly one swaync (systemd-managed)" '[ "$(pgrep -xc swaync)" = 1 ] && systemctl --user is-active swaync'
chk "no leaked swaync-client watchers" '[ "$(pgrep -xc swaync-client)" -le 2 ]'
for p in waybar swaync hypridle swayosd-server; do chk "$p running" "pgrep -x $p"; done
chk "clipboard watchers (2)"              '[ "$(pgrep -fc "^wl-paste .*cliphist store")" -ge 2 ]'
chk "Ubuntu settings sync running"        'pgrep -f "bash .*/hypr/scripts/gnome-sync.sh"'
chk "polkit agent"                        'systemctl --user is-active hyprpolkitagent || pgrep -f polkit.*agent'
chk "idle timers registered (hypridle)"   '! grep -q "timeout = [0-9]* ;" ~/.config/hypr/hypridle.conf'
chk "backlight writable by session"       '[ -w /sys/class/backlight/nvidia_wmi_ec_backlight/brightness ]'
chk "notifications support buttons"       'gdbus call --session --dest org.freedesktop.Notifications --object-path /org/freedesktop/Notifications --method org.freedesktop.Notifications.GetCapabilities | grep -q actions'
if systemctl --user is-enabled --quiet myos-hydration.service; then
  chk "hydration service active" 'systemctl --user is-active myos-hydration.service'
  chk "hydration activity observer ready" 'myos-hydration status | python3 -c "import json,sys; assert json.load(sys.stdin)[\"observer\"]"'
  for f in hydration.py hydration_engine.py hydration_panel.py; do
    chk "hydration $f matches repo" "cmp -s '$root/config/desktop/$f' '$HOME/.local/share/myos/$f'"
  done
  chk "hydration unit matches repo" "cmp -s '$root/config/systemd/myos-hydration.service' '$HOME/.config/systemd/user/myos-hydration.service'"
fi
if systemctl --user is-enabled --quiet myos-border-signals.service; then
  chk "border signals service active" 'systemctl --user is-active myos-border-signals.service'
  chk "border signals match repo" "cmp -s '$root/config/desktop/border_signals.py' '$HOME/.local/share/myos/border_signals.py' && cmp -s '$root/config/systemd/myos-border-signals.service' '$HOME/.config/systemd/user/myos-border-signals.service'"
  chk "border at the theme colour (no signal stuck)" '[ "$(hyprctl getoption general:col.active_border | head -1)" = "custom type: $(sed -nE "s/.*col.active_border = rgba\((..)(..)(..)(..)\).*/\4\1\2\3/p" ~/.config/hypr/colors.conf) 0deg" ]'
fi
chk "Bluetooth on (not rfkill-blocked)"    '! rfkill list bluetooth | grep -q "Soft blocked: yes" && bluetoothctl show | grep -q "Powered: yes"'
chk "Blueman power plugins disabled"       'gsettings get org.blueman.general plugin-list | grep -q PowerManager'
echo "Shortcuts"
miss=$(hyprctl binds -j | jq -r '.[]|select(.dispatcher=="exec")|.arg' | while read -r a; do
  c=$(sed -E "s/^(sh -c .|env [^ ]+ )//" <<<"$a" | awk '{print $1}' | sed "s#^~#$HOME#; s/'//g"); [ -z "$c" ] && continue
  command -v "$c" >/dev/null || [ -x "$c" ] || echo "$c"; done | sort -u | tr '\n' ' ')
[ -z "$miss" ] && ok "every shortcut's command exists ($(hyprctl binds -j | jq length) binds)" || bad "missing commands: $miss"
chk "every shortcut has a help description" '[ "$(hyprctl binds -j | jq "[.[]|select(.description==\"\" and (.key|test(\"Lock\")|not) and .dispatcher!=\"bringactivetotop\")]|length")" = 0 ]'
echo "Scripts"
for f in $S/*.sh; do chk "$(basename $f) syntax" "bash -n $f"; done
chk "status scripts return JSON"          "for s in lockstate.sh power-profile.sh 'nightlight.sh status' 'tablet-display.sh json' 'tablet-control.py json'; do $S/\$s | jq -e . ; done"
chk "screenshot tools"                    'command -v grim && command -v slurp && command -v swappy && command -v wl-copy'
if [ "$ui_only" != --ui ]; then
echo "Work layouts and security menu"
chk "work layout parser" 'python3 "$S/flow.py" --dry-run "chrome and 2 terminals" | python3 -c "import json,sys; assert json.load(sys.stdin)==[\"chrome\",\"terminal\",\"terminal\"]"'
chk "seclab catalogue matches repo" "cmp -s '$root/config/security/tools.json' '$HOME/.local/share/security-workbench/tools.json'"
chk "seclab executable matches repo" "cmp -s '$root/config/security/seclab' '$HOME/.local/share/security-workbench/seclab'"
chk "board (remote devices) matches repo" "cmp -s '$root/config/remote/board.py' '$HOME/.local/share/myos/remote/board.py' && test -x '$HOME/.local/bin/board'"
chk "battery-health matches repo"            "cmp -s '$root/config/desktop/battery.py' '$HOME/.local/share/myos/battery.py' && test -x '$HOME/.local/bin/battery-health'"
chk "monitors (display layouts) matches repo" "cmp -s '$root/config/desktop/monitors.py' '$HOME/.local/share/myos/monitors.py' && test -x '$HOME/.local/bin/monitors'"
chk "projects (dashboard) matches repo" "cmp -s '$root/config/desktop/projects.py' '$HOME/.local/share/myos/projects.py' && test -x '$HOME/.local/bin/projects'"
chk "services (ports + Docker) matches repo" "cmp -s '$root/config/desktop/services.py' '$HOME/.local/share/myos/services.py' && test -x '$HOME/.local/bin/services'"
chk "new-project matches repo" "cmp -s '$root/config/desktop/newproject.py' '$HOME/.local/share/myos/newproject.py' && test -x '$HOME/.local/bin/new-project'"
chk "tasks (agent board) matches repo" "cmp -s '$root/config/desktop/tasks.py' '$HOME/.local/share/myos/tasks.py' && test -x '$HOME/.local/bin/tasks'"
chk "trust (network levels) matches repo" "cmp -s '$root/config/network/trust.py' '$HOME/.local/share/myos/trust.py' && test -x '$HOME/.local/bin/trust'"
chk "tidy (Downloads) matches repo" "cmp -s '$root/config/desktop/tidy.py' '$HOME/.local/share/myos/tidy.py' && test -x '$HOME/.local/bin/tidy'"
chk "secret scan before commits (global hook)" "cmp -s '$root/config/git/secret-scan.py' '$HOME/.local/share/myos/secret-scan.py' && cmp -s '$root/config/git/hooks/dispatch' '$HOME/.config/git/hooks/dispatch' && [ \"\$(git config --global --get core.hooksPath)\" = \"$HOME/.config/git/hooks\" ]"
chk "profile (work profiles) matches repo"  "cmp -s '$root/config/desktop/profile.py' '$HOME/.local/share/myos/profile.py' && test -x '$HOME/.local/bin/profile'"
chk "security-check matches repo"            "cmp -s '$root/config/desktop/security.py' '$HOME/.local/share/myos/security.py' && test -x '$HOME/.local/bin/security-check'"
chk "disk (storage cleanup) matches repo"   "cmp -s '$root/config/desktop/disk.py' '$HOME/.local/share/myos/disk.py' && test -x '$HOME/.local/bin/disk'"
chk "job (memory-capped jobs) matches repo" "cmp -s '$root/config/desktop/job.py' '$HOME/.local/share/myos/job.py' && test -x '$HOME/.local/bin/job'"
chk "phone (phone link) matches repo"       "cmp -s '$root/config/phone/phone.py' '$HOME/.local/share/myos/phone/phone.py' && test -x '$HOME/.local/bin/phone'"
echo "AI layer"
chk "AI offline regressions" 'python3 -m unittest discover -s "$root/tests"'
for f in fai.py chat.py watch.py dictate-live.py voice-ask.py system-adapt.py zsh-ai.zsh; do
  chk "AI $f matches repo" "cmp -s '$root/config/ai/$f' '$HOME/.local/share/local-ai/$f'"
done
chk "assistant voice (Kokoro) installed" "cmp -s '$root/config/ai/voice-server.py' '$HOME/.local/share/local-ai/voice-server.py' && '$HOME/.local/share/local-ai/venv-voice/bin/python' -c 'import kokoro_onnx' && test -s '$HOME/.local/share/local-ai/voice/kokoro-v1.0.int8.onnx'"
for f in ai-menu ai-chat ai-ocr ai-search ai-dictate ai-voice ai-status; do
  chk "$f installed + syntax" "cmp -s '$root/config/ai/bin/$f' '$HOME/.local/bin/$f' && bash -n '$HOME/.local/bin/$f'"
done
chk "index unit matches repo" "cmp -s '$root/config/ai/systemd/docs-index.service' '$HOME/.config/systemd/user/docs-index.service'"
chk "Ollama service"                     'systemctl --user is-active ollama-local && curl -s --max-time 2 127.0.0.1:11434/api/version'
chk "configured generation and embedding models present" 'python3 -c "import json,pathlib,subprocess; c=json.loads((pathlib.Path.home()/\".config/local-ai/config.json\").read_text()); assert all(subprocess.run([\"ollama\",\"show\",c[k]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0 for k in (\"model\",\"embed_model\"))"'
chk "adapt service"                      'systemctl --user is-active system-adapt'
chk "index timer"                        'systemctl --user is-active docs-index.timer'
chk "fai answers"                        'timeout 60 fai ask "reply with the single word OK" | grep -qi ok'
chk "semantic index has files"           '[ "$(fai status | awk "/^index/{print \$2}")" -gt 0 ]'
chk "OCR (tesseract eng+mal)"            'tesseract --list-langs 2>/dev/null | grep -qx mal'
chk "Whisper + model"                    '(command -v whisper-cli || command -v whisper-cpp) && ls ~/.local/share/local-ai/whisper/ggml-*.bin'
chk "zsh AI helpers loaded in .zshrc"    'grep -q local-ai/zsh-ai.zsh ~/.zshrc'
echo "Agents"
chk "one rulebook linked (Claude/Codex/Antigravity)" '[ "$(readlink ~/.claude/CLAUDE.md)" = "$(readlink ~/.codex/AGENTS.md)" ] && [ "$(readlink ~/.gemini/GEMINI.md)" = "$(readlink ~/.codex/AGENTS.md)" ]'
chk "local-tools MCP server answers"            'printf "%s\n" "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}" | timeout 20 python3 ~/.local/share/local-ai/mcp-local-tools.py | grep -q system_status'
chk "system status runs (no crash, GPU line present)" 'timeout 30 python3 -c "import importlib.util as u,os;s=u.spec_from_file_location(\"f\",os.path.expanduser(\"~/.local/share/local-ai/fai.py\"));m=u.module_from_spec(s);s.loader.exec_module(m);assert \"NVIDIA GPU:\" in m.system_status()"'
chk "Codex: notify + local-tools MCP"           'python3 -c "import tomllib;c=tomllib.load(open(\"$HOME/.codex/config.toml\",\"rb\"));assert \"agent-notify\" in c[\"notify\"][1] and \"local-tools\" in c[\"mcp_servers\"]"'
chk "Claude: notify hooks"                  'grep -q agent-notify ~/.claude/settings.json'
chk "agent tools installed"                 'for b in agent agent-menu agent-review agent-notify proj-init fai-chat; do command -v $b; done'
fi
echo "Speed and memory"
# ponytail: fixed budgets (~5x today's numbers: zsh 60 ms, bar 30 ms, 570 MB); tighten if they never come close.
secs(){ /usr/bin/time -f %e "$@" 2>&1 >/dev/null | tail -1; }
zs=$(secs zsh -i -c exit); bs=$(secs python3 "$S/bar-status.py")
pss=$(for p in $(pgrep -u "$USER" -f "waybar|myos/(run|panel|hydration)\.py|swaync$|blueman-applet|udiskie|hyprpaper|swayosd-server|polkitagent|system-adapt|hypridle|xdg-desktop-portal"); do
  awk '/^Pss:/{print $2}' "/proc/$p/smaps_rollup" 2>/dev/null; done | awk '{s+=$1} END{print int(s/1024)}')
chk "shell starts in ${zs}s (budget 0.3s)"        "awk 'BEGIN{exit !($zs < 0.3)}'"
chk "bar status runs in ${bs}s (budget 0.3s)"     "awk 'BEGIN{exit !($bs < 0.3)}'"
chk "desktop services use ${pss} MB (budget 1000)" "[ ${pss:-0} -gt 0 ] && [ $pss -lt 1000 ]"
echo "Look"
chk "Nerd Font installed"                 'fc-list | grep -qi "JetBrainsMono Nerd Font"'
chk "Ubuntu Sans installed"               'fc-list | grep -qi "Ubuntu Sans"'
chk "bar icons not stripped"              'grep -q "\\\\U\\|[^ -~]" ~/.config/waybar/config.jsonc'
echo; [ $fail = 0 ] && echo "All checks passed." || echo "$fail check(s) failed."
exit $fail
