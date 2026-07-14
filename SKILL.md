---
license: MIT
description: 'OCAS self-improvement orchestrator (Darwin''s finch — adaptive evolution).
  Mines session JSONL files to detect corrections, breakthroughs, methodologies, course-changes,
  and behavioral directives (Always/Never). Routes each finding to the optimal storage
  tier: MEMORY.md, skill files, reference files, or Chronicle KG. Compacts MEMORY.md
  by routing entries to the correct tier. Part of the OCAS System Evolution Layer
  alongside Mentor, Fellow, and Forge. NOT for real-time behavioral adaptation, skill
  evaluation, or skill creation.'
includes:
- references/**
- scripts/**
metadata:
  author: Indigo Karasu (indigokarasu)
  version: 2.15.3
name: ocas-finch
source: https://github.com/indigokarasu/finch
tags:
- self-improvement
- session-mining
- behavioral-adaptation
- OCAS-core
triggers:
- self-improvement
- session mining
- behavioral adaptation
- skill evolution
- correction detection
- health scan
- finch scan
- system health
- cron errors
- task list
- memory full
- MEMORY.md at capacity
- memory compaction
- memory guard
---

# ocas-finch

Finch is the OCAS System Evolution Layer's self-improvement orchestrator. It runs as a set of cron jobs — see **Manual run & verification** below for the actual deployed job set (the design doc's `finch:work` is not currently a separate deployed cron). Jobs are primarily pure-LLM cron prompts, plus one `no_agent` script floor (`finch:floor`). Deprecated scripts are in `archive/`.

**Signal sources (7)**: cron health, email, calendar, sessions, Drive, kanban, system. See `references/scan-work-architecture.md` for the full table.


## Interactive Menu

When invoked interactively, present a two-level menu. See `references/interactive-menu.md` for the full two-level menu layout, Clarify timeout behavior, response parsing, and platform adaptation.

## Responsibility Boundary

ocas-finch owns its core domain operations.

ocas-finch does not own: trigger detection, session management, or cross-skill orchestration (those belong to the calling agent).

## When to Use

- Scheduled self-improvement: finch:scan (every 2h), finch:work (every 30 min), finch:daily (6am PT), finch:weekly (Sunday 8am PT)
- Manual session mining via `finch.mine` or `finch.run`
- After major sessions: auto-detect corrections, directives, breakthroughs, methodologies
- Memory at/near capacity (`memory` tool refuses edits, ~79%+ warning threshold): run `finch.compact` / `memory_guard.py` — tier-route + consolidate, do NOT prune entries ad hoc via the memory tool. Finch owns compaction; this is the procedure, not "there is no skill."
- Skill library maintenance: route findings to SKILL.md patches

## When NOT to Use

- Real-time behavioral adaptation (Chronicle handles pattern detection)
- Skill evaluation scoring (Mentor handles OKR evaluation)
- Skill creation/architecting (Forge handles skill building)
- Entity identity resolution (Chronicle tools handle direct writes)

## Storage

See `references/storage-layout.md` for the full directory tree and skill package structure.

## Scanning Gotchas

- **Verify tool availability before parallel batches**: When finch:scan calls multiple tools in parallel, one invalid tool name poisons the entire batch — ALL calls return "Skipped" with no partial results. Always verify tool names exist before batching. The `cronjob` tool does NOT exist in all session profiles. Use `search_files` or `terminal` to inspect cron state when unavailable. **Updated 2026-06-30**: The old guidance said `mcp_google_workspace_*` tools are unreachable in cron. This is now WRONG — Composio tools (`GMAIL_FETCH_EMAILS`, `GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS`, `GOOGLEDRIVE_FIND_FILE`) work in cron context via `COMPOSIO_MULTI_EXECUTE_TOOL`. The Gmail toolkit may lack an active connection (no OAuth), but Calendar and Drive are functional. Always attempt these tools first — only skip if the toolkit connection is inactive, not as a blanket rule.
- **MCP tools are now reachable in cron via Composio**: The old guidance said `mcp_google_workspace_*` tools are completely unreachable in cron context. **Updated 2026-06-30**: This is no longer true. The `COMPOSIO_MULTI_EXECUTE_TOOL` and `COMPOSIO_SEARCH_TOOLS` meta-tools work in cron context and can call Google Calendar and Drive tools directly. Gmail may fail if the toolkit has no active OAuth connection — check `has_active_connection` in the search response. When retrieving message content from search results (e.g., Gmail), note the common two-step pattern: first call the search tool to get ID lists, then call the content retrieval tool with those IDs to get full message details. Calendar and Drive have active connections as of 2026-06-30. Use these tools in their own batch (they use a different backend than `terminal`/`read_file` calls). **Do NOT skip email/calendar/drive as a blanket rule — attempt them first and only skip on connection failure.**
- **REALITY CHECK — `tool_search` ≠ `tool_call` availability (confirmed 2026-07-13)**: In the **indigo cron profile**, `tool_search` LISTS `mcp__google_workspace__*` tools AND `tool_describe` returns their full schema, yet `tool_call` to the same name can FAIL with `Tool 'mcp__google_workspace__...' does not exist` — the runtime's own available-tools list omits all mcp tools (the MCP server is indexed but NOT actually loaded in this profile's runtime). Consequence: Google Workspace email/calendar/drive can be UNVERIFIABLE. Operational rule: (1) Probe a suspect MCP tool ALONE before batching it with needed tools (e.g. `session_search`) — a failed `tool_call` in a parallel batch poisons the WHOLE batch (`another tool call in this turn used an invalid name` → all siblings SKIPPED). (2) One failed `tool_call` is sufficient proof of unavailability for THAT run — do NOT also call `tool_describe` (wasted) or retry sibling mcp tools. (3) Treat the source as UNVERIFIED and carry forward prior findings.
  - **CORRECTION (2026-07-13T22:09 PDT) — MCP availability is INTERMITTENT, not permanently blocked**: The "unavailable" conclusion from the earlier 2026-07-13 run was contradicted LATER the SAME DAY — a scan at 22:09 successfully called `mcp__google_workspace__search_gmail_messages` / `get_events` / `list_drive_items` / `get_gmail_messages_content_batch`. The MCP server IS loaded on some runs. Therefore: **re-probe MCP with a real `tool_call` every scan; never treat a prior run's failure as a permanent block.** Critically, **DISTINGUISH THE TWO FAILURE MODES**: (a) a pydantic `unexpected_keyword_argument` / validation error means the tool IS reachable but you passed wrong params — `tool_describe` and fix params (this is what the earlier run actually hit, and was misread as "unreachable"); (b) a `Tool '...' does not exist` error means the server is NOT loaded this run — treat as UNVERIFIED, carry forward. The 2026-06-30 Composio path is the documented mechanism but was NOT active in this profile's runtime on either 2026-07-13 run, so MCP verifiability flips between runs with server load state.
- **Stale errors from `hermes cron list`**: The text output of `hermes cron list` shows the full history of each job. A job that failed at 14:00 but recovered at 15:00 will still show the error line. **`grep -B1 "error:"` matches these stale errors, inflating the error count.** Always verify the `Last run:` timestamp is from the latest run before counting an error as active. If the last run shows `ok`, the error is stale and should not be counted or reported. Observed 2026-06-13: 9 grep hits but only 3 were actual transient errors; the rest had already recovered. Create tasks only for persistent issues that won't self-resolve.
- **Re-verify prior completions against LIVE signal (scan must NOT trust prior verdicts)**: A FULL rescan must re-validate every `completed`/`done` task against current data and RE-OPEN on contradiction. Prior scans can be wrong: a job marked "fixed" may have relapsed with the identical error, or a provider key marked "resolved" may still be failing. **Confirmed 2026-07-13**: the prior scan marked TASK-027 `completed` with 4 fixes applied, but the live `hermes cron list` showed all 4 jobs still erroring with the exact same errors (`vibes:update` git-auth, `weave:enrichability-recalc` "db does not exist", `weave:sync-google` traceback, `Chronicle Embedding Enrichment` "no such table facts_fts"); the prior scan's "Nous key RESOLVED" claim was also wrong (`weave:overnight-enrichment` still 401'd). Procedure: when a prior task's signal is contradicted by live data, flip status back to `active`, append a `[RE-OPENED <ts>]` note with the live evidence, and do NOT re-mark done until a live run confirms. This is the SCAN-level analogue of the WORK-step "already-fixed-verification" and "repeated check-and-close" rules.
- **MCP Google Workspace param is `page_size`, not `limit`/`max_results`**: `mcp__google_workspace__search_gmail_messages` raises a pydantic `unexpected_keyword_argument` error if you pass `max_results` or `limit`. The correct param is `page_size` (default 10). **Always `tool_describe` an unfamiliar MCP tool before the first `tool_call`** to capture exact param names/schema — do not guess from analogous tools (the gws CLI uses `--max`, but the MCP tool uses `page_size`). The other MCP google-workspace tools (`get_events`, `list_drive_items`, `get_gmail_messages_content_batch`) follow the same describe-first discipline. Confirmed 2026-07-13: 2 wasted calls before `tool_describe` revealed `page_size`.
- **EMAIL SCAN MUST PAGINATE TO COMPLETION (confirmed 2026-07-13T22:09)**: `search_gmail_messages` with `newer_than:2d` returned **50 messages across 2 pages** (page_size 25). The result includes a `page_token` for the next page; loop until no `page_token` is returned. **A page-1-only fetch misses high-value items** — the P1 D.E.Shaw consulting reply (TASK-020) was on **page 2**. Same applies to any time-windowed Gmail query. Procedure: fetch page 1 → collect IDs → if `page_token` present, fetch next page with `page_token=` → repeat → then batch-fetch content for ALL collected IDs across pages. Do NOT stop at the first page. (Parsing recipe for the large batch-result file: see `references/email-mcp-pagination-parsing.md`.)
- **Sessions scan — date-string workaround**: When recent sessions don't appear with `query="last 24h"` (FTS5 limitation), use `query="YYYY-MM-DD"` for today's date. This matches timestamps in session IDs and reliably returns recent sessions. Confirmed 2026-06-28: `query="last 24h"` returned sessions from June 20; `query="2026-06-28"` returned today's actual sessions.
- **Mining interactive session messages — session_search scroll is unreliable; use direct SQL.** Scroll mode (`session_id` + `around_message_id`) fails with `around_message_id N not in session_id` because message IDs are global, not per-session sequential. To mine user messages from interactive (non-cron) sessions, query `state.db` directly: `sqlite3 /root/.hermes/profiles/indigo/state.db` → tables `sessions(id, source, started_at, title, message_count)` + `messages(session_id, role, content, timestamp)`. Filter `source != 'cron'` and `started_at >= (now_unix - 7*86400)`, then pull `role='user'` rows and keyword-scan. This is the reliable path (used by weekly-0831 and weekly-0858 runs). Browse-mode `session_search` returns only session listings, not message bodies.
- **Only report actual fixes, never stale/transient issues**: User explicitly stated: do not report transient errors, already-recovered jobs, or stale errors. If nothing was actually fixed or changed, say "Nothing new" and stop. Reporting noise wastes the user's time. **Interpreter-shutdown errors are always transient** — they self-resolve on the next scheduled run. Never create HIGH priority investigation tasks for them. See `references/scan-error-classification.md`.
- **Never force model overrides on cron jobs**: Only `openrouter/owl-alpha` is available. If a job's output is too large and truncated, fix the prompt to be more concise — never pin a different model in the cron job config.
- **Maintain a skill index**: Build and maintain `~/.hermes/profiles/indigo/references/skill-index.md` listing all skills and their GitHub repos. Refer to it instead of re-deriving from scratch every time. After any skill file modifications, commit and push to the source repo immediately.
- **Push local changes to GitHub (MANDATORY — user directive)**: After modifying any skill file (SKILL.md, references/, scripts/), **always** commit and push to the source repo immediately after testing and code verification. `git add -A && git commit -m "sync" && git push origin main` (or `--force` if remote diverged). **Do not wait for the user to ask.** This is an explicit user directive ("ALWAYS... automatically push and merge... Do not wait for the user to ask"). Never leave local changes uncommitted.
- **Disk-before-auth diagnostic**: When ALL Google MCP services fail simultaneously, first check `df -h /`. ENOSPC produces errors that look like auth failures. Do not generate auth URLs or ask user to re-auth while disk is full. See `references/session-2026-05-31-disk-recovery.md`.
- **`execute_code` in cron jobs**: While previously restricted, `execute_code` can now be used in cron jobs to run Python scripts that directly access files using standard `open()` calls. This avoids the line-number prefix issue from the `read_file` tool. For task-list.json updates: use `execute_code` to read the file with `open()`, parse/modify the JSON in Python, then write it back with `open()`. If using `read_file`, remember to strip line-number prefixes (`1|`, `2|`, ...) before parsing JSON. See `references/pitfalls.md` for additional patterns.
- **CAVEAT — `execute_code` blocked in the indigo cron profile (confirmed 2026-07-13)**: The claim above does NOT hold for this profile. `execute_code` is blocked by `approvals.cron_mode` with error `BLOCKED: execute_code runs arbitrary local Python ... Cron jobs run without a user present to approve it. Use normal tools instead, or set approvals.cron_mode: approve`. Fallback for JSON work in cron: use `terminal` with `python3 -c "..."` for load/dump/validation, plus `patch`/`write_file` for edits. After a multi-`patch` JSON edit, re-validate with `terminal python3 -c "import json;json.load(open('path'))"` — see the "patch lint applies but does not block" caveat below.
- **Concurrent-write hazard on task-list.json**: When `write_file` warns that a sibling subagent modified the file, do NOT overwrite. Read the current state first, merge your changes, then write. If the file contains JSON corruption from a concurrent write, use `patch` for surgical repair (see `references/task-list-json-pattern.md` § "Concurrent-Write Hazard").
- **Concurrent-write hazard on MEMORY.md**: Weekly/daily compaction can race with sibling agents or other Finch runs updating `/root/.hermes/profiles/indigo/memories/MEMORY.md`. If any write/patch reports a sibling modification warning, immediately re-read the current MEMORY.md and merge conservatively; preserve newly added directives unless they clearly duplicate stronger entries. For small corrections, prefer `patch` over full-file `write_file`. For full compaction rewrites, perform a final read-back + `wc -c`/size verification before journaling applied counts.
- **Concurrent-write hazard on MEMORY.md**: The same sibling-write warning applies to profile memory compaction. If `write_file` warns that another agent modified `/root/.hermes/profiles/indigo/memories/MEMORY.md`, immediately re-read the current file, merge your intended compaction/signals into that version, then write. Never assume your earlier read is still authoritative; memory compaction runs can overlap with other self-improvement jobs.
- **`jobs.json` for cron health**: When the `cronjob` tool is unavailable in cron context, read `~/.hermes/cron/jobs.json` or `~/.hermes/profiles/indigo/cron/jobs.json` directly. Parse with `json.load()` and filter on `last_error=None` vs set — `consecutive_failures > 0` alone is not evidence of active errors. **Always check `consecutive_failures`**: a job with `last_error` set but `consecutive_failures: 0` has already recovered. This is the single most reliable field for "is this actually broken right now?"
- **`hermes cron list` hides disabled jobs**: The CLI listing only shows enabled/active jobs. Disabled jobs (`enabled: false`) still exist in `jobs.json` but are completely invisible to `hermes cron list`. When a task involves cleaning up cron jobs or investigating "missing" scripts, always parse `jobs.json` directly to find disabled jobs. Confirmed 2026-06-28: two disabled email-brief jobs (`brief:email-morning`, `brief:email-evening`) did not appear in `hermes cron list` output but were present in `jobs.json` with `enabled: false` and stale error status. For cleanup: use `hermes cron delete <id>` to remove, then delete orphaned script files and stale reference docs.
- **Provider errors are NOT always transient — classify by HTTP status before acting**: `RuntimeError: Provider returned error` (no HTTP status) is transient LOW. But `HTTP 400` from LLM provider endpoints is **MEDIUM** — it will NOT self-resolve (expired API key, billing issue, format change). Distinguish from `oauth-token-expired` (HTTP 400 on `oauth2.googleapis.com/token` only) — that's a different category (CRITICAL). When 4+ jobs fail simultaneously with HTTP 400, it's a systemic credential issue — check provider dashboard. See `references/scan-error-classification.md` for the full error taxonomy including the `provider-http400` category.
- **Missing-script errors need path verification, not just debugging**: When a cron job's `Script:` field points to a file that doesn't exist (`[Errno 2] No such file or directory`), the fix is to update the cron's script path to the correct file — not to debug the script itself. List the actual scripts in the skill's `scripts/` directory to find the correct path. This is a 30-second fix (update cron config) vs. hours of debugging. Confirmed 2026-06-29: `email:check` cron pointed to `email_check.py` which never existed; actual scripts were `gmail_scan.py` and `check_unread.py`.
- **finch:work tasks referencing removed cron jobs**: When a task names a cron job that no longer exists (deleted, not just disabled), verify with `hermes cron list` AND `jobs.json` before concluding the task is actionable. If the job is absent from both and its function is covered by an active pipeline, mark the task done as stale. See `references/stale-cron-task-detection.md`.
- **finch:scan is NOT a task executor**: The scan job only observes and reports. It does not fix cron jobs, install packages, or send emails. Creating tasks is the output — execution belongs to finch:work or the user. Confirmed 2026-06-28: scan correctly identified 4 errors but did not attempt to fix them.
**read_file tilde expansion path doubling**: In profile cron context, `read_file(path="~/.hermes/MEMORY.md")` resolves to a doubled non-existent path (`/root/.hermes/profiles/indigo/home/.hermes/MEMORY.md`). Always use absolute paths. The canonical finch-managed memory for the indigo profile is `/root/.hermes/profiles/indigo/memories/MEMORY.md` (note the `/memories/` subdir — `/root/.hermes/profiles/indigo/MEMORY.md` does NOT exist). `/root/.hermes/MEMORY.md` is the DEFAULT profile's memory; do NOT edit it from an indigo-profile run (cross-profile guard). The finch HARD RULE references `memory_guard.py --file ~/.hermes/profiles/indigo/memories/MEMORY.md` — that path is authoritative.
- **`jobs.json` field types — dicts vs strings**: Some job object fields like `schedule` are `dict` type (`{"kind": "cron", "expr": "*/5 * * * *"}`), not strings. Applying string operations like `[:30]` directly to a dict raises `TypeError: unhashable type: 'slice'`. Always coerce with `str()` before slicing: `str(j.get('schedule', '?'))[:30]`.
- **Gateway RSS growth tracking**: The hermes gateway process RSS can grow significantly over days. When reporting system health in scan journals, always note the gateway RSS and compare to prior scans. A 3x increase (e.g., 538MB → 1.5GB in one day) is notable — flag it in the scan summary as "elevated, trending up" even if not yet actionable. Only escalate to MEDIOUS if it exceeds 2GB or causes OOM pressure. **Confirmed 2026-06-30**: Gateway RSS grew from 538MB → 1.5GB between consecutive 2h scans.
- **consecutive_failures is the ONLY reliable error gate — confirmed 2026-06-30**: A job with `last_error` set to a non-null string but `consecutive_failures: 0` has ALREADY RECOVERED. The error string persists as a stale artifact from a previous run. **Never create a CRITICAL or HIGH task based on `last_error` alone without checking `consecutive_failures > 0`.** Scan #13 (2026-06-30 03:00Z) misdiagnosed 3 transient LLM provider HTTP 400/429 errors (all `consecutive_failures: 0`) as "Google OAuth revoked," creating task_019 + task_014 that blocked email/calendar/drive scrutiny for 24h. Scan #14 (03:33Z) discovered all 140 jobs were healthy and the tasks were stale. gate: filter `consecutive_failures > 0` BEFORE classifying errors. If 0 jobs have consec > 0, report "all clear" and do not create error tasks.** See `references/scan-error-classification.md` § "CRITICAL RULE: consecutive_failures gates task creation."

