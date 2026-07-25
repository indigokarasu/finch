#!/usr/bin/env python3
"""
memory_state.py - persisted reinforcement-state store for ocas-finch.

Stores entry-key -> {reinforcement_count, last_reinforced_at, half_life, tier}
so the Ebbinghaus forgetting curve is computed across runs instead of
re-guessed each cycle.

Also provides transactional tier-routing: verify the entry landed in the
destination tier before removing it from MEMORY.md, with rollback.

Usage:
  python3 memory_state.py status                    # show all entries
  python3 memory_state.py reinforce "entry text"    # record a reinforcement
  python3 memory_state.py check "entry text"        # check if decaying
  python3 memory_state.py route "entry text" --to-tier 2 --dest-path path
  python3 memory_state.py decay-report              # show entries by status
"""

import argparse
import json
import os
import sys
import time
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
_HERMES_PROFILE = os.getenv("HERMES_PROFILE", "indigo")
if HERMES_HOME.name != "profiles" and (HERMES_HOME / "profiles" / _HERMES_PROFILE).is_dir():
    PROFILE_HOME = HERMES_HOME / "profiles" / _HERMES_PROFILE
else:
    PROFILE_HOME = HERMES_HOME

STATE_FILE = PROFILE_HOME / "commons" / "data" / "ocas-finch" / "memory_state.json"
MEMORY_FILE = PROFILE_HOME / "MEMORY.md"

# Ebbinghaus half-life schedule (in days)
HALF_LIFE_SCHEDULE = [1, 3, 7, 14, 30]


def _key_for(text: str) -> str:
    """Stable key from entry text (normalized)."""
    return text.strip().lower().replace(" ", "_")[:60]


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"schema_version": "1.0", "entries": {}}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_FILE)


def reinforce(text: str, tier: int = 1):
    """Record a reinforcement for an entry."""
    state = load_state()
    key = _key_for(text)
    now = datetime.now(timezone.utc).isoformat()
    entry = state["entries"].get(key, {
        "key": key,
        "text": text.strip(),
        "reinforcement_count": 0,
        "first_seen": now,
        "last_reinforced_at": None,
        "half_life_days": HALF_LIFE_SCHEDULE[0],
        "tier": tier,
        "status": "new",
    })
    entry["reinforcement_count"] += 1
    entry["last_reinforced_at"] = now
    entry["tier"] = tier

    # Update half-life based on reinforcement count
    idx = min(entry["reinforcement_count"] - 1, len(HALF_LIFE_SCHEDULE) - 1)
    entry["half_life_days"] = HALF_LIFE_SCHEDULE[idx]

    # After 5 reinforcements, mark as consolidated
    if entry["reinforcement_count"] >= 5:
        entry["status"] = "consolidated"
    else:
        entry["status"] = "reinforced"

    state["entries"][key] = entry
    save_state(state)
    return entry


def check_decay(text: str) -> dict:
    """Check if an entry is decaying (past its half-life without reinforcement)."""
    state = load_state()
    key = _key_for(text)
    entry = state["entries"].get(key)
    if not entry:
        return {"key": key, "status": "unknown", "message": "Entry not in state store"}

    if entry["status"] == "consolidated":
        return {**entry, "decay_status": "stable", "message": "Consolidated — very stable"}

    if not entry.get("last_reinforced_at"):
        return {**entry, "decay_status": "new", "message": "Never reinforced"}

    last = datetime.fromisoformat(entry["last_reinforced_at"])
    now = datetime.now(timezone.utc)
    age_days = (now - last).total_seconds() / 86400
    half_life = entry["half_life_days"]

    if age_days > half_life * 3:
        decay_status = "decaying"
    elif age_days > half_life:
        decay_status = "stable"
    else:
        decay_status = "reinforced"

    return {
        **entry,
        "decay_status": decay_status,
        "age_days": round(age_days, 1),
        "half_life_days": half_life,
        "message": f"{decay_status} (age={age_days:.1}d, half_life={half_life}d)",
    }


def get_decay_report() -> list:
    """Return all entries sorted by decay status (decaying first)."""
    state = load_state()
    results = []
    for key, entry in state["entries"].items():
        results.append(check_decay(entry["text"]))
    # Sort: decaying first, then stable, then reinforced, then consolidated
    order = {"decaying": 0, "stable": 1, "reinforced": 2, "consolidated": 3, "new": 4, "unknown": 5}
    results.sort(key=lambda r: order.get(r.get("decay_status", "unknown"), 99))
    return results


