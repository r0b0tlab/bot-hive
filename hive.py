#!/usr/bin/env python3
"""hive.py — Bot Hive board CLI. Stdlib only. Enforces PROTOCOL.md.

Every state transition in PROTOCOL.md §3 is checked here; invalid
transitions exit non-zero. This script is the protocol's teeth.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("BOT_HIVE", Path(__file__).resolve().parent))
BOARD = REPO / "board"
LOCKS = BOARD / ".locks"
DOCS = REPO / "docs"
LOGS = REPO / "logs"

STATUSES = {
    "draft": ["queued"],
    "queued": ["claimed", "blocked"],
    "claimed": ["running", "done", "blocked", "queued"],
    "running": ["done", "blocked", "queued"],
    "done": ["verified", "rejected"],
    "verified": ["closed"],
    "rejected": ["queued", "failed"],
    "blocked": ["queued"],
    "failed": [],
    "closed": [],
}

LOCK_TTL_S = 30 * 60


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------- rolling project log (§10) ----------

def log_line(plan: str, entry: str):
    """Append one line to logs/<plan>.md, creating the file if needed."""
    LOGS.mkdir(exist_ok=True)
    plan = plan or "unassigned"
    path = LOGS / f"{plan}.md"
    if not path.exists():
        path.write_text(f"# {plan} — Bot Hive rolling project log\n\n")
    ts = now_iso()
    with open(path, "a") as f:
        f.write(f"- {ts} — {entry}\n")
    return path


def auto_log(meta: dict, event: str):
    """Automatic log entry for a card event (transition, check-in, etc.)."""
    log_line(meta.get("plan") or "",
             f"{meta.get('id')} [{meta.get('lane')}] {event}")


def fail(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def require_board(cmd: str):
    """Hard-fail when the repo or board is missing instead of silently
    operating on an empty one (e.g. a phantom-HOME session)."""
    if not REPO.is_dir():
        fail(f"{cmd}: hive repo not found: {REPO} — set BOT_HIVE to the repo "
             f"or run from inside it")
    if not BOARD.is_dir():
        fail(f"{cmd}: hive board not found: {BOARD} — set BOT_HIVE to the repo "
             f"or run from inside it")


# Commands that operate on the board (guarded by require_board).
BOARD_CMDS = {"new", "plan", "list", "claim", "start", "done", "verify",
              "close", "block", "release", "checkin", "log", "status", "show"}


# ---------- frontmatter (tiny YAML subset: scalars + lists) ----------

def parse_card(path: Path) -> dict:
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        print(f"{path.name}: missing frontmatter", file=sys.stderr)
        sys.exit(1)
    raw = m.group(1)
    meta = {}
    key = None
    for line in raw.splitlines():
        if re.match(r"^\s*- ", line) and key:
            meta[key].append(line.strip()[2:].strip("'\" "))
            continue
        mm = re.match(r"^(\w+):\s*(.*)$", line)
        if not mm:
            continue
        key, val = mm.group(1), mm.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
        elif val == "" or val.startswith("#"):
            meta[key] = [] if val.startswith("#") else ""
        elif val.lower() in ("true", "false"):
            meta[key] = val.lower() == "true"
        else:
            meta[key] = val.strip("'\"")
    meta["_path"] = path
    return meta


def render_fm(meta: dict) -> str:
    keys = ["id", "title", "lane", "status", "owner", "plan", "deps",
            "priority", "attempts", "created"]
    out = ["---"]
    for k in keys:
        v = meta.get(k, "")
        if k == "deps" and isinstance(v, list):
            out.append(f"deps: [{', '.join(v)}]")
        elif k == "deps" and v:
            out.append(f"deps: [{v}]")
        else:
            out.append(f"{k}: {v}")
    out.append("---")
    return "\n".join(out)


def write_card(meta: dict):
    path = meta["_path"]
    body = path.read_text()
    body = re.sub(r"^---\n.*?\n---\n", render_fm(meta) + "\n", body, flags=re.DOTALL)
    path.write_text(body)


def load_card(card_id: str) -> dict:
    path = BOARD / f"{card_id}.md"
    if not path.exists():
        fail(f"{card_id}: no such card")
    return parse_card(path)


def assert_lane(meta: dict, lane: str | None):
    if lane and meta.get("lane") != lane:
        fail(f"{meta['id']}: lane is {meta['lane']}, not {lane}")


def transition(meta: dict, target: str):
    src = meta.get("status", "draft")
    if target not in STATUSES.get(src, []):
        fail(f"{meta['id']}: illegal {src} -> {target} "
             f"(allowed: {STATUSES.get(src, []) or 'none'})")
    meta["status"] = target
    write_card(meta)
    auto_log(meta, f"status {src} -> {target}")


# ---------- commands ----------

def cmd_new(args):
    meta = {
        "id": "", "title": args.title, "lane": args.lane,
        "status": "draft", "owner": "", "plan": args.plan or "",
        "deps": args.deps or [], "priority": args.priority,
        "attempts": 0, "created": now_iso(),
    }
    # allocate id
    existing = sorted(BOARD.glob("T-*.md"))
    n = 1
    for p in existing:
        m = re.match(r"T-(\d+)", p.name)
        if m:
            n = max(n, int(m.group(1)) + 1)
    card_id = f"T-{n:04d}"
    meta["id"] = card_id
    path = BOARD / f"{card_id}.md"
    body = f"""{render_fm(meta)}

