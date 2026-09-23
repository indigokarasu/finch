# finch:scan pitfalls (consolidated)

Concrete traps observed while running finch:scan against the live cron registry,
the Gmail/Calendar/Drive MCP, and the task-list.json store. Genericised — no
real names, job IDs, or paths.

## 1. Cron-error "completed" can be a FALSE RECOVERY — re-run the script
When a cron-error task was previously closed as `completed`, do NOT trust that
status on the next scan. The prior closure may have validated against the wrong
evidence (e.g. read a different file/line than the one actually failing, or
inspected a stale stack trace).

Require TWO independent confirmations before marking recovered:
- (a) the LIVE `jobs.json` no longer carries `last_status=error` for that job
  (or `consecutive_failures` has reset), AND
- (b) you actually RE-RAN the failing script in the same interpreter the cron
  uses and it exited 0 / produced the expected artifact.

If you cannot re-run, read the EXACT failing line from the CURRENT registry
`last_error` stack trace and confirm that line no longer errors. Inspecting a
guessed or adjacent line is exactly how false recoveries slip through. (This
anti-pattern is why the skill mandates live re-validation every cycle, and why
"0 errors" must be re-proven from a full jobs.json enumeration each run.)

## 2. The `expanduser("...{PROFILE}...")` missing-f-string bug class
A frequent cause of `FileNotFoundError` in profile-aware scripts:
```python
PROFILE = os.environ.get("HERMES_PROFILE", "<profile>")
AGENT_ROOT = os.path.expanduser("~/.hermes/profiles/{PROFILE}")   # BUG: literal {PROFILE}
```
`expanduser` only substitutes `~`; the `{PROFILE}` braces are NOT interpolated
without an `f` prefix, so the path stays literally `<fs-root>/profiles/{PROFILE}/...`
and every file open dies. The cron runner typically does NOT export
`HERMES_PROFILE`, so the fallback value is used — but the missing f-string
defeats it regardless of env.
FIX: `os.path.expanduser(f"~/.hermes/profiles/{PROFILE}")`.
Detect all instances: `grep -rn 'profiles/{PROFILE}' <skill>/scripts/`. A single
missing f-string can sit behind a previously "fixed" inspection of a different
line, which is how a false recovery hides.

## 3. task-list.json mutation: append to the live list, not a parallel dict
When re-ranking or adding tasks in a python script, build a dict keyed by id
FROM the list for lookup, but APPEND new tasks to the actual list object
returned by `json.load`, NOT to the dict. Appending only to the dict loses the
items at serialize time (the list and dict diverge, so new entries never reach
disk). Correct pattern:
```python
data = json.load(open(TL)); tasks = data["tasks"]
by_id = {t["id"]: t for t in tasks}   # for mutation lookups (shared objects)
by_id["x"]["status"] = "pending"      # OK: mutates the shared list element
tasks.append({...new task...})        # append to the LIST, not by_id
tasks.sort(key=...)
json.dump(data, open(TL, "w"), indent=2)
```

## 4. Google Workspace MCP content-batch REQUIRES user_google_email
`get_gmail_messages_content_batch(message_ids=[...])` returns a pydantic
validation error ("user_google_email Missing required argument") if
`user_google_email` is omitted — even though `search_gmail_messages` may appear
to work without it. Always pass `user_google_email="<operator_email>"` on EVERY
gws_* call (search, content batch, get_events, list_drive_items).

## 5. task-list.json SCHEMA CLOBBER — a scan can replace the `tasks` array with a 2-item `open_issues` stub

Confirmed 2026-09-22 (finch:scan #96). The LIVE
`<fs-root>/data/ocas-finch/task-list.json` had been overwritten (mtime
09-22T08:07) with a stub shaped `{"as_of", "generated_by", "open_issues":[2],
"summary"}` — top-level key `open_issues`, NOT the canonical `tasks`. 33 tasks
were lost, and both surviving items were noise (one a phantom artifact, one a
already-healthy job). A subsequent scan that trusts the file as "the task list"
will rebuild from 2 items and silently discard every real open issue.

Detection (mandatory, first thing after `json.load`):
```python
d = json.load(open(TL))
assert "tasks" in d, f"CORRUPT: top-level keys={list(d)} — expected 'tasks'"
```
A missing `tasks` key is CORRUPTION, never "an empty list". Do not append to
`open_issues`.

Recovery (single script, one process, validate-after-write — never `patch`):
1. Copy the stub aside as `task-list.json.stub-<MMDD>` for forensics. Never `rm`
   it — the stub's contents are evidence of what the writer believed.
2. Restore from the newest `task-list.json.bak-scan<N>` (these backups are
   written by every scan and are the recovery source of truth).
3. Re-apply this scan's signal updates to the restored tasks, append only ids
   not already present, re-sort by priority, set `version`/`scan_count`/
   `scan_cycle`/`updated_at`, write to a tempfile in the same dir, `os.replace`,
   then `json.load` the result.
4. Report the loss + restoration explicitly in the journal (`task_list_integrity`
   block) — a silent restore hides a real corruption event.

## 6. Phantom-artifact validation — prove the path exists BEFORE re-verifying

A pending task that names a file (or a directory) is unverifiable until that
path is proved to exist. The 09-22 stub carried
"Read-truncation recurrence in scan reads", asking the next scan to re-verify
`jobs.txt` / `tasks.txt` / `skilldir.txt`. `find <fs-root> -maxdepth 5` for
all three returned NOTHING — the artifacts were never real products of this
skill, so there was no truncation to re-verify and no fix to confirm.

Rules:
- Run the filesystem check FIRST: `find <root> -maxdepth N -name '<file>'`.
- Path absent ⇒ resolve the task as **PHANTOM** (`status: done`, with the
  path-absence command recorded as evidence). Never carry it forward as
  `pending_verification` — that is how a phantom item becomes load-bearing for
  a dozen scans.
- Never "fix" a phantom by *creating* the referenced file. That manufactures an
  artifact to justify the ticket and converts a no-op into permanent sprawl.

## 7. Ledger "fix applied / job seeded" claims need live-verification before closing an item

A custodian/escalation ledger (`issues.jsonl`, `escalation-runner-state.json`, journal
`fixes_applied`) can record a fix that never landed. Observed 2026-09-23: a ledger
entry marked a cron-timeout issue **resolved** with "Seeded a new cron job
`<job-name>` (id: `<hex-id>`)" — but the id was absent from BOTH the live profile
registry and the default registry, including a `jobs.json` snapshot written ~16 min
after the claimed seed; the escalation runner's own `fixes_pending` list still
carried the item.

Rules:
- Before treating a superseded/erroring job as resolved on a ledger claim, grep the
  live registry for the claimed seed:
  `grep -c "<hex-id>" ~/.hermes/profiles/<profile>/cron/jobs.json`
  → 0 matches means the seed claim is UNVERIFIED. Keep the finch task open and
  record the claim-vs-registry discrepancy for the next scan.
- A re-validation that TIMED OUT ("re-run timed out after Ns") is a FAILED
  re-validation, not a validated fix — the registry still shows `last_status=error`.
  Never inherit the ledger's resolved status from it.
- Cross-check `<fs-root>/commons/data/ocas-custodian/escalation-runner-state.json`
  `fixes_pending` — it often still lists the item as pending even after its issue
  record says resolved.