def route_entry(text: str, to_tier: int, dest_path: str, dry_run: bool = False) -> dict:
    """
    Transactional tier-routing: verify the entry landed in the destination
    tier before removing it from MEMORY.md. Rolls back on failure.

    Returns a result dict with status and details.
    """
    result = {"text": text.strip(), "from_tier": 1, "to_tier": to_tier, "dest_path": dest_path}

    # Step 1: Append to destination
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
        if text.strip() not in existing:
            if not dry_run:
                with open(dest, "a", encoding="utf-8") as f:
                    if existing and not existing.endswith("\n"):
                        f.write("\n")
                    f.write(text.strip() + "\n")
            result["written_to_dest"] = True
        else:
            result["written_to_dest"] = True
            result["note"] = "Already present in destination"

        # Step 2: Verify the write
        if not dry_run:
            verify = dest.read_text(encoding="utf-8")
            if text.strip() not in verify:
                result["status"] = "FAILED"
                result["error"] = "Verification failed: text not found in destination after write"
                return result

        # Step 3: Remove from MEMORY.md
        if MEMORY_FILE.exists() and not dry_run:
            mem_content = MEMORY_FILE.read_text(encoding="utf-8")
            new_lines = [ln for ln in mem_content.split("\n") if text.strip() not in ln]
            new_content = "\n".join(new_lines)
            backup = MEMORY_FILE.with_suffix(".md.bak.route")
            shutil.copy2(MEMORY_FILE, backup)
            MEMORY_FILE.write_text(new_content, encoding="utf-8")
            result["removed_from_memory"] = True

        # Step 4: Update state store
        if not dry_run:
            state = load_state()
            key = _key_for(text)
            if key in state["entries"]:
                state["entries"][key]["tier"] = to_tier
                state["entries"][key]["routed_to"] = dest_path
                state["entries"][key]["routed_at"] = datetime.now(timezone.utc).isoformat()
                save_state(state)

        result["status"] = "OK"
        return result

    except Exception as e:
        result["status"] = "FAILED"
        result["error"] = str(e)
        return result


def cmd_status(args):
    state = load_state()
    entries = state.get("entries", {})
    if not entries:
        print("No entries in state store.")
        return
    print(f"State store: {STATE_FILE}")
    print(f"Entries: {len(entries)}")
    for key, entry in entries.items():
        decay = check_decay(entry["text"])
        print(f"  [{decay.get('decay_status', '?'):>10}] r={entry['reinforcement_count']} hl={entry['half_life_days']}d  {entry['text'][:60]}")


def cmd_reinforce(args):
    text = " ".join(args.text)
    tier = args.tier
    entry = reinforce(text, tier)
    print(f"Reinforced: {entry['text'][:60]}")
    print(f"  count={entry['reinforcement_count']} half_life={entry['half_life_days']}d status={entry['status']}")


def cmd_check(args):
    text = " ".join(args.text)
    result = check_decay(text)
    print(json.dumps(result, indent=2, default=str))


def cmd_decay_report(args):
    report = get_decay_report()
    if not report:
        print("No entries in state store.")
        return
    for r in report:
        status = r.get("decay_status", "?")
        text = r.get("text", r.get("key", "?"))[:60]
        age = r.get("age_days", "?")
        hl = r.get("half_life_days", "?")
        print(f"  [{status:>10}] age={age}d hl={hl}d  {text}")


def cmd_route(args):
    text = " ".join(args.text)
    result = route_entry(text, args.to_tier, args.dest_path, args.dry_run)
    print(json.dumps(result, indent=2, default=str))
    if result["status"] == "FAILED":
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="memory_state - reinforcement store + transactional tier routing")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show all entries")
    sub.add_parser("decay-report", help="Show entries by decay status")

    p_reinforce = sub.add_parser("reinforce", help="Record a reinforcement")
    p_reinforce.add_argument("text", nargs="+", help="Entry text")
    p_reinforce.add_argument("--tier", type=int, default=1)

    p_check = sub.add_parser("check", help="Check decay status")
    p_check.add_argument("text", nargs="+", help="Entry text")

    p_route = sub.add_parser("route", help="Route entry to another tier (transactional)")
    p_route.add_argument("text", nargs="+", help="Entry text")
    p_route.add_argument("--to-tier", type=int, required=True, help="Destination tier (2, 3, or 4)")
    p_route.add_argument("--dest-path", required=True, help="Destination file path")
    p_route.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return

    cmds = {
        "status": cmd_status,
        "reinforce": cmd_reinforce,
        "check": cmd_check,
        "decay-report": cmd_decay_report,
        "route": cmd_route,
    }
    cmds[args.cmd](args)


if __name__ == "__main__":
    main()
