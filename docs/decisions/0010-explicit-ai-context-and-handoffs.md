# 0010 — Explicit AI context and reviewable handoffs

Date: 2026-09-27 · Status: accepted

The AI menu asks the user to choose selected text, clipboard text, or a fresh question. A source label and the popup/clipboard destination appear before the model request. This avoids treating an old primary selection as the current one. OCR, a chosen file, a chosen project, and a spoken clipboard question enter the same answer window. Audio output remains disabled.

Project retrieval filters indexed paths before loading vectors and combines embeddings with SQLite FTS5 rank. FTS5 is built once on the existing index and kept current by insert/delete triggers. Indexed files still pass path, symlink, and credential checks before appearing in results. A source can be opened only from the numbered citations.
Terminal `ais` and `aip` choose the current Git repository root, falling back to the current directory.

The error action captures a live read-only status snapshot only when invoked. Its answer shows that snapshot and may use the existing allow-listed diagnostics and setup-doc search. The answer cannot run a fix. Suggested terminal commands and paths use a preview card: the popup copies only after `COPY`, and `??`/`why` insert text on an editable prompt only after `INSERT`. The user executes any command separately.
