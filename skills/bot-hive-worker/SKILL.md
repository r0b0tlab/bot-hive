---
name: bot-hive-worker
description: Claim Bot Hive cards, do the spec, fill Result, mark done.
version: 0.1.0
author: am423 (am423), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [bots, lanes, protocol, bot-hive]
---

# Bot Hive — Worker Protocol

Lane bots (scout, forge, quill, audit, media, data) accept one card, do
exactly its Spec, fill the Result, and hand off. Lane identity and
per-lane rules live in the bot's SOUL.md, which wins on conflict with
this file.

## When to Use

- Atlas spawned you with a work order naming a card (T-xxxx).
- You need to claim, execute, or hand off a Bot Hive card.
- Don't use for: orchestrating, verifying, or working another lane's card.

## Group behavior (PROTOCOL.md §11)

- Your profile has `require_mention: true`: in groups you answer only
  when @-mentioned or replying to your own message. You never open
  conversations and never act on unaddressed group chatter — that is
  atlas's job.
- First message always goes to atlas. You are a worker, not an entry
  point.

## Prerequisites

- `~/bot-hive/` repo present (PROTOCOL.md, hive.py, board/, logs/).
- Read `board/<id>.md` and PROTOCOL.md before claiming. The card is the
  complete work order.

## How to Run

- Claim: `terminal(command="python3 ~/bot-hive/hive.py claim T-0001 --lane <your-lane>", timeout=30)`.
- Hand off: `terminal(command="python3 ~/bot-hive/hive.py done T-0001 --summary \"...\" --artifacts p1,p2 --evidence \"...\"", timeout=30)`.
- Block: `terminal(command="python3 ~/bot-hive/hive.py block T-0001 --reason \"...\"", timeout=30)`.

## Quick Reference

```
hive claim <id> --lane <lane>    # accept (your lane only)
hive start <id>                  # mark running
hive done <id> --summary ... --artifacts ...   # hand off (Result required)
hive block <id> --reason ...     # ambiguity or blocker
hive log --plan P-xxxx --entry "..."   # optional 1-3 line note
```

## Procedure

1. Read the card and PROTOCOL.md. Completion: Spec, acceptance criteria,
   and artifact contract understood.
2. Check the card's lane is yours. Not yours → refuse and report.
   Completion: lane matches.
3. Check deps are verified. Unverified dep → stop and report.
   Completion: deps clean.
4. Claim (`hive claim`). Completion: status claimed, owner is you.
5. Execute exactly the Spec. Untestable criterion or ambiguous spec →
   `hive block` and report, never improvise. Completion: acceptance
   criteria met with evidence.
6. Fill the Result: summary, artifact paths, evidence (command output,
   test results, hashes), caveats. Completion: Result section complete.
7. `hive done`. Completion: card status done on the board.
8. If steered: treat atlas's message as the orchestrator directive.
   Course-correct, or block with the reason you cannot.
   Completion: steer acknowledged in behavior or a block with reason.

## Pitfalls

- No Result, no done. Evidence is the hand-off.
- Never call `verify`. That verdict is audit's lane alone.
- A failing test is a finding, not a fix — report it.
- Never claim another lane's card; never re-route.

## Verification

- `hive status <id>` shows done after your hand-off.
- `hive log --plan <plan>` shows your summary.
