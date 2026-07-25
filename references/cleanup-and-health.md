# Cleanup Patterns & System Health

## Recurring Cleanup Automation Pattern

When you identify a class of files or data that accumulates and poses risk (security, disk, staleness):

1. Write a cleanup script to `~/.hermes/scripts/<descriptive-name>.sh`
2. Make it idempotent — safe to run multiple times
3. Add logging — echo timestamp + actions to a log file
4. Install a cron job — schedule at appropriate frequency
5. Update this reference doc

### Template

```bash
#!/bin/bash
# Cleanup <description>
TARGET_DIR="$HOME/.hermes/<dir>"
PATTERN="<glob_pattern>"
MAX_AGE_HOURS=<N>

if [ ! -d "$TARGET_DIR" ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) Directory not found: $TARGET_DIR"
    exit 0
fi

count=0
while IFS= read -r -d '' file; do
    rm -f "$file"
    count=$((count + 1))
done < <(find "$TARGET_DIR" -name "$PATTERN" -mmin +$((MAX_AGE_HOURS * 60)) -print0 2>/dev/null)

if [ "$count" -gt 0 ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) Cleaned up $count files"
fi
```

### Installed Instances

| Script | Target | Age threshold | Frequency | Installed |
|--------|--------|---------------|-----------|-----------|
| `cleanup-request-dumps.sh` | `request_dump_*.json` | 24h | hourly | 2026-05-17 |

## Manual Cleanup Patterns

### Empty journal directories

OCAS skills create `~/.hermes/commons/journals/<skill-name>/` on install but many never write entries. Check periodically:

```bash
find ~/.hermes/commons/journals/ -maxdepth 2 -type d -empty -delete
```

99 empty dirs were removed on 2026-05-17. Check monthly or when disk audit runs.

### Stale LadybugDB files

After corruption/recovery, LadybugDB may leave `.corrupted` snapshots and `_new.lbug` rebuild files. After confirming the main DB is healthy:

```bash
# Check main DB is in use
lsof ~/.hermes/commons/db/*/weave.lbug
# Remove stale files
rm -f ~/.hermes/commons/db/*/weave.lbug.corrupted
rm -f ~/.hermes/commons/db/*/weave_new.lbug
```

28.6M freed on 2026-05-17. Check after any DB recovery event.

### Stale weave snapshot accumulation

Weave DB snapshots under `commons/db/ocas-weave/snapshots/` accumulate over time (145 files, 78M as of 2026-05-17). These are operational data — review retention policy before pruning.

### Stale `.bak` files in commons/data

After data migrations or skill updates, `.bak` files accumulate under `~/.hermes/commons/data/`. Safe to remove once the migration is confirmed stable (typically 24h later):

```bash
find ~/.hermes/commons/data -name "*.bak*" -mtime +1 -delete
```

Common sources: `ocas-taste/*.bak.YYYYMMDD`, `ocas-custodian/issues.jsonl.bak`, `ocas-dispatch/threads.jsonl.bak`.

## Stale Lock File Detection

### Detection approach

1. Find all `.lock` files under `~/.hermes/` (excluding `node_modules/`)
2. For each lock file:
   - Check age via `os.stat().st_mtime`
   - If empty and age > 1h → stale, safe to remove
   - If contains JSON with `pid` field → check `/proc/{pid}` for liveness
   - If PID dead → stale, safe to remove
3. Never remove `gateway.lock` without verifying PID is dead

### Common Lock File Locations

| Path | Description | Safe to remove if stale? |
|------|-------------|-------------------------|
| `~/.hermes/cron/.tick.lock` | Cron tick lock | Yes, if cron not running |
| `~/.hermes/gateway.lock` | Gateway process lock | **No** — verify PID alive first |
| `~/.hermes/shared/nous_auth.lock` | Auth token lock | Yes |
| `~/.hermes/skills/.usage.json.lock` | Skills usage tracker | Yes |
| `~/.hermes/auth.lock` | Auth state lock | Yes |
| `~/.hermes/auth/google_oauth.json.lock` | Google OAuth lock | Yes |
| `~/.hermes/memories/*.lock` | Memory file locks | Yes |

### Python snippet

```python
import os, time, json

def is_lock_stale(path):
    stat = os.stat(path)
    age_hours = (time.time() - stat.st_mtime) / 3600
    try:
        with open(path) as f:
            content = f.read().strip()
        if not content:
            return age_hours > 1
        data = json.loads(content)
        pid = data.get('pid')
        if pid:
            return not os.path.exists(f"/proc/{pid}")
    except (json.JSONDecodeError, ValueError):
        pass
    return age_hours > 1
```

## Cron Health Quick Check

```bash
hermes cron list
```

**Note:** `hermes cron list --json` does NOT exist. Read `~/.hermes/cron/jobs.json` directly for structured data.

Look for:
- `last_status: error` — investigate the error message
- Transient errors (HTTP 429) usually self-resolve
- Permanent errors (HTTP 404 model deprecated) need config changes
- `model: null` means the job uses the system default

### Reading Cron Job Details

Job details are in `~/.hermes/cron/jobs.json` under the `jobs` key. Each job has: `id`, `name`, `model`, `last_status`, `last_error`, `last_run_at`, `next_run_at`.

### Common Cron Error Patterns

| Error | Meaning | Action |
|-------|---------|--------|
| `HTTP 429: Rate limit exceeded` | Transient quota exhaustion | No action — self-resolves on next run |
| `Not a git repository` | Skill's `.git` dir was lost during update | Patch `skill_update.py` to tolerate non-git dirs (done 2026-05-17) |
| `Script exited with code 1` | Generic script failure | Check the job's script and recent logs |
| `RuntimeError: HTTP 404` | Model deprecated or endpoint changed | Update job model config |

### Pitfalls

- Don't try to parse `jobs.json` via `cat | python3` — the Tirith security scanner blocks pipe-to-interpreter. Use `execute_code` with `json.load()` instead.
- Don't assume a job is broken just because `last_status: error` — check the error type and date.
- Don't use `hermes cron run <id>` unless explicitly required — manual runs can cause double-execution and consume rate limits.
