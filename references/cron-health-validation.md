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
# NOTE: the live registry carries paused=true WITH enabled=true. A detector that
# tests only `enabled is False` reports 0 paused for jobs that are plainly paused.
paused_err = [j for j in error_jobs
              if j.get("state") in ("paused",) or j.get("enabled") is False
              or j.get("paused") is True]
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
  **Caveat proven live 2026-09-26 (`39d06c70d0a6`):** the registry read
  `last_status: error` with `consecutive_failures: 0` while `cron/output/39d06c70d0a6/`
  held four consecutive `**Status:** script failed` files (01:13, 01:40, 02:10, 02:30).
  `consecutive_failures` is NOT maintained for every job, so treat `cf == 0` as
  "unknown" and let the output dir decide: if the NEWEST run file still says
  `script failed`, the job is broken regardless of `cf`. This gate alone would
  have passed a failing job as clean indefinitely.
- **PAUSED-BY-DESIGN** if `state == "paused"` OR `enabled is False` OR `paused is True`,
  AND the job was deliberately parked (e.g. awaiting interactive OAuth). Surface it as a
  known item, not a new defect. The live `jobs.json` still shows its last error — that is
  expected. Do NOT rely on `enabled is False` alone: observed live 2026-09-26 with
  `paused=True, enabled=True, state="scheduled"` on a job that had not run since 2026-08-03.
- **DELETED, NOT REPAIRED** if a job you have been tracking is absent from the registry
  entirely. A vanished name is not a healthy name — distinguish healthy / parked / gone and
  record which. Deletions can mask error-count changes: a deletion offsetting a new failure
  keeps the count flat while the underlying situation gets worse.
- **REAL** if `consecutive_failures > 0` and no later success evidence. Open
  or re-activate a task.
- **STALE `last_error` STRING** — the registry's `last_error` can name a defect
  that is ALREADY FIXED, so classify from the newest run OUTPUT and use
  `last_error` only to recognise the error class. Proven live 2026-09-26 on
  `39d06c70d0a6`: `last_error` still read `ModuleNotFoundError: No module named 'yaml'`,
  but the 02:30 run had progressed past that import (reporting "5183 events to embed")
  and was failing later, on `http://127.0.0.1:8080 ... (timed out)`. Trusting the
  string would mean chasing a fixed import bug and missing the live one.
- **`paused: true` does NOT mean the job stopped (confirmed 2026-09-26).** Both
  errored jobs in the live registry carried `enabled: true` + `paused: true` +
  `state: "scheduled"`. The scheduler gate (`cron/jobs.py` `_has_pause_marker()`)
  honours `state == "paused"` or a non-null `paused_at` and never reads the bare
  boolean — so these jobs are RUNNING and failing while looking parked. Do not
  discount an errored job on the strength of `paused: true`; see
  `scripts/pause_gate_watch.py`.

## Hard rules

- **NEVER report "cron health clean" / "0 errors" from a prior scan's state
  or from `hermes cron list` output.** Derive the claim from a FULL enumeration
  of the live `jobs.json` every run.
- A "0 errors" claim is a HIGH-RISK false-negative. Re-prove it each cycle.
- **Explain every change in the job COUNT between scans.** A shrinking registry is a
  finding, not background noise. Observed live: 157 -> 155 jobs in ~2.5h with the error
  count flat, because `monitor:wikipedia-talk` was deleted outright rather than repaired.
- **A non-zero exit from a self-diagnosing script is not a failure of its subject.** Read
  the script before classifying. `searxng_watchdog.py` exits 1 deliberately when
  `/proc/loadavg[0] > 6.0` — a 0-results verdict on a 2-core box is an environment
  false-negative — and prints "Host starved ... skipping restart" in the same breath. Probe
  the actual service (HTTP 200 + results, process count) before opening a task.
- `hermes cron list` returns 0 rows in some cron contexts (CLI unavailable) —
  if your only source is that CLI and it comes back empty, that is NOT evidence
  of health; fall back to `jobs.json` immediately.
- Stale `last_error` strings persist in `jobs.json` even after recovery — gate
  on `consecutive_failures` + output-dir evidence, not on the presence of an
  error string alone.
