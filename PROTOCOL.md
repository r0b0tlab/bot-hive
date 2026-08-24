# PROTOCOL.md — Bot Hive v0.1 work contract

The single source of truth for how work is accepted, executed, and handed
off. Every bot reads this file before touching a card.

## 1. Lanes

| Lane | Bot (profile) | Scope | v0.1 |
|---|---|---|---|
| atlas | orchestrator | elicit, plan, assign, verify gate, report. Never executes. | yes |
| scout | research | recon, fact gathering, source digging | yes |
| forge | build/code | implement, build, test, artifacts | yes |
| quill | writing | docs, articles, reports | yes |
| audit | verify | acceptance checks; verdict binding | yes |
| media | images/video/audio | creative media requests | registry-ready |
| data | ML/data ops | quantization, KD/QAT, eval runs | registry-ready |

A new lane = one new row here + one profile + one SOUL.md. Nothing else
changes. Never add a lane by reusing an existing bot.

## 2. Card schema

File: `board/<id>.md`. IDs are `T-0001` upward, allocated by `hive.py`.

```yaml
---
id: T-0001
title: <one line>
lane: forge            # scout | forge | quill | audit (the assignee)
status: queued
owner: ''              # profile name, set at claim time
plan: P-0001
deps: []               # card ids that must be VERIFIED before this starts
priority: 2            # 1 (urgent) - 3 (low)
attempts: 0            # rework counter, managed by hive.py
created: 2026-08-24T10:00:00-05:00
---

## Objective
One sentence. Why this card exists.

## Spec
Do:
- ...
Do not:
- ...

## Acceptance criteria
- [ ] testable criterion
- [ ] testable criterion

## Artifact contract
Deliverables (paths) + evidence (command output, test results, hashes).

## Result
(filled by the lane bot at `hive done`)
Summary: ...
Artifacts: ...
Evidence: ...
Caveats: ...
```

## 3. State machine (accept and hand-off)

```
draft -> queued -> claimed -> running -> done -> [audit] -> verified -> closed
                         |         |                  |
                         +- blocked/failed ---------+- rejected
                                                    |
                                        (rework: back to queued,
                                         attempts+1, max 2, then escalate)
```

| Transition | Command | Who | Rule |
|---|---|---|---|
| draft -> queued | `hive plan P-0001` | atlas | plan gate: only after user approval |
| queued -> claimed | `hive claim T-0001` | lane bot | atomic mkdir lock; owner set; heartbeat = re-claim |
| claimed -> running | `hive start T-0001` | lane bot | optional |
| running/claimed -> done | `hive done T-0001` | lane bot | Result section must be filled |
| done -> verified | `hive verify --verdict verified` | audit only | checks acceptance criteria + original request |
| done -> rejected | `hive verify --verdict rejected` | audit only | must name unmet criteria |
| verified -> closed | `hive close T-0001` | atlas | all deps verified |
| any -> blocked | `hive block T-0001` | lane bot | needs input; requeues on unblock |

## 4. Accept rules (lane bot)

1. Claim only cards where `lane` matches your lane. Never claim another
   lane's card; never re-route it yourself — `hive reroute` is atlas-only.
2. Read `deps` before starting. If any dep is not `verified`, do not start;
   report the state to atlas instead.
3. The card body is the complete work order. If the spec is ambiguous or the
   acceptance criteria are untestable, do NOT improvise: `hive block` and
   report the ambiguity to atlas.
4. When done, `hive done` with the Result section filled: exact artifact
   paths, the evidence (command outputs, test results, hashes) that proves
   each acceptance criterion, and any caveats. No Result, no done.

## 5. Hand-off rules (verifier + atlas)

1. `audit` receives the original user request, the plan, and the card.
   Its verdict is binding: `verified` closes nothing by itself — atlas
   `close`s the card after.
2. `rejected` must name the unmet acceptance criteria in the notes. The card
   goes back to `queued` with `attempts+1`. At `attempts >= 3`, the card is
   `failed` and escalated to the user — no silent third try.
