# `hermes cron list` text-table parse recipe (finch:scan)

`hermes cron list` (terminal CLI, `<fs-root>/.local/bin/hermes`) is the LIVE,
current-authoritative view of ALL active + paused cron jobs. It returns a
**human text table, not JSON** — there is no `--format json` mode; that flag
still emits text and `json.load(stdout)` raises `JSONDecodeError: Expecting
value: line 1 column 1`.

## Block structure (verified 2026-07-23, 156 jobs)

```
  bd7510e04226 [active]
    Name:      Gateway health monitor
    Schedule:  3-59/10 * * * *
    Repeat:    ∞
    Next run:  2026-07-22T22:13:00-07:00
    Deliver:   local
    Script:    sysadmin_gateway.sh
    Mode:      no-agent (script stdout delivered directly)
    Last run:  2026-07-22T21:54:04.079466-07:00  ok
```

## CRITICAL quirk (discovered 2026-07-23)

The CLI text output does **NOT** include a `last_status` or `consecutive_failures`
field. Error state lives ONLY in the `Last run:` line's trailing token:

- `Last run:  <ts>  ok` → healthy
- `Last run:  <ts>  error: <message>` → errored (the word `error:` follows the timestamp)

So you CANNOT gate on a `last_status` column from the CLI (unlike `jobs.json`,
which has `last_status` / `last_error` / `consecutive_failures`). **The error gate
for the CLI path = `Last run:` trailing text != exactly `ok`.** A parser that
scans for `Last status:` lines will find ZERO matches and silently report "0 errors"
— the false-negative trap. (Confirmed this run: first naive parser looked for
`Last status:` and returned 0 jobs; the corrected parse keyed on `Last run:`
trailing text and surfaced the 2 real stale errors.)

## Reusable parse (terminal python3 — execute_code is blocked in indigo cron)

```python
import re
raw = open('/tmp/cron_list_raw.txt').read()
lines = raw.splitlines()
jobs, cur = [], None
for ln in lines:
    m = re.match(r'\s*([a-f0-9]{12})\s+\[(\w+)\]', ln)
    if m:
        cur = {'id': m.group(1), 'state': m.group(2), 'name': None,
               'last_run': None, 'last_error': None, 'next_run': None}
        jobs.append(cur); continue
    if cur is None:
        continue
    s = ln.strip()
    if s.startswith('Name:'):
        cur['name'] = s[5:].strip()
    elif 'Last run:' in s:
        mm = re.search(r'Last run:\s*(\S+)\s*(.*)', s)
        if mm:
            cur['last_run'] = mm.group(1)
            tail = mm.group(2).strip()
            if tail and tail != 'ok':
                cur['last_error'] = tail
    elif s.startswith('Next run:'):
        mm = re.search(r'Next run:\s*(\S+)', s)
        if mm:
            cur['next_run'] = mm.group(1)
err = [j for j in jobs if j['last_error']]
```

Then classify each `err` entry (transient-vs-real procedure in
`references/cron-health-validation.md`). The CLI exposes no `consecutive_failures`,
so judge recurrence by inspecting `cron/output/<id>/` run history or by comparing
against prior scans — NOT by a CLI field.

## CLI vs jobs.json

| | CLI `hermes cron list` | `jobs.json` (`~/.hermes/profiles/<profile>/cron/jobs.json`) |
|---|---|---|
| `last_status` / `consecutive_failures` | **absent** | present |
| paused / disabled jobs | shown | HIDDEN (unless state filter) |
| stale `state-snapshots/` copy | n/a | avoid `find` — pin live path |
| best for | live current health of all active jobs | `consecutive_failures` gate; errors on paused/disabled jobs |

Use BOTH: CLI for the live active-job error surface; `jobs.json` when you need the
`consecutive_failures` gate or to see errors on paused/disabled jobs. Never report
"cron clean" without enumerating via at least one of them (prefer CLI grep for
active jobs + jobs.json for the full set).
