# Work layouts in Super+Space

Open **Super+Space** and select `▶ Start: Coding`, `Web dev`, `Research`, or `Security lab`. To describe a layout, type **chrome and 2 terminals** and press **Ctrl+Enter**. Regular app searches still use the desktop application list. The combined launcher lists layout profiles first; their labels avoid application names so they do not intercept searches such as `chrome` or `code`.

Supported names: chrome/browser, firefox, code/vscode/editor, obsidian/notes, files/nautilus, slack, terminal/ptyxis, btop, seclab. Counts include digits, one through six, and “a couple of”. Maximum six windows. Examples:

```sh
~/.config/hypr/scripts/flow.py --dry-run 'chrome and 2 terminals'
~/.config/hypr/scripts/flow.py 'code and a couple of terminals'
```

A layout opens on an empty workspace. GUI apps come first, then terminals. The first window occupies about 60% on the left; additional windows split the right-hand region vertically. With more than three windows, repeated vertical splits are not equal-height rows. Existing windows are never moved or closed. The default dwindle layout is required. One layout runs at a time; missing apps are detected before switching workspace.

The launcher first parses app names locally. For unsupported phrasing, `fai` may suggest a JSON list of allowed apps; you must confirm the displayed interpretation before it launches. Invalid JSON, unknown apps, an empty list, or more than six windows aborts. AI output never becomes shell code. Plain CLI use only tries AI when `--ai` is supplied.

Research opens Chrome, Files and a terminal so it does not depend on opening a second Obsidian window. Already-running Slack/Obsidian are rejected before switching workspace.

Apps that reuse an existing window (especially Slack or Obsidian) may not create one on the new workspace. After 15 seconds the launcher reports that failure and cancels remaining launches. Windows already opened remain available; it does not close apps to roll back. Changing workspace between launches also cancels the remaining layout. Wofi fallback continues to offer ordinary apps only.

Implementation targets this laptop's Hyprland 0.53.3. The actual three-window geometry was checked live: 60.1% left width and two stacked right windows. The matching [Hyprland source](https://github.com/hyprwm/Hyprland/blob/v0.53.3/src/managers/KeybindManager.cpp) uses the `splitratio` dispatcher; `layoutmsg splitratio` silently does nothing on this version.
