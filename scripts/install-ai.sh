#!/usr/bin/env bash
# Install the KadaOS AI layer (user-level; no sudo). Re-runnable.
set -u
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; src="$root/config/ai"
share=~/.local/share/local-ai; mkdir -p "$share" ~/.local/bin ~/.config/local-ai ~/.config/systemd/user ~/.local/state/setup
install -m755 "$src/fai.py" "$share/fai.py";  ln -sf "$share/fai.py" ~/.local/bin/fai
install -m755 "$src/system-adapt.py" "$share/system-adapt.py"
install -m755 "$src/dictate-live.py" "$share/dictate-live.py"
install -m755 "$src/voice-ask.py" "$share/voice-ask.py"
install -m755 "$src/chat.py" "$share/chat.py"
install -m755 "$src/watch.py" "$share/watch.py"
install -m755 "$src/secretary.py" "$share/secretary.py"
# Assistant voice: Kokoro-82M TTS on the CPU in its own venv (keeps the GPU for the LLM); models from kokoro-onnx releases.
install -m755 "$src/voice-server.py" "$share/voice-server.py"
[ -x "$share/venv-voice/bin/python" ] || python3 -m venv "$share/venv-voice"
"$share/venv-voice/bin/python" -c "import kokoro_onnx" 2>/dev/null || "$share/venv-voice/bin/pip" install -q kokoro-onnx
mkdir -p "$share/voice"
for f in kokoro-v1.0.int8.onnx voices-v1.0.bin; do
  [ -s "$share/voice/$f" ] || curl -fsSL -o "$share/voice/$f" "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f"
done
mkdir -p ~/.local/share/applications
sed "s|%h|$HOME|" "$src/applications/org.myos.Chat.desktop" > ~/.local/share/applications/org.myos.Chat.desktop
for b in "$src"/bin/*; do install -m755 "$b" ~/.local/bin/; done
install -m644 "$src/zsh-ai.zsh" "$share/zsh-ai.zsh"
[ -f ~/.config/local-ai/config.json ] || cp "$src/config.json" ~/.config/local-ai/config.json
cp "$src"/systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ollama-local.service docs-index.timer myos-watch.timer >/dev/null 2>&1
[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] && systemctl --user restart system-adapt.service
grep -q 'local-ai/zsh-ai.zsh' ~/.zshrc 2>/dev/null || printf '\n# KadaOS AI (??, ??!, why, ai)\n[ -f ~/.local/share/local-ai/zsh-ai.zsh ] && source ~/.local/share/local-ai/zsh-ai.zsh\n' >> ~/.zshrc
# Honor the configured generation/embedding models and check exact tags.
models=$(python3 - "$HOME/.config/local-ai/config.json" <<'PYTHON'
import json, sys
config = json.load(open(sys.argv[1]))
for key in ('model', 'embed_model'):
    print(config[key])
PYTHON
) || exit 1
while IFS= read -r m; do
  ollama show "$m" >/dev/null 2>&1 || ollama pull "$m" || exit 1
done <<< "$models"
w=$share/whisper; mkdir -p "$w"
[ -f "$w/ggml-silero-v5.1.2.bin" ] || curl -fsSL -o "$w/ggml-silero-v5.1.2.bin" https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin
[ -f "$w/ggml-large-v3-turbo-q5_0.bin" ] || curl -fL -o "$w/ggml-large-v3-turbo-q5_0.bin" https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin
echo "AI layer installed. Try: fai status"
