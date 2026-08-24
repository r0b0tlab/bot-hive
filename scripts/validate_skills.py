#!/usr/bin/env python3
"""Validate Bot Hive SKILL.md files against authoring standards.

Checks per SKILL.md: frontmatter starts at byte 0 and parses as key/values;
name and description present; description <= 60 chars, one sentence ending
in a period; non-empty body; skill name matches its directory name (the
loader requires the match). Stdlib only.

Usage: python3 scripts/validate_skills.py
Checks repo skills/ plus the staged copies in every bot profile.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIRS = [REPO / "skills"]
HOME = Path.home()
for bot in ("atlas", "scout", "forge", "quill", "audit"):
    SKILL_DIRS.append(HOME / ".hermes" / "profiles" / bot / "skills")


def parse_fm(text):
    if not text.startswith("---"):
        return None
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^(\w+):\s*(.*)$", line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip().strip('"')
    return fm, m.group(2)


def check(path: Path):
    problems = []
    text = path.read_text()
    parsed = parse_fm(text)
    if parsed is None:
        return [f"{path}: frontmatter invalid (must start with --- at byte 0)"]
    fm, body = parsed
    if not body.strip():
        problems.append(f"{path}: empty body after frontmatter")
    if "name" not in fm:
        problems.append(f"{path}: missing name")
    if "description" not in fm:
        problems.append(f"{path}: missing description")
    else:
        d = fm["description"]
        if len(d) > 60:
            problems.append(f"{path}: description {len(d)} chars (> 60 hardline)")
        if not d.endswith("."):
            problems.append(f"{path}: description must end with a period")
        if ":" in d:
            problems.append(f"{path}: description contains ':' — quotes required")
    name = fm.get("name", "")
    if name and path.parent.name != name:
        problems.append(f"{path}: name '{name}' != directory '{path.parent.name}'")
    return problems


def main():
    bad = False
    for d in SKILL_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.glob("*/SKILL.md")):
            if not p.parent.name.startswith("bot-hive"):
                continue  # only Bot Hive skills are in scope
            for prob in check(p):
                print("FAIL", prob)
                bad = True
    if bad:
        sys.exit(1)
    print("validate_skills: PASS (all Bot Hive SKILL.md compliant)")
    return 0


if __name__ == "__main__":
    main()
