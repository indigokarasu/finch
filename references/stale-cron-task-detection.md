# Stale Cron Job Task Detection (finch:work)

## Problem

A task in `task-list.json` references cron jobs by name or script (e.g., "Fix email brief scripts — both disabled"). The task assumes the cron jobs exist. When the jobs were already removed (disabled, deleted, or never deployed), the task is stale — there's nothing to fix.

## Detection Pattern

When a task references cron job names or script file paths, verify before acting:

1. **Check `hermes cron list` text output**: Shows only active jobs. Absence from this list means the job is either disabled or deleted.
2. **Check `jobs.json`**: Parse `~/.hermes/profiles/indigo/cron/jobs.json` to find disabled (`enabled: false`) jobs.
3. **Check if scripts exist on disk**: If the task mentions a script file (e.g., `brief:email-morning` → `email_morning_brief.py`), verify with `find` or `terminal("which <script>")`.
4. **Check for pipeline coverage**: Even if a cron job was removed, its function may be handled by a different active pipeline. Check if the same output is produced by other jobs.

## Resolution

If the cron job no longer exists AND no active pipeline covers its function:
- Mark task `done` with resolution: "Stale entry — [job name] no longer exists in cron list or jobs.json. [Function description] is handled by [active pipeline]."

If the cron job is disabled but its function is covered by an active pipeline:
- Mark task `done` with resolution: "Already resolved — [job name] is disabled, function covered by [active pipeline]. No action needed."

## Example (Confirmed 2026-06-29)

**task_015**: "Fix scripts or remove disabled cron jobs on next maintenance window"
- Referenced: `brief:email-morning` and `brief:email-evening`
- Checked `hermes cron list`: both absent (not even disabled — fully deleted)
- Checked `jobs.json`: absent
- Checked scripts: `email_morning_brief.py` and `email_evening_brief.py` do not exist
- Checked pipeline coverage: `sands:morning-brief` + `dispatch:briefing-deliver` handle the same workflow
- Resolution: Done — stale entry, nothing to fix

## Key Insight

The task description says "disabled" but the actual state is "deleted." The scan that created the task ran when the jobs were disabled; they were subsequently deleted. Time gap between scan and work = state change.
