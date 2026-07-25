# Fixing a cron-detected code crash (finch:work)

When `finch:scan` surfaces a cron `last_status=error` carrying a Python traceback
message (e.g. `'tuple' object has no attribute 'get'`, `TypeError: ...`,
`KeyError: ...`), it is a genuine code defect — NOT a transient (no 429,
interpreter-shutdown, or provider 401). The task is to locate the module, find
the broken line, and fix it. Workflow:

## 1. The fix may already be in the working tree (uncommitted)
The committed (HEAD) code is what failed, but a working-tree modification may
already repair it — common when an interactive session or sibling run patched the
file but didn't commit. `jobs.json` still shows the crash because the *prior* tick
ran the broken HEAD. Check before assuming the crash is live:
```
cd <repo> && git status --short && git diff HEAD -- <file>
```
If ` M <file>` shows a diff that addresses the crash, the source is likely already
fixed — you only need to verify it and make it durable.

## 2. Get a real traceback (scripts swallow exceptions)
Many OCAS scripts wrap `main()` in:
```python
try:
    sys.exit(main(...))
except Exception as e:
    print(f"FAIL: ... crashed: {e}")
    sys.exit(1)
```
The cron stderr then shows ONLY the message, NO line number — so the broken line
is invisible from `jobs.json`. To find it, run a harness that imports the entry
and prints the full traceback:
```python
# _repro.py  (run via terminal python3; execute_code is blocked in indigo cron)
import traceback, sys
sys.path.insert(0, "scripts")
import rally_daily_performance as m   # the module whose main() you need
try:
    rc = m.main()
    print("RC=", rc)
except SystemExit as e:
    print("SystemExit rc=", e.code)
except Exception:
    traceback.print_exc()
```
Run `terminal python3 _repro.py`. The traceback names the exact `file:line`.
Delete `_repro.py` after. (Paths are repo-relative; the module imports its
siblings via `sys.path.insert(0, .../scripts)`.)

## 3. Commit the fix — don't leave it uncommitted
A working-tree-only fix is fragile: under cron these repos routinely carry many
local commits ahead of upstream and are exposed to `git pull` / rebase that
DISCARDS or CONFLICTS uncommitted changes. The next scheduled tick would crash
again. Commit ONLY the fix file (leave unrelated working-tree modifications
uncommitted, e.g. a separate watchdog tweak belonging to another task):
```
git add <fix-file>
git -c user.name="<agent-name>" -c user.email="<agent-email>" \
    commit -m "fix(<area>): <one-line root cause + contract>  [finch:work]"
```
Verify: `python3 -m py_compile <fix-file>` and re-run the harness (expect `RC=0`).
Confirm the broken call now matches the contract used by other callers
(e.g. `fetch_daily_closes()` returns `(dict, truncated)` — index `[0]` to get the
dict, exactly like its other callers).

## 4. Clean verification side-effects (dedupe appended log rows)
Running `main()` usually APPENDS a row to an append-only log (jsonl). Your
verification run therefore leaves a DUPLICATE same-key row (the crashed cron never
wrote one, so you now have 2–3). Dedupe to one deterministic row per key:
```python
import json, pathlib
P = pathlib.Path("<log>.jsonl")
rows, seen, removed = [], set(), 0
for line in open(P):
    line = line.strip()
    if not line:
        continue
    o = json.loads(line)
    k = o.get("date")                       # the dedup key for THIS log
    if k in seen:
        removed += 1
        continue
    seen.add(k)
    rows.append(json.dumps(o))
open(P, "w").write("\n".join(rows) + "\n")
print("removed", removed)
```
CAUTION for mixed-type logs (e.g. `decisions.jsonl` carries many `decision_type`s
per date): key on `(decision_type, date)`, NOT `date` alone, or you will wrongly
collapse distinct record types. After deduping, confirm the other record types in
the file are untouched (only the targeted type/key should shrink). Validate the
file still parses: `terminal python3 -c "import json; [json.loads(l) for l in open(P)]"`.
