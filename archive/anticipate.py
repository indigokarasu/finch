#!/usr/bin/env python3
"""
Finch — Anticipate Engine (ocas-finch v3.0)

Manages the task list for the hourly finch cron job.
The LLM does the thinking; this script manages the data.

Each task item has:
  id          — unique identifier (slug)
  title       — short description
  priority    — 1-10 (10 = highest)
  status      — pending | done
  governed_by — which skill's rules apply (e.g. "ocas-dispatch", "ocas-headhunter", "system")
               The executing sub-agent loads this skill first and follows its safeguards.
  description — longer context for the sub-agent
  source      — what signal triggered this task (e.g. "email", "calendar", "disk", "session")
  created     — ISO timestamp
  completed   — ISO timestamp (when done)

Usage:
    python3 anticipate.py --build          # Signal the LLM should build a fresh list
    python3 anticipate.py --status         # Show current list status
    python3 anticipate.py --mark-done <id> # Mark item complete
    python3 anticipate.py --get-top        # Get the top pending item
    python3 anticipate.py --should-refresh # Exit 0 if refresh needed, 1 if not
    python3 anticipate.py --set-list <json># Set the task list from JSON string

The task list is stored at: ~/.hermes/commons/data/ocas-finch/task-list.json
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
OCAS_DATA_DIR = HERMES_HOME / "commons" / "data" / "ocas-finch"
TASK_LIST_PATH = OCAS_DATA_DIR / "task-list.json"

OCAS_DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_task_list() -> dict:
    if TASK_LIST_PATH.exists():
        try:
            with open(TASK_LIST_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"version": 3, "created": None, "refreshed": None, "items": [], "done_count": 0, "total_count": 0}


def save_task_list(tl: dict):
    tl["refreshed"] = datetime.now(timezone.utc).isoformat()
    with open(TASK_LIST_PATH, "w") as f:
        json.dump(tl, f, indent=2, default=str)


def should_refresh(tl: dict) -> bool:
    """Check if the list should be refreshed."""
    if not tl.get("items"):
        return True

    done = sum(1 for i in tl["items"] if i.get("status") == "done")
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


def mark_done(item_id: str) -> bool:
    tl = load_task_list()
    for item in tl["items"]:
        if item["id"] == item_id and item.get("status") == "pending":
            item["status"] = "done"
            item["completed"] = datetime.now(timezone.utc).isoformat()
            tl["done_count"] = sum(1 for i in tl["items"] if i.get("status") == "done")
            save_task_list(tl)
            print(f"Marked done: {item_id} ({tl['done_count']}/{len(tl['items'])} complete)")
            return True
    print(f"Item '{item_id}' not found or already done.")
    return False


def get_top_pending() -> dict | None:
    tl = load_task_list()
    for item in tl["items"]:
        if item.get("status") == "pending":
            return item
    return None


def get_status() -> str:
    tl = load_task_list()
    if not tl.get("items"):
        return "No task list. The LLM should build one."

    done = sum(1 for i in tl["items"] if i.get("status") == "done")
    total = len(tl["items"])
    pending = total - done

    lines = [
        f"Task list: {done}/{total} done, {pending} pending",
        f"Last refreshed: {tl.get('refreshed', 'never')}",
        "",
    ]
    for item in tl["items"]:
        status = "✓" if item.get("status") == "done" else "○"
        gov = item.get("governed_by", "system")
        lines.append(f"  {status} [{item.get('priority', '?')}] {item.get('title', 'Untitled')}  (governed_by: {gov})")
        if item.get("source"):
            lines.append(f"       source: {item['source']}")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Finch Task List Manager v3")
    parser.add_argument("--build", action="store_true", help="Signal that LLM should build a fresh list")
    parser.add_argument("--status", action="store_true", help="Show current list status")
    parser.add_argument("--mark-done", metavar="ITEM_ID", help="Mark an item as done")
    parser.add_argument("--get-top", action="store_true", help="Get the top pending item as JSON")
    parser.add_argument("--should-refresh", action="store_true", help="Exit 0 if refresh needed, 1 if not")
    parser.add_argument("--set-list", metavar="JSON", help="Set the task list from JSON string")
    args = parser.parse_args()

    if args.status:
        print(get_status())
        return

    if args.mark_done:
        mark_done(args.mark_done)
        return

    if args.get_top:
        top = get_top_pending()
        if top:
            print(json.dumps(top, indent=2))
        else:
            print("{}")
        return

    if args.should_refresh:
        tl = load_task_list()
        sys.exit(0 if should_refresh(tl) else 1)

    if args.set_list:
        try:
            new_list = json.loads(args.set_list)
            new_list["refreshed"] = datetime.now(timezone.utc).isoformat()
            save_task_list(new_list)
            print(f"Task list updated: {len(new_list.get('items', []))} items")
        except json.JSONDecodeError as e:
            print(f"Invalid JSON: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.build:
        tl = load_task_list()
        if should_refresh(tl):
            print("REFRESH_NEEDED")
        else:
            print("LIST_CURRENT")
        return

    # Default: show status
    print(get_status())


if __name__ == "__main__":
    main()
