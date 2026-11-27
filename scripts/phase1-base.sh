#!/usr/bin/env bash
# Phase 1: base packages, shell/terminal UX, directories. Idempotent.
# shellcheck disable=SC2024 # setup.log is user-writable; only apt needs sudo.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
log "== phase1 start =="
sudo apt-get update >>"$LOG" 2>&1 && sudo DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y >>"$LOG" 2>&1
printf 'iperf3 iperf3/start_daemon boolean false\n' | sudo debconf-set-selections
apt_try build-essential git curl wget ca-certificates gnupg jq yq unzip zip p7zip-full \
  ripgrep fd-find fzf tmux zsh btop htop tree rsync rclone sqlite3 openssh-client \
  shellcheck shfmt make cmake ninja-build pkg-config python3-venv pipx stow direnv just \
  bat eza zoxide starship kitty git-lfs pre-commit timeshift fonts-jetbrains-mono \
  clang clangd lldb gdb iperf3 mtr-tiny traceroute dnsutils socat netcat-openbsd tcpdump \
  fwupd ncdu
# Debian names differ: bat->batcat, fd->fdfind
mkdir -p ~/.local/bin
command -v batcat >/dev/null && ln -sf "$(command -v batcat)" ~/.local/bin/bat
command -v fdfind >/dev/null && ln -sf "$(command -v fdfind)" ~/.local/bin/fd

mkdir -p ~/Projects ~/Workspaces ~/AI ~/Labs/{VMs,ISO,Networks,Notes} ~/Containers ~/Scripts ~/Notes ~/Tools \
  ~/Templates ~/dotfiles ~/Downloads/Development

# zsh config (only create if absent; never overwrite)
if [ ! -f ~/.zshrc ]; then
cat > ~/.zshrc <<'ZRC'
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/go/bin:$PATH"
HISTFILE=~/.zsh_history; HISTSIZE=50000; SAVEHIST=50000
setopt SHARE_HISTORY HIST_IGNORE_DUPS AUTO_CD
autoload -Uz compinit; if [[ -n ~/.zcompdump(N.mh+24) || ! -s ~/.zcompdump ]]; then compinit -d ~/.zcompdump; touch ~/.zcompdump; zcompile ~/.zcompdump 2>/dev/null; else compinit -C -d ~/.zcompdump; fi  # full check once a day
alias ll='eza -lah --group-directories-first'
alias gs='git status'
alias gl='git log --oneline --decorate --graph -20'
alias lg='lazygit'
alias dc='docker compose'
alias dps='docker ps'
alias ..='cd ..'
alias ...='cd ../..'
command -v zoxide >/dev/null && eval "$(zoxide init zsh)"
command -v direnv >/dev/null && eval "$(direnv hook zsh)"
[[ -t 0 && -t 1 ]] && [ -f /usr/share/doc/fzf/examples/key-bindings.zsh ] && . /usr/share/doc/fzf/examples/key-bindings.zsh
command -v fnm >/dev/null && eval "$(fnm env --use-on-cd --shell zsh)"
ZRC
log "wrote ~/.zshrc"
else log "$HOME/.zshrc exists, left untouched"; fi

# git defaults from the doc
git config --global init.defaultBranch main
git config --global fetch.prune true
git config --global pull.rebase true
git config --global rebase.autoStash true
git config --global diff.algorithm histogram
git config --global core.autocrlf input

[ "$(getent passwd "$USER" | cut -d: -f7)" = "$(command -v zsh)" ] || {
  log "switching login shell to zsh"
  sudo chsh -s "$(command -v zsh)" "$USER"
}
grep -q skip_global_compinit ~/.zshenv 2>/dev/null || echo 'skip_global_compinit=1   # ~/.zshrc runs compinit (cached)' >> ~/.zshenv
log "== phase1 done =="
