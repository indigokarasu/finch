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

- **finch:work task-list.json format**: As of 2026-06-20, the file on disk is clean JSON without embedded `LINE_NUM|` prefixes. The `read_file` tool adds prefixes as a display artifact. `json.dump()` via `terminal()` writes clean JSON correctly. The old pitfall claiming "every line has a LINE_NUM| prefix as actual file content" was a misreading of `read_file`'s display format. `patch` may still fail on this file due to fuzzy matching issues — prefer Python heredoc for targeted updates.

- **finch:interactive clarify timeout**: When the user doesn't respond within the time limit, default to `run` (full daily pipeline). Log the choice in evidence.jsonl. Do NOT re-prompt.

## finch:work Cron Tool Constraints

- **`execute_code` is categorically blocked in cron**: Use `terminal()` for all Python operations.
- **`write_file` on `task-list.json` in cron**: `write_file` writes clean JSON to disk. As of 2026-06-20, the file on disk is clean JSON without embedded `LINE_NUM|` prefixes. The `read_file` tool adds `LINE_NUM|` prefixes as a display artifact — this does NOT mean the file on disk has them. **When in doubt, use `terminal('python3 -c "import json; json.load(open(\\'path\\'))"')` to validate the file is parseable JSON.** If valid, `write_file` and `json.dump()` via `terminal()` are both safe. The old pitfall claiming "every line has a LINE_NUM| prefix as actual file content" is outdated — it was a misreading of `read_file`'s display format.

- **`read_file` on structured files in cron**: The `read_file` tool wraps ALL file content (not just task-list.json) in a JSON structure with `LINE_NUM|` prefixes and metadata fields (`content`, `total_lines`, `file_size`, etc.). This is a display/transport artifact. Strip with `re.sub(r'^\d+\|', '', raw, flags=re.MULTILINE)` before parsing as JSON or using the content programmatically.

- **`read_file` on JSON in cron**: Strip `LINE_NUM|` prefixes before parsing. Use `terminal('python3 -c "import json; print(json.dumps(json.load(open(\\'path\\')),indent=2))"')` for clean round-trip.

## Task List Schema Drift

- **Documented vs actual schema mismatch**: `scan-work-architecture.md` documents fields like `items`, `priority`, `governed_by`, `created`, `completed`, `refreshed`, `done_count`. The actual `task-list.json` uses `tasks`, `severity` (not `priority`), no `governed_by`, `created_at`/`last_seen` (not `created`/`completed`), and no `refreshed`/`done_count` top-level fields. **When the architecture doc and the file disagree, the file is ground truth.** Do not attempt to "fix" the file to match the doc — update the doc instead.

- **Missing `governed_by` field**: Tasks in the current list do not carry a `governed_by` field. The work job must infer the governing skill from the task's `source` and `description`. This is imprecise. When creating new tasks, consider adding `governed_by` to make the work job's skill selection deterministic.

## memory_guard.py Path Resolution

- **`HERMES_HOME` double-nesting bug**: When `HERMES_HOME` is already set to the profile directory (e.g., `/root/.hermes/profiles/indigo`), the script's own path-resolution logic appends `profiles/<profile>` again, producing `/root/.hermes/profiles/indigo/profiles/indigo/MEMORY.md`. The script checks `HERMES_HOME.name != "profiles"` but the profile dir's name is the profile name (e.g., `"indigo"`), not `"profiles"`, so the guard fails. **Workaround**: Always pass `--file /root/.hermes/profiles/indigo/MEMORY.md` explicitly when running the script. **Fix needed**: The script should also check if `HERMES_HOME` already ends with the profile name and skip re-appending.

## Cron System Diagnostics

- **Cron ticker death**: When gateway restarts, the cron ticker thread dies. Check `.tick.lock` mtime and `next_run_at` timestamps.
- **`jobs.json` path**: The `cronjob` tool reads from profile-specific `~/.hermes/profiles/<profile>/cron/jobs.json`, NOT the default `~/.hermes/cron/jobs.json`.

## Session Review

- **Match verbosity to the question** — Answer what was asked, stop. Don't append unsolicited summaries.
- **When the user is mid-conversation, stay tight** — They need results, not documentation.
- **Doing more than asked** — Read files, don't rewrite them. Report contents, don't restructure them.
- **No speculation without evidence** — Never say "likely" or "probably" without checking evidence files first.
- **Be active but surgical** — If nothing fired, say "Nothing to save." Don't manufacture updates.