## Objective
{args.objective}

## Spec
Do:
- 

Do not:
- 

## Acceptance criteria
- [ ] 

## Artifact contract
Deliverables (paths) + evidence (command output, test results, hashes):

## Result
(filled at `hive done`)
Summary: 
Artifacts: 
Evidence: 
Caveats: 
"""
    path.write_text(body)
    print(f"{card_id} created (lane={args.lane}, status=draft) "
          f"— queue with: hive plan {args.plan or '<plan-id>'}")
    return 0


def cmd_plan(args):
    plan = args.plan
    queued = 0
    for path in sorted(BOARD.glob("T-*.md")):
        meta = parse_card(path)
        if meta.get("plan") == plan and meta.get("status") == "draft":
            transition(meta, "queued")
            queued += 1
    print(f"plan {plan}: {queued} card(s) queued")
    return 0


def cmd_claim(args):
    meta = load_card(args.card)
    assert_lane(meta, args.lane)
    transition(meta, "claimed")
    meta["owner"] = args.lane or "?"
    write_card(meta)
    (LOCKS / args.card).mkdir(exist_ok=True)
    print(f"{args.card} claimed by {meta['owner']}")
    return 0


def cmd_start(args):
    meta = load_card(args.card)
    transition(meta, "running")
    print(f"{args.card} running")
    return 0


def cmd_done(args):
    meta = load_card(args.card)
    if meta.get("status") not in ("claimed", "running"):
        fail(f"{args.card}: must be claimed/running to mark done")
    path = meta["_path"]
    text = path.read_text()
    new = text
    def rep(section, value):
        nonlocal new
        new = re.sub(
            rf"(\n## {section}\n[^#]*(?=## |\Z))",
            lambda m: f"\n## {section}\n{value}\n",
            new, flags=re.DOTALL, count=1,
        )
    rep("Result",
        f"(filled at `hive done`)\nSummary: {args.summary}\n"
        f"Artifacts: {args.artifacts or ''}\nEvidence: {args.evidence or 'see artifacts'}\n"
        f"Caveats: {args.caveats or 'none'}")
    path.write_text(new)
    meta["status"] = "done"
    meta["_path"] = path
    write_card(meta)
    print(f"{args.card} done — ready for audit")
    return 0


def cmd_verify(args):
    meta = load_card(args.card)
    if args.lane and args.lane != "audit":
        fail("verify is audit-only (pass --lane audit if invoked directly)")
    if meta.get("status") != "done":
        fail(f"{args.card}: only done cards can be verified")
    if args.verdict not in ("verified", "rejected"):
        fail("verdict must be verified|rejected")
    if args.verdict == "rejected" and not args.notes:
        fail("rejected requires --notes naming the unmet criteria")
    if args.verdict == "rejected":
        meta["attempts"] = int(meta.get("attempts", 0)) + 1
        if meta["attempts"] >= 3:
            transition(meta, "failed")
            log_failure(meta, args.notes)
            print(f"{args.card} FAILED after {meta['attempts']} rounds — escalate to user")
            return 0
        transition(meta, "rejected")
        meta["status"] = "queued"
        write_card(meta)
        log_failure(meta, args.notes)
        print(f"{args.card} rejected (round {meta['attempts']}/2) — back to queued")
    else:
        transition(meta, "verified")
        print(f"{args.card} VERIFIED — atlas may close it")
    return 0


def remove_lock(card: str) -> bool:
    """Delete a card's lock dir; shared by close and release."""
    lock = LOCKS / card
    if lock.exists():
        import shutil
        shutil.rmtree(lock)
        return True
    return False


