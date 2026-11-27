#!/usr/bin/env python3
"""The assistant's voice: a small resident TTS server (Kokoro-82M on the CPU, so the GPU stays free for the LLM).

Runs in its own venv (~/.local/share/local-ai/venv-voice). The chat app starts it on demand and talks to it over a
unix socket, one JSON object per line:
  {"say": "text"}     queue a sentence (spoken in order, starts as soon as it is synthesized)
  {"stop": true}      stop speaking now and drop the queue (barge-in / Esc)
  {"status": true}    → {"speaking": bool}
Exits after 30 idle minutes; the next request starts it again.
"""
import json, os, queue, socket, subprocess, sys, threading, time
from pathlib import Path

HOME = Path.home()
SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "myos-voice.sock"
MODEL = HOME / ".local/share/local-ai/voice"
CFG = {"voice": "bm_george", "voice_speed": 1.05}
try: CFG.update({k: v for k, v in json.loads((HOME / ".config/local-ai/config.json").read_text()).items() if k in CFG})
except Exception: pass

from kokoro_onnx import Kokoro
tts = Kokoro(str(MODEL / "kokoro-v1.0.int8.onnx"), str(MODEL / "voices-v1.0.bin"))
LANG = "en-gb" if CFG["voice"].startswith("b") else "en-us"

jobs, gen = queue.Queue(), 0          # gen increments on stop: stale jobs/audio are dropped
player, speaking, last = None, False, time.time()
lock = threading.Lock()

def worker():
    global player, speaking, last
    while True:
        g, text = jobs.get()
        if g != gen: continue
        speaking = True                    # synthesizing counts as speaking (no flicker between sentences)
        try: audio, sr = tts.create(text, voice=CFG["voice"], speed=float(CFG["voice_speed"]), lang=LANG)
        except Exception as e: print("tts:", e, file=sys.stderr); audio = None
        if audio is None or g != gen:      # failed or interrupted while synthesizing
            speaking = not jobs.empty(); continue
        with lock:
            speaking = True
            player = subprocess.Popen(["pw-cat", "--playback", "--rate", str(sr), "--channels", "1", "--format", "f32", "-"],
                                      stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try: player.stdin.write(audio.astype("float32").tobytes()); player.stdin.close(); player.wait()
        except (BrokenPipeError, ValueError): pass
        with lock:
            player = None; last = time.time()
            if jobs.empty(): speaking = False

def stop():
    global gen, speaking
    gen += 1
    with lock:
        if player: player.kill()
        speaking = False
    while not jobs.empty():
        try: jobs.get_nowait()
        except queue.Empty: break

def handle(conn):
    global last
    with conn, conn.makefile("rw") as f:
        for line in f:
            try: req = json.loads(line)
            except ValueError: continue
            last = time.time()
            if req.get("say", "").strip(): jobs.put((gen, req["say"].strip()))
            if req.get("stop"): stop()
            if req.get("status"): f.write(json.dumps({"speaking": speaking or not jobs.empty()}) + "\n"); f.flush()

def main():
    SOCK.unlink(missing_ok=True)
    srv = socket.socket(socket.AF_UNIX); srv.bind(str(SOCK)); os.chmod(SOCK, 0o600); srv.listen(8); srv.settimeout(60)
    threading.Thread(target=worker, daemon=True).start()
    while True:
        try: conn, _ = srv.accept()
        except socket.timeout:
            if not speaking and jobs.empty() and time.time() - last > 1800: break
            continue
        threading.Thread(target=handle, args=(conn,), daemon=True).start()
    SOCK.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
