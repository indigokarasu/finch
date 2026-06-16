# Custodian Error Investigation Pattern for finch:work

When a finch:scan task surfaces a custodian-related error (e.g., `custodian-deep-broken-pipe`), use this investigation pattern before marking the task status.

## Journal Location

```
/root/.hermes/profiles/indigo/commons/journals/ocas-custodian/
```

Key files:
- `issues.jsonl` — Consolidated issue tracker with status, resolution, and escalation tier
- `YYYY-MM-DD/` directories — Daily journal runs (light, deep, escalation-runner)
- `deep-*.json` — Deep scan runs with detailed findings
- `esc-run-*.json` — Escalation runner journals with resolution summaries
- `light-*.json` / `light-scan-*.json` — Light scan journals

## Investigation Steps

1. **Check `issues.jsonl` first** — Look for the issue_id matching the task. Check `status` (open/resolved), `resolved_at`, and `resolution` fields.

2. **Check today's journal directory** — `YYYY-MM-DD/` for light scan journals running every hour. Look for recent entries.

3. **Check escalation runner journals** — `esc-run-*.json` files contain resolution summaries for escalated issues.

4. **Cross-reference with cron schedule** — Use `hermes cron list` to find next run time for the failing job. If next run is imminent, set task status to `watching` with note about awaiting next run.

## Example: custodian-deep-broken-pipe (Jun 15 2026)

- Task created from finch:scan at 17:07 UTC
- `issues.jsonl` showed no matching issue_id (first occurrence)
- Journal directory `2026-06-15/` had only light scans (no deep scan yet)
- Cron schedule: `0 8,14,20,2 * * *` — next run 14:00 PT (21:00 UTC)
- Decision: Status `watching`, note "awaiting 14:00 PT run to confirm transient"

## Known Pitfalls

- **Pipe-to-interpreter errors** (`Broken pipe` / `Errno 32`) are a known custodian:deep pitfall per ocas-custodian SKILL.md — often transient
- **Stale errors in `hermes cron list`** — Text output shows full history. Always verify `Last run:` timestamp before counting as active error
- **Missing `custodian:deep` journal** — If deep scan hasn't run yet today, no journal file exists. This is normal, not an error.

## Task Status Guidance

| Situation | Status | Note Template |
|-----------|--------|---------------|
| First occurrence, next run pending | `watching` | "First occurrence. Next run at [time] — if succeeds, close as transient." |
| Recurring (2+ failures) | `action-needed` | "Recurring at [times]. Investigate deep scan log tailing pipe logic." |
| Resolved in issues.jsonl | `resolved` | "Resolved per issues.jsonl: [resolution summary]" |
| Escalation runner handled | `resolved` | "Escalation runner [run_id] resolved: [fix summary]" |