#!/usr/bin/env python3
"""Capture one spoken question and open the existing AI answer window."""
import importlib.util
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("dictate_live", Path(__file__).with_name("dictate-live.py"))
speech = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speech)

cancelled = False


def cancel(*_):
    global cancelled
    cancelled = True


def notify(message):
    subprocess.run(["notify-send", "-t", "3500", "Voice question", message],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def capture(command=None):
    """Stop after one phrase, 15 seconds without speech, or 20 seconds of speech."""
    rec = subprocess.Popen(command or ["pw-record", "--rate", str(speech.RATE), "--channels", "1",
                                       "--format", "s16", "-"], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL)
    pre, segment, history = [], bytearray(), []
    speaking = False; hot = silence_ms = 0
    started = time.monotonic()
    last_audio = started
    try:
        while not cancelled:
            if not select.select([rec.stdout], [], [], 1)[0]:
                if time.monotonic() - last_audio > (3 if speaking else 15): break
                continue
            buf = rec.stdout.read(speech.FRAME * 2)
            if len(buf) != speech.FRAME * 2: break
            last_audio = time.monotonic()
            x = np.frombuffer(buf, dtype=np.int16).astype(np.float32)
            energy = float(np.sqrt((np.abs(np.fft.rfft(x * speech.WIN)) ** 2)[speech.BAND].sum()) / speech.FRAME)
            history.append(energy); history[:] = history[-150:]
            if len(history) < 20: continue
            floor = float(np.percentile(history, 30))
            on, off = max(floor * 3.5, 350.0), max(floor * 2.2, 220.0)
            hot = hot + 1 if energy > on else 0
            voiced = energy > off if speaking else hot >= 3
            if speaking:
                segment += buf
                silence_ms = 0 if voiced else silence_ms + 20
                if silence_ms >= 850 or len(segment) >= 20 * speech.RATE * 2: break
            else:
                pre.append(buf); pre[:] = pre[-15:]
                if voiced:
                    speaking = True
                    segment = bytearray(b"".join(pre))
                elif time.monotonic() - started > 15:
                    break
    finally:
        rec.terminate()
        try: rec.wait(timeout=2)
        except subprocess.TimeoutExpired: rec.kill()
        rec.stdout.close()
    return bytes(segment) if speaking and not cancelled else b""


def route_question(question):
    """Spoken source prefixes use the same answer flows as keyboard input."""
    clipboard = re.match(r"^(?:ask|answer) (?:about|using|from) (?:my |the )?clipboard[\s,:-]*(.*)$", question, re.I)
    if clipboard and clipboard.group(1).strip(): return "clipboard", clipboard.group(1).strip()
    match = re.match(r"^(?:ask|answer) (?:using|from) my files(?: about)?[\s,:-]*(.*)$",
                     question, flags=re.I)
    return ("rag", match.group(1).strip()) if match and match.group(1).strip() else ("system", question)


def main():
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    notify("Listening. Ask one question, then pause. Press Super+Shift+D again to cancel.")
    pcm = capture()
    if cancelled: notify("Canceled"); return
    if not pcm: notify("No speech heard. Try again."); return
    question = speech.transcribe(pcm)
    if not question: notify("Could not understand the question. Try again."); return
    action, question = route_question(question)
    notify(f"Heard: {question[:150]}")
    args = ["kitty", "--class", "fai-answer", "-e", "fai", "window",
            "--action", "ask" if action == "clipboard" else action, "--question", question,
            "--context-label", "Voice question + clipboard" if action == "clipboard" else "Voice question"]
    if action == "clipboard": args.append("--clipboard")
    subprocess.Popen(args,
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    try: main()
    except Exception as error:
        notify(f"Voice question failed: {error}")
        sys.exit(1)
