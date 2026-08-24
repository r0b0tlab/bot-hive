#!/usr/bin/env python3
"""dashboard/server.py — Bot Hive activity dashboard. Stdlib only.

Serves a single-file UI plus read-only JSON views over board/ and logs/.
Never writes to board/, logs/, or card state. Run:

    python3 dashboard/server.py [--port 8099]     # or env PORT

or via the CLI:  python3 hive.py dashboard [--port 8099]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
os.environ.setdefault("BOT_HIVE", str(HERE.parent))
sys.path.insert(0, str(HERE.parent))
import hive  # noqa: E402  (reuse the board parser + paths; read-only use)

BOARD = hive.BOARD
LOCKS = hive.LOCKS
LOGS = hive.LOGS
LOCK_TTL_S = hive.LOCK_TTL_S

CARD_ID_RE = re.compile(r"^T-\d{4}$")
LOG_LINE_RE = re.compile(r"^- (\S+) — (.*)$")
RESULT_RE = re.compile(r"\n## Result\n(.*?)(?=\n## |\Z)", re.DOTALL)


# ---------- read-only board/log views ----------

def all_cards() -> list[dict]:
    cards = []
    for path in sorted(BOARD.glob("T-*.md")):
        meta = hive.parse_card(path)
        deps = meta.get("deps")
        if isinstance(deps, str):
            deps = [d for d in deps.split(",") if d.strip()] if deps.strip() else []
        cards.append({
            "id": meta.get("id", path.stem),
            "title": meta.get("title", ""),
            "lane": meta.get("lane", ""),
            "status": meta.get("status", "draft"),
            "owner": meta.get("owner", ""),
            "plan": meta.get("plan", ""),
            "deps": deps or [],
            "priority": _int(meta.get("priority"), 2),
            "attempts": _int(meta.get("attempts"), 0),
            "created": meta.get("created", ""),
        })
    return cards


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def stale_locks() -> list[dict]:
    out = []
    if not LOCKS.exists():
        return out
    now = datetime.now().timestamp()
    for lock in sorted(LOCKS.glob("T-*")):
        age = now - lock.stat().st_mtime
        if age > LOCK_TTL_S:
            out.append({"card": lock.name, "age_minutes": int(age // 60)})
    return out


def tmux_sessions() -> set[str]:
    if not shutil.which("tmux"):
        return set()
    try:
        r = subprocess.run(["tmux", "list-sessions", "-F", "#{session_name}"],
                           capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return set()
    if r.returncode != 0:
        return set()
    return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}


def status_payload() -> dict:
    cards = all_cards()
    plans: dict[str, dict] = {}
    lanes: dict[str, dict] = {}
    for c in cards:
        p = plans.setdefault(c["plan"] or "unassigned",
                             {"total": 0, "by_status": {}, "complete": 0})
        p["total"] += 1
        p["by_status"][c["status"]] = p["by_status"].get(c["status"], 0) + 1
        if c["status"] in ("verified", "closed"):
            p["complete"] += 1
        lane = lanes.setdefault(c["lane"] or "unassigned",
                                {"total": 0, "active": 0, "by_status": {}})
        lane["total"] += 1
        lane["by_status"][c["status"]] = lane["by_status"].get(c["status"], 0) + 1
        if c["status"] in ("queued", "claimed", "running", "blocked", "rejected"):
            lane["active"] += 1
    sessions = tmux_sessions()
    running = []
    for c in cards:
        if c["status"] in ("claimed", "running"):
            running.append({**c, "tmux_session": f"hive-{c['id']}",
                            "tmux_live": f"hive-{c['id']}" in sessions})
    return {
        "generated_at": hive.now_iso(),
        "cards": cards,
        "plans": plans,
        "lanes": lanes,
        "stale_locks": stale_locks(),
        "running": running,
    }


def log_payload() -> dict:
    entries = []
    seq = 0
    if LOGS.exists():
        for path in sorted(LOGS.glob("*.md")):
            plan = path.stem
            try:
                text = path.read_text()
            except OSError:
                continue
            for line in text.splitlines():
                m = LOG_LINE_RE.match(line)
                if m:
                    entries.append({"plan": plan, "timestamp": m.group(1),
                                    "text": m.group(2), "seq": seq})
                    seq += 1
    entries.sort(key=lambda e: (e["timestamp"], e["seq"]), reverse=True)
    for e in entries:
        e.pop("seq", None)
    return {"entries": entries, "plans": sorted({e["plan"] for e in entries})}


def card_result_text(card_id: str) -> str:
    try:
        text = (BOARD / f"{card_id}.md").read_text()
    except OSError:
        return ""
    m = RESULT_RE.search(text)
    return m.group(1).strip() if m else ""


def activity_payload(card_id: str) -> tuple[int, dict]:
    # Validate against the board: anything else is rejected before subprocess.
    if not CARD_ID_RE.fullmatch(card_id or ""):
        return 400, {"error": "invalid card id", "card": card_id}
    if not (BOARD / f"{card_id}.md").exists():
        return 404, {"error": "unknown card", "card": card_id}
    session = f"hive-{card_id}"
    body = {"card": card_id, "session": session,
            "result": card_result_text(card_id)}
    if not shutil.which("tmux"):
        return 200, {**body, "state": "tmux unavailable", "tail": ""}
    try:
        r = subprocess.run(["tmux", "capture-pane", "-p", "-t", session],
                           capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError) as e:
        return 200, {**body, "state": "no session", "tail": "",
                     "detail": str(e)}
    if r.returncode != 0:
        return 404, {**body, "state": "no session", "tail": ""}
    lines = r.stdout.splitlines()
    tail = "\n".join(lines[-30:]).rstrip("\n")
    return 200, {**body, "state": "live", "tail": tail}


# ---------- HTTP layer ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "BotHiveDashboard/0.1"

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, indent=2).encode(), "application/json")

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        try:
            if path in ("/", "/index.html"):
                html = (HERE / "index.html").read_bytes()
                self._send(200, html, "text/html; charset=utf-8")
            elif path == "/api/status":
                self._json(200, status_payload())
            elif path == "/api/log":
                self._json(200, log_payload())
            elif path == "/api/activity":
                card = parse_qs(url.query).get("card", [""])[0]
                code, payload = activity_payload(card)
                self._json(code, payload)
            else:
                self._json(404, {"error": "not found", "path": path})
        except BrokenPipeError:
            pass
        except Exception as e:  # never leak a traceback to the socket
            self._json(500, {"error": "internal", "detail": str(e)})

    def log_message(self, format, *args):  # quieter logs: one line per request
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bot Hive activity dashboard")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("PORT", "8099")))
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Bot Hive dashboard → http://{args.host}:{args.port} "
          f"(repo: {hive.REPO}) — Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
