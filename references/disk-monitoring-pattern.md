# Disk Monitoring Pattern

## /tmp growth can be rapid

`/tmp` can grow from ~170M to ~900M in under 24h without any user action (cron jobs, hermes results, temporary Python files). When reporting disk trends, always include `/tmp` size and its delta since last scan. A sudden `/tmp` spike often indicates a looping or misconfigured cron job writing large outputs. Investigate with `du -sh /tmp/* | sort -rh | head -10`.

Confirmed 2026-06-28: /tmp grew from 168M → 898M in ~18h with no user interaction.

## When to Use

When a finch:work task involves disk usage investigation (typically `source: "system"` with title containing "Disk usage").

## Investigation Cascade

Run these in order — each level drills down only if the previous level shows concern:

### Level 1: Overall filesystem state
```bash
df -h / /tmp
```
- **Action threshold**: ≥85% = flag, ≥90% = critical, ≥95% = emergency (ENOSPC imminent)
- Note: ENOSPC at ≥95% produces MCP errors that masquerade as auth failures. See `session-2026-05-31-disk-recovery.md`.

### Level 2: Top-level directories
```bash
du -sh /root/ /var/log/ /var/cache/ /tmp/ /root/.hermes/ 2>/dev/null | sort -rh
```
Identify which top-level directory is consuming space.

### Level 3: Drill into the biggest consumer
```bash
# Example if /root/.hermes/ is biggest:
du -sh /root/.hermes/*/ 2>/dev/null | sort -rh | head -10
# Then drill further:
du -sh /root/.hermes/profiles/*/ 2>/dev/null | sort -rh
du -sh /root/.hermes/profiles/indigo/*/ 2>/dev/null | sort -rh | head -10
```

### Level 4: Find large individual files
```bash
find /root/.hermes/ -type f -size +100M -exec ls -lh {} \; 2>/dev/null | sort -k5 -rh
```

### Level 5: Journal and logs
```bash
journalctl --disk-usage
du -sh /var/log/journal/
du -sh /root/.hermes/*/logs/ 2>/dev/null | sort -rh | head -5
```

## Rapid Growth Detection (Confirmed 2026-06-29)

Disk grew from 64% (61G/96G) on Jun 27 → 89% (85G/96G) on Jun 29 — **~10.5G/day**. At this rate, disk full by Jul 1.

**Top suspect:** Chronicle DB (`commons/db/chronicle/`) — the P4 Timeline live write (kanban task `t_b8179ffa`) wrote 59 facts + 62 episodes + 15 documents on Jun 29, plus embeddings (2048d). Each embedding is ~8KB. 136 items × 8KB = ~1MB for embeddings alone, but the Chronicle DB may have grown from VACUUM-less operation or WAL file accumulation.

**Other suspect:** `verify_fix.py` (kanban task `t_8c2b9ff4`) running at 90% CPU for 12+ minutes — may be creating a large scratch DB at `/root/.chronicle-scratch/chron_test.db`.

**Diagnostic commands for rapid growth:**
```bash
# Find what grew since last scan
du -sh /root/.hermes/profiles/indigo/commons/db/chronicle/ 2>/dev/null
du -sh /root/.chronicle-scratch/ 2>/dev/null
du -sh /root/.hermes/state-snapshots/ 2>/dev/null
# Find files modified in last 24h, sorted by size
find /root/.hermes/ -type f -mtime -1 -size +10M -exec ls -lh {} \; 2>/dev/null | sort -k5 -rh | head -20
```

**When growth rate >5G/day:** Escalate to HIGH immediately. Identify the largest file modified in the last 24h. If it's a scratch/test DB from a kanban task, it can be safely deleted after the task completes.

## Known Large Consumers (as of 2026-06-28)

| Path | Typical Size | Growth Rate | Cleanup? |
|------|-------------|-------------|----------|
| `profiles/indigo/commons/db/chronicle/` | 13G | Steady | VACUUM; archive old entries |
| `state-snapshots/` | 11G (1 snapshot) | Per snapshot | Delete old snapshots (>7d) |
| `profiles/indigo/` (total) | 26G | Slow | Subdirs vary |
| `migrations/` | 6.1G | Static post-migration | Safe to remove after verification |
| `profiles/indigo/commons/data/` | 891M | Slow | Selective pruning |
| `profiles/indigo/node/` | 530M | Static | No — required |
| `profiles/indigo/skills/` | 382M | Slow | No — required |
| `/var/log/journal/` | ~500M | Steady | `journalctl --vacuum-size=200M` |

### Full breakdown (2026-06-28 scan)

```
/root/.hermes/                     45G total
  profiles/                        28G
    indigo/                        26G
      commons/                     14G
        db/chronicle/              13G  ← largest single consumer
        data/                      891M
      node/                        530M
      skills/                      382M
      lsp/                         130M
      checkpoints/                 115M
      plugins/                     76M
      logs/                        67M
    koda/                          2.6G
  state-snapshots/                 11G  ← single pre-update snapshot (20260627)
  migrations/                      6.1G
  commons/                         485M
```

## Reporting Format

When reporting disk status to task-list.json, include:
1. Percentage and absolute numbers (e.g., "84% — 81G used of 96G, 16G free")
2. Top 3 consumers with sizes
3. Trend (up/down/stable vs last scan)
4. Verdict: `ok` / `monitor` / `cleanup_recommended` / `critical`
5. If `cleanup_recommended`: specific actionable suggestion

## Cleanup Commands (use with caution)

```bash
# Journal vacuum
journalctl --vacuum-size=200M

# Old state-snapshots (keep latest 2)
ls -dt /root/.hermes/state-snapshots/*/ | tail -n +3 | xargs rm -rf

# /tmp cleanup (safe — tmpfs)
find /tmp -type f -mtime +7 -delete

# Chronicle DB vacuum (SQLite — reclaims space after deletes)
sqlite3 /root/.hermes/profiles/indigo/commons/db/chronicle/chronicle.db "VACUUM;"
```

> **NEVER run cleanup commands without explicit user approval.** Report findings and recommendations. The user decides what to delete.
