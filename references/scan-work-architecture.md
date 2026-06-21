# finch:scan / finch:work Architecture

## Problem

The finch anticipation system went through three architectural iterations in May 2026, each failing for a distinct reason:

### V1 — Single Prompt (Scan + Action)
- One cron prompt that scanned all signal sources AND executed tasks
- **Failure:** Scanning consumed the entire context window. The agent would read emails, calendar, sessions, cron health, etc., then run out of tokens before reaching the action phase. Result: lots of analysis, no action.

### V2 — Python Script + LLM
- Split into `anticipate.py` (Python scans, writes task list JSON) + cron agent (reads JSON, acts)
- **Failure:** The Python script was the scanner, so the LLM became a dumb executor with no judgment. As Jared put it: "You took the LLM out of the loop so it became useless." The interop overhead also added latency and failure modes.

### V3 — Two LLM Cron Jobs (Current)
- `finch:scan` (every 2h): Wide lens, prioritization intelligence. Scans all signal sources, maintains the ranked task list. Does NOT execute tasks.
- `finch:work` (every 30min): Narrow lens, execution intelligence. Picks top pending item, loads the governing skill, executes the task. ONE task per run.
- **Key insight:** Both sides must be LLM-powered. The difference is scope, not capability.

## Why This Works

1. **Bounded scanning:** The scan job has a wide lens but a single job — maintain the list.
2. **Focused execution:** The work job picks ONE item and goes deep.
3. **LLM both sides:** The scanner makes value judgments about priority. The worker makes value judgments about how to execute.
4. **No Python interop:** Pure cron prompts. No scripts between the LLM and the task list.
5. **Skill governance:** The work job loads the governing skill before executing.

## What To Never Do

- Never merge scan and action into one prompt (V1 failure)
- Never put a Python script between the LLM and the task list (V2 failure)
- Never make the worker "dumb" — it needs full LLM reasoning
- Never invoke `anticipate.py` or `task_list_builder.py` — they're deprecated
- Never use `delegate_task` from a cron job for finch work items
- Never include LinkedIn as a scan source — the LinkedIn MCP only accesses the agent's own LinkedIn, not Jared's
- Never call Gmail/Calendar/Drive MCP without `user_google_email="jared.zimmerman@gmail.com"`
- Never skip a signal source during scanning — all 6 sources must be checked every run
- **Never treat the existing task list as ground truth — always validate items are still active.** When finch:scan refreshes the task list, re-check each pending task's underlying signal. If the signal has self-resolved (cron job now healthy, OAuth now valid, appointment now passed), mark it done rather than carrying it forward. Stale pending tasks waste finch:work cycles on already-fixed issues.

## Signal Sources Scanned by finch:scan

| Source | What to look for | Tool |
|--------|-----------------|------|
| **Cron health** | Jobs with error status, jobs that haven't run when expected | `search_files` or `terminal('cat /root/.hermes/cron/jobs.json')` — `cronjob(action='list')` does NOT exist in all profiles |
| **Email** | Unread/urgent messages needing response, actionable threads | Gmail MCP — **must pass user_google_email=jared.zimmerman@gmail.com**. NOTE: The MCP tool names `mcp_google_workspace_*` referenced in the finch:scan prompt do NOT exist. When unavailable, mark as blocked. |
| **Calendar** | Next 48h events, prep needs, travel gaps, conflicts | Google Calendar MCP — **must pass user_google_email=jared.zimmerman@gmail.com**. NOTE: Same MCP availability issue as email. |
| **Sessions** | Unfinished work from recent conversations | session_search |
| **Drive** | Recently shared/modified files needing attention | Drive MCP — **must pass user_google_email=jared.zimmerman@gmail.com**. NOTE: Same MCP availability issue as email. |
| **System** | Disk space, stale lock files, /tmp size, zombie processes | terminal(df -h, du -sh, etc.) |

**NOTE:** LinkedIn is NOT a valid scan source for Jared's account.

## Governance Model

Each task item has a `governed_by` field. The work job loads the corresponding skill before executing:

| governed_by | Skill rules |
|---|---|
| `ocas-dispatch` | Draft-only in cron. Never send email directly. |
| `private/headhunter` | Quality over speed. No repeats. CDO/VP/SVP/CPO only. $500k+ base. |
| `ocas-sands` | Calendar management rules from ocas-sands SKILL.md |
| `ocas-rally` | Portfolio research rules from ocas-rally SKILL.md |
| `ocas-odds` | Prediction market rules from ocas-odds SKILL.md |
| `ocas-weave` | Contact management rules from ocas-weave SKILL.md |
| `ocas-sift` | Research rules from ocas-sift SKILL.md |
| `system` | General system maintenance. No special skill rules. |

NEVER create a task that asks the work agent to violate its governing skill's rules.

## Task List Schema

> **NOTE (2026-06-20):** The actual `task-list.json` file on disk uses a slightly different schema than what was originally documented below. The file is ground truth — update this doc to match the file, not vice versa.

### Actual schema (as of 2026-06-20)

```json
{
  "version": 1,
  "scan_time": "2026-06-19T20:00:00Z",
  "total_jobs": "N/A",
  "error_jobs": "N/A",
  "healthy_jobs": "N/A",
  "notes": "Free-text summary of scan findings",
  "tasks": [
    {
      "id": "unique-slug",
      "title": "Short description",
      "description": "Full context for the work agent",
      "severity": "medium",
      "status": "pending",
      "source": "email",
      "created_at": "2026-06-19T20:00:00Z",
      "last_seen": "2026-06-19T20:00:00Z",
      "note": "Additional context or action hints"
    }
  ]
}
```

Key differences from original doc:
- Top-level: `tasks` (not `items`), no `refreshed`/`done_count`
- Per-task: `severity` (not `priority`), `created_at`/`last_seen` (not `created`/`completed`), no `governed_by`
- Status values: `pending`, `in_progress`, `done`, `cancelled`, `blocked`, `needs_review`

### Original documented schema (superseded)

## Superseded: Delegation Pattern

The previous delegation pattern (orchestrator cron → `delegate_task` → sub-agent) was replaced by the scan/work architecture. The finch:scan job IS the orchestrator. The finch:work job IS the executor. No `delegate_task` from cron jobs. See `archive/delegation-pattern.md` in earlier versions for historical reference.