## Architecture

- **All finch jobs are pure LLM**

**Role:** Session mining engine. Detects behavioral signals from conversation transcripts and routes them to durable modification targets (MEMORY.md, skill patches).

**Journal type:** Action Journal. Every finch run emits an Action Journal entry to `{agent_root}/commons/journals/ocas-finch/`.

**Cooperation:**
- Receives: Session transcripts (read-only, from the agent's session store)
- Reads: BehavioralSignal files from Chronicle (Corvus was merged into Chronicle)
- Emits: DecisionRecords to the Finch decision log
- Writes: MEMORY.md (via memory tool), skill SKILL.md files (via skill_manage)

## File governance

See `references/file-governance.md` for write targets, read-only files, off-limits files, and creation criteria.

## Signal types

See `references/signal-types-table.md` for the full signal type table.

## Behavioral directives (priority 0)

When the user says "Always" or "Never", this is an explicit behavioral rule. **Priority 0** — highest priority. Apply immediately and prominently. Route to MEMORY.md under `## Always Rules` or `## Never Rules`. Never batch with lower-priority findings.

## Core loop

Finch operates as a continuous improvement cycle:

1. **Scan** (`finch:scan`, every 2h) — Read 7 signal sources (cron health, email, calendar, sessions, Drive, kanban, system). Validate existing tasks. Maintain prioritized task list at `task-list.json`.
2. **Work** (`finch:work`, every 30 min) — Pick top pending task. Load governing skill via `skill_view`. Execute ONE task per run. Before selecting, check for duplicate task IDs and clean up if found (see `references/duplicate-task-detection.md`). When completing a task:
   - Update the task's description to include a work log with timestamp and summary of actions taken (e.g., `\n\n[Work log: At <timestamp> checked DNS for art.indigokarasu.com - no records found (NXDOMAIN).]`)
   - Set the task's status to `"done"`
   - Set the task's `done_at` timestamp to the completion time
   - Update the task's `updated_at` timestamp
   Route findings to MEMORY.md, skill patches, or reference files.

### Task selection priority (finch:work)

When multiple tasks are `pending`, select by:
1. **`action_required: true`** — tasks needing external action take absolute precedence
2. **Priority** — `high` > `medium` > `low`
3. **Due date urgency** — sooner due date wins within same priority
4. **Status** — `pending` tasks are picked before `in_progress` tasks (which are already being handled)

Skip tasks where `action_required: false` AND `status: "in_progress"` — these are events happening now (e.g., Jared is at the appointment). Only pick them if they transition to needing action.

If NO tasks have `action_required: true` and all remaining tasks are `pending` with `action_required: false`, pick the highest-priority one to validate/monitor (e.g., disk monitoring) and mark it `completed` with a resolution note. This prevents the list from accumulating stale low-priority items.

### Repeated check-and-close anti-pattern (work execution)

When a task was completed and marked `done`, then re-opened by a subsequent scan for the same unresolved issue, **do NOT run another check-and-close cycle.** After the first re-open, the correct action is decisive resolution or escalation — not re-verifying the same fact.

**Symptoms:**
- Task description says "still NXDOMAIN" / "still unresolved" / "re-opened from prior done status"
- Task was previously marked done with a "checked, found X" work log but the underlying issue persists
- The work log shows N consecutive identical checks with no fix attempted

**Procedure when you encounter a re-opened task:**
1. **Classify the task** — Is this a verification-only task (monitor, check, validate) or an action task (fix, create, configure, deploy)?
   - Verification tasks that are repeatedly re-opened for the same stable condition should be downgraded to `watching` with a note: "Stable state — not actionable." Do not mark `done`; that triggers re-open.
   - Action tasks that were marked `done` without the action being taken should be escalated: the prior closure was premature. Execute the actual fix.
2. **Identify the decisive action** — What single action would close this task permanently? For DNS: create the record. For config: apply the fix. For monitoring: leave as `watching` (not `done`).
3. **Pick decisive execution over verification** — If the task title or description implies an action (e.g., "DNS... unresolved"), invest the first tool call in actually resolving it, not re-verifying. Verification was already done by the prior finch:run or finch:scan.
4. **If genuinely stuck** — Mark the task `watching` with a `blocked_reason` field explaining what's needed to unblock it (e.g., "needs Jared to choose IP", "requires panel access to provision"). Do NOT mark `done`.

**Rationale:** Three cycles of check-and-close for one unmet DNS record cost ~9 tool calls over 12 hours. One decisive action costs 2 tool calls. The system learns nothing from re-verification; it only learns from resolution.

### Task actionability filter (cron context)

When running as a cron job with no user present, **filter for autonomous actionability** before applying the priority selection. A task is autonomously actionable if:

1. **No external response required** — The task doesn't depend on someone else replying (e.g., "track response from X" is NOT actionable; "check if X responded" IS actionable as a monitoring check)
2. **No business decision required** — The task doesn't require accepting/declining engagements, making commitments, or choosing between options with capital implications (e.g., "respond to consulting inquiry — accept or decline" is NOT actionable)
3. **No authentication required** — The task doesn't need app login, OAuth, or credentials the agent doesn't have (e.g., "check One Medical app" is NOT actionable)
4. **No user input required** — The task doesn't need the user to clarify, confirm, or choose

**When all pending tasks fail the actionability filter:** Pick the highest-priority task that CAN be executed (even if low-priority), execute it as a monitoring/validation check, and mark it done with a resolution note. Report that higher-priority tasks are blocked pending user input. This is preferable to returning "no tasks" — at minimum, validate system health signals.

**When a task becomes actionable later** (e.g., Ever Solano replies, Jared provides input), finch:scan will create a new task or re-activate the existing one. The blocked status is not permanent — it's a reflection of current actionability, not importance.

#### Cascading dependency awareness (confirmed 2026-06-29)

When a critical infrastructure dependency fails, it blocks MANY tasks simultaneously — not just the task that names the failure. Before iterating through each pending task individually, check for cascading blockers:

1. **Identify infrastructure-level blockers first** — If any `critical` task names an infrastructure failure (OAuth revoked, disk full, gateway down, provider outage), assume ALL tasks depending on that infrastructure are blocked until it's resolved.
2. **Map the dependency graph mentally** — OAuth revocation blocks: email tasks, calendar tasks, Drive tasks, Takeout tasks, any task requiring Gmail API. Provider outages block: all LLM-dependent tasks. Disk full blocks: all write operations.
3. **Skip the blocked bulk** — Don't waste time evaluating each email task individually when OAuth is known-dead. Skip the entire dependency cluster in one decision.
4. **Find the first non-dependent task** — Look for tasks that don't depend on the broken infrastructure: cron health monitoring (uses `hermes cron list`, not Gmail), disk checks (`df -h`), system stats, web lookups, non-Google API calls.
5. **Execute the first actionable task** — Even if it's low-priority, a monitoring check that produces a useful signal (e.g., "provider errors recovered") is better than returning "no tasks."

**Confirmed 2026-06-29 (this session):** OAuth revoked (task_019) blocked 6+ email/Gmail tasks simultaneously (task_004, task_005, task_006, task_021, task_012, plus the OAuth task itself). Rather than evaluating each one, the correct move was to recognize the cascade, skip the entire cluster, and pick task_014 (cron provider error monitoring) which only needed `hermes cron list` — no Gmail dependency. **Total impact**: 8/140 cron jobs failed from one OAuth revocation event.

**Key insight:** The actionability filter's 4 conditions are per-task checks. Cascading dependency awareness is a pre-filter that eliminates entire clusters before per-task evaluation. It saves 5-10 tool calls per blocked cluster.

### Pipeline task resumption (ledger/state-based)

When an `in_progress` task involves a data pipeline that uses an idempotency ledger or state file (e.g., Chronicle ingest ledger, corpus processing), the original background process may have died while the pipeline was partially complete. Do NOT re-run from scratch — the ledger tracks completed windows.

**Resumption pattern:**
1. **Verify the process is dead** — `ps -p <PID>` or `ps aux | grep <script_name>`. Confirm the process is actually terminated, not still running silently.
2. **Check the ledger/state** — Read the pipeline's idempotency ledger (SQLite, JSONL, or similar) to determine which work units are already complete.
3. **Compare ledger to source data** — Identify which work units (months, files, batches) from the source data are NOT yet in the ledger.
4. **Run without limits** — The pipeline's ledger-based dedup will skip already-complete units automatically. Running `run_ingest.py --source X --file Y --apply` without `--limit` is safe — it processes only what's missing.
5. **Update task to done** — Once the ledger shows all units processed, mark the task `done` with a resolution noting the final completion timestamp.

**Confirmed 2026-06-29 (task_023):** Background PID 1663225 (Timeline ingest) was dead. Ledger showed 8/10 months complete (through 2026-04). Source data had 10 months (2025-09 through 2026-06). Ran `run_ingest.py --source timeline --file location-history.json --apply` without `--limit` — ledger correctly skipped the 8 completed months, processed 2026-05 and 2026-06 (2 documents written at 07:33Z). Task marked done.

**Key insight:** Pipeline tasks with idempotency ledgers are ALWAYS resumable. The `--limit N` parameter is only needed for initial testing. Once confirmed working, subsequent runs should omit `--limit` so the ledger handles dedup.

2. **Work** (`finch:work`, every 30 min) — Pick top pending task. Load governing skill via `skill_view`. Execute ONE task per run. Before selecting, check for duplicate task IDs and clean up if found (see `references/duplicate-task-detection.md`). Route findings to MEMORY.md, skill patches, or reference files.
2a. **Sessions scan — correct pattern**: When scanning recent sessions in finch:scan, call `session_search(limit=10, sort='newest')` WITHOUT `query` (FTS5 treats query as literal text, not a time filter — `query="last 24h"` matches sessions containing those words, not recent sessions). Manually check result timestamps. For finch:daily/weekly mining, follow the cron-skew filtering procedure in SKILL.md § "Session source filtering".
3. **Mine** (`finch:daily` / `finch:weekly`) — Process session JSONL files for signals: corrections, directives (Always/Never), course changes, breakthroughs, methodologies, stop signals. See `references/mining_methodology.md` for the full methodology.
4. **Route** — Direct each finding to the optimal storage tier: MEMORY.md (Tier 1: corrections, directives), skill SKILL.md/references/ (Tier 2: tool-usage, service gotchas), reference files (Tier 3: guides, paths, URLs), or Chronicle KG (Tier 4: entity facts). See `references/file-governance.md` for routing criteria and the tier model.
5. **Journal** — Every run emits Action Journal + DecisionRecord to `decisions.jsonl`.

### Failure-phase taxonomy (from arxiv:2508.13143)

When mining corrections and failures, categorize each by the task phase where the failure occurred. This taxonomy enables targeted skill patches instead of vague "be more careful" updates:

| Phase | Description | Example signal |
|-------|-------------|----------------|
| **Planning** | Wrong approach chosen, incorrect assumptions, missing prerequisites | "You should have checked X first" |
| **Execution** | Right plan but tool call/API/step failed, wrong parameters, timeout | "The command failed because..." |
| **Response** | Correct result but wrong format, verbosity, tone, or framing | "Too verbose" / "Wrong format" |

Route planning-phase corrections to skill preconditions/setup sections. Route execution-phase corrections to tool-usage/gotchas sections. Route response-phase corrections to output-formatting sections. This produces surgical patches instead of blanket directives.

### Elaborative interrogation (from Dunlosky et al. 2013)

When recording a correction or lesson, don't just capture WHAT was wrong — extract the underlying principle by asking "why" and "when":

- **Why was this wrong?** — What assumption was violated? What constraint was unknown?
- **When does this apply?** — What contexts trigger this pattern? What's the boundary condition?
- **What's the causal mechanism?** — Why does the correct approach work?

Format: `[CORRECTION] What: <what was wrong>. Why: <underlying principle>. When: <applicable context>`

This produces lessons that transfer across contexts, not just single-instance fixes.

### Signal triage before execution (WORK step)

A task on the list may aggregate multiple distinct failure modes under one title (e.g., "cron 429 errors" that actually mix transient rate limits, script timeouts, and path blocks). Before committing to a fix:

1. **Decompose the task** — List the distinct error signatures from logs/jobs.json. Group by root cause, not by symptom label.
2. **Classify each group** — Transient (will self-resolve), persistent (needs intervention), or already-fixed (mitigation in place).
3. **Handle each group appropriately** — Transient groups get "monitoring" with a 24h recheck. Persistent groups get fixes. Already-fixed groups get a note that the Tier 1 was already applied.
4. **Journal the decomposition** — Record the group counts so the next finch:scan can check recovery per group, not just per task.

Do NOT assume a task with N affected jobs has one root cause. The task title is a scan heuristic, not a diagnosis.

#### Already-fixed verification (resumed investigations)

When a task asks to "resume" or "complete" an interrupted investigation (e.g., "Session identified systemic issues but did not complete fixes"), do NOT assume the fixes are missing. The prior session may have produced findings that were already implemented, or the features may have existed under different names.

**Procedure:** Read the actual code at the relevant file:line locations. Map each claimed-missing feature to a function/class. Check for detection → classification → response → guard completeness. Run existing tests for those features. If all checks pass, mark the task `done` with specific file:line references and test counts as evidence. See `references/already-fixed-verification.md` for the full procedure and an example. For CI-failure tasks on a repo PR/branch, also consult `references/gh-ci-stale-run-verification.md` — a failing run is point-in-time and may already be superseded by a green run on the same head SHA.

#### All-transient resolution (no fix needed)

When investigation reveals that ALL errors in a task are transient (provider errors with `consecutive_failures: 0`, missing-module errors where the package is actually installed, interpreter-shutdown errors), the correct action is:

1. **Verify** — Read `jobs.json`, check `last_status`, `last_error`, `consecutive_failures` for each affected job. Do NOT trust the task description alone.
2. **Mark task done** — Set `status: "done"`, add `resolved` timestamp, write `outcome` explaining what was checked and why no fix is needed.
3. **Downgrade priority if misclassified** — If a task was marked HIGH for interpreter-shutdown or provider errors, downgrade to LOW per the error taxonomy.
4. **Journal** — Record the resolution so finch:scan doesn't re-create the task on next scan.

**Confirmed 2026-06-28:** task_019 (provider errors + missing-module) — all jobs showed `consecutive_failures: 0` and `last_status: ok`. googleapiclient was already installed. No intervention required. task_014 (interpreter-shutdown) — also transient, downgraded HIGH→LOW.

MEMORY.md entries decay without reinforcement. During compaction:

1. **Reinforcement check**: For each existing entry, check if it was reinforced (re-encountered or re-applied) since last compaction. Entries reinforced within their expected half-life get a `§` durability marker.
2. **Concept classification**: Classify each entry by storage tier (see `references/forgetting_curve.md` § Storage Tier Model). Is this entry in the right tier?
3. **Tier routing**: Entries in the wrong tier get moved — tool-usage facts to skills (Tier 2), reference details to reference files (Tier 3), entity facts to Chronicle (Tier 4). Only evict if truly stale.
4. **Decay candidates**: Entries not reinforced in 3+ compaction cycles that cannot be routed to another tier are candidates for eviction.
5. **Priority for retention** (Tier 1 only): Directives (Always/Never) > Corrections with causal grounding > Bare corrections > Breakthroughs > Methodologies > Pointers to Tier 2/3 knowledge
6. **Consolidation**: Merge entries that share the same underlying principle into a single entry with multiple contexts. Within-tier only.

See `references/forgetting_curve.md` for the full compaction algorithm including the tier routing procedure.

See `references/scan-work-architecture.md` for signal source details and governance rules.

## Manual run & verification (when the user says "run finch")

"Run finch" means verify ALL deployed finch cron jobs are healthy and (optionally) force a run. The deployed job set (2026-07-07) is **FIVE jobs**, not the four in the design doc:

- **`finch`** — profile-root MEMORY.md compaction (runs `memory_guard.py` on the DEFAULT profile's MEMORY.md — NOT the indigo profile's; guard the `--file` override or it compacts the wrong memory).
- **`finch:floor`** — `no_agent` script safety floor (memory guard). Normally `enabled: false` but self-triggers; do NOT treat its disabled state as broken.
- **`finch:scan`** — every 2h, pure LLM.
- **`ocas-finch:daily`** — daily 6am PT, pure LLM.
- **`ocas-finch:weekly`** — Sunday 8am PT, pure LLM.

(NOTE: the design doc lists `finch:work` every 30min — that job was NOT present in deployment on 2026-07-07. Work execution is covered by the interactive `finch.work` command / `finch:scan`-driven task list, not a separate cron. Verify with `cronjob list` before assuming job names, since they drift.)

### Forcing an immediate run
`cronjob action='run'` does NOT force a scheduled **LLM** job to execute — it only bumps `next_run_at` to the next NATURAL tick (the job fires on its normal schedule, not immediately). To force execution NOW: **PAUSE the job first (`action='pause'`), then `run` (`action='run'`)** — the paused state triggers forced execution. `no_agent`/script jobs (e.g. `finch`, `finch:floor`) run on a plain `run` without pausing. After a forced run succeeds, the job returns to `state: scheduled` automatically.

**Verification gate:** A queued immediate run is not a completed run. After every manual trigger, re-read `jobs.json`/`cronjob list` and verify `last_run_at` advanced to the current run window and `last_status` is current. If `next_run_at` is in the past but `last_run_at` did not advance after a tick, report the job as **queued/not yet executed**, not completed. For `finch.scan`, `finch.work`, `daily`, and `weekly`, run deterministic sub-functions directly where available (for example `self_update.py`, `memory_guard.py`, task-list inspection, journal write) and distinguish those completed direct actions from still-queued LLM cron jobs.

### Mass 401 across finch (and other) jobs
If multiple finch jobs error with `401`, first classify WHICH 401 it is before acting:

- **MCP-auth 401** (dead `[mcp_servers]` token): the cause is a **stale `[mcp_servers]` block in the profile `.env`** (`/root/.hermes/profiles/<p>/.env`) shipping an invalid/expired token (e.g. a dead Discord token) that breaks ALL MCP calls. Fix: remove the `[mcp_servers]` section; the client falls back to valid config and MCP works.
- **Provider-auth 401** (LLM provider token): the run output shows `RuntimeError: Error code: 401` with `token_expired` ("Provided authentication token is expired") or `"Your API key is invalid, blocked or out of funds"` from `portal.nousresearch.com`. This is NOT the `[mcp_servers]` block. Confirmed 2026-07-12: finch jobs 401'd with Nous `token_expired`; `grep mcp_servers` on the indigo `.env` returned nothing; the gateway was holding a stale provider credential. **Fix: restart the gateway** (kill the `--profile indigo gateway run` process and let it respawn, or `hermes gateway run`) so it reloads the current valid provider token. After restart, post-restart runs (`finch:scan`, `finch:memory-guard-floor`) returned `ok`.

Diagnostic steps: (1) Read the actual run output / `jobs.json` `last_error` — `cronjob list` may display `last_error: None` even when jobs.json holds the 401, so don't trust the list's None. (2) `grep -n "mcp_servers" /root/.hermes/profiles/<p>/.env` — if absent, it's provider-auth, not MCP-auth. (3) If interactive sessions on the same `provider`/`model` work but cron 401s, the scheduler is holding a stale token → restart the gateway.

See `cron-job-repair` for the model-routing 401 vs MCP-auth 401 distinction.

### Autonomy — take the action without being prompted
When a finch job (or any cron job) is failing and the fix is clear, DO NOT ask "continue?" or wait for the user to "say the word." Apply the fix, run all affected jobs, then report results in one message. The user explicitly requires the agent to take the needed action without prompting (stated 2026-07-07: "I shouldn't have to 'say the word' you should just take action that needs to be taken").

## Commands

- `finch.run` — Full daily pipeline
- `finch.mine` — Mine sessions for signals only
- `finch.compact` — Compact MEMORY.md only
- `finch.route` — Route mined findings
- `finch.dry-run` — Full pipeline without applying changes
- `finch.status` — Show recent stats
- `finch.scan` — Run scan manually
- `finch.work` — Run work manually

## Scheduled tasks

| Job | Frequency | Behavior |
|-----|-----------|----------|
| **finch:scan** | Every 2h | Scan 7 sources → maintain task list |
| **finch:work** | Every 30 min | Pick top item → execute. ONE task per run. |
| **finch:daily** | Daily 6am PT | Mine 24h → Compact → Route → Auto-apply low-risk |
| **finch:weekly** | Sunday 8am PT | Mine 7d → Compact → Route → Full plan |

## Recovery Behavior

This section defines error handling and recovery procedures for all finch jobs.

- **Evidence**: Every run writes to `evidence.jsonl` (including no-op runs with `not_activity_reason`).
- **Gap detection**: On every wake, checks evidence log. If gap exceeds expected cadence (2h for scan, 30min for work), logs `gap_detected` and runs compact remedial pass.
- **Degraded mode**: When behavioral signals unavailable from Chronicle, continues with available inputs. When session store unavailable, logs `degraded: session_store` and skips mining.
- **Log compaction**: Evidence/decision logs older than 30 days (no-op) or 90 days (error/gap) compacted. Last 7 days retained.

## OKRs

See `references/okrs.md` for targets (schedule adherence, data integrity).

|-----|--------|--------|
| `schedule_adherence` | ≥ 0.98 | 30 runs |
| `data_integrity` | 1.00 | 30 runs |

## Anti-patterns

See `references/anti-patterns.md` for the full list of 10 anti-patterns including declaration of victory and code fence pitfalls.

## Active review principle

See `references/active-review.md` for the full principle.

## Skill Library Maintenance

After every session, review the conversation for signals and update the skill library. See `references/skill-library-maintenance.md` for the full procedure including signals that warrant action, preference order for updates, and what NOT to capture.

**Skill integration hygiene (confirmed 2026-07-14):** When adding external/upstream skills to the local library, prefer integrating relevant LEARNINGS into the closest existing skill rather than installing a new conflicting skill. For upstream skill repos Jared shares: (1) determine if any capability overlaps an existing skill; (2) if yes, merge the valuable parts into that skill (including code-review patterns Jared may say were "skipped"); (3) only install a new skill if it has no close match and won't conflict. Jared: "Would any of these skills be useful in KODA skill library, if so integrate them into the closest match don't install new skills that may conflict" and "You should integrate what makes sense in code review as well. The ones you skipped."

## Gotchas

See `references/pitfalls.md` for the full consolidated pitfalls list.

### `memory` tool may be unavailable in cron

If the `memory` tool returns unavailable during finch daily/compact runs, do not stop after reporting failure. Use the canonical profile memory path (`/root/.hermes/profiles/indigo/memories/MEMORY.md`) and perform the same operation by direct file edit, preserving the compaction cap and directive priority ordering. Treat direct writes as a fallback for cron execution only; re-read before writing if any sibling-write warning appears.

### MEMORY.md must not contain pointers to routed content

After tier routing, MEMORY.md should contain **only Tier 1 knowledge** — behavioral directives, cross-cutting corrections, and critical operating constraints. Do NOT add pointers like "see skill/references/X.md" for routed entries. Pointers add noise without value. If a session needs Tier 2/3/4 knowledge, it loads the skill or reads the reference directly. MEMORY.md is not a directory of everything the agent knows.

**Symptom of violation:** MEMORY.md grows back to 2,000+ chars after compaction because pointers were added for every routed entry.
**Fix:** Remove all pointers. MEMORY.md should be under 500 chars for a well-compacted library.

### Directive consolidation pattern

When two directives share the same underlying principle, merge them into one entry with combined provenance. This reduces MEMORY.md bloat and strengthens the surviving entry by showing it was reinforced across multiple sessions.

**Example from 2026-06-21:**
- "NEVER assume MCP broken without testing — verify first" (Jun 12)
- "NEVER state a wrong diagnosis with certainty — test simplest hypothesis first" (Jun 20)
- → Merged: "NEVER state a wrong diagnosis with certainty — test simplest hypothesis first. Verify before concluding." (Jun 12, Jun 20)

**Rule:** When merging, keep the more specific/vivid phrasing and list both dates. The merged entry is stronger because it was reinforced across sessions.

### FTS5 minimum token length

When mining sessions via `session_search` with `query=`, FTS5 silently drops tokens shorter than its minimum length (typically 3-4 characters). This means short-form correction signals are **invisible** to FTS5 queries:

- `"No"` (2 chars) → **dropped entirely**
- `"Don't"` → tokenized as `"don"` + `"t"`, both **dropped**
- `"Stop"` (4 chars) — borderline, may or may not match depending on tokenizer

**What to do:** When mining for corrections, always use `session_search` WITHOUT `query` (browse mode, no FTS5 filter) and read user messages directly. Use `role_filter=user` to narrow to user messages and scan for short-form corrections visually. Only use `query=` for multi-word terms (≥3 chars each) like `"actually wrong"` or `"don't do that"` where at least one token survives.

This applies to all finch jobs that mine sessions: finch:daily, finch:weekly, and manual finch.mine runs.

### Session source filtering — cron-skew problem

When `session_search` is called without a source filter, the results are overwhelmingly cron sessions (health monitors, heartbeats, dispatcher runs). These contain **zero** user-facing behavioral signals. Interactive sessions (where corrections, directives, and preferences live) are a small fraction of total sessions.

**Mining procedure — ALWAYS do this:**
1. First call: `session_search(limit=20, sort='newest')` — identify which sessions are interactive (source=telegram/web/cli) vs cron.
2. Pull actual user messages with direct SQL, not `session_search` scroll. Use `sqlite3 /root/.hermes/profiles/indigo/state.db` and join `sessions` to `messages`, filtering `s.source!='cron'`, `m.role='user'`, and the desired `started_at` window. Scroll mode is unreliable because message IDs are global, not session-local.
3. Filter out context compaction, system notes, tool results, and messages shorter than 3 chars before signal extraction.
4. Only mine cron sessions for system-health signals (job failures, errors), never for behavioral signals.
5. **Query-based fallback when browse shows zero interactive sessions:** Browse mode returns at most 20 sessions, which can all be cron if the window is busy even when interactive sessions exist. If step 1 shows no interactive sessions, run targeted queries before concluding: `query="That's wrong"`, `query="No,"`, `query="Don't"`, `query="Actually"`, `query=YYYY-MM-DD` for each day in the mining window. Interactive sessions have user messages containing natural-language corrections that don't appear in cron prompts. Only report "no interactive sessions" after all keyword queries return zero non-cron results.
6. If no interactive sessions exist in the mining window, report "no interactive sessions — nothing to mine" rather than mining cron noise

**Confirmed pattern:** As of June 2026, a typical 24h window contains 50+ cron sessions and 0-3 interactive sessions. Mining without source filtering wastes the entire pass on cron noise.

### Skill usage analytics — state.db mining

For mining skill usage data from state.db (not behavioral signals), the opposite is true — cron sessions ARE the signal. See `util-skill-analytics` skill for the full procedure. Key differences:
- Use `JOIN sessions s ON m.session_id = s.id` (not `session_id`)
- `PRAGMA busy_timeout=30000` (gateway locks the DB)
- Parse `tool_calls` JSON in Python (LIKE is a full table scan)
- Filter by `source != 'cron'` for interactive-only analysis

### HERMES_HOME path resolution in scripts

When writing Python scripts that reference MEMORY.md or commons directories, never hardcode `~/.hermes/MEMORY.md`. The `HERMES_HOME` env var may point to either `~/.hermes` or `~/.hermes/profiles/<name>`. Use this pattern:

```python
HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
_HERMES_PROFILE = os.getenv("HERMES_PROFILE", "indigo")
# Handle three cases: (1) HERMES_HOME already IS the profile dir, (2) standard layout with profiles/ subdir, (3) fallback
if HERMES_HOME.name == _HERMES_PROFILE and (HERMES_HOME / "MEMORY.md").exists():
    PROFILE_HOME = HERMES_HOME
elif HERMES_HOME.name != "profiles" and (HERMES_HOME / "profiles" / _HERMES_PROFILE).is_dir():
    PROFILE_HOME = HERMES_HOME / "profiles" / _HERMES_PROFILE
else:
    PROFILE_HOME = HERMES_HOME
MEMORY_FILE = PROFILE_HOME / "MEMORY.md"
```

**Gotcha**: The old two-branch logic (`name != "profiles"`) fails when `HERMES_HOME` is already the profile directory (name is e.g. `"indigo"`, not `"profiles"`), causing double-nesting to `profiles/indigo/profiles/indigo/MEMORY.md`. Fixed in `scripts/memory_guard.py` as of 2026-06-21 — the script now uses three-branch logic: (1) detect if HERMES_HOME already IS the profile dir by checking `name == _HERMES_PROFILE && MEMORY.md.exists()`, (2) standard `profiles/` subdir layout, (3) fallback to HERMES_HOME directly.

### Two evals.json files must be kept in sync

There are two `evals.json` files: `evals.json` (root) and `evals/evals.json` (subdirectory). Both must be updated when adding/removing test cases. The root one is the canonical reference.

## Support File Map

| File | When to read |
|------|-------------|
| `references/active-review.md` | Before scanning for signals |
| `references/signal_patterns.md` | Before mining sessions |
| `references/mining_methodology.md` | Before first mining run |
| `references/scan-work-architecture.md` | Before configuring scan/work jobs |
| `references/skill-library-maintenance.md` | After any session that produces a learning |
| `references/skill-update-directive.md` | During end-of-session skill review |
| `references/cleanup-and-health.md` | During system health audits |
| `references/session-2026-05-31-disk-recovery.md` | When investigating disk-full → MCP auth cascades, parallel tool batch poisoning, or emergency cleanup patterns |
| `references/external-skill-overlap-map.md` | Before creating evaluation skills |
| `references/git-skill-push-pattern.md` | When pushing skill changes to GitHub |
| `references/pitfalls.md` | Before any finch operation |
| `references/anti-patterns.md` | Before any finch operation — 10 anti-patterns including declaration of victory and code fence pitfalls |
| `references/okrs.md` | During OKR evaluation |
| `references/storage-layout.md` | When inspecting data directories or skill package structure |
|| `references/forgetting_curve.md` | During MEMORY.md compaction — reinforcement scan, tier routing, consolidation, eviction ||
|| `references/file-governance.md` | Before routing findings — write targets, tier model, off-limits files, creation criteria ||
|| `references/signal-triage-before-fix.md` | Before executing any finch:work task — decompose multi-failure tasks into distinct root causes ||
|| `references/already-fixed-verification.md` | When finch:work asks to "resume" or "complete" an interrupted investigation — verify whether the code already implements the requested fixes before writing new code ||
|| `references/gh-ci-stale-run-verification.md` | When finch:work picks a repo-CI-failure task — verify the failing run wasn't superseded by a green run on the same head SHA before opening a fix ||
|| `references/email-task-draft-workflow.md` | When finch:work picks an email task requiring contact with a third party not in the thread — full draft workflow (fetch thread → find contact → draft → save → mark done) ||| `references/email-thread-verification.md` | When finch:work picks an email "track response" task — search + fetch thread → check last sender → determine if substantive reply received → update note field. Includes `google_auth.py` fallback for when MCP Gmail tools are unavailable in cron context. ||| `references/gmail-token-expired-draft-workflow.md` | When finch:work picks an email task but Gmail API token is expired/unavailable — cached data search, local draft creation in drafts.jsonl, task-list update pattern for degraded mode. ||
|| `references/oauth-failure-cron-diagnostic.md` | When finch:work picks an OAuth failure task in cron context — diagnostic flow (token expired vs. revoked vs. malformed), auth URL generation for reporting, task-list update pattern for `blocked` status. Distinguishes "auto-refreshing" from "needs re-auth" from "never authed". ||
|| `references/systemic-oauth-failure-detection.md` | When 4+ cron jobs fail simultaneously with HTTP 400 on oauth2.googleapis.com/token — systemic revocation pattern, fingerprint, affected jobs list, correct response (one task, not N). Confirmed 2026-06-29. ||| `references/disk-monitoring-pattern.md` | When a finch:work task involves disk usage investigation — cascade from `df -h` down to specific large files, with known consumers table and cleanup commands ||
|| `references/custodian-error-investigation.md` | When a finch:work task involves a custodian error (e.g., custodian:deep Broken pipe) — investigation pattern for journal files and issues.jsonl ||
|| `references/composio-cron-tool-pattern.md` | When finch:scan needs email/calendar/drive data in cron context — how to call Google APIs via COMPOSIO_SEARCH_TOOLS + COMPOSIO_MULTI_EXECUTE_TOOL |
|| `references/scan-error-classification.md` | During finch:scan when grouping errored cron jobs by root cause fingerprint (certifi, missing-script, missing-module, rate-limit, interpreter-shutdown, provider-error, provider-http400) ||
|| `references/runaway-process-pattern.md` | When finch:scan detects a process consuming >50% CPU for >5 min — diagnosis, decision tree, and resolution for stuck background processes from kanban tasks ||
|| `references/email-mcp-pagination-parsing.md` | When finch:scan fetches Gmail via MCP — paginate to completion (page_token loop), batch-fetch content, and parse the JSON-escaped saved result file ||
|| `references/session-20260629-finch-work-cascade-skip.md` | When finch:work faces multiple pending tasks and a critical infrastructure failure (OAuth, disk, provider) — skip the entire dependent cluster without per-task evaluation |
|| `references/duplicate-task-detection.md` | When reading task-list.json in finch:work — detect and clean up duplicate task IDs |
|| `references/session-20260630-scan12-mcp-unreachable.md` | When finch:scan cannot access email/calendar/drive MCP tools in cron context — confirms MCP is LLM-session-only, no CLI workaround, cached-data fallback required. Also covers kanban board systemic failure patterns and gateway RSS growth tracking. || `references/stale-cron-task-detection.md` | When finch:work picks a task referencing cron jobs — verify jobs still exist before attempting fixes ||
|| `references/patch-json-tool-behavior.md` | When using `patch` on JSON files — escape-drift errors, non-blocking pagination warnings, recommended patterns for cron context ||
|| `references/cron-json-edit-pattern.md` | Cron-scope JSON edits without execute_code — patch-lint-doesn't-block, trailing-comma/backslash corruption, validate-after-edit, batch-probe rule for untrusted MCP tools ||
|| `references/signal-types-table.md` | Before mining — signal type definitions and routing ||
|| `references/interactive-menu.md` | When invoked interactively via `/` command — two-level menu layout, Clarify timeout, response parsing, platform adaptation |
|| `scripts/memory_guard.py` | Deterministic safety floor for MEMORY.md — hard cap enforcement, directive protection, pointer stripping, atomic locked write. Run as final step of finch.compact or via finch:memory-guard-floor cron. ||
|| `scripts/memory_state.py` | Persisted reinforcement-state store — entry-key -> {reinforcement_count, last_reinforced_at, half_life, tier}. Use `reinforce`, `check`, `route`, `decay-report` subcommands. ||

## Scripts

### memory_guard.py eviction priority — Methodologies outrank Course Changes

The memory guard's `LOW_PRIORITY_REFILE` regex and eviction sort order can evict Methodologies entries while keeping bare Course Changes entries. This is wrong — Methodologies (actionable techniques) are higher value than Course Changes (historical pivots).

**Symptom:** After guard runs, Methodologies section is empty but Course Changes still has entries.
**Confirmed:** 2026-06-21 — guard evicted "Root-cause-first debugging" (Methodologies) while keeping "Seamless task-switching" and "Budget exhaustion" (Course Changes).

**Mandatory post-guard verification (Step 7.5):**
After every guard run, BEFORE writing the final MEMORY.md:
1. Check if any Methodologies entries were evicted
2. If yes: restore the highest-value Methodologies entries by consolidating or removing Course Changes entries to make room
3. Never leave MEMORY.md with Course Changes intact but Methodologies empty — this inverts the priority ordering

**Fix needed in guard:** The guard's eviction sort should rank: Directives > Corrections > Methodologies > Course Changes > Pointers. Currently Methodologies and Course Changes are both in the "non-directive" bucket with no differentiation. Until the guard is fixed, the manual Step 7.5 workaround is MANDATORY.

```bash
# Dry-run report
python3 scripts/memory_guard.py

# Enforce + safe-write
python3 scripts/memory_guard.py --apply --emit-decision

# JSON output
python3 scripts/memory_guard.py --json
```

Run as Step 7 of `finch.compact` or independently via `finch:memory-guard-floor` cron (every 6h).

### self_update.py / self_update.sh

`self_update.py` must be a real Python wrapper (not a bash script with a `.py` extension) and must resolve the skill directory from `Path(__file__).resolve().parents[1]`, never from a hardcoded default-profile path like `/root/.hermes/skills/ocas-finch`. Manual Finch runs should execute `python3 scripts/self_update.py` and require exit 0 before reporting update health. `self_update.sh` is the GitHub-version fetch/install path; if it exits 1 with no output, inspect the `gh api`/remote-version step rather than treating Finch as generally broken.

### memory_state.py

Persisted reinforcement-state store. Computes Ebbinghaus forgetting curve across runs.

```bash
# Record a reinforcement
python3 scripts/memory_state.py reinforce "entry text" --tier 1

# Check decay status
python3 scripts/memory_state.py check "entry text"

# Transactional tier-routing (verify dest before removing from MEMORY.md)
python3 scripts/memory_state.py route "entry text" --to-tier 2 --dest-path path/to/skill/references/foo.md

# Full decay report (decaying entries first)
python3 scripts/memory_state.py decay-report
```

State stored at `commons/data/ocas-finch/memory_state.json`.

## Self-update

`finch.update` pulls the latest from GitHub. Runs silently unless version changed or error.

## Platform notes

Finch is designed for Hermes but degrades gracefully on other harnesses. Minimum viable platform: any harness with `write_file`, `read_file`, and `terminal` tools.