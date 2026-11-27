# Long jobs without a frozen laptop (`job`)

Builds, model training, big conversions: run them with `job` and the desktop stays responsive, even if the job goes wild.

```sh
job -- make -j8                  # runs in the background; you can close the terminal
job --mem 6G -- python train.py  # cap at 6 GB (default: 70 % of RAM)
job --plugged -- ./render.sh     # waits for the charger, then starts
job --fg -- cargo build          # stays in this terminal, same cap
job ls                           # ● running · ✓ done · ✗ failed · ■ stopped
job log ID -f                    # follow the output   ·   job stop ID
```

When a job ends you get a notification (and on the phone when the laptop is locked, see [PHONE.md](PHONE.md)).
A job that runs out of its memory is **stopped and reported**, never left crawling: it has no swap, so it can't drag
the laptop down, and systemd-oomd picks it, not Hyprland or your apps, if memory ever runs short.

How: each job is a transient systemd user service (`job-ID`) with `MemoryMax` and `MemorySwapMax=0`. No sudo.
Output: `~/.local/state/myos/jobs/ID.log`. Remote devices have the same thing: `board job` ([REMOTE.md](REMOTE.md)).
