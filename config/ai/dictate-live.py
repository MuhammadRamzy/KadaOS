#!/usr/bin/env python3
"""Live dictation: speak naturally — a live preview shows what you're saying, and each phrase is typed into the
focused app when you pause. Whisper large-v3-turbo runs on the RTX 5050 (whisper-server via Vulkan).

Started/stopped by `ai-dictate` (Super+D). Say "new line" / "new paragraph" to press Enter.
"""
import io, json, os, re, signal, subprocess, threading, time, urllib.request, uuid, wave
from pathlib import Path
import numpy as np

HOME = Path.home()
RT = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
PIDF = RT / "dictate.pid"
URL = "http://127.0.0.1:8178/inference"
CFG = {}
try: CFG = json.loads((HOME / ".config/local-ai/config.json").read_text())
except Exception: pass
LANG = CFG.get("dictate_language", "auto")

RATE, FRAME = 16000, 320                        # 20 ms frames
WIN = np.hanning(FRAME).astype(np.float32)
_fr = np.fft.rfftfreq(FRAME, 1 / RATE); BAND = (_fr >= 300) & (_fr <= 3400)
PAUSE_MS, MIN_SPEECH_MS, PREROLL_MS = 650, 300, 300
MAX_SEG_S, IDLE_STOP_S, PARTIAL_EVERY = 20, 60, 0.9
HALLU = {"thank you.", "thanks for watching!", "thank you for watching.", "you", "bye.", "subtitles by the amara.org community",
         ".", "..", "...", "[blank_audio]", "(silence)", "[silence]", "[music]", "(music)"}

