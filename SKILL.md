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
  hermes:
    category: software-development
    tags:
    - self-improvement
    - session-mining
    - behavioral-adaptation
    - OCAS-core
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
- Memory at/near capacity (`memory` tool refuses edits, ~79%+ warning threshold): **RUN `finch.compact` / `memory_guard.py` — do NOT hand-edit MEMORY.md to dodge the cap.** Manual memory surgery (condensing entries into one giant block, dropping context to fit) is exactly the work Finch owns, and doing it by hand produces bloat (a single ~1,900-char entry where tier-routing would have moved procedure out to a skill/reference). The user's correction (2026-07-15): "Why are you manually cleaning up memory? You have Finch for that." If the `memory` tool refuses an edit at capacity, hand it to Finch (force `ocas-finch:daily` or run `memory_guard.py --file /root/.hermes/profiles/indigo/memories/MEMORY.md`); do not fight the limit with manual `memory` writes. Finch owns compaction; this is the procedure, not "there is no skill."
- Skill library maintenance: route findings to SKILL.md patches

## When NOT to Use

- Real-time behavioral adaptation (Chronicle handles pattern detection)
- Skill evaluation scoring (Mentor handles OKR evaluation)
- Skill creation/architecting (Forge handles skill building)
- Entity identity resolution (Chronicle tools handle direct writes)

## Storage

See `references/storage-layout.md` for the full directory tree and skill package structure.

## Scanning Gotchas

The full operational detail for each item below lives in `references/scanning-gotchas.md` (one-line pointers, full bodies there):

- Verify tool availability before parallel batches (one bad tool name poisons the whole batch)
- MCP tools reachable in cron via Composio (`COMPOSIO_MULTI_EXECUTE_TOOL`); attempt Calendar/Drive first, skip only on connection failure
- `tool_search` ≠ `tool_call` availability — probe a suspect MCP tool alone before batching; MCP load state is intermittent between runs
- Direct MCP credential-store fallback (`/root/.google_workspace_mcp/credentials/<email>.json`) when dispatch rejects + legacy token is `deleted_client`
- Stale errors from `hermes cron list` — verify `Last run:` timestamp; `consecutive_failures` is the only reliable error gate
- Re-verify prior completions/STATES against LIVE signal bidirectionally (re-open on relapse, resolve on live recovery)
- MCP Google Workspace param is `page_size`, not `limit`/`max_results` — always `tool_describe` first
- Email scan MUST paginate to completion (`page_token` loop) — page-1-only misses high-value items
- Sessions scan date-string workaround (`query="YYYY-MM-DD"`); mine interactive messages via direct `state.db` SQL, not session_search scroll
- Only report actual fixes, never stale/transient issues; interpreter-shutdown errors are always transient
- Never force model overrides on cron jobs; maintain skill index; push local changes to GitHub immediately (user directive)
- Disk-before-auth diagnostic (`df -h /` before OAuth); `execute_code` blocked in indigo cron profile — use `terminal` python3
- Concurrent-write hazards on task-list.json / MEMORY.md — re-read before write on sibling-modify warning
- `read_file` view of a JSON file is NOT validation — it can display trailing-comma corruption as valid and misreport size; only `json.load()` catches it. Validate-after-edit with `terminal python3 -c "import json; json.load(open(...))"` (execute_code is blocked in indigo cron).
- `jobs.json` for cron health when `cronjob` tool unavailable; `hermes cron list` hides disabled jobs
- Provider HTTP 400 is MEDIUM (not transient) — classify by status; missing-script errors need path verification not debugging
- finch:scan is NOT a task executor; read_file tilde-expansion path doubling; `jobs.json` schedule fields are dicts not strings
- Gateway RSS growth tracking (3x = notable, >2GB = escalate)

See `references/scan-error-classification.md` for the full error taxonomy.



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

When running as a cron job with no user present, **filter for autonomous actionability** before applying the priority selection. A task is autonomously actionable if it passes ALL of:

- [ ] **No external response required** — doesn't depend on someone else replying (e.g., "track response from X" is NOT actionable; "check if X responded" IS actionable as a monitoring check)
- [ ] **No business decision required** — doesn't require accepting/declining engagements, making commitments, or choosing between options with capital implications (e.g., "respond to consulting inquiry — accept or decline" is NOT actionable)
- [ ] **No authentication required** — doesn't need app login, OAuth, or credentials the agent doesn't have (e.g., "check One Medical app" is NOT actionable)
- [ ] **No user input required** — doesn't need the user to clarify, confirm, or choose

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

## Gotchas (verbose bodies in `references/operational-gotchas.md`)

- `memory` tool may be unavailable in cron — fall back to direct file edit at the canonical profile memory path; re-read before write on sibling-warning
- MEMORY.md must contain only Tier 1 knowledge — no pointers to routed content; under 500 chars when well-compacted
- Directive consolidation — merge two directives sharing a principle, keep specific phrasing, list both dates
- FTS5 minimum token length (3-4 chars) drops short corrections (`No`, `Don't`) — mine without `query=`, use `role_filter=user`, scan visually
- Session source filtering — cron sessions drown interactive ones; identify interactive first, pull user messages via direct `state.db` SQL, fallback to keyword queries before declaring "no interactive sessions"
- Skill usage analytics — cron sessions ARE the signal for state.db mining (opposite of behavioral mining); use JOIN + busy_timeout + Python JSON parse
- HERMES_HOME path resolution — three-branch logic, never hardcode `~/.hermes/MEMORY.md`; old two-branch double-nests
- Two evals.json files (root + evals/) must stay in sync; root is canonical

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
|| `references/email-mcp-pagination-parsing.md` | When finch:scan fetches Gmail via MCP — paginate to completion (page_token loop), pre-filter automated noise with `-from:()` before content fetch, strip residual batch to From/Subject/Date in terminal (avoid context flood; do NOT double-decode unicode_escape), and use `from:<addr> newer_than:Nd=0` as a "no reply" proof ||
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

Full detail (eviction priority, self_update wrapper contract, memory_state subcommands) in `references/operational-gotchas.md` § Scripts:

- `memory_guard.py` — deterministic MEMORY.md safety floor; mandatory post-guard Step 7.5 verification (Methodologies must outrank Course Changes in eviction)
- `self_update.py` / `self_update.sh` — real Python wrapper resolving skill dir from `Path(__file__).resolve().parents[1]`; `self_update.sh` is the GitHub fetch/install path
- `memory_state.py` — persisted reinforcement-state store (Ebbinghaus forgetting curve); `reinforce` / `check` / `route` / `decay-report` subcommands

## Self-update

`finch.update` pulls the latest from GitHub. Runs silently unless version changed or error.

## Platform notes

Finch is designed for Hermes but degrades gracefully on other harnesses. Minimum viable platform: any harness with `write_file`, `read_file`, and `terminal` tools.