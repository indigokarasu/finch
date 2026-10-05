# The retired-writer class: scripts that write shared state on ANY invocation

First observed 2026-10-05 (finch:work #1193) when the per-profile `scripts/finch_update_tasklist.py`
was run with `--help` expecting usage output.

## What happened

`finch_update_tasklist.py` was a hardcoded one-shot from finch:work #202. It had no argument
handling at all: `NOW` was the literal `2026-09-27T07:16:00Z`, it targeted task `#120`, it appended
a `NEW_TASK` for `#121`, and `main()` wrote unconditionally. The `--help` probe executed a real write:

- `as_of` `2026-10-05T13:08:45Z` -> `2026-09-27T07:16:00Z` (a stamp 8 days in the PAST)
- `last_work_cycle` `1191` -> `202`
- `last_work_task` -> `chronicle-context-engine-db-lock-storm`
- the entire body of that task's signal / re_verify_trigger / work_log rewritten with 09-27 prose
- a task appended with `id: null`

Recovery was possible only because the script copied `task-list.json` to
`task-list.json.bak.<epoch>` before writing. That backup's byte size (2415433) matched what the
projection script had reported, which is what confirmed it was the true pre-write state.

## Why no gate caught it

Two independent gaps, both since closed:

1. **A second script surface.** `check_help_guard_placement.py` scanned only the skill's own
   `scripts/`. The offender lived in the per-profile `scripts/` dir, which no gate covered.
   The checker now walks both (463 files, was ~180).
2. **Static-only checking.** The checker only ran `source_violations()`; its own output says
   "this check does NOT execute the files". A script with no guard at all produces no static
   violation — absence of a guard is invisible to a check that only looks for misplaced guards.

## Rules

- **Never probe a script by running it.** Use `read_file`. A `--help` invocation is only safe on a
  script whose guard you have already read. This is the same rule the skill states for watchers,
  and it applies with full force to writers.
- **A writer must be argument-driven and idempotent.** No hardcoded timestamp literal, no
  hardcoded target id, no write on the import path. `finch_tasklist_single_write.py` is the
  sanctioned pattern: one process, read-modify-write, exclusive lock, atomic replace, `json.load()`
  confirmation inside the same process.
- **Every writer backs up before it writes**, and the backup is the only recovery path. Verify a
  restore by byte size against an independently observed figure, then `json.load()`.
- **An idempotency guard needs a marker unique to the cycle.** `if TASK_ID in json.dumps(work_log)`
  can never work: every log entry embeds `task_id`, so it matches all of them and the write is
  silently skipped forever. Use a per-cycle nonce written INTO the entry, assert absent before the
  first write and present after.
- **Keep the tombstone.** The retired file still exists and exits 2 with a pointer to the sanctioned
  writers. Deleting it would repeat the condition it documents.

## Related

`references/pitfalls.md`, `references/file-governance.md`, and the `--help` rule in SKILL.md's
"Why these rules hold" (the rule this script violated).