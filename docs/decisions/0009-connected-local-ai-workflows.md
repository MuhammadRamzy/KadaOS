# 0009 — Connected local AI workflows

Date: 2026-09-27 · Status: accepted

The AI entry points share one answer window. Text, clipboard, OCR and file-search questions can flow into that window, with follow-ups. The voice shortcut captures one question using the existing Whisper service and routes an explicit “ask using my files” request to grounded file answers. Answers appear on screen only, per the user's preference. Dictation remains a separate voice-to-typing action.

File answers from terminal and desktop use the same retrieved excerpts and numbered sources. Search combines semantic similarity with exact terms and boosts lines that contain an actual key binding for shortcut questions. Search results open files by the indexed path, not by parsing their display label. All model calls and transcription stay local unless the user explicitly selects Claude.

The voice question stops after a pause, a 20-second utterance, or an idle timeout. A second shortcut press cancels recording. Voice questions and dictation share the Whisper service and its two-minute idle release; the release checks both recording types before stopping it. Voice recognition still needs a real microphone test with the user's speech.
