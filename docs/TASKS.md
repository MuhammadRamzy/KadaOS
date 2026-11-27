# Agent tasks (`tasks`, Super + Ctrl + A)

Give a coding task to an agent and carry on with your own work. Each task gets its own git **worktree** (a second checkout
in `~/.local/share/myos/worktrees/`) on a new branch `agent/<agent>-<what>-<id>`, so the agent never touches the folder you're
working in.

## Flow
1. **Queue and start:** in the panel pick a project, the agent and what to do, then Start. Terminal:
   `tasks add webshop "Add a dark mode toggle" --agent claude --start`
2. **It runs** through [`job`](JOBS.md): memory-capped, stdin closed (agents can't hang waiting for input), notification when
   it ends. Watch it: the terminal button, or `tasks log ID -f`.
3. **Review:** `tasks diff ID` shows the changes; `tasks review ID` asks the *other* agent for a second opinion
   (`agent-review`). Treat review findings as input, not orders.
4. **Merge or discard:** merge only goes into the branch the task started from, and only with a clean working tree (it tells
   you what to do otherwise; a conflict is aborted and left for you). Discard deletes the worktree and branch.

## What the agents may do
- Nothing starts by itself: a task runs only when you press Start (or pass `--start`).
- **Claude** runs `claude -p` with `--permission-mode auto` (the safety classifier decides each action); **Codex** runs
  `codex exec -s workspace-write` (it can write only inside the worktree). Antigravity isn't offered: headless it can't use tools.
- They're told to run the tests, commit on their branch and never push. Anything left uncommitted is committed for them so
  the diff is complete. A run that changes nothing is marked failed.

## Commands
`tasks ls` · `tasks start ID` (also retries a failed one) · `tasks log ID [-f]` · `tasks diff ID` · `tasks review ID [--by codex|claude]`
· `tasks merge ID` · `tasks discard ID`. IDs can be shortened to their last digits. State: `~/.local/state/myos/tasks/`.
