# Bot Hive

A bot orchestration framework: an orchestrator that never executes work,
lane-specialized worker bots, and a verification bot whose verdict is
binding. Every task moves through a filesystem board with a strict state
machine enforced by `hive.py`.

## How it works

```
user request
   └─► atlas (orchestrator, lane: atlas)
         1. classify the request (code/research/writing/media/data)
         2. elicit: targeted questions, max 3 rounds
         3. draft full plan: cards, lanes, deps, acceptance criteria
         4. plan gate: NO cards queued until the user approves
         5. assign: spawn lane bots one-shot (hermes -p <bot> chat -q)
         6. verify: audit bot checks work vs. original request + plan
         7. report: per-card evidence, nothing claimed unverified
```

Every bot is a Hermes profile with its own SOUL.md (canonical copies in
`souls/`). Lane registry lives in `PROTOCOL.md` §1.

## Quickstart

```bash
# 1. Board tooling (stdlib only, Python 3.11+)
python3 hive.py selftest          # PASS = protocol enforced

# 2. Atlas — the orchestrator profile
hermes profile create atlas --clone
hermes -p atlas config set model.default deepseek-v4-flash-vision-exp
hermes -p atlas config set model.provider deepseek
hermes -p atlas config set agent.reasoning_effort xhigh
cp souls/atlas.md ~/.hermes/profiles/atlas/SOUL.md

# 3. Lane bots (one profile per lane, SOUL.md staged from souls/)
for bot in scout forge quill audit media data; do
  hermes profile create $bot --clone
  cp souls/$bot.md ~/.hermes/profiles/$bot/SOUL.md
done

# 4. Group routing: first message in a bot group goes to atlas
python3 scripts/configure_group_routing.py --apply
python3 scripts/configure_group_routing.py --check   # expect: PASS

# 5. Ask atlas. It elicits, plans, gates, assigns, and verifies.
hermes -p atlas chat -q "I want a benchmark for my local model"
```

## Card lifecycle

```
draft -> queued -> claimed -> running -> done -> [audit verdict]
                                     -> verified -> closed
                                     -> rejected -> queued (rework, max 2)
```

Atlas checks in on every claimed/running card each 60 s: observes the
bot's session (tmux), records the check-in, and steers when the bot is
stuck, off task, or misreading the plan. Two consecutive stuck
check-ins = block + report to the user.

Every plan has a rolling log (`logs/<plan>.md`): hive.py appends status
changes and check-ins automatically; atlas appends the narrative (plan
gate, steers, escalations, verdicts, final report). Human-readable and
append-only.

Commands: `python3 hive.py <new|plan|list|claim|start|done|verify|close|block|checkin|log|status|selftest>`
Full contract: `PROTOCOL.md`. Cross-agent guide: `AGENTS.md`.

## Adding a lane

1. Add a row to `PROTOCOL.md` §1 (lane, profile, scope).
2. Write `souls/<lane>.md`; stage to `~/.hermes/profiles/<lane>/SOUL.md`.
3. `hermes profile create <lane> --clone`.
4. Add the lane to `scripts/configure_group_routing.py` LANE_BOTS.
5. `python3 scripts/configure_group_routing.py --check` must exit 0.
No other code changes. Any request class without a lane becomes a lane —
the orchestrator never does the work itself.

## Group routing (PROTOCOL.md §11)

In a group chat with several Hive bots, atlas is the default responder:
`atlas.require_mention: false` answers every unaddressed message, so the
first message always lands on the orchestrator. Lane bots keep
`require_mention: true` and act only when @-mentioned or replying to
their own message. `exclusive_bot_mentions: true` keeps an explicit
mention deterministic. Every profile needs its own bot token.

## License

MIT.
