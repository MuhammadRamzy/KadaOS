# 0014: Ornith 9B as the local model; god-mode assistant with approval

Date: 2026-11-05 · Claude · Status: accepted (user chose it after the comparison)

## Context
The abliterated Qwen3-8B looped on refused calls, announced instead of acting, and invented scan results. The user
asked for a JARVIS-like assistant with full system power, and for a comparison before any switch.

## Decision
- **Model:** `ornith:9b` for everything local (assistant, `fai`, text menu, MCP `local_ai`). In the comparison it
  was the best agent (acts, prefers read-only paths, fewest approvals, best summaries). Its weaknesses are covered:
  a `calculate` tool for exact arithmetic (it answered 505.8 for 17% of 2,340), and translation is removed because
  the user doesn't need it. The abliterated build is deleted; stock `qwen3:8b` is not kept. Results:
  `docs/plans/jarvis-assistant-roadmap.md`.
- **Power with the user as authority:** read-only tools run immediately. Changes go through an inline approval
  card. Simple, non-destructive programs can be "always allowed" (`~/.config/local-ai/allow.json`); compound
  commands and destructive programs never can. Root tasks run via `pkexec` behind the approval card *and* the
  system password prompt; sudo is never typed by the model. Every step and its real output is shown and fed back.

## Consequences
One model on the GPU (about 5.2 GB), no swapping. Arithmetic and approvals are explicit. Revisit if a better ≤9B
agent model appears; rerun the harness first.
