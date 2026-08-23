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
PROFILE = os.environ.get("HERMES_PROFILE", "indigo")
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
