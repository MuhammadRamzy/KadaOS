#!/usr/bin/env bash
# Phase 2: dev toolchain (uv, fnm/node/pnpm/bun, rust, go, jdk21, VS Code, gh, lazygit)
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
log "== phase2 start =="
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.bun/bin:$PATH"
apt_try golang-go openjdk-21-jdk gh
# uv (vendor installer)
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh >>"$LOG" 2>&1; }
uv python install 3.12 >>"$LOG" 2>&1 && log "python 3.12 via uv"
# fnm + node LTS + pnpm
command -v fnm >/dev/null || { curl -fsSL https://fnm.vercel.app/install | bash -s -- --skip-shell >>"$LOG" 2>&1; }
export PATH="$HOME/.local/share/fnm:$PATH"
if command -v fnm >/dev/null; then
  eval "$(fnm env --shell bash)"; fnm install --lts >>"$LOG" 2>&1; fnm default lts-latest >>"$LOG" 2>&1
  corepack enable pnpm >>"$LOG" 2>&1 || npm i -g pnpm >>"$LOG" 2>&1
fi
grep -q 'fnm' ~/.zshrc 2>/dev/null && ! grep -q '.local/share/fnm' ~/.zshrc && \
  sed -i '1a export PATH="$HOME/.local/share/fnm:$PATH"' ~/.zshrc
# bun
command -v bun >/dev/null || { curl -fsSL https://bun.sh/install | bash >>"$LOG" 2>&1; }
if [ -x "$HOME/.bun/bin/bun" ] && ! grep -q '\.bun/bin' "$HOME/.zshrc" 2>/dev/null; then
  printf '\nexport PATH="$HOME/.bun/bin:$PATH"\n' >> "$HOME/.zshrc"
fi
# rustup
command -v rustup >/dev/null || { curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y >>"$LOG" 2>&1; }
# lazygit (GitHub release)
if ! command -v lazygit >/dev/null; then
  v=$(curl -s https://api.github.com/repos/jesseduffield/lazygit/releases/latest | jq -r .tag_name | tr -d v)
  [ -n "$v" ] && [ "$v" != null ] && curl -sL "https://github.com/jesseduffield/lazygit/releases/download/v${v}/lazygit_${v}_Linux_x86_64.tar.gz" | tar xz -C ~/.local/bin lazygit && log "lazygit $v"
fi
# VS Code (Microsoft apt repo)
if ! command -v code >/dev/null; then
  curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor | sudo tee /usr/share/keyrings/microsoft.gpg >/dev/null
  echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/code stable main" | sudo tee /etc/apt/sources.list.d/vscode.list >/dev/null
  sudo apt-get update >>"$LOG" 2>&1; apt_try code
fi
# VS Code baseline settings + core extensions (only if not already configured)
mkdir -p ~/.config/Code/User
[ -f ~/.config/Code/User/settings.json ] || cat > ~/.config/Code/User/settings.json <<'J'
{
  "editor.formatOnSave": true,
  "editor.rulers": [100, 120],
  "editor.minimap.enabled": false,
  "editor.stickyScroll.enabled": true,
  "editor.bracketPairColorization.enabled": true,
  "terminal.integrated.defaultProfile.linux": "zsh",
  "files.trimTrailingWhitespace": true,
  "files.insertFinalNewline": true,
  "git.autofetch": true
}
J
if command -v code >/dev/null; then
  for e in eamodio.gitlens github.vscode-pull-request-github usernamehw.errorlens editorconfig.editorconfig \
    esbenp.prettier-vscode dbaeumer.vscode-eslint redhat.vscode-yaml yzhang.markdown-all-in-one \
    davidanson.vscode-markdownlint bierner.markdown-mermaid ms-python.python charliermarsh.ruff \
    rust-lang.rust-analyzer golang.go llvm-vscode.clangd ms-azuretools.vscode-docker \
    ms-vscode-remote.remote-ssh anthropic.claude-code catppuccin.catppuccin-vsc pkief.material-icon-theme; do
    code --install-extension "$e" >>"$LOG" 2>&1 && log "ext $e" || log "ext FAILED $e"
  done
fi
log "== phase2 done =="
