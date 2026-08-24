# AGENTS.md — Bot Hive

Cross-agent guide for any AI coding agent (Claude Code, Codex, Cursor,
Hermes, etc.) working in this repo.

## What this is

Bot Hive is a bot orchestration framework. An orchestrator bot (lane
`atlas`) elicits a user request into a fully detailed plan, decomposes it
into task cards, and assigns each card to a lane bot. Lane bots never
change lanes, and a verification bot (lane `audit`) holds the binding
verdict. The orchestrator never executes work itself.

## Entry points

- `PROTOCOL.md` — the work contract: lane registry, card schema, state
  machine, accept/hand-off rules. Read this FIRST.
- `hive.py` — CLI that enforces the state machine. Stdlib only.
- `souls/*.md` — canonical SOUL.md per lane bot (staged into Hermes
  profiles at `~/.hermes/profiles/<bot>/SOUL.md`).

## Rules for agents working here

1. Card files are the only work-order channel. Never describe work in
   prose and call it assigned.
2. Do not edit a card you did not claim; do not claim a card whose lane
   is not yours.
3. Do not mark `verified` — that verdict belongs to lane `audit` only.
4. `hive done` without a filled Result section is a protocol violation.
5. Run `python3 hive.py selftest` before committing changes to
   `hive.py`; it must exit 0.
6. New lane = new row in PROTOCOL.md §1 + new profile + new
   `souls/<lane>.md`. Do not reuse an existing bot for a new lane.
7. Atlas checks in on claimed/running cards every 60 s (PROTOCOL.md §9)
   and steers via tmux send-keys when a bot is stuck, off task, or
   misreading the plan. Two stuck check-ins = block + escalate.
8. `logs/<plan>.md` is the rolling project log: hive.py writes every
   status change and check-in; atlas writes the narrative. Append-only,
   one file per plan.
9. Group routing (PROTOCOL.md §11): atlas is the group entry point
   (`require_mention: false`); lane bots answer only when @-mentioned
   (`require_mention: true`). `scripts/configure_group_routing.py --check`
   must exit 0 before committing profile/group changes.

## Commands

```
python3 hive.py new --lane forge --title "..." [--deps T-0002 ...] [--priority 2]
python3 hive.py plan --plan P-0001
python3 hive.py list [--lane X] [--status Y]
python3 hive.py show T-0001
python3 hive.py claim T-0001
python3 hive.py start T-0001
python3 hive.py done T-0001 --summary "..." --artifacts p1,p2
python3 hive.py verify T-0001 --verdict verified|rejected --notes "..."
python3 hive.py close T-0001
python3 hive.py block T-0001 --reason "..."
python3 hive.py checkin T-0001 --note "bot is building"
python3 hive.py log --plan P-0001 [--entry "narrative"]   # read / append
python3 hive.py status [T-0001]
python3 hive.py release T-0001        # atlas only
python3 hive.py selftest
```

## Conventions

- Python 3.11+, stdlib only, no third-party deps.
- Board is git-tracked: every accept/hand-off/verdict is a commit.
- Keep souls in sync: change a SOUL.md in `souls/` AND stage it to the
  profile (`~/.hermes/profiles/<bot>/SOUL.md`).