3. Atlas promotes downstream cards (deps satisfied) only after upstream is
   `verified`, not merely `done`.
4. Atlas reports to the user only when every card of the plan is `verified`
   or `closed`, with per-card evidence. Unverified = not done.

## 6. Locking and concurrency

- A claim is `mkdir board/.locks/<id>` — atomic on POSIX. The lock dir's
  mtime is the heartbeat; a lock older than 30 min is stale.
- `hive claim` on a claimed card refreshes the heartbeat (owner only).
- `hive status` lists stale locks; `hive release` (atlas only) clears one.
- Single-writer per card. The board is not a chat.

## 7. Failure logging

Every rejected or failed card gets an entry in `docs/failures.md`:

```
## T-0001 (2026-08-24)
Lane: forge | Rework rounds: 2
Verdict notes: <what the verifier said>
Root cause: <one line>
Fix applied: <one line>
```

Failures are also appended to the plan's rolling log (§10) with the
rework round.

## 8. Invocation

Atlas spawns lane bots in interactive tmux sessions so it can watch and
steer them (see §9). Session name = `hive-<card>`.

```
tmux new-session -d -s hive-T-0001 -x 120 -y 40 'hermes -p forge'
sleep 8 && tmux send-keys -t hive-T-0001 'Execute card T-0001. Read
/home/am/bot-hive/board/T-0001.md and PROTOCOL.md. Claim it, do the
work, fill the Result, and mark it done.' Enter
```

Timeouts: 600 s minimum for build cards; build+test cards 900 s.
`tmux kill-session -t hive-T-0001` when the card is done or failed.

## 9. Check-in role (atlas steers the team)

Atlas checks in on every `claimed`/`running` card every 60 seconds from
claim time until the card is `done` or `failed`.

A check-in is:
1. Record it: `python3 hive.py checkin T-0001 --note "<status>"`
2. Observe: `tmux capture-pane -t hive-T-0001 -p | tail -30`
   (or the card Result/Artifact contract if the bot updated it)
3. Compare with the previous check-in.

Steer triggers (any one fires a steer):
- **Stuck:** no state change AND no new output since the last check-in.
- **Off task:** the bot is working on something not in the card's Spec or
  outside its lane (scope drift, unrelated files, wrong deliverable).
- **Misreading the plan:** output contradicts the acceptance criteria or
  the original user request.

Steer action: `tmux send-keys -t hive-T-0001 '<targeted message>' Enter`.
A steer is targeted, not generic: name the card, the artifact, and what is
expected. Examples:
- "Stuck on T-0001 — you've had no output for 2 min. What is blocking?
  If the spec is unclear, hive block and report; do not guess."
- "Off task on T-0001 — the card asks for X only. Stop doing Y."

Escalation: two consecutive stuck check-ins → atlas `hive block` with the
stuck reason and reports to the user. The card must not sit in a stuck
`running` state silently.

## 10. Rolling project log

One human-readable running account per plan: `logs/<plan>.md`, appended
for the life of the project. It is the story of the work, in plain
language, and must be intelligible to a person who never watched the
board.

What appends to it:
- **Automatic (hive.py):** every state transition, every check-in, every
  action with a timestamp and actor.
- **Atlas (narrative):** plan gate (plan approved), assignment decisions,
  every steer with its reason, escalations, verification verdicts, and
  the final report to the user.
- **Lane bots:** a 1-3 line note at `done` (via `hive done`'s summary) and
  any surprise or deviation discovered along the way.

Log commands:
```
python3 hive.py checkin T-0001 --note "<what the bot is doing>"
python3 hive.py log --plan P-0001            # read the log
python3 hive.py log --plan P-0001 --entry "<narrative>"   # append (atlas)
```

Rules: one file per plan; never rewritten, only appended; every check-in
and steer has a timestamp, an actor, and a reason.
