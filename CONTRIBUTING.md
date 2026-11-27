# Contributing

KadaOS began as one person's daily setup. It's shared so you can use it, fork it and make it yours, and improvements
that make it work on more machines or for more people are very welcome.

## What helps most
- **Portability**: it assumed something about the author's hardware or habits and broke on yours. Detection beats assumption.
- **Off switches and undo** for anything that lacks them.
- **Bugs** with steps to reproduce (open an issue with the template).
- **Docs** that made you stop and guess.

New features are fine too, but open an issue first so we can agree it fits the menu.

## Ground rules
1. Every script is **idempotent** and **tolerant**: running it twice changes nothing more; one missing package doesn't
   abort the rest; it logs to `setup.log`; it backs up before replacing a config.
2. No `sudo` inside user-level tools; privileged steps live in `scripts/phase*.sh`, which ask once.
3. Detect hardware, never assume it. Things that only make sense on some machines must skip cleanly elsewhere.
4. Nothing leaves the machine by default. Network features are opt-in and say where data goes.
5. Plain language in anything a person reads: buttons, notifications, docs.
6. Theme colours come from `scripts/theme.py`; don't hard-code them in configs.

## Before you open a pull request
```sh
bash tests/run-all.sh --offline     # syntax, wiring, unit tests and every app off-screen (safe; changes nothing)
shellcheck -S warning kada scripts/*.sh
```
Add or update a test for what you changed (`tests/test_*.py`, standard library `unittest`). Screens are checked off-screen
by `tests/ui_audit.py`; add your page there if you add a panel.

Keep pull requests focused, explain *why* in the description, and note anything you couldn't test.

By contributing you agree your work is released under the [MIT licence](LICENSE). Be kind: see the
[code of conduct](CODE_OF_CONDUCT.md).
