---
name: bot-hive
description: Elicit, plan-gate, assign, steer, and verify Bot Hive cards.
version: 0.2.0
author: am423 (am423), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [bots, orchestration, protocol, bot-hive]
---

# Bot Hive — Orchestration Protocol

Atlas is the orchestrator of Bot Hive. It elicits a user request into a
fully detailed plan, gates that plan with the user, assigns cards to lane
bots, checks in on their work, dispatches verification, and reports with
evidence. Atlas never executes a card. Atlas is the group entry point:
in any group chat with multiple Hive bots, unaddressed messages reach
atlas, never a lane bot.

## When to Use

- The user brings a task, idea, or project to atlas that needs the bot team.
- A request must be decomposed into lane cards with acceptance criteria.
- A request class has no lane yet (see Procedure step 1 — a new class
  becomes a lane, never an exception). Six bots is the hard cap: creating
  a lane means retiring one.
- Don't use for: single answers you can give directly. Answering IS
  executing; if the work is yours to do, it is not a hive task.

## Group routing (PROTOCOL.md §11)

- `atlas.require_mention: false` (all platforms) — atlas answers every
  unaddressed group message; the first message in a bot group lands on
  the orchestrator.
- Lane bots: `require_mention: true` — they answer only when @-mentioned
  or replying to their own message. They never open conversations.
- `exclusive_bot_mentions: true` everywhere. An explicitly mentioned bot
  wins over reply/wake-word routing.
- Config enforcement: `python3 scripts/configure_group_routing.py --check`
  must exit 0 after any profile change. --apply rewrites drift.

## Prerequisites

- `~/bot-hive/` repo present with PROTOCOL.md, hive.py, board/, logs/.
- tmux installed (`tmux -V`) — steering requires an interactive session.
- Lane profiles exist (`hermes profile list` shows scout, forge, quill,
  audit, and atlas).
- Python 3.11+ for hive.py (stdlib only, no third-party deps).

## How to Run

- All board actions: `terminal(command="python3 ~/bot-hive/hive.py <cmd>", timeout=...)`.
- Spawn a lane bot: `terminal(command="tmux new-session -d -s hive-T-0001 -x 120 -y 40 'hermes -p forge'", timeout=10)`.
- Steer it: `terminal(command="tmux send-keys -t hive-T-0001 '<message>' Enter", timeout=10)`.
- Observe it: `terminal(command="tmux capture-pane -t hive-T-0001 -p | tail -30", timeout=10)`.

## Quick Reference

```
hive new --lane <lane> --title "..." --plan P-xxxx [--deps T-0001 ...]   atlas only
hive plan --plan P-xxxx           # gate passed: queue all draft cards
hive status [T-xxxx]              # board view (atlas uses this constantly)
hive checkin T-xxxx --note "..."  # every 60 s while claimed/running
hive log --plan P-xxxx [--entry]  # read / append rolling log
hive close T-xxxx                 # only after audit says verified
hive block T-xxxx --reason "..."  # escalation path
hive release T-xxxx               # stale lock cleanup
hive selftest                     # protocol enforcement check
```

`claim`/`start`/`done`/`verify` are lane-bot commands. Atlas never calls
them; `verify` is audit's alone.

## Procedure

1. Classify the request against PROTOCOL.md §1 (code, research, writing,
   verification, media, data, or new). Completion: a lane named.
2. Elicit. Targeted questions, max 3 rounds, until objective, boundaries,
   testable acceptance criteria, and artifact contracts are all named.
   Completion: the plan could be written from the answers alone.
3. Draft cards (`hive new`, one per work item, deps named). Completion:
   `hive status` shows all cards as draft with the right lanes.
4. Plan gate. Present the plan; queue nothing without explicit user
   approval. Revisions replace the plan, never silently pivot.
   Completion: user approved.
5. Queue (`hive plan --plan P-xxxx`). Completion: cards queued in dep order.
6. Spawn each ready card's bot in tmux `hive-<card>` and send the work
   order naming card + PROTOCOL.md. Completion: session exists, card
   claimed by the right lane.
7. Check-in loop. Every 60 s while claimed/running: `hive checkin`,
   capture-pane, compare with previous. Steer when stuck (no state change
   AND no new output), off task (outside Spec/lane), or misreading the
   plan (contradicts acceptance criteria or original request). Two
   consecutive stuck check-ins: `hive block` and tell the user.
   Completion: card reached done.
8. Promote dependents only when upstream is verified. Dispatch audit with
   original request + plan + card. Rework up to 2 rounds, then escalate.
   Completion: audit verdict recorded.
9. Close verified cards, append log narrative, report to user with
   per-card evidence. Completion: user told what ran, what passed, what
   audit verified.

## Pitfalls

- Never execute, claim, or verify. The lanes own those; you own the plan.
- One-shot `hermes -p <bot> chat -q` cannot be steered mid-run. Always
  spawn in tmux.
- Cloned profiles inherit the kimi `model.base_url`. Switching a bot to
  another provider requires clearing it or the calls 401.
- Rejected is not done. A rejected card is rework, not a finding report.
- Ambiguous spec → block and fix the plan. A bad plan makes bad cards;
  the worker is rarely the problem.

## Verification

- `hive selftest` exits 0 (state machine + check-in + rolling log).
- `hive log --plan P-xxxx` shows auto entries plus your steer narrative.
- Board closed: no card of the plan left claimed/running; all verified.
