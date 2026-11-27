# Per-project environments

Each project carries its own environment: `cd` into the folder and its tools, virtualenv, `.env` values and (for robotics)
ROS are loaded; `cd` out and they're gone. Nothing global changes.

## Start a project
```sh
new-project shop --lang node          # python | node | go | rust | none
new-project rover --lang python --ros # + ROS 2 Lyrical, and a ROS Jazzy distrobox recipe
new-project notes --open              # then VS Code + a terminal there
```
It creates `~/Projects/NAME` (or `--dir`) with git, `.gitignore` (`.env` is never committed), a README, `AGENTS.md` for the
coding agents (Claude reads it via `CLAUDE.md`, Antigravity via `GEMINI.md`), `docs/HANDOFF.md`, `docs/decisions/`,
`.envrc` and `mise.toml`. It stops if the folder already exists. The new repo shows up in Projects (Super + Ctrl + G).

## How it works
- **direnv** (installed) runs `.envrc` when you enter the folder. If you edit `.envrc`, approve it once with `direnv allow`.
- **Python:** a `.venv` made with `uv` on first entry, activated automatically.
- **Node:** `node_modules/.bin` is on PATH (run `vite`, `eslint`… directly).
- **mise** pins the language version per project (`mise.toml`). It isn't installed yet; until it is, the system's own
  toolchain is used. Install it (user-level, no password, official installer): `curl https://mise.run | sh`
  then open a new terminal. After that, `mise install` inside a project fetches its versions.
- **ROS (`--ros`):** `.envrc` sources ROS 2 Lyrical and your workspace's `install/setup.bash` if built. For packages that
  aren't built for this Ubuntu yet, `distrobox assemble create` makes a ROS Jazzy container (`distrobox enter NAME-ros`)
  that shares your home folder.
