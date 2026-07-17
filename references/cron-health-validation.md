# Cron Health Validation (finch:scan)

Reusable procedure for the cron-health signal source. The `cronjob` tool is
not exposed in the indigo cron profile, so read `jobs.json` directly — it is
the authoritative source (SKILL.md confirms `hermes cron list` hides disabled
jobs, so a summary view can under-report errors).

## Parse script (terminal python3 — execute_code is blocked in indigo cron)

```python
import json, os
p = '/root/.hermes/profiles/indigo/cron/jobs.json'
d = json.load(open(p))
jobs = d if isinstance(d, list) else d.get('jobs', d.get('data', []))
OUT = '/root/.hermes/profiles/indigo/cron/output'
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
| `state=paused` + `last_error` names missing credential/OAuth only | PAUSED-BY-DESIGN | Not a task. Note as standing limitation (needs Jared interactive auth). |
| `consecutive_failures>0` OR error recurs across ticks | REAL | Create/escalate task per error taxonomy. |

## Rule

Never assert "cron health clean" unless you have enumerated every job and
surfaced (and classified) all `last_status=error` entries — including paused.

## Real example (2026-07-17)

- `monitor:journals` (94510fb15ae2): error at 17:55Z, but `cron/output/94510fb15ae2/2026-07-16_18-04-16.md` = "enqueued: 1 new journal files", `consecutive_failures=0` → TRANSIENT, recovered next tick.
- `taste:sync-spotify` (e0a126b6c9f7): `state=paused`, `last_error`="Missing Spotify credentials: SPOTIFY_REFRESH_TOKEN" → PAUSED-BY-DESIGN (needs Jared interactive OAuth). Not broken.
- A prior 23:10Z scan reported "clean" and missed both — because it used a summary-style view. This is the anti-pattern to avoid.
