#!/usr/bin/env python3
"""
Finch — Autonomous Task List Builder (ocas-finch v2.1)

Runs hourly. Builds a prioritized task list by:
1. Mining recent sessions for actionable signals (not just behavioral corrections)
2. Scanning system state (cron health, stale items, pending work)
3. Writing the list to commons/data/ocas-finch/task-list.json
4. Returning the top-priority item for execution

The cron agent reads the list, executes the top item, marks it done,
and moves to the next. When half the list is complete, re-runs this
script to refresh.

Usage:
    python3 task_list_builder.py              # Full analysis, output top item
    python3 task_list_builder.py --list-only  # Just build/refresh the list
    python3 task_list_builder.py --mark-done <item_id>  # Mark item complete
    python3 task_list_builder.py --status     # Show current list status
"""

import json
import os
import re
import sys
import glob
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", Path.home() / ".hermes" / "sessions"))
HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
OCAS_DATA_DIR = HERMES_HOME / "commons" / "data" / "ocas-finch"
TASK_LIST_PATH = OCAS_DATA_DIR / "task-list.json"
DECISIONS_PATH = OCAS_DATA_DIR / "decisions.jsonl"

# Ensure dirs exist
OCAS_DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_task_list() -> dict:
    """Load existing task list from disk."""
    if TASK_LIST_PATH.exists():
        try:
            with open(TASK_LIST_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"version": 2, "created": None, "refreshed": None, "items": [], "done_count": 0, "total_count": 0}


def save_task_list(tl: dict):
    """Write task list to disk."""
    tl["refreshed"] = datetime.now(timezone.utc).isoformat()
    with open(TASK_LIST_PATH, "w") as f:
        json.dump(tl, f, indent=2, default=str)


