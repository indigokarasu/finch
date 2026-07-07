# Runaway Background Process Pattern

## When finch:scan detects a process consuming >50% CPU for >5 minutes

A background process from a kanban task or previous session may be stuck in a loop, running a long-lived verification, or waiting on a slow I/O operation. This consumes resources that other cron jobs need and can cause disk growth (scratch DBs, log files).

## Detection

```bash
ps aux --sort=-%mem | head -6
# or
ps aux --sort=-%cpu | head -6
```

Look for:
- `python3` processes with script names (not `hermes` or `gateway`)
- CPU% >50% sustained (not a brief spike)
- Runtime >5 minutes (check START column)

## Common Causes (Confirmed 2026-06-29)

| Cause | Process Pattern | Resolution |
|-------|----------------|------------|
| Verification script in tight loop | `python3 verify_fix.py` at 90% CPU | Check if it's making progress (log output). If stuck >15 min, `kill <PID>` |
| Rebuild against large DB | `python3 verify_rebuild.py` streaming events | Expected — let it finish. Monitor disk for scratch DB growth. |
| Embedding generation | `python3` calling LLM API in loop | Slow but expected. Don't kill unless disk critical. |

## Decision Tree

1. **Is the process making progress?** — Check `ls -la /proc/<PID>/fd/` for open files, or tail its output file. If file sizes are growing, it's working.
2. **Is disk critical (>90%)?** — If yes AND the process is writing large files, kill it: `kill <PID>`. The kanban task can resume from its ledger.
3. **Has it been running >30 minutes?** — Likely stuck. Kill and report to user.
4. **Is it a kanban task process?** — Check `ps aux | grep kanban` or look at the script name. Kanban tasks have worktree paths (`/root/indigo-repo/.worktrees/t_<id>/`). Killing the process does NOT lose work — the task remains in_progress and can be resumed.

## Confirmed 2026-06-29

`verify_fix.py` (PID 1830991) — kanban task `t_8c2b9ff4` (Chronicle plugin fix). Running at 90.9% CPU for ~12 minutes. Process was started by a previous kanban worker session. Not stuck — it's running a full rebuild against a 400K-event test DB. Expected to complete, but monitor for disk growth from scratch DB at `/root/.chronicle-scratch/chron_test.db`.
