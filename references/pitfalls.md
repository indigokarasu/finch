# Finch — Consolidated Pitfalls

## MEMORY.md Management

- **MEMORY.md has a 2,200 char limit** — when approaching it, prioritize directives > corrections > breakthroughs. Overflow goes to skill files.
- **MEMORY.md is the highest-impact target** — a correction in MEMORY.md affects every future session. A skill patch only affects sessions where that skill loads. When in doubt, put it in MEMORY.md.
- **MEMORY.md bloat from operational details** — never add cron IDs, script internals, skip logic, or transient state to MEMORY.md. It's for durable facts and directives only.
- **Context compaction messages leak through** — Sessions contain "[CONTEXT COMPACTION]" blocks that mention "always" and "never" as part of the summary. Filter these out or you'll get false positive directives.

## Signal Validation

- **finch:work must validate signal before executing** — Check that the underlying signal is still active (email still needs response, calendar event still upcoming, cron job still errored). If the signal resolved itself, mark the task done with note "auto-resolved during work".
- **finch:work blocked tasks** — If the work job cannot complete a task (missing permissions, external service down), mark it status="blocked" with a description. Do not leave blocked tasks as "pending" — they'll be retried every 30 minutes pointlessly.

## Architecture

- **All finch jobs are pure LLM** — No finch cron job (scan, work, daily, weekly) invokes Python scripts. The scripts in `archive/` are deprecated. If you find yourself wanting to call miner.py/router.py/compact.py, stop — do it with LLM reasoning instead.

## File Discovery

- **Symlinked file discovery** — Python's `Path.rglob()` does NOT follow symlinks by default. When scanning directories for files (skills, configs, references), use `os.walk(path, followlinks=True)` or `iter_skill_index_files()` instead of `rglob()`. This is especially important for `~/.hermes/skills/` where users may symlink skill directories from external locations. See GitHub issue #8293 for the original bug report.

## Session Review

- **Doing more than asked** — When the user asks you to read a file, read it — do not also rewrite it, update it, or "improve" it unless explicitly asked. When the user asks about contents, report them — don't restructure them. Respond to the request as stated. If the task is "review the PR," comment on it — don't also edit README, update configs, or do other unsolicited work.
- **Unsolicited cross-referencing** — Do not add issue numbers, PR links, or cross-references to commit messages, PR descriptions, or comments unless explicitly asked. Adding "Fixes #X" when not asked is an overreach.
- **Be active but surgical** — "Most sessions produce at least one skill update" means: scan for corrections, techniques, or loaded-skill gaps. If nothing fired, say "Nothing to save." Don't manufacture updates to stay active.