def session_files(hours: int = 24) -> list[Path]:
    """Get session files modified in the last N hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    files = []
    for f in sorted(SESSIONS_DIR.glob("*.jsonl")):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                files.append(f)
        except OSError:
            continue
    return files


def extract_signals_from_sessions(hours: int = 24) -> list[dict]:
    """
    Mine recent sessions for actionable signals.
    Unlike the behavioral miner (which looks for corrections/directives),
    this looks for: pending work, failed tasks, system issues, opportunities.
    """
    signals = []
    files = session_files(hours)

    # Patterns that indicate actionable work
    ACTION_PATTERNS = [
        # Unfinished work
        {"pattern": r"(?i)\b(left|still needs?|remaining|pending|unfinished|not (yet )?done|TODO)\b", "category": "pending_work", "priority": 7},
        {"pattern": r"(?i)\b(needs? to be (fixed|updated|completed|reviewed|checked))\b", "category": "pending_work", "priority": 8},
        {"pattern": r"(?i)\b(broken|failed|error|issue|bug|problem)\b", "category": "issue", "priority": 9},
        {"pattern": r"(?i)\b(should (run|check|verify|test|update|sync|fix))\b", "category": "action_needed", "priority": 8},
        {"pattern": r"(?i)\b(next step|then we need|after that|before we can)\b", "category": "sequence", "priority": 6},
        # System health
        {"pattern": r"(?i)\b(disk (space|full|usage)|storage)\b", "category": "system_health", "priority": 9},
        {"pattern": r"(?i)\b(cron (job|failed|error|stuck|missing))\b", "category": "cron_health", "priority": 8},
        {"pattern": r"(?i)\b(stale|outdated|old|expired)\b", "category": "stale_item", "priority": 5},
        # Enrichment / improvement opportunities
        {"pattern": r"(?i)\b(could be (better|improved|enhanced|optimized))\b", "category": "improvement", "priority": 4},
        {"pattern": r"(?i)\b(missing|gap|lacks?|no .* yet)\b", "category": "gap", "priority": 6},
        {"pattern": r"(?i)\b(garbage|bad data|wrong data|incorrect|clean up)\b", "category": "data_quality", "priority": 8},
    ]

    for fpath in files:
        try:
            with open(fpath) as f:
                lines = f.readlines()
        except IOError:
            continue

        session_id = fpath.stem
        for i, line in enumerate(lines):
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content or role not in ("user", "assistant"):
                continue

            # Skip system messages
            if content.startswith("[System") or content.startswith("[IMPORTANT"):
                continue

            for pat in ACTION_PATTERNS:
                if re.search(pat["pattern"], content):
                    # Get context window (surrounding messages)
                    ctx_start = max(0, i - 2)
                    ctx_end = min(len(lines), i + 3)
                    context = ""
                    for cl in lines[ctx_start:ctx_end]:
                        try:
                            cm = json.loads(cl)
                            cr = cm.get("role", "")
                            cc = cm.get("content", "")[:200]
                            if cr in ("user", "assistant") and cc:
                                context += f"[{cr}]: {cc}\n"
                        except (json.JSONDecodeError, KeyError):
                            continue

                    signals.append({
                        "session_id": session_id,
                        "line_num": i,
                        "category": pat["category"],
                        "priority": pat["priority"],
                        "matched_text": content[:300],
                        "context": context[:500],
                        "timestamp": msg.get("timestamp", ""),
                    })

    return signals


def scan_system_state() -> list[dict]:
    """
    Scan system state for actionable items.
    Checks: cron health, disk usage, stale files, failed jobs.
    """
    items = []

    # Check disk usage
    try:
        stat = shutil.disk_usage("/")
        pct_used = (stat.used / stat.total) * 100
        if pct_used > 85:
            items.append({
                "id": "disk_cleanup",
                "title": f"Disk usage at {pct_used:.0f}% — clean up",
                "category": "system_health",
                "priority": 9,
                "source": "system_scan",
                "detail": f"Disk: {pct_used:.0f}% used ({stat.free // (1024**3)} GB free)",
            })
        elif pct_used > 75:
            items.append({
                "id": "disk_monitor",
                "title": f"Disk usage at {pct_used:.0f}% — monitor",
                "category": "system_health",
                "priority": 5,
                "source": "system_scan",
                "detail": f"Disk: {pct_used:.0f}% used ({stat.free // (1024**3)} GB free)",
            })
    except OSError:
        pass

    # Check for stale lock files
    lock_files = list(HERMES_HOME.glob("**/*.lock"))
    old_locks = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    for lf in lock_files:
        try:
            mtime = datetime.fromtimestamp(lf.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                old_locks.append(str(lf))
        except OSError:
            continue
    if old_locks:
        items.append({
            "id": "stale_locks",
            "title": f"Clean up {len(old_locks)} stale lock file(s)",
            "category": "cleanup",
            "priority": 6,
            "source": "system_scan",
            "detail": "\n".join(old_locks[:5]),
        })

    # Check for large temp files
    tmp_large = []
    for tmp_dir in [Path("/tmp"), HERMES_HOME / "tmp"]:
        if tmp_dir.exists():
            for f in tmp_dir.glob("*"):
                try:
                    if f.is_file() and f.stat().st_size > 100 * 1024 * 1024:  # >100MB
                        tmp_large.append(f"{f} ({f.stat().st_size // (1024**2)} MB)")
                except OSError:
                    continue
    if tmp_large:
        items.append({
            "id": "large_tmp",
            "title": f"Clean up {len(tmp_large)} large temp file(s)",
            "category": "cleanup",
            "priority": 5,
            "source": "system_scan",
            "detail": "\n".join(tmp_large[:5]),
        })

    return items


def build_task_list(signals: list[dict], system_items: list[dict]) -> dict:
    """
    Merge signals and system items into a prioritized task list.
    Deduplicate, score, and rank.
    """
    items = []

    # Add system items first (they're already structured)
    for item in system_items:
        items.append({
            "id": item["id"],
            "title": item["title"],
            "category": item["category"],
            "priority": item["priority"],
            "source": item["source"],
            "detail": item["detail"],
            "status": "pending",
            "created": datetime.now(timezone.utc).isoformat(),
        })

    # Cluster signals by category and session to avoid duplicates
    seen_categories = set()
    for sig in sorted(signals, key=lambda s: -s["priority"]):
        cat = sig["category"]
        session = sig["session_id"]

        # Deduplicate: one action item per category per session
        key = f"{cat}:{session}"
        if key in seen_categories:
            continue
        seen_categories.add(key)

        # Skip low-priority duplicates across sessions
        cat_key = f"{cat}"
        if cat_key in seen_categories and sig["priority"] < 7:
            continue

        item_id = f"{cat}_{session[:8]}"
        items.append({
            "id": item_id,
            "title": f"[{cat}] Action needed — {sig['matched_text'][:80]}",
            "category": cat,
            "priority": sig["priority"],
            "source": "session_mine",
            "session_id": session,
            "detail": sig["context"],
            "status": "pending",
            "created": datetime.now(timezone.utc).isoformat(),
        })

    seen_categories.add(cat_key)

    # Sort by priority (descending)
    items.sort(key=lambda x: -x["priority"])

    # Deduplicate by ID
    seen_ids = set()
    unique_items = []
    for item in items:
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            unique_items.append(item)

    now = datetime.now(timezone.utc).isoformat()
    return {
        "version": 2,
        "created": now,
        "refreshed": now,
        "items": unique_items,
        "done_count": 0,
        "total_count": len(unique_items),
    }


def mark_done(item_id: str):
    """Mark a task as done in the list."""
    tl = load_task_list()
    found = False
    for item in tl["items"]:
        if item["id"] == item_id and item["status"] == "pending":
            item["status"] = "done"
            item["completed"] = datetime.now(timezone.utc).isoformat()
            tl["done_count"] = sum(1 for i in tl["items"] if i["status"] == "done")
            found = True
            break

    if not found:
        print(f"Item '{item_id}' not found or already done.")
        return False

    save_task_list(tl)
    print(f"Marked done: {item_id} ({tl['done_count']}/{len(tl['items'])} complete)")
    return True


def get_status() -> str:
    """Return human-readable status of the task list."""
    tl = load_task_list()
    if not tl["items"]:
        return "No task list. Run the builder first."

    done = sum(1 for i in tl["items"] if i["status"] == "done")
    total = len(tl["items"])
    pending = total - done

    lines = [
        f"Task list: {done}/{total} done, {pending} pending",
        f"Last refreshed: {tl.get('refreshed', 'never')}",
        "",
    ]

    for item in tl["items"]:
        status = "✓" if item["status"] == "done" else "○"
        lines.append(f"  {status} [{item['priority']}] {item['title']}")

    return "\n".join(lines)


def should_refresh(tl: dict) -> bool:
    """Check if the list should be refreshed (half done or stale)."""
    if not tl["items"]:
        return True

    done = sum(1 for i in tl["items"] if i["status"] == "done")
    total = len(tl["items"])

    # Refresh if half or more are done
    if total > 0 and done >= total / 2:
        return True

    # Refresh if list is older than 2 hours
    if tl.get("refreshed"):
        try:
            refreshed = datetime.fromisoformat(tl["refreshed"])
            age = datetime.now(timezone.utc) - refreshed.replace(tzinfo=timezone.utc)
            if age > timedelta(hours=2):
                return True
        except (ValueError, TypeError):
            return True

    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Finch Task List Builder")
    parser.add_argument("--list-only", action="store_true", help="Only build the list, don't output top item")
    parser.add_argument("--mark-done", metavar="ITEM_ID", help="Mark an item as done")
    parser.add_argument("--status", action="store_true", help="Show current list status")
    parser.add_argument("--hours", type=int, default=24, help="Hours of sessions to scan (default: 24)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.status:
        print(get_status())
        return

    if args.mark_done:
        mark_done(args.mark_done)
        return

    # Load existing list
    existing = load_task_list()

    # Check if we should refresh
    if existing["items"] and not should_refresh(existing):
        # List is fresh and not half-done; just return top pending item
        pending = [i for i in existing["items"] if i["status"] == "pending"]
        if pending:
            top = pending[0]
            if args.json:
                print(json.dumps(top, indent=2))
            else:
                print(f"TOP TASK: [{top['priority']}] {top['title']}")
                print(f"Category: {top['category']}")
                print(f"ID: {top['id']}")
                if top.get("detail"):
                    print(f"Detail: {top['detail'][:200]}")
        else:
            print("All tasks complete. Run with --list-only to refresh.")
        return

    # Build fresh list
    signals = extract_signals_from_sessions(hours=args.hours)
    system_items = scan_system_state()
    tl = build_task_list(signals, system_items)

    # Preserve done status from existing list for items that carry over
    done_ids = {i["id"] for i in existing.get("items", []) if i["status"] == "done"}
    for item in tl["items"]:
        if item["id"] in done_ids:
            item["status"] = "done"
    tl["done_count"] = sum(1 for i in tl["items"] if i["status"] == "done")

    save_task_list(tl)

    if args.list_only:
        if args.json:
            print(json.dumps(tl, indent=2, default=str))
        else:
            print(f"Task list refreshed: {tl['total_count']} items ({tl['done_count']} already done)")
            for item in tl["items"]:
                status = "✓" if item["status"] == "done" else "○"
                print(f"  {status} [{item['priority']}] {item['title']}")
        return

    # Output top pending item for the cron agent
    pending = [i for i in tl["items"] if i["status"] == "pending"]
    if pending:
        top = pending[0]
        if args.json:
            print(json.dumps(top, indent=2))
        else:
            print(f"TOP TASK: [{top['priority']}] {top['title']}")
            print(f"Category: {top['category']}")
            print(f"ID: {top['id']}")
            if top.get("detail"):
                print(f"Detail: {top['detail'][:300]}")
    else:
        print("No pending tasks. System is clean.")


if __name__ == "__main__":
    main()
