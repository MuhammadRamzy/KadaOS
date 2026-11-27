#!/usr/bin/env bash
# Browsers, user-level (no sudo). Re-run any time; it updates in place.
#   Chrome (daily, default): launched through ~/.local/bin/google-chrome-stable, which adds the flags in
#     ~/.config/chrome-flags.conf (touchpad back/forward swipes, hardware video decode on the Intel iGPU).
#     Every way of opening Chrome goes through it: Super+B, the app grid, links, Super+Space web search.
#   Zen (work, many tabs; Firefox-based): installed to ~/.local/opt/zen from the official release, checksum
#     verified; `zen` command, app-grid entry, Super+Alt+B. It updates itself (the folder is yours).
#   Import from Chrome into Zen: Super+Space → "Zen: import from Chrome" (pick the Chrome profile to bring:
#     bookmarks, history, passwords). Chrome keeps all its profiles; nothing is removed from it.
# Hardware video decode needs Intel's VA-API driver once:  sudo apt install intel-media-va-driver-non-free
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
apps=~/.local/share/applications; mkdir -p "$apps" ~/.local/bin ~/.local/opt

# ── Chrome: flags file (kept if you've edited it) + wrapper + launcher entry pointing at the wrapper
[ -f ~/.config/chrome-flags.conf ] || install -Dm644 "$root/config/browsers/chrome-flags.conf" ~/.config/chrome-flags.conf
install -Dm755 "$root/config/browsers/google-chrome-stable" ~/.local/bin/google-chrome-stable
ln -sfn ~/.local/bin/google-chrome-stable ~/.local/bin/google-chrome
if [ -f /usr/share/applications/google-chrome.desktop ]; then
  sed "s|/usr/bin/google-chrome-stable|$HOME/.local/bin/google-chrome-stable|g" /usr/share/applications/google-chrome.desktop > "$apps/google-chrome.desktop"
fi

# ── Zen: official tarball, verified against the checksum GitHub publishes for it
if [ ! -x ~/.local/opt/zen/zen ]; then                       # installed: Zen updates itself, leave it be
  meta="$(curl -fsSL https://api.github.com/repos/zen-browser/desktop/releases/latest)"
  read -r tag sum < <(python3 -c 'import json,sys; d=json.load(sys.stdin); a=[a for a in d["assets"] if a["name"]=="zen.linux-x86_64.tar.xz"][0]; print(d["tag_name"], (a.get("digest") or "").removeprefix("sha256:"))' <<<"$meta")
  [ -n "$sum" ] || { echo "Zen: no checksum published for $tag; not installing" >&2; exit 1; }
  tmp="$(mktemp -d)"; trap 'rm -rf "${tmp:?}"' EXIT
  echo "Downloading Zen $tag (~110 MB)…"
  curl -fL --progress-bar -o "$tmp/zen.tar.xz" "https://github.com/zen-browser/desktop/releases/download/$tag/zen.linux-x86_64.tar.xz"
  echo "$sum  $tmp/zen.tar.xz" | sha256sum -c --quiet || { echo "Zen: checksum mismatch; not installing" >&2; exit 1; }
  mkdir "$tmp/x"; tar -xJf "$tmp/zen.tar.xz" -C "$tmp/x"
  [ -x "$tmp/x/zen/zen" ] || { echo "Zen: unexpected archive layout" >&2; exit 1; }
  rm -rf ~/.local/opt/zen.old; [ -d ~/.local/opt/zen ] && mv ~/.local/opt/zen ~/.local/opt/zen.old
  mv "$tmp/x/zen" ~/.local/opt/zen; echo "$tag" > ~/.local/opt/zen/.kada-version; rm -rf ~/.local/opt/zen.old
fi
install -Dm644 "$root/config/browsers/zen-policies.json" ~/.local/opt/zen/distribution/policies.json
ln -sfn ~/.local/opt/zen/zen ~/.local/bin/zen
icon=~/.local/opt/zen/browser/chrome/icons/default/default128.png
sed -e "s|@ZEN@|$HOME/.local/opt/zen/zen|g" -e "s|@ICON@|$icon|g" "$root/config/browsers/zen.desktop" > "$apps/zen.desktop"
update-desktop-database "$apps" 2>/dev/null || true
echo "browsers: Chrome (default, Super+B) with ~/.config/chrome-flags.conf · Zen $(cat ~/.local/opt/zen/.kada-version 2>/dev/null) (Super+Alt+B, \`zen\`)"
