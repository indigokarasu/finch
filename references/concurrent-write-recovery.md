# Concurrent-Write Recovery & File-Tool Flake Fallback

## Trigger
A `write_file` / `read_file` returns a warning like:

> "sibling subagent '9f64b5cb-...' modified `<file>` but this agent never read it. Read the file before writing to avoid overwriting the sibling's changes."

OR a `read_file` / `search_files` returns:

> "Error during OpenAI-compatible API call #N: 'DaemonThreadPoolExecutor' object has no attribute '_initializer'"

## Case 1 — Sibling-agent concurrent write

1. **Do NOT blindly re-write.** A sibling subagent may have a legitimate change in flight.
2. **Read the file back** (`read_file` or `terminal`) and compare against what you intended to write.
3. **Confirm mtime** — `stat -c '%y %n' <file>` — verify YOUR version is the latest on disk. If your content is present and newest, your write won and no sibling change was lost (typically because your change was a strict superset, e.g. an added script).
4. **Record the flag** in the task note: concurrency hazard observed, how resolved, mtime-confirmed. Keeps the audit trail honest — do not silently overwrite.
5. **If your change was NOT a superset** (sibling added something you'd clobber), merge rather than overwrite — use `terminal python3` to load both and merge programmatically.

Confirmed 2026-07-17 (finch:work, `relay-shutdown`): `write_file` on `EXPORT-RUNBOOK.md` warned a sibling touched it concurrently; read-back showed my verifier addition was intact and `stat` confirmed it was the newest mtime. No sibling content lost.

## Case 2 — `DaemonThreadPoolExecutor` file-tool flake

- `read_file` and `search_files` can throw this framework error in bursts (3+ consecutive identical failures observed 2026-07-17). **Retrying the same tool does NOT help.**
- **Fallback: `terminal`.** Use `python3` to read/parse files, `stat` for mtimes/sizes, `find` for listing. All succeed where the file tools flake.
- For JSON validation after edit: `terminal python3 -c "import json; json.load(open('<path>'))"` (execute_code is blocked in indigo cron).
- This is a transient infra error, not a permanent tool failure — do not encode "file tools do not work" as a standing rule.

## Why this matters
Silent overwrite of a sibling's in-flight change corrupts shared state (task-list.json, MEMORY.md, runbooks). The read-back + mtime check is cheap insurance and preserves the audit trail.
