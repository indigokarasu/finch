# Session 2026-06-30 — Scan #12: MCP Completely Unreachable in Cron + Kanban Interrupted

## What Happened

finch:scan #12 ran at 01:10 UTC. Two new findings beyond the ongoing OAuth revocation:

### 1. MCP Tools Completely Unreachable in Cron Context

Attempted to scan email/calendar/drive sources. The `mcp_google_workspace_*` tools are not available as native tools in cron context. Attempted workaround via CLI:

```
hermes mcp call google-workspace search_gmail_messages '{"query": "newer_than:2d"}'
→ ERROR: invalid choice: 'call'
```

The `hermes mcp` CLI only supports: serve, add, remove, list, test, configure, login, reauth, picker, catalog, install. There is NO way to invoke MCP tools from shell/cron context.

**Implication**: finch:scan can NEVER access email/calendar/drive data when running as a cron job. The cached-data fallback (dispatch journals, vesper briefings) is the ONLY option.

**Sources blocked**: email, calendar, drive (3 of 7 sources)

### 2. Kanban Board Investigation Interrupted

Jared's 15:15 Telegram session asked: "Check what's going on with the kanban board. Why is KODA's tasks blocked and why aren't you picking up your tasks"

The session was interrupted mid-diagnosis. Five systemic issues were identified:
1. No circuit breaker for rate-limit retries (KODA retried 29+ times)
2. Crash classification wrong (rc=0 after rate limit → "crashed" not "rate_limited")
3. No auto-recovery after rate-limit reset
4. Wrong assignee routing (email audit task assigned to KODA instead of Indigo)
5. Load balancing gap (Indigo had zero tasks despite being available)

No fixes were applied before interruption. Created task_023 (HIGH) to resume.

### 3. Gateway RSS Growth

Gateway process RSS grew from 538MB → 1.5GB between scans (3x in ~2h). Not critical but notable.

## Error State (Unchanged)

3 cron jobs still in error from OAuth revocation:
- haiku:follow-maintenance (HTTP 400)
- bower:scan (HTTP 429)
- sands:conflict-scan (HTTP 400)

## Deadlines Tomorrow (June 30)

- Clayroom Soma studio closes (clay pickup deadline)
- COC proof for Shannon Badiee (effective date July 1)

## Key Lesson

The skill's existing gotcha about MCP tools being "not registered in config.yaml" understates the problem. It's not a config issue — it's an architectural limitation. MCP tools are LLM-session-only. No shell workaround exists. The scan must treat email/calendar/drive as permanently unavailable in cron context and rely entirely on cached-data fallbacks.