def cmd_close(args):
    meta = load_card(args.card)
    transition(meta, "closed")
    if remove_lock(args.card):
        print(f"{args.card} closed (lock removed)")
    else:
        print(f"{args.card} closed")
    return 0


def cmd_block(args):
    meta = load_card(args.card)
    transition(meta, "blocked")
    print(f"{args.card} blocked: {args.reason}")
    return 0


def cmd_release(args):
    if remove_lock(args.card):
        print(f"{args.card} lock released")
    else:
        print(f"{args.card}: no lock")
    return 0


def cmd_checkin(args):
    meta = load_card(args.card)
    log_line(meta.get("plan") or "",
             f"{meta['id']} [{meta['lane']}] check-in: {args.note}")
    print(f"{args.card} check-in logged: {args.note}")
    return 0


def cmd_log(args):
    plan = args.plan or "unassigned"
    path = LOGS / f"{plan}.md"
    if args.entry:
        log_line(plan, args.entry)
        print(f"appended to logs/{plan}.md")
        return 0
    if not path.exists():
        print(f"no log yet for {plan}")
        return 0
    print(path.read_text())
    return 0


def cmd_status(args):
    if args.card:
        meta = load_card(args.card)
        print(f"{meta['id']} [{meta['status']}] lane={meta['lane']} "
              f"owner={meta.get('owner') or '-'} attempts={meta.get('attempts', 0)} "
              f"plan={meta.get('plan') or '-'}")
        print(f"  deps: {meta.get('deps') or []}")
        return 0
    stale = []
    for lock in sorted(LOCKS.glob("T-*")):
        age = (datetime.now().timestamp() - lock.stat().st_mtime)
        if age > LOCK_TTL_S:
            stale.append(f"{lock.name} (stale {int(age // 60)}m)")
    for path in sorted(BOARD.glob("T-*.md")):
        meta = parse_card(path)
        print(f"{meta['id']} [{meta['status']:>8}] lane={meta['lane']:<6} "
              f"plan={meta.get('plan') or '-':<6} {meta.get('title', '')[:50]}")
    if stale:
        print(f"\nstale locks: {', '.join(stale)}")
    return 0


def cmd_list(args):
    for path in sorted(BOARD.glob("T-*.md")):
        meta = parse_card(path)
        if args.lane and meta.get("lane") != args.lane:
            continue
        if args.status and meta.get("status") != args.status:
            continue
        print(f"{meta['id']} [{meta['status']}] {meta.get('title', '')[:60]}")
    return 0


def log_failure(meta: dict, notes: str):
    DOCS.mkdir(exist_ok=True)
    entry = (f"\n## {meta['id']} ({now_iso()})\n"
             f"Lane: {meta.get('lane')} | Rework rounds: {meta.get('attempts', 0)}\n"
             f"Verdict notes: {notes}\n"
             f"Root cause: \nFix applied: \n")
    with open(DOCS / "failures.md", "a") as f:
        f.write(entry)


def cmd_dashboard(args):
    """Start the activity dashboard (dashboard/server.py) in the foreground.

    Uses os.execv to replace this process with the server, so signals
    (Ctrl-C) go straight to the HTTP server and no child is left behind.
    """
    server = Path(__file__).resolve().parent / "dashboard" / "server.py"
    if not server.exists():
        fail(f"dashboard server missing: {server}")
    port = args.port or int(os.environ.get("PORT", "8099"))
    print(f"hive dashboard → http://localhost:{port} (Ctrl-C to stop)")
    os.execv(sys.executable, [sys.executable, str(server), "--port", str(port)])
    return 0  # unreachable


