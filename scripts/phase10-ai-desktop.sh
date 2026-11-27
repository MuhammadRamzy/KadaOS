#!/usr/bin/env bash
# Phase 10: system packages for the AI desktop features (OCR + voice). Everything else is user-level.
set -u
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log "== phase10 AI desktop start =="
apt_try python3-numpy python3-gi curl jq tesseract-ocr tesseract-ocr-eng tesseract-ocr-mal whisper.cpp libggml0-backend-vulkan vulkan-tools ffmpeg
bash "$root/scripts/install-ai.sh" | tee -a "$LOG"
log "== phase10 done =="
