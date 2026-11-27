# Hyprland beginner guide

**Super** is the Windows key. **You only need one shortcut: Super + Space.** Type what you want and press Enter.

| Type | You get |
|---|---|
| an app, a feature or a task: `chrome`, `record`, `free up space`, `bluetooth`, `presenting` | it opens or runs; every shortcut in this guide is in there too, with its keys shown so you learn them as you go |
| a setting: `volume`, `display`, `printer`, `dark mode` | that Settings page |
| a file, folder or project name | it opens (projects open in VS Code with a terminal) |
| anything else: `best biryani kochi` | **Enter searches Google in Chrome** (`yt …` YouTube · `gh …` GitHub · `w …` Wikipedia · `maps …` · `img …`) |
| `? question` | asks the assistant · `> command` runs it in a terminal |
| `12*7`, `10 km to mi`, `255 to hex`, `sha256 text`, `emoji fire` | the answer; Enter copies it |
| `clip word` | clipboard history · `edit hyprland` (or `tidy`, `monitor`…) opens that config file · `help` shows all of this |

What you pick often moves to the top (and shows up before you type). Typos are fine (`bluetoth` finds Bluetooth).
Still handy: **Super + /** lists every shortcut, **Super + Shift + /** opens this guide.

The **?** button in the bar's quick-tools drawer (hover the **‹** arrow) also opens the shortcut list. Right-click it to open this guide.

## 1. How Hyprland differs from GNOME/Windows
- **Windows tile automatically.** A new window splits the space with the current one, so nothing overlaps.
  To get a normal floating window, press **Super + F**.
- **Workspaces replace minimizing.** You have workspaces 1–9, like separate desks.
  Press **Super + 1…9** to switch, or **Super + Shift + 1…9** to send the current window there.
  The dots on the left of the bar show which workspaces you're using.
- **Keyboard first, mouse optional.** You can still hold **Super** and drag with the left mouse button to move a window,
  or with the right mouse button to resize it. A 3-finger swipe on the touchpad changes workspace.

## 2. Everyday shortcuts (these work the same in Ubuntu/GNOME too)
| Keys | Action |
|---|---|
| Super + Enter / Ctrl + Alt + T | Terminal (Ptyxis, same as Ubuntu) |
| Super + T | Floating quick terminal |
| Super + ` (backtick) | Dropdown terminal (slides from the top; toggle to hide) |
| Super + Space or Super + A | App launcher — type an app name, pick a **▶ Start** work layout, or **✦ Custom layout…** (e.g. "chrome and 2 terminals") to open several windows tiled |
| Super + B / E | Your default browser / Files |
| Super + V | Clipboard history (search and paste, like Win + V) |
| Super + Ctrl + V | VS Code |
| Super + Z | AI Chat (conversations, files, web sources) |
| Super + C / X | Claude Code / Codex |
| Super + R / Super + Ctrl + R | **Remote devices** panel / connect to a device (Pi, board, server; see [REMOTE.md](REMOTE.md)) |
| Super + U / Super + Shift + U | Serial console / **who is on my network** (every IP, vendor, open ports) |
| Super + I | **Settings** (Ubuntu's Settings app: Wi-Fi, Bluetooth, sound, mouse, displays…) |
| Super + Shift + I | **Mouse & touchpad speed** quick menu |
| Super + Q or Alt + F4 | Close window |
| Super + M | Maximize (Super + Shift + M = true fullscreen) |
| Super + F | Float/tile the window (Hyprland only) |
| Super + 1…9 / Super + Shift + 1…9 | Go to workspace / move window there |
| Super + Arrows / Super + Shift + Arrows | Focus / move window |
| Super + Alt + Arrows | Resize the window |
| Super + Tab / Alt + Tab | Last workspace / cycle windows |
| Super + N | Notification center with quick toggles (Super + Shift + N = do not disturb) |
| Super + L | Lock the screen. While locked, the **number pad always types digits** (even with Num Lock off), so a numeric PIN works. Your normal keypad returns after unlocking |
| Super + Shift + E | Power menu |
| Ctrl + Shift + Esc | Task manager (btop) |
| Super + Shift + P | Power mode: balanced → performance → power saver (replaces Fn+P, which Linux can't see) |

### Screenshots
All screenshots go to **~/Pictures/Screenshots** (the same folder as Ubuntu) and are copied to the clipboard.
| Keys | Action |
|---|---|
| Print | Take a full-screen screenshot immediately |
| Super + Print | Menu: area, window, full screen, annotate, or a 5-second timer |
| Super + Shift + S or Shift + Print | Area |
| Alt + Print | Active window |
| Super + Shift + A | Area, then annotate it (arrows, text, blur) in Swappy |

### Screen recording
**Ctrl + Shift + Alt + R** (same as Ubuntu) opens the menu: area, window, full screen, full screen with your microphone,
or an area as a GIF. While recording, a red **● 0:42** timer shows in the top bar: click it, or press the keys again, to
stop. Videos go to **~/Videos/Recordings** and the file is copied, ready to paste into a chat. The notification offers
Open, Show in folder and **Make a GIF**. Also in the screenshot menu (Super + Print → Record screen…).
Plugged in it encodes on the NVIDIA GPU; on battery on the CPU, which uses less power than waking the GPU.

The notification that follows each screenshot has **Open**, **Annotate** and **Show in folder** buttons.

### Clipboard
| Keys | Action |
|---|---|
| Super + V | Clipboard history — search, preview, and paste into the window you were in (like Win + V). Images show thumbnails |

You can also open it from the control center (**Clipboard**). Clear the whole history from the trash icon in that panel.

### File actions (Tangerine-style)
Select file(s) in Files and press **Ctrl+Shift+X** (or right-click → **Scripts → Convert & more…**; or Super+Space → "Convert files…") for a visual grid of what you can do with the
selection: convert images (PNG/JPG/WebP/AVIF), resize or compress them, combine to PDF; convert or compress
video, extract audio, make a GIF; convert audio; documents → PDF/Word; compress/merge PDFs or export pages;
extract archives; zip; copy path. Originals are always kept and output lands beside the source.

### Extras
- **Background:** Hyprland uses plain black. Super + W opens a picker where you can choose an image, or "Plain black" to go back.
- **Super + F11** turns the night light on or off. It stays off until you turn it on, and stays warm until you turn it off. You can also use the bar or control center toggle.
- **Super + Shift + C** opens a colour picker that copies the colour's hex code.
- **Super + F12** turns Pad control (laptop mouse + keyboard on the tablet) on or off; **Super + Shift + F12** uses the Pad as a second screen.
- **Super + F10** switches the screen between 165 Hz and 60 Hz.
- **Super + S** shows or hides the scratchpad. **Super + Ctrl + Shift + S** sends a window to it.
  In Ubuntu, Super + S opens Quick Settings instead.
- **Super + Shift + R** reloads the Hyprland config.

## 3. The top bar (from left to right)
The bar stays quiet: things that only matter sometimes appear only while they're active.
- **Left:** the Apps button (right-click for Settings), numbered workspaces (blue = the one you're on; scroll over them to switch), then the current window's title.
- **Centre:** the date and time (click for a calendar panel). Then the song that's playing (click to pause, scroll to skip).
- **Only while active:** a red **dictation** badge while you're dictating, a **Caps Lock** badge, and running **agents**. Num Lock is normally on, so it only shows in the tooltip.
- **Always visible status:** **keep awake** (coffee cup — stops auto-lock and sleep), **power mode** (click or Super + Shift + P), and live **CPU** and **temperature** (click for the system monitor).
- **Tray**, then the **AI** icon (blue while the model is loaded; click to ask, right-click to free the GPU).
- **Wi-Fi:** click for the live **Wi-Fi panel** (Super + Shift + W) — pick a network right there, it updates as networks come and go. **Bluetooth** appears only while a device is connected; click it for the **Bluetooth panel**.
- **Volume:** scroll to change, click for sound settings, right-click to mute. **Battery:** click for power settings. Brightness is in the control center and on the keyboard keys.
- The **bell** opens the control center (Super + N; right-click for do not disturb). Everything else lives there.

### Work profiles (Super + Ctrl + P, or Profile in the control center)
One switch for how the laptop behaves right now. It sticks until you pick another one, even when you plug in or unplug.
| Profile | Does |
|---|---|
| **AI work** | Performance power, full refresh rate, the local model loaded and kept warm (instant answers) |
| **Battery** | Power saver, 60 Hz, the local model unloaded (frees about 6 GB) |
| **Presenting** | Do Not Disturb, and no dimming, locking or sleeping |
| **Automatic** | The default: power follows the charger |
Going back to Automatic only undoes what the profile changed (a Do Not Disturb you turned on yourself stays on).
Terminal: `profile ai | battery | present | auto`.

### Battery health (click the battery in the bar)
How the battery is aging: health (what it holds now vs when new), charge cycles, a chart of health over time (one reading
a day) with how long until it counts as worn (80 %), what it's doing right now (draw, time left) and how to make it last.
Right-click the battery for power settings. You get a warning if it ever drops below 80 %. Terminal: `battery-health`.

### Projects (Super + Ctrl + G, or Projects in the control center)
Every repo in ~/Projects (and this setup) in one list, the ones that need something first: uncommitted changes, commits to
push or pull, failing CI and open pull requests (from GitHub, refreshed every 10 minutes). Click one to open VS Code and a
terminal in that folder on an empty workspace. Terminal: `projects` (add `--gh` for CI and PRs).

### Network trust (Super + Ctrl + W)
Mark the Wi-Fi you're on as Home, Work or Public. Public hides the laptop (new random MAC, no announcing itself, encrypted
DNS) and blocks everything coming in. Open Wi-Fi counts as Public until you say otherwise. Details: [NETWORK_TRUST.md](NETWORK_TRUST.md).

### Agent tasks (Super + Ctrl + A)
Hand a coding task to Claude or Codex and keep working: pick a project, say what to do, Start. The agent works on its own
branch in a separate folder (your checkout isn't touched) and you get a notification when it's done. Then see the changes, ask
the other agent for a second opinion, and Merge or Discard. Details: [TASKS.md](TASKS.md).

### Services (Super + Ctrl + S)
What's running for development: every port your programs listen on (the program, its folder, and whether it's local only or
open to the network), and your Docker containers grouped by compose project. Open a dev server in the browser, stop it, start
or stop a whole compose project, or follow a container's logs. It won't stop the setup's own pieces (agents, the local model,
the phone link). Terminal: `services` · `services who 3000` · `services stop-port 3000` · `services compose stop NAME`.

### External monitors (remembered per set of displays)
Plug in a monitor and it goes to the right of the laptop. To keep a different arrangement, arrange it once with
`nwg-displays` (drag the screens, Apply), then run `monitors save`. Next time that same set of displays is connected (on any port or
cable) the layout comes back by itself; each set (laptop alone, laptop + office monitor, laptop + TV…) has its own. Unplug and
the windows move back to the laptop. Terminal: `monitors` (what's connected) · `monitors save | apply | forget`.

### What needs you (Super + Y or the inbox icon)
One list of what's waiting: agents that need an answer or finished, messages from people, a meeting soon, warnings. Every
notification is sorted (needs you / people / system / low); it stays on this laptop.
- **While you were busy:** when Do Not Disturb ends, one notification sums up what arrived.
- **While you were away:** unlock after 10 minutes or more (including after sleep) and you get the same summary, with an
  **Open inbox** button. Shorter breaks stay quiet.

### Control center (Super + N or the bell)
- **Toggles** (blue = on): Wi-Fi, Bluetooth, Night light, Pad control.
- **One-tap actions:** Screenshot, Clipboard, AI Chat, Voice question, Find files, Dictate, Shortcuts, Power mode, Settings, Power.
- Volume and brightness sliders, do not disturb, and your notifications.

### Power menu (Super + Shift + E or the power icon)
Lock (L), Log out (E), Sleep (S), Restart (R) and Shut down (P). Press the letter or click.
Hibernate isn't offered because the 4 GB swap file is too small for 16 GB of RAM.

## 4. What's shared between Ubuntu (GNOME) and Hyprland
| Thing | How it's shared |
|---|---|
| Mouse/touchpad speed, natural scroll, tap-to-click, keyboard repeat, cursor theme, Num Lock | Change them in **Settings (Super + I)** and Hyprland applies them instantly |
| Wallpaper | Ubuntu keeps its own wallpaper and Hyprland stays black. Choosing an image with Super + W sets it for both |
| Dark mode, GTK theme, fonts, icons | Same settings store, so apps look the same in both |
| Wi-Fi, Bluetooth, sound, displays, printers | Same system services. Manage them in Settings from either desktop |
| Saved passwords (browser, Wi-Fi, SSH) | GNOME Keyring also runs in Hyprland |
| Terminal, prompt, `helpme` | Same Ptyxis terminal and zsh setup |
| Screenshots | Same ~/Pictures/Screenshots folder |
| Shortcuts | The same keys, set up by `scripts/gnome-shared-keys.sh` |
| Default apps (browser etc.) | Settings > Default Apps applies to both |

## 4a. Android tablet: control it with the laptop's mouse and keyboard (Hyprland)
Like Mouse Without Borders: the Pad keeps its own Android screen, and the laptop's touchpad/mouse and keyboard
work on it. Nothing is mirrored or streamed, so it's light on battery.

One-time setup: enable **USB debugging** on the Pad (steps 2–3 below). No app is needed on the Pad.

1. Plug the Pad in (or pair it with Android **Wireless debugging**) and accept the "Allow USB debugging" prompt.
2. Press **Super + F12**, or turn on **Pad control** in the control center (Super + N), or click the tablet icon in the bar.
3. Push the pointer into the laptop's **right edge**: it continues on the Pad as a mouse pointer, and typing goes to the Pad.
4. Press **Super** on its own to come back to the laptop. Super + F12 again turns it off.

- Laptop shortcuts (Super + …) keep working while you're on the Pad.
- If the pointer doesn't jump, click once at the right edge (that also hands the mouse over).
- Log: `$XDG_RUNTIME_DIR/tablet-control.log`. Unplugging the Pad turns control off with a notification.

## 4a-ii. Android tablet as a second screen (Hyprland)
One-time setup:
1. On the Pad, install **AVNC** from the Play Store or F-Droid.
2. Enable Developer options: Settings > About tablet, then tap "MIUI/HyperOS version" 7 times.
3. In Developer options, turn on **USB debugging**.

Each time you want to use it:
1. Plug the Pad in with a USB cable and accept the "Allow USB debugging" prompt the first time.
2. Press **Super + Shift + F12** (or right-click the tablet icon in the bar).
3. In AVNC, connect to `127.0.0.1`, port `5900`.

The Pad becomes a screen to the right of the laptop. Move windows onto it with **Super + Shift + Right**,
and press Super + Shift + F12 again to stop. Pad control and the second screen are one-at-a-time.
- Over Wi-Fi without a cable: connect both devices to Tailscale, run
  `~/.config/hypr/scripts/tablet-display.sh start tailscale`, then connect AVNC to the laptop's Tailscale IP.
  Your normal Wi-Fi network is never exposed.
- Resolution: the default is 1800x1125 at 60 Hz. To change it, set `TABLET_RES=2400x1500` before starting.
- This works in Hyprland only. In Ubuntu (GNOME), the tablet can only mirror the screen, not extend it.

## 4b. Automatic behaviour
- The screen dims after 2.5 minutes and locks after 5. It turns off after 5.5 minutes and the laptop sleeps after 20.
  Fullscreen video, or the coffee-cup button, pauses this.
- The desktop runs on the Intel GPU to save battery. To run an app on the RTX 5050, prefix it with `nvrun`,
  for example `nvrun blender` or `nvrun steam`.

## 4c. AI features (details: docs/AI_GUIDE.md)
| Keys | Action |
|---|---|
| Super + Shift + Space | AI on the selected text: explain, fix, rewrite, translate, reply… |
| Super + Z | **AI Chat** — a full chat app: conversations, file attachments, and current web answers with sources |
| Super + Shift + T / Super + Ctrl + T | Copy text from a screen area / ask AI about it |
| Super + D | Dictation on/off (voice typing) |
| Super + Shift + D | Talk to the assistant (it answers out loud); Esc interrupts |
| Super + Shift + F | Search your files by meaning |

In the terminal: `?? what you want` suggests a command, and `why` explains the last error.

## 5. Customising
- The configs live in `~/KadaOS/config/` (the source) and are copied into `~/.config/`.
- The main file is `~/.config/hypr/hyprland.conf`, and **Super + Shift + R** reloads it.
- To add a shortcut, use `bindd = SUPER, K, My description, exec, some-command`. Because of the description,
  it appears in the Super + / menu automatically.
- To check a config for errors, run `Hyprland --verify-config`.
- To re-apply everything from the repo, run `bash ~/KadaOS/scripts/phase8b-hyprland-polish.sh`.
  Your old configs are backed up to `~/.config/setup-backups/`.
- The KadaOS mark (sources in `config/brand/`) is on the bar's apps button and beside the Super + Space search box.
  The lock screen is a big clock over the KadaOS backdrop (the mark drawn as glass, its cursor glowing). For the
  matching boot and login screens, run `! bash scripts/phase17-brand.sh` (`… undo` restores Ubuntu's, including the
  theme that was selected before). After changing the brand, `python3 config/brand/render.py` remakes the images.

## 5b. Self-test
Run `bash ~/KadaOS/scripts/desktop-check.sh` inside Hyprland. It checks the config, the background services, every shortcut and the scripts, and prints PASS or FAIL for each.

## 6. If something goes wrong
| Problem | Fix |
|---|---|
| Bar disappeared or looks stuck | Run `~/.config/hypr/scripts/bar-restart.sh` |
| Keys stop working / weird state | Reload with Super + Shift + R |
| Broken after a config edit | Run `Hyprland --verify-config` and read the error line |
| Want GNOME back | Log out with Super + Shift + E, then pick "Ubuntu" on the login screen with the gear icon |
| Password prompts not appearing | `systemctl --user start hyprpolkitagent` |
| Bluetooth says "no adapter" / "plug in a dongle", or it's off | Run `rfkill unblock bluetooth && bluetoothctl power on`. Use Blueman (click the bar icon), not Ubuntu's Bluetooth page, in Hyprland |
| Two mouse cursors (one frozen) | Cleared at every login by `cursor-reset.sh`. If it returns, run `~/.config/hypr/scripts/cursor-reset.sh 0` |
| Mouse too slow or fast | Super + Shift + I, or Settings > Mouse & Touchpad |
| Undo the Ubuntu shortcut changes | `dconf load /org/gnome/desktop/wm/keybindings/ < ~/.config/setup-backups/gnome-_org_gnome_desktop_wm_keybindings_*.ini` |