def selftest(args=None):
    """Exercise the state machine against a throwaway REPO copy."""
    import shutil
    import tempfile
    global BOARD, LOCKS, DOCS, LOGS
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(BOARD, tmp / "board") if BOARD.exists() else (tmp / "board").mkdir()
    os.environ["BOT_HIVE"] = str(tmp)
    BOARD = tmp / "board"
    LOCKS = BOARD / ".locks"
    DOCS = tmp / "docs"
    LOGS = tmp / "logs"
    (LOCKS).mkdir(exist_ok=True)
    # build a card and walk the machine
    meta = {"id": "T-9999", "title": "selftest", "lane": "forge",
            "status": "draft", "owner": "", "plan": "P-0000", "deps": [],
            "priority": 2, "attempts": 0, "created": now_iso()}
    path = BOARD / "T-9999.md"
    path.write_text(render_fm(meta) + "\n## Objective\nx\n## Spec\nDo:\nDo not:\n## Acceptance criteria\n- [ ] c\n## Artifact contract\nx\n## Result\n")
    meta["_path"] = path
    seq = [("queued", True), ("claimed", True), ("running", True),
           ("done", True), ("verified", True), ("closed", True),
           ("closed", False), ("done", False)]
    for target, ok in seq:
        try:
            transition(meta, target)
            assert ok, f"illegal {target} accepted"
        except SystemExit:
            assert not ok, f"legal {target} rejected"
    # check-in + rolling log (§9, §10)
    log_line("P-0000", "T-9999 [forge] check-in: smoke")
    log_line("P-0000", "T-9999 [forge] atlas steer: stay on spec")
    log_path = LOGS / "P-0000.md"
    assert log_path.exists(), "rolling log not created"
    text = log_path.read_text()
    assert "check-in: smoke" in text and "steer: stay on spec" in text, \
        "log entries missing"
    print("selftest: PASS (state machine + check-in + rolling log)")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="hive", description="Bot Hive board CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    # (name, handler, [(argname, spec)]) where spec is a dict passed to add_argument
    for name, fn, specs in [
        ("new", cmd_new, [("--lane", dict(required=True)),
                          ("--title", dict(required=True)),
                          ("--objective", dict(default="")),
                          ("--plan", dict(default="")),
                          ("--deps", dict(nargs="+", default=[])),
                          ("--priority", dict(type=int, default=2))]),
        ("plan", cmd_plan, [("--plan", dict(required=True))]),
        ("list", cmd_list, [("--lane", dict()), ("--status", dict())]),
        ("claim", cmd_claim, [("card", dict()), ("--lane", dict(default=""))]),
        ("start", cmd_start, [("card", dict())]),
        ("done", cmd_done, [("card", dict()), ("--summary", dict(default="")),
                            ("--artifacts", dict(default="")),
                            ("--evidence", dict(default="")),
                            ("--caveats", dict(default=""))]),
        ("verify", cmd_verify, [("card", dict()), ("--verdict", dict(required=True)),
                                ("--notes", dict(default="")), ("--lane", dict(default=""))]),
        ("close", cmd_close, [("card", dict())]),
        ("block", cmd_block, [("card", dict()), ("--reason", dict(default=""))]),
        ("release", cmd_release, [("card", dict())]),
        ("checkin", cmd_checkin, [("card", dict()), ("--note", dict(default=""))]),
        ("log", cmd_log, [("--plan", dict(default="")), ("--entry", dict(default=""))]),
        ("status", cmd_status, [("card", dict(nargs="?"))]),
        ("show", cmd_status, [("card", dict(nargs="?"))]),
        ("dashboard", cmd_dashboard, [("--port", dict(type=int, default=0))]),
        ("selftest", selftest, []),
    ]:
        p = sub.add_parser(name)
        for argname, spec in specs:
            p.add_argument(argname, **spec)
    args = ap.parse_args()
    fn = {
        "new": cmd_new, "plan": cmd_plan, "list": cmd_list, "claim": cmd_claim,
        "start": cmd_start, "done": cmd_done, "verify": cmd_verify,
        "close": cmd_close, "block": cmd_block, "release": cmd_release,
        "checkin": cmd_checkin, "log": cmd_log, "status": cmd_status,
        "show": cmd_status, "dashboard": cmd_dashboard,
        "selftest": selftest,
    }[args.cmd]
    if args.cmd in BOARD_CMDS:
        require_board(args.cmd)
    sys.exit(fn(args))


if __name__ == "__main__":
    main()
