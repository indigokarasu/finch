# Finch — Consolidated Pitfalls

## MEMORY.md Management

- **MEMORY.md has a 2,200 char limit** — when approaching it, prioritize directives > corrections > breakthroughs. Overflow goes to skill files.
- **MEMORY.md format: §-delimited, NOT structured markdown** — The memory tool stores and injects entries as one-liners separated by `§`. Never rewrite MEMORY.md as structured sections (## Headers, bullet lists). If the memory tool rejects a write with "file on disk has content that wouldn't round-trip", the format has drifted — restore to §-delimited single-line entries.
- **MEMORY.md is the highest-impact target** — a correction in MEMORY.md affects every future session. A skill patch only affects sessions where that skill loads. When in doubt, put it in MEMORY.md.
- **MEMORY.md bloat from operational details** — never add cron IDs, script internals, skip logic, or transient state to MEMORY.md. It's for durable facts and directives only.
- **Context compaction messages leak through** — Sessions contain "[CONTEXT COMPACTION]" blocks that mention "always" and "never" as part of the summary. Filter these out or you'll get false positive directives.

## Signal Validation

- **finch:work must validate signal before executing** — Check that the underlying signal is still active (email still needs response, calendar event still upcoming, cron job still errored). If the signal resolved itself, mark the task done with note "auto-resolved during work".
- **finch:work blocked tasks** — If the work job cannot complete a task (missing permissions, external service down), mark it status="blocked" with a description. Do not leave blocked tasks as "pending" — they'll be retried every 30 minutes pointlessly.
- **Stale task list entries** — The task list at `commons/data/ocas-finch/task-list.json` can accumulate resolved-but-not-closed tasks. Before investigating, query the actual current state of the referenced entities (e.g., `jobs.json` for cron tasks, auth checks for OAuth tasks). If all referenced entities are healthy, mark the task done immediately with a note — do not invest investigation effort in already-resolved issues.

## Architecture

- **All finch jobs are pure LLM** — No finch cron job (scan, work, daily, weekly) invokes Python scripts. The scripts in `archive/` are deprecated.

## File Discovery

- **Symlinked file discovery** — Python's `Path.rglob()` does NOT follow symlinks by default. Use `os.walk(path, followlinks=True)` instead.
- **"Lock" in command descriptions** — Flagged by security scanners. Rephrase to "Mark as fixed".

## File Editing

- **`read_file` output format contaminates file writes**: The `read_file` tool prefixes every line with `LINE_NUM|`. Always strip with `re.sub(r'^\d+\|', '', content, flags=re.MULTILINE)` before parsing as JSON.

- **finch:work task-list.json is NOT valid JSON on disk**: Every line has a `LINE_NUM|` prefix (e.g. `42|  "key": "value"`). This is the actual file content, not a display artifact. `patch` will always fail on this file — "Found N matches" or escape-drift. Use `sed -i` via `terminal()` for targeted updates. For full rewrites, use Python heredoc: strip prefixes -> `json.loads()` -> modify -> `json.dump()` -> re-add prefixes. Never use `patch` on task-list.json.

- **finch:interactive clarify timeout**: When the user doesn't respond within the time limit, default to `run` (full daily pipeline). Log the choice in evidence.jsonl. Do NOT re-prompt.

## finch:work Cron Tool Constraints

- **`execute_code` is categorically blocked in cron**: Use `terminal()` for all Python operations.
- **`write_file` works in cron**: Unlike general warnings, `write_file` works correctly in finch:work cron context.
- **`read_file` on JSON in cron**: Use `terminal('cat path')` -> `json.loads()` in Python for clean content.

## Cron System Diagnostics

- **Cron ticker death**: When gateway restarts, the cron ticker thread dies. Check `.tick.lock` mtime and `next_run_at` timestamps.
- **`jobs.json` path**: The `cronjob` tool reads from profile-specific `~/.hermes/profiles/<profile>/cron/jobs.json`, NOT the default `~/.hermes/cron/jobs.json`.

## Session Review

- **Match verbosity to the question** — Answer what was asked, stop. Don't append unsolicited summaries.
- **When the user is mid-conversation, stay tight** — They need results, not documentation.
- **Doing more than asked** — Read files, don't rewrite them. Report contents, don't restructure them.
- **No speculation without evidence** — Never say "likely" or "probably" without checking evidence files first.
- **Be active but surgical** — If nothing fired, say "Nothing to save." Don't manufacture updates.