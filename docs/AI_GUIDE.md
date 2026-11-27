# AI features

Everything runs **locally**: Ornith 9B through Ollama (chosen by test, see ADR 0014) on the RTX 5050, Whisper for voice (also on the RTX 5050 via Vulkan, about 1 s per sentence) and Tesseract for OCR.
Nothing leaves the laptop unless you pick a **Claude** option. The model loads onto the GPU the first time you
use it (about 4 s) and unloads after 5 idle minutes, so it uses no GPU memory or battery while idle.

## Shortcuts (Hyprland)
| Keys | What it does |
|---|---|
| **Super + Shift + Space** | Choose **selected text**, **clipboard text**, or a fresh question, then use Explain, Summarize, Fix, Rewrite, Reply, Ask, or Explain error. The source is shown before sending. |
| **Super + Z** | Open/close the **assistant** (also: click the floating orb). It works *in the chat*: checks your laptop, converts files, runs layouts and scoped security recipes, and runs any command you approve (admin tasks via the system password prompt). Every step and its real output is shown. |
| **Super + Shift + T** | Select a screen area and its **text is copied** (English + Malayalam OCR) |
| **Super + Ctrl + T** | Select a screen area and ask AI about it (e.g. an error on screen) |
| **Super + D** | **Live dictation** on/off. Speak naturally: a live preview shows your words, and each phrase is typed into the current app when you pause. Say "new line" or "new paragraph" to press Enter. It stops by itself after 60 s of silence |
| **Super + Shift + D** | **Talk to the assistant.** (Also: hold the orb, the mic button, or Ctrl+Space in the panel.) The orb listens (green ring), you speak and pause, and the request goes to the assistant with all its tools. It **answers out loud** (Kokoro voice on the CPU, `"voice"` in `~/.config/local-ai/config.json`) while the full answer stays on screen. Esc or speaking again interrupts. Panel menu → **Speak every reply** makes typed questions spoken too. Voice log: `~/.cache/myos-assistant.log`. |
| **Super + Shift + F** | **Search your files by meaning**, open a result, or "Ask AI using these files" |

The answer window shows the source and output destination before sending, streams the reply, and copies a successful answer automatically. A failed or empty answer leaves the existing clipboard intact. Then:
- **Enter** pastes into the previous app only for Fix, Rewrite, Reply, and Translate.
- **F** asks a follow-up question.
- **C** asks Claude instead.
- **O** opens a numbered cited file (file answers only).
- **H** previews a command or path from the answer and copies it only after you type `COPY`. It never executes it.
- **Esc** or **Q** closes the window.

From **Super + Z**, type `/files <question>` to answer using indexed files, `/project <question>` to choose one indexed project folder, `/file <question>` to choose one file, `/search <words>` to open file search, or `/clipboard <question>` to ask about copied text. The selection and screen-text menus offer **Find related files** and **Explain error with laptop facts**. Project search also works in the terminal with `fai search --project PATH <words>` or `fai rag --project PATH <question>`. File answers show numbered citations and **F** keeps their context for follow-ups.

For a voice question, say **“ask using my files about …”** to use indexed files, or **“ask about my clipboard …”** to use the current clipboard. Other questions use the laptop assistant. The answer appears on screen only. Dictation (**Super + D**) still types into the focused app and does not submit an AI question.

## Your laptop's assistant
Ask about your system with Super + Z, `ai <question>` in the terminal, or "Troubleshoot on my system" in the selection menu.
The AI then checks the laptop live before answering:
1. It calls a **status** tool: battery and time left, power mode, temperatures, fan, GPU, memory, disk, key services, containers, network and top processes.
2. If needed, it runs **read-only** diagnostics such as `journalctl`, `systemctl status` or `nmcli`.
3. It searches the setup docs to answer "how do I…" questions about this setup.

**Safety:**
- It **cannot change anything**. Commands come from a read-only allow-list, and it refuses anything that would restart, delete, change settings, use sudo, use pipes or read secrets.
- When a fix is needed, it shows you the exact command to run, and you decide. The allow-list validates complete commands and options; unrestricted environment dumps, container inspection and mutating flags are refused. File-content reads are limited to setup docs, Hyprland configuration and selected system metrics. Other diagnostics are suggested for you to run manually.
- The commands it ran are listed in grey as `⟩ …`, so you can see what it checked.
- **Explain error with laptop facts** takes a live read-only status snapshot on demand, shows those facts under the answer, and may look up relevant setup docs. It never runs the proposed fix.

Examples: "why is my battery draining?", "is anything broken?", "what's using my RAM?", "why no sound?", "how do I change my wallpaper here?"

