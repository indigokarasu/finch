# Cron-health validation (reusable parse script)

**PURPOSE**
The authoritative cron registry is the profile `jobs.json`
(`~/.hermes/profiles/<profile>/cron/jobs.json`), NOT `hermes cron list`
and NOT `cronjob(action='list')` (the latter is not a deferrable tool and will
fail). `hermes cron list` (terminal CLI) surfaces only a subset of jobs
(enabled/scheduled only) and emits NO `last_status`/`consecutive_failures`
columns and no parseable JSON. Relying on it undercounts erroring jobs —
including PAUSED/disabled jobs that still carry `last_status=error`.

**Always enumerate cron health from the LIVE `jobs.json`.** Run the script
below via `terminal` (NOT `execute_code` — blocked in cron profiles).

> NOTE: this directory is PUBLIC. Genericise every path/name/id before
> committing. Use placeholders `<profile>`, `<agent-handle>`, `<job-id>`.

## The script

Pin the LIVE path (a `state-snapshots/` copy under `find` can be stale):

```python
import json, sys, os

JOBS = os.path.expanduser("~/.hermes/profiles/<profile>/cron/jobs.json")

def load_jobs(path):
    with open(path) as f:
        d = json.load(f)
    # Registry is a top-level object whose list lives under "jobs".
    # A few copied/old registries wrap it under data.jobs — only fall back
    # when the top-level "jobs" key is absent.
    if "jobs" in d:
        return d["jobs"], d.get("updated_at")
    if "data" in d and "jobs" in d["data"]:
        return d["data"]["jobs"], d.get("updated_at")
    return [], d.get("updated_at")

jobs, updated_at = load_jobs(JOBS)
print(f"registry_updated_at={updated_at}  total_jobs={len(jobs)}")

error_jobs = [j for j in jobs if str(j.get("last_status", "")).lower() == "error"]
paused_err = [j for j in error_jobs if j.get("state") in ("paused",) or j.get("enabled") is False]
print(f"last_status=error: {len(error_jobs)}  (of which paused/disabled: {len(paused_err)})")

# Bucket by consecutive_failures for triage (0 = likely recovered/transient)
from collections import Counter
buckets = Counter(str(j.get("consecutive_failures", "?")) for j in error_jobs)
print("consecutive_failures buckets:", dict(buckets))

for j in sorted(error_jobs, key=lambda x: str(x.get("consecutive_failures", 0)), reverse=True):
    jid = j.get("id")
    name = j.get("name")
    cf = j.get("consecutive_failures")
    st = j.get("state", "?")
    err = str(j.get("last_error", "")).replace("\n", " ")[:120]
    print(f"  {jid}  cf={cf}  state={st}  {name}\n      |_ {err}")
```

## Classification gate (apply to each error job)

- **TRANSIENT / self-recovered** if `consecutive_failures == 0` AND a later
  run produced success output. Verify by reading `cron/output/<job-id>/` and
  comparing its `success`/ok file mtime to the error run. Do NOT open a task.
- **PAUSED-BY-DESIGN** if `state == "paused"` or `enabled is False` AND the
  job was deliberately parked (e.g. awaiting interactive OAuth). Surface it as
  a known item, not a new defect. The live `jobs.json` still shows its last
  error — that is expected.
- **REAL** if `consecutive_failures > 0` and no later success evidence. Open
  or re-activate a task.

## Hard rules

- **NEVER report "cron health clean" / "0 errors" from a prior scan's state
  or from `hermes cron list` output.** Derive the claim from a FULL enumeration
  of the live `jobs.json` every run.
- A "0 errors" claim is a HIGH-RISK false-negative. Re-prove it each cycle.
- `hermes cron list` returns 0 rows in some cron contexts (CLI unavailable) —
  if your only source is that CLI and it comes back empty, that is NOT evidence
  of health; fall back to `jobs.json` immediately.
- Stale `last_error` strings persist in `jobs.json` even after recovery — gate
  on `consecutive_failures` + output-dir evidence, not on the presence of an
  error string alone.
