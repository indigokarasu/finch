# Duplicate Task Detection and Cleanup (finch:work)

## Problem

The task-list.json can accumulate duplicate task entries when finch:scan re-creates a task that already exists (e.g., from a scan that runs before the previous scan's "done" status is written, or from concurrent scan jobs). Confirmed 2026-06-29: two `task_025` entries existed with identical signals (bower:scan 429 monitoring) but different `created` timestamps.

## Detection Pattern

When finch:work reads task-list.json, check for duplicate task IDs before selecting a task:

```python
from collections import Counter
task_ids = [t['id'] for t in tasks]
dupes = {tid: count for tid, count in Counter(task_ids).items() if count > 1}
```

Also watch for:
- Same signal text with different IDs (semantic duplicate — harder to detect automatically)
- Same ID with different statuses (concurrent-write corruption, not a true duplicate)

## Cleanup Pattern

When duplicates are found:
1. Keep the entry with the earlier `created` timestamp (it has the fullest context)
2. Remove the later entry
3. Log the cleanup in the work report
4. Do NOT merge entries with the same ID — if they have the same ID, one is stale from a concurrent write and should simply be removed

## Prevention

- finch:scan should check `task-list.json` for existing entries with the same signal before creating a new task
- Use `patch` or `terminal` to update existing entries rather than appending new ones
- The concurrent-write hazard pattern (see `references/task-list-json-pattern.md` § "Concurrent-Write Hazard") can produce duplicates when two scan jobs run simultaneously

## Confirmed

2026-06-29T13:30Z — finch:work found two `task_025` entries. Removed the later one (created 2026-06-29T19:06:36), kept the earlier (created 2026-06-29T17:11:51Z).
