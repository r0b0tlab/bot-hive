#!/usr/bin/env python3
"""configure_group_routing.py — enforce PROTOCOL.md §11.

Set/verify group routing on every Bot Hive profile:

  atlas        require_mention: false, exclusive_bot_mentions: true
  lane bots    require_mention: true,  exclusive_bot_mentions: true

Stdlib only. Non-destructive by default: run `--check` to see drift,
run with `--apply` to write it.

Usage:
  python3 scripts/configure_group_routing.py --check   # exit 0 = compliant
  python3 scripts/configure_group_routing.py --apply   # write configs
"""
import argparse
import os
import sys
from pathlib import Path

HOME = Path.home()
PROFILES = HOME / ".hermes" / "profiles"
ORCHESTRATOR = "atlas"
LANE_BOTS = ["scout", "forge", "quill", "audit", "media", "data"]
ALL_BOTS = [ORCHESTRATOR] + LANE_BOTS

# Platform keys that carry require_mention in Hermes config.yaml.
# Telegram/Discord/Slack/etc. all expose it at the platform level.
PLATFORM_KEYS = [
    "telegram.require_mention",
    "discord.require_mention",
    "slack.require_mention",
    "signal.require_mention",
    "mattermost.require_mention",
    "matrix.require_mention",
    "wecom.require_mention",
    "bluebubbles.require_mention",
    "buzz.require_mention",
    "photon.require_mention",
]
# exclusive_bot_mentions gates mention routing; default true in Hermes,
# but we assert it where the platform exposes it.
EXCLUSIVE_KEYS = [
    "telegram.exclusive_bot_mentions",
]


def config_path(profile: str) -> Path:
    if profile == "default":
        return HOME / ".hermes" / "config.yaml"
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
    """Set base.key = value, preserving file structure. Stdlib only."""
    lines = path.read_text().splitlines(keepends=True)
    out = []
    in_section = False
    section_written = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and ":" in stripped:
            section = stripped.split(":", 1)[0].strip()
            in_section = section == base
            out.append(line)
            continue
        if in_section and indent == 2 and stripped.split(":", 1)[0].strip() == key:
            out.append(f"  {key}: {value}\n")
            section_written = True
            continue
        out.append(line)
    if in_section and not section_written:
        # section exists but key missing — append under it
        out.append(f"  {key}: {value}\n")
    text = "".join(out)
    path.write_text(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report drift, don't write")
    ap.add_argument("--apply", action="store_true", help="write configs")
    ap.add_argument("--profile", default=None, help="only this profile")
    args = ap.parse_args()

    if not args.check and not args.apply:
        args.check = True  # default = check

    changed = []
    for profile in ALL_BOTS:
        if args.profile and profile != args.profile:
            continue
        path = config_path(profile)
        if not path.exists():
            print(f"SKIP {profile}: no config at {path}")
            continue
        want_mention = "false" if profile == ORCHESTRATOR else "true"
        cfg = read_config(path)
        for key in PLATFORM_KEYS + EXCLUSIVE_KEYS:
            base, sub = key.split(".", 1)
            val = get_key(cfg, key)
            if val is None:
                # platform not configured -> nothing to set
                continue
            if sub == "require_mention":
                want = want_mention
            elif sub == "exclusive_bot_mentions":
                want = "true"
            else:
                continue
            if val.lower() not in ("true", "false"):
                continue  # odd value; don't touch
            if val.lower() != want:
                changed.append((profile, key, val, want))
                if args.apply:
                    set_key_in_file(path, base, sub, want)
                    print(f"APPLIED {profile}: {key} {val} -> {want}")
    if not args.apply:
        if changed:
            print("DRIFT (run with --apply):")
            for profile, key, val, want in changed:
                print(f"  {profile}: {key} = {val}, want {want}")
            sys.exit(1)
        print("group routing: PASS (all profiles in spec)")
        sys.exit(0)
    if args.apply and not changed:
        print("group routing: PASS (already in spec)")
    sys.exit(0 if not changed else 0)


if __name__ == "__main__":
    main()