def notify(body, ms=60000, title="● Dictating"):
    subprocess.Popen(["notify-send", "-t", str(ms), "-a", "Dictation", "-h", "string:x-canonical-private-synchronous:dictate",
                      title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def wav_bytes(pcm):
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
    return b.getvalue()

def transcribe(pcm, prompt=""):
    boundary = uuid.uuid4().hex
    parts = [("response_format", "json"), ("temperature", "0.0"), ("language", LANG)]
    if prompt: parts.append(("prompt", prompt[-200:]))
    body = b"".join(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode() for k, v in parts)
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\nContent-Type: audio/wav\r\n\r\n").encode()
    body += wav_bytes(pcm) + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try: text = json.loads(urllib.request.urlopen(req, timeout=20).read()).get("text", "")
    except Exception as e: return ""
    text = " ".join(text.split())
    return "" if text.lower().strip() in HALLU or not re.search(r"\w", text) else text

def type_text(t):
    subprocess.run(["wtype", "--", t], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def active_window():
    try: return json.loads(subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True, text=True, timeout=2).stdout or "{}").get("address")
    except Exception: return None

def target_ok(state):
    """Late phrases must never land in another app: same window as at start, and screen not locked."""
    if not state.get("target"): return True              # not on Hyprland: no window identity to check
    locked = subprocess.run(["pgrep", "-x", "hyprlock"], stdout=subprocess.DEVNULL).returncode == 0
    return not locked and active_window() == state["target"]

def emit(text, state):
    """Type a finished phrase; handle spoken commands."""
    if not target_ok(state):
        state["held"] = (state.get("held", "") + " " + text).strip()
        subprocess.run(["wl-copy"], input=state["held"], text=True)
        notify("Focus changed — not typed. Held text is on the clipboard (Ctrl+V)", 6000, "● Dictation paused typing")
        return
    low = text.lower().strip(" .,!")
    if low in ("new line", "next line"): subprocess.run(["wtype", "-k", "Return"]); state["first"] = True; return
    if low in ("new paragraph",): subprocess.run(["wtype", "-k", "Return", "-k", "Return"]); state["first"] = True; return
    text = re.sub(r"\s*\b(new line|next line)\b[.,]?\s*", "\n", text, flags=re.I)
    out = ("" if state["first"] else " ") + text
    type_text(out); state["first"] = False; state["typed"] += out
    subprocess.run(["wl-copy"], input=state["typed"].strip(), text=True)

def main():
    PIDF.write_text(str(os.getpid()))
    stop = threading.Event()
    for s in (signal.SIGTERM, signal.SIGINT): signal.signal(s, lambda *_: stop.set())
    src = os.environ.get("DICTATE_TEST_PCM")          # test hook: raw s16le 16 kHz file instead of the mic
    cmd = ["cat", "--", src] if src else ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"]
    rec = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    notify("Listening… speak naturally · pause to type · Super+D to stop", title="● Dictation on")
    subprocess.run(["pkill", "-RTMIN+10", "waybar"])

    state = {"first": True, "typed": "", "held": "", "target": active_window()}
    pre = []                                   # pre-roll frames
    seg, speaking, speech_ms, silence_ms = bytearray(), False, 0, 0
    hist, calib, hot = [], True, 0
    last_voice = time.time(); last_partial = 0.0; busy = threading.Lock()
    fin_q = []; fin_lock = threading.Lock()

    def partial(pcm):
        if not busy.acquire(blocking=False): return
        try:
            t = transcribe(pcm, state["typed"])
            if t and not stop.is_set(): notify(f"{t} …")
        finally: busy.release()

    def finalizer():
        while not (stop.is_set() and not fin_q):
            with fin_lock: job = fin_q.pop(0) if fin_q else None
            if job is None: time.sleep(0.03); continue
            t = transcribe(job, state["typed"])
            if t: emit(t, state); notify(f"✔ {t}", 4000, "● Dictating")
    ft = threading.Thread(target=finalizer, daemon=True); ft.start()

    def finish_segment():
        nonlocal seg, speaking, speech_ms, silence_ms
        if speech_ms >= MIN_SPEECH_MS:
            with fin_lock: fin_q.append(bytes(seg))
        seg, speaking, speech_ms, silence_ms = bytearray(), False, 0, 0

    try:
        while not stop.is_set():
            buf = rec.stdout.read(FRAME * 2)
            if not buf or len(buf) < FRAME * 2: break
            x = np.frombuffer(buf, dtype=np.int16).astype(np.float32)
            # energy in the speech band only (300–3400 Hz): ignores fan rumble / hum
            e = float(np.sqrt((np.abs(np.fft.rfft(x * WIN)) ** 2)[BAND].sum()) / FRAME)
            hist.append(e); hist[:] = hist[-150:]                       # last 3 s
            if calib:
                if len(hist) >= 20: calib = False
                continue
            floor = float(np.percentile(hist, 30))
            on_thr, off_thr = max(floor * 3.5, 350.0), max(floor * 2.2, 220.0)
            hot = hot + 1 if e > on_thr else 0
            voiced = (e > off_thr) if speaking else (hot >= 3)       # hysteresis + 60 ms onset (skips key clicks)
            if speaking:
                seg += buf
                if voiced: speech_ms += 20; silence_ms = 0; last_voice = time.time()
                else: silence_ms += 20
                if silence_ms >= PAUSE_MS or len(seg) >= MAX_SEG_S * RATE * 2: finish_segment()
                elif time.time() - last_partial > PARTIAL_EVERY and len(seg) > RATE * 2 * 0.8:
                    last_partial = time.time(); threading.Thread(target=partial, args=(bytes(seg),), daemon=True).start()
            else:
                pre.append(buf); pre[:] = pre[-(PREROLL_MS // 20):]
                if voiced:
                    speaking, seg, speech_ms, silence_ms = True, bytearray(b"".join(pre)), 20, 0
                    last_voice = time.time()
                elif time.time() - last_voice > IDLE_STOP_S:
                    notify("Stopped after 60 s of silence", 3000, "Dictation off"); break
    finally:
        if speaking: finish_segment()
        stop.set(); rec.terminate()
        ft.join(timeout=25)
        PIDF.unlink(missing_ok=True)
        subprocess.run(["pkill", "-RTMIN+10", "waybar"])
        typed = state["typed"].strip()
        if state["held"]: notify(f"Not typed (focus changed), copied: {state['held'][:200]}", 8000, "Dictation off")
        else: notify((typed[:200] + ("…" if len(typed) > 200 else "")) if typed else "Nothing typed", 4000, "✔ Dictation off (copied)" if typed else "Dictation off")

if __name__ == "__main__":
    main()
