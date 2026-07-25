# Cron Health Validation (finch:scan)

Reusable procedure for the cron-health signal source. The `cronjob` tool is
not exposed in the indigo cron profile, so read `jobs.json` directly — it is
the authoritative source (SKILL.md confirms `hermes cron list` hides disabled
jobs, so a summary view can under-report errors).

## Parse script (terminal python3 — execute_code is blocked in indigo cron)

```python
import json, os
p = '~/.hermes/profiles/<profile>/cron/jobs.json'
d = json.load(open(p))
jobs = d if isinstance(d, list) else d.get('jobs', d.get('data', []))
if isinstance(jobs, dict):
    jobs = list(jobs.values())  # current jobs.json schema stores jobs as a dict (job_id -> job)
OUT = '~/.hermes/profiles/<profile>/cron/output'
for j in jobs:
    ls = j.get('last_status')
    if ls in ('error',) or j.get('last_delivery_error') or j.get('consecutive_failures'):
        jid = j.get('id'); rid = j.get('rid') or jid
        out_dir = os.path.join(OUT, rid)
        recovered = False
        if os.path.isdir(out_dir):
            files = sorted(os.listdir(out_dir))
            # a later file than last_run_at with non-error content = recovered
            recovered = any('Script exited' not in open(os.path.join(out_dir, f)).read()[:400]
                            for f in files if f.endswith('.md') or f.endswith('.txt'))
        print('ERR', jid, j.get('name'), 'state=', j.get('state'), 'enabled=', j.get('enabled'),
              'last_status=', ls, 'consec=', j.get('consecutive_failures'),
              'last_run=', j.get('last_run_at'), 'recovered_next_tick=', recovered)
        print('   last_error:', repr(j.get('last_error'))[:300])
```

Note: output dirs are keyed by `rid` (runtime id) when present, else `id`.
Check both `rid` and `id` when matching.

## Classification gate

| Condition | Class | Action |
|-----------|-------|--------|
| `consecutive_failures=0` AND a later run wrote success output | TRANSIENT / recovered | Not a task. Mention in journal. |
| `state=paused` + `last_error` names missing credential/OAuth only | PAUSED-BY-DESIGN | Not a task. Note as standing limitation (needs <operator> interactive auth). |
| `consecutive_failures>0` OR error recurs across ticks | REAL | Create/escalate task per error taxonomy. |

## Rule

Never assert "cron health clean" unless you have enumerated every job and
surfaced (and classified) all `last_status=error` entries — including paused.

## Recovery evidence: trust `cron/output/<rid>/`, NOT `executions.db`

The parse script's `recovered_next_tick` check reads `executions.db` — but that
DB is **trimmed/rotated** (it only retains the most recent N runs), so a job's
prior-run history is frequently NOT in `executions.db` even when the job is
healthy. A `SELECT` that returns no rows for a job id proves nothing. The
**authoritative per-job run history** is the artifact directory
`~/.hermes/profiles/<profile>/cron/output/<rid or id>/` (one `.md`/`.txt` file
per run, named `YYYY-MM-DD_HH-MM-SS.*`). To confirm "was this a one-off or a
recurring fault," `ls -la` that directory and read the run artifacts directly:

- A clean long run history (many prior-success files) + a single trailing
  failure file that aborted early = **transient, single occurrence** (monitor).
- Many failure files clustered in time = **recurring** (real task).

Confirmed 2026-07-23 (finch:scan): `Engineering Manager — BOOK Escalation
Handler` (b1ae8917c3a2) was `last_status=error` with a Tencent upstream error,
but `executions.db` had ZERO rows for it (trimmed), while
`cron/output/b1ae8917c3a2/` held ~55 files spanning 05:36→19:53 PDT — all
success until the final truncated 19:53 failure. The output dir, not the DB,
established it as a one-off transient.

## Transient signature: Tencent "Upstream error… Retry once"

`RuntimeError: Upstream error from Tencent: An internal error occurred. Retry once;
if it persists, contact support with your request_id.` is a **provider 5xx-class
transient**, NOT a code defect. Diagnostic tells (confirmed 2026-07-22/23):

- The run artifact (`cron/output/<rid>/<timestamp>.md`) shows the agent prompt
  started but the **failure occurred at the model call** (error appears before
  any `git`/`gh`/script step ran) — i.e. the LLM upstream returned an internal
  error and the run aborted at inference, not in user code.
- `consecutive_failures` is `null`/0 and the prior run history is clean.
- It is in the SAME transient class as ocas-autobio 429 and reach
  interpreter-shutdown → classify as **P3 monitor**; auto-retries on the next
  tick. Do NOT create a code-fix task.

Distinguish from a genuine code crash (e.g. `'tuple' object has no attribute
'get'`): a code defect has a Python traceback and the failure is IN a script
step, recurs every tick until fixed, and warrants a finch:work fix. The Tencent
"Upstream error" message never has a traceback and never names a local symbol.

## Real example (2026-07-17)

- `<other-ocas-skill>:journals` (94510fb15ae2): error at 17:55Z, but `cron/output/94510fb15ae2/2026-07-16_18-04-16.md` = "enqueued: 1 new journal files", `consecutive_failures=0` → TRANSIENT, recovered next tick.
- `<other-ocas-skill>:sync-spotify` (e0a126b6c9f7): `state=paused`, `last_error`="Missing Spotify credentials: SPOTIFY_REFRESH_TOKEN" → PAUSED-BY-DESIGN (needs <operator> interactive OAuth). Not broken.
  - **Verified stable (2026-07-18):** the SAME job (`e0a126b6c9f7`) still `state=paused` + `last_status=error` with `last_run_at=2026-07-13`, confirmed across 5+ scans (07-13→07-18). It is a permanent PAUSED-BY-DESIGN fixture — appears in every enumeration but is never a task. Classify once, then stop re-examining it each scan.
- A prior 23:10Z scan reported "clean" and missed both — because it used a summary-style view. This is the anti-pattern to avoid.
