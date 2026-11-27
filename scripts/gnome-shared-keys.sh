#!/usr/bin/env bash
# Give Ubuntu (GNOME) the SAME shortcuts as Hyprland so muscle memory works in both. No sudo needed.
# Saves the previous GNOME keybindings to ~/.config/setup-backups/ first (restore: dconf load).
set -u
bk=~/.config/setup-backups; mkdir -p "$bk"; t=$(date +%Y%m%d-%H%M%S)
for path in /org/gnome/desktop/wm/keybindings/ /org/gnome/shell/keybindings/ /org/gnome/settings-daemon/plugins/media-keys/ /org/gnome/mutter/ /org/gnome/desktop/wm/preferences/; do
  dconf dump "$path" > "$bk/gnome-$(echo "$path" | tr / _)$t.ini"; done
S() { gsettings set "$@" 2>/dev/null || echo "skip: $*"; }
W=org.gnome.desktop.wm.keybindings; SH=org.gnome.shell.keybindings; MK=org.gnome.settings-daemon.plugins.media-keys

# 9 fixed workspaces: Super+N go, Super+Shift+N move window (like Hyprland)
S org.gnome.mutter dynamic-workspaces false
S org.gnome.desktop.wm.preferences num-workspaces 9
S org.gnome.shell.extensions.dash-to-dock hot-keys false
for i in $(seq 1 9); do
  S $SH switch-to-application-$i "[]"
  S $W switch-to-workspace-$i "['<Super>$i']"
  S $W move-to-workspace-$i "['<Super><Shift>$i']"
done
S $W switch-to-workspace-left  "['<Super><Control>Left']"
S $W switch-to-workspace-right "['<Super><Control>Right']"
S $W switch-to-workspace-last  "['<Super>End']"
# windows
S $W close "['<Super>q', '<Alt>F4']"
S $W toggle-maximized "['<Super>m', '<Alt>F10']"
S $W toggle-fullscreen "['<Super><Shift>m']"
S $SH toggle-message-tray "['<Super>n']"
S $SH focus-active-notification "[]"
S $W move-to-monitor-left "[]"; S $W move-to-monitor-right "[]"; S $W move-to-monitor-up "[]"; S $W move-to-monitor-down "[]"
S $W minimize "['<Super>h']"
# system
S $MK screensaver "['<Super>l']"
S $MK logout "['<Super><Shift>e', '<Control><Alt>Delete']"
S $MK home "['<Super>e']"
S $MK www "['<Super>b']"
S $SH show-screenshot-ui "['Print', '<Super><Shift>s']"
S $SH screenshot "['<Shift>Print']"
S $SH screenshot-window "['<Alt>Print']"
cd_ext=~/.local/share/gnome-shell/extensions/clipboard-indicator@tudmotu.com/schemas
[ -d "$cd_ext" ] && gsettings --schemadir "$cd_ext" set org.gnome.shell.extensions.clipboard-indicator toggle-menu "['<Super><Shift>v']"
# same screenshot folder as Hyprland (GNOME default) — nothing to change

# custom launchers (same keys as Hyprland)
base=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
add(){ # id name binding command
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$base/$1/ name "$2"
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$base/$1/ binding "$3"
  gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$base/$1/ command "$4"
  ids+=("'$base/$1/'")
}
ids=()
add terminal  "Terminal"           "<Super>Return"     "ptyxis --new-window"
add vscode    "VS Code"            "<Super>v"          "code"
add claude    "Claude Code"        "<Super>c"          "kitty --class kitty-scratch -e claude"
add codex     "Codex"              "<Super>x"          "kitty --class kitty-scratch -e codex"
add quickterm "Quick terminal"     "<Super>t"          "kitty --class kitty-scratch"
add settings  "Settings"           "<Super>i"          "gnome-control-center"
add guide     "Shortcut guide"     "<Super>slash"      "kitty --class kitty-scratch -e sh -c 'glow -p $HOME/KadaOS/docs/HYPRLAND_GUIDE.md'"
add power     "Power mode cycle"   "<Super><Shift>p"   "$HOME/.config/hypr/scripts/power-profile.sh cycle"
add btop      "Task manager"       "<Control><Shift>Escape" "kitty --class kitty-scratch -e btop"
gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "[$(IFS=,; echo "${ids[*]}")]"
echo "GNOME shortcuts now match Hyprland. Backup: $bk/gnome-*-$t.ini"
