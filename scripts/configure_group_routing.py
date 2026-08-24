#!/usr/bin/env python3
"""configure_group_routing.py — enforce PROTOCOL.md §10.

Set/verify group routing on every Bot Hive profile:

  atlas        require_mention: false, exclusive_bot_mentions: true
  lane bots    require_mention: true,  exclusive_bot_mentions: true

Profiles root: env HERMES_PROFILES_ROOT, else the real user home via
pwd.getpwuid (immune to desktop sessions whose Path.home() is a phantom
profile dir). A missing/unreadable profile config is FATAL — a vacuous
PASS is a bug. exit 0 only when every hive profile was checked and none
drifted.

Stdlib only. Non-destructive by default: run `--check` to see drift,
run with `--apply` to write it.

Usage:
  python3 scripts/configure_group_routing.py --check   # exit 0 = compliant
  python3 scripts/configure_group_routing.py --apply   # write configs
"""
import argparse
import os
import pwd
import sys
from pathlib import Path

REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
PROFILES = Path(os.environ.get("HERMES_PROFILES_ROOT",
                               REAL_HOME / ".hermes" / "profiles"))
ORCHESTRATOR = "atlas"
LANE_BOTS = ["scout", "forge", "quill", "audit", "data"]
ALL_BOTS = [ORCHESTRATOR] + LANE_BOTS

# Hard design limit (PROTOCOL.md §1): atlas + 5 lanes.
MAX_BOTS = 6

# Known platform sections that carry group-routing keys in Hermes config.yaml.
PLATFORM_BASES = [
    "telegram", "discord", "slack", "signal", "mattermost", "matrix",
    "wecom", "bluebubbles", "buzz", "photon",
]
# Keys asserted on every present platform section.
ROUTING_KEYS = ["require_mention", "exclusive_bot_mentions"]


def assert_cap():
    if len(ALL_BOTS) > MAX_BOTS:
        print(f"FATAL: {len(ALL_BOTS)} bots > cap {MAX_BOTS} "
              f"(PROTOCOL.md §1). Retire a lane before adding one.",
              file=sys.stderr)
        sys.exit(1)


def config_path(profile: str) -> Path:
    if profile == "default":
        return REAL_HOME / ".hermes" / "config.yaml"
    return PROFILES / profile / "config.yaml"


def read_config(path: Path) -> dict:
    """Tiny YAML-subset reader: top-level + one-level nested keys."""
    data = {}
    cur = None
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        s = line.strip()
        if indent == 0 and ":" in s:
            k, _, v = s.partition(":")
            k = k.strip()
            data[k] = v.strip()
            data["_" + k] = {}
            cur = k
        elif indent == 2 and ":" in s and cur and cur not in ("_",):
            k, _, v = s.partition(":")
            data["_" + cur][k.strip()] = v.strip()
    return data


def get_key(cfg: dict, key: str):
    """get_key(cfg, 'telegram.require_mention') -> value or None"""
    parts = key.split(".", 1)
    if len(parts) == 1:
        return cfg.get(parts[0])
    section, sub = parts
    return cfg.get("_" + section, {}).get(sub)


def set_key_in_file(path: Path, base: str, key: str, value: str):
    """Set base.key = value, preserving file structure. Stdlib only.

    Rewrites an existing `key:` line inside the section, or inserts one
    at the end of the section when missing (never at end of file).
    """
    lines = path.read_text().splitlines(keepends=True)
    key_line = None
    insert_at = None
    in_section = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and ":" in stripped:
            name = stripped.split(":", 1)[0].strip()
            if in_section:
                insert_at = i  # section ended: insert before next top-level
                break
            in_section = (name == base)
            continue
        if in_section and indent == 2 and stripped.split(":", 1)[0].strip() == key:
            key_line = i
            break
    if key_line is not None:
        lines[key_line] = f"  {key}: {value}\n"
    elif insert_at is not None:
        lines.insert(insert_at, f"  {key}: {value}\n")
    elif in_section:
        lines.append(f"  {key}: {value}\n")
    # else: section not found — caller only invokes this for present sections.
    path.write_text("".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report drift, don't write")
    ap.add_argument("--apply", action="store_true", help="write configs")
    ap.add_argument("--profile", default=None, help="only this profile")
    args = ap.parse_args()

    if not args.check and not args.apply:
        args.check = True  # default = check

    assert_cap()

    profiles = [p for p in ALL_BOTS if not args.profile or p == args.profile]
    changed = []
    checked = 0
    for profile in profiles:
        path = config_path(profile)
        if not path.exists():
            print(f"FATAL: {profile}: no config at {path} "
                  f"(checked {checked}/{len(profiles)} profiles)",
                  file=sys.stderr)
            sys.exit(1)
        cfg = read_config(path)
        sections = [b for b in PLATFORM_BASES if "_" + b in cfg]
        want_mention = "false" if profile == ORCHESTRATOR else "true"
        profile_drift = 0
        for base in sections:
            for sub in ROUTING_KEYS:
                want = want_mention if sub == "require_mention" else "true"
                val = get_key(cfg, f"{base}.{sub}")
                if val is None:
                    changed.append((profile, f"{base}.{sub}", "<missing>", want))
                    profile_drift += 1
                    if args.apply:
                        set_key_in_file(path, base, sub, want)
                        print(f"APPLIED {profile}: {base}.{sub} <missing> -> {want}")
                    continue
                if val.lower() not in ("true", "false"):
                    continue  # odd value; don't touch
                if val.lower() != want:
                    changed.append((profile, f"{base}.{sub}", val, want))
                    profile_drift += 1
                    if args.apply:
                        set_key_in_file(path, base, sub, want)
                        print(f"APPLIED {profile}: {base}.{sub} {val} -> {want}")
        checked += 1
        print(f"{profile}: {len(sections)} platform section(s) checked, "
              f"{profile_drift} drift")

    if checked == 0:
        print("FATAL: no profiles checked", file=sys.stderr)
        sys.exit(1)

    if changed and not args.apply:
        print("DRIFT (run with --apply):")
        for profile, key, val, want in changed:
            print(f"  {profile}: {key} = {val}, want {want}")
        sys.exit(1)

    print(f"group routing: PASS ({checked} profile(s) checked, 0 drift)")
    sys.exit(0)


if __name__ == "__main__":
    main()
