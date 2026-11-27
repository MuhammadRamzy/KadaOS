# Disk space (`disk` and the Storage panel)

Open **Storage** in the control center (`myos-panel storage`), or run `disk` in a terminal.

- **Free up N GB**: one click frees caches and build leftovers that come back by themselves when needed (Docker build
  cache, npm / pnpm / uv / pip caches, the security scanner database, Raspberry Pi Imager downloads, thumbnails, old
  logs). It never empties the Trash and never touches Chrome's cache while Chrome is open (those have their own buttons).
- **Each item** has its own **Free** button and says what happens if you free it.
- **Needs your password**: apt's package cache, old snap versions, system logs. The panel copies the exact command.
- **Your files**: big files in Downloads and duplicate files (same content, compared by hash) only ever go to the
  **Trash**, so you can restore them from Files → Trash.

When the disk gets low, the watcher's warning says how much can be freed and has a **Review** button that opens this page.

```sh
disk                          # free space + what can be freed
disk clean docker-build npm   # free those   ·   disk clean --all-safe
disk big · disk dupes         # big files in Downloads · duplicates
disk trash FILE…              # to the Trash
```

## Tidy Downloads (`tidy`, off until you turn it on)
`tidy` shows what it would do: images → Downloads/Images, PDFs and office files → Documents, archives, installers, video,
audio and code into their own folders. Only files older than a day; unfinished downloads, hidden files and folders are left
alone; a name clash becomes "name (2)". `tidy --apply` does it now; `tidy on` once a day (a notification says what moved),
`tidy off` stops. Rules: `~/.config/myos/tidy.json` (`tidy rules`); old installers can go to the Trash after N days
(`trash_installers_after_days`, 0 = never).