**Remote devices** (Super+Z): "are my Pis online?", "what's failing on pi5?", "start `make` on pi5 and tell me when it's done".
Status, logs, network and jobs are read-only. Running commands, jobs and reboots ask first. See [REMOTE.md](REMOTE.md#ask-the-assistant).

## Terminal (zsh, works in Ubuntu too)
| Command | What it does |
|---|---|
| `?? find big files in Downloads` | Suggests one command, shows its exact text, and inserts it on your editable prompt only after you type `INSERT`. It never runs anything by itself |
| `??! …` | Same, but asks Claude (more accurate, slower) |
| `why` | Right after a failed command, explains what went wrong and offers an `INSERT` card for an explicit command/path. It asks before re-running the failed command to capture output |
| `cmd 2>&1 \| why` | Explains an error from piped output |
| `ai <question>` | Answer in the terminal. It can check your laptop live (read-only) |
| `fai search <words>` / `fai rag <question>` | Search files, or get an answer grounded in your own files |
| `ais <words>` / `aip <question>` | Search or ask within the current Git project (or current folder outside Git) |
| `fai status` / `fai unload` | Server, model and index status / free the GPU now |

## Automatic behaviour (system-adapt service)
| When | What happens |
|---|---|
| You unplug | Power saver and 60 Hz. Plugging in switches to balanced and 165 Hz. A manual choice with Super + Shift + P lasts until the next plug or unplug |
| A window goes fullscreen | Do not disturb turns on, and turns off again when you leave fullscreen |
| Every 10 min | Checks disk usage above 90%, failed services, CPU at 95°C or more, low RAM and overdue backups (7 days or more). Each warning repeats at most every 6 h |

## Bar and control center
- **Robot icon:** gold means the model is on the GPU. Click it to ask, right-click to unload it.
- **Red REC badge:** shows while live dictation is on. Click it to stop.
- **GPU memory:** the speech engine (whisper-server, about 0.8 GB of video memory) starts when you begin dictating and stops 2 minutes after the worker exits, including automatic silence stops. Starting another recording keeps it running.
- **Control center** (Super + N): has **Ask AI**, **Voice question**, **Find files**, and **Dictate** buttons.

## Settings
Settings live in `~/.config/local-ai/config.json`:
- `model`: the AI model to use. Default: `ornith:9b` (Ollama library; the best tool use in our comparison, ADR 0014). Any Ollama model works; smaller ones answer faster on modest hardware.
- `dictate_language`: `auto`, `en` or `ml`.
- `search_roots`: which folders are indexed. The index refreshes hourly on AC power, with a battery-drain check for the HP charger-reporting bug; run `fai index` to refresh it manually. Search combines local embeddings with SQLite FTS5 keyword ranking; a project filter avoids scanning unrelated projects. Credential-named files and symlinks are excluded. Edits and deletions update both indexes; empty retrieval does not generate an unsupported answer.
- `adapt`: which power profile and refresh rate to use on AC and on battery.

Model changes apply to new `fai` calls immediately; restart existing agent sessions to reload their MCP settings. For `adapt` changes, run `systemctl --user restart system-adapt`.

## Where things live
| What | Where |
|---|---|
| Code | `config/ai/` (fai.py, system-adapt.py, bin/ai-*) |
| Installer | `scripts/install-ai.sh` (user-level) |
| System packages | `scripts/phase10-ai-desktop.sh` (tesseract, whisper.cpp, ffmpeg) |
| Models | `~/.ollama/models` and `~/.local/share/local-ai/whisper` |
| Search index | `~/.local/share/local-ai/index.db` |
| Services | `ollama-local`, `system-adapt`, `docs-index.timer` (`systemctl --user status …`) |

## Limits
- **Model size:** an 8B model is good for everyday text jobs and short commands. For hard reasoning or code, pick a Claude option.
- **Voice input:** one question can be up to about 20 seconds. Recognition quality depends on the microphone, language, and noise level.
- **Hyprland only:** the desktop pop-ups (AI menu, OCR, dictation) work in Hyprland only. Ubuntu/GNOME blocks the screen-capture and typing tools they use. The terminal commands work in both desktops.

## Verification and troubleshooting

- `bash scripts/desktop-check.sh` checks desktop services, AI installation mirrors, models, and a local answer. `--ui` skips model/agent checks.
- `python3 -m unittest discover -s tests -v` runs offline regression tests without recording audio, typing, or running model-generated commands.
- `systemctl --user status docs-index` shows indexing status; a battery skip is logged explicitly. Ambiguous zero-watt battery readings are sampled for up to 90 seconds before indexing.
- `why` preserves the previous command. Open a new terminal or run `source ~/.local/share/local-ai/zsh-ai.zsh` to load updated shell hooks.
- After updating `fai.py`, restart existing agent sessions when convenient to reconnect their MCP server and load the new diagnostic guard. Newly launched desktop AI commands use the installed code immediately.

The AI remains fallible. Automated checks verify integration behavior; they do not guarantee model answers or recognition of your voice in every acoustic setting.
