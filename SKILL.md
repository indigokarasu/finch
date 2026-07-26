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
  author: <profile> Karasu (indigokarasu)
  version: 3.1.0
  hermes:
    category: software-development
    tags:
    - self-improvement
    - session-mining
    - behavioral-adaptation
    - OCAS-core
name: ocas-finch
source: https://github.com/<agent-handle>/finch
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

> **PUBLIC REPO — GENERICISE EVERY REFERENCE.** This skill is published publicly.
> Reference files are distilled from real runs, so never write a real name, email,
> employer, thread id, task id, phone number, token or home path into one — use the
> placeholders in `references/reference-file-workflow.md` ("Genericise Before You
> Write"). Run `python3 scripts/check_no_pii.py` before committing; CI enforces it.
> **And route before you write:** this directory is for finch's OWN docs only. A
> finding about another system (cron, MCP, Gmail, patch, OAuth, git) goes to that
> skill or to `<fs-root>/references/` (local, unpublished) — never here.


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
- Memory at/near capacity (`memory` tool refuses edits, ~79%+ warning threshold): **RUN `finch.compact` / `memory_guard.py` — do NOT hand-edit MEMORY.md to dodge the cap.** Manual memory surgery (condensing entries into one giant block, dropping context to fit) is exactly the work Finch owns, and doing it by hand produces bloat (a single ~1,900-char entry where tier-routing would have moved procedure out to a skill/reference). The user's correction (2026-07-15): "Why are you manually cleaning up memory? You have Finch for that." If the `memory` tool refuses an edit at capacity, hand it to Finch (force `ocas-finch:daily` or run `memory_guard.py --file ~/.hermes/profiles/<profile>/memories/MEMORY.md`); do not fight the limit with manual `memory` writes. Finch owns compaction; this is the procedure, not "there is no skill."
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

- Verify tool availability before parallel batches (one bad tool name poisons the whole batch). **DEFERRED-MCP DIRECT CALL = WHOLE-BATCH KILL (confirmed → full body in `references/scanning-gotchas.md`
- **Absent-namespace closure — `tool_call` ALSO fails, pivot immediately (re-validated 2026-07-23T19:48Z finch:scan)** → full body in `references/scanning-gotchas.md`
- **MCP-absent triage (distinguish mount-failure from config/cred failure)** → full body in `references/scanning-gotchas.md`
- **googleapiclient direct-fallback RESPONSE SHAPE (confirmed 2026-07-23 finch:scan)** → full body in `references/scanning-gotchas.md`
- Unreachable workspace source = GAP, never "no signal". When the google-workspace MCP namespace is entirely absent from the tool list (not just failing → full body in `references/scanning-gotchas.md`
- MCP tools reachable in cron via Composio (`COMPOSIO_MULTI_EXECUTE_TOOL`); attempt Calendar/Drive first, skip only on connection failure
- `tool_search` ≠ `tool_call` availability — probe a suspect MCP tool alone before batching; MCP load state is intermittent between runs
- **Google Workspace MCP = proxy invocation, not direct** → full body in `references/scanning-gotchas.md`
- **Large MCP batch responses persist to disk — parse with `terminal`, not inline** → full body in `references/scanning-gotchas.md`
- **`get_gmail_messages_content_batch` 429 partial-failure (2026-07-22)** → full body in `references/scanning-gotchas.md`
- Direct MCP credential-store fallback (`<gworkspace-creds>/credentials/<email>.json`) when dispatch rejects + legacy token is `deleted_client`
- **Host egress filter 404s RAW requests to Calendar/Drive — use googleapiclient (confirmed 2026-07-22 finch:scan)** → full body in `references/scanning-gotchas.md`
- Stale errors from `hermes cron list` — verify `Last run:` timestamp; `consecutive_failures` is the only reliable error gate
- Re-verify prior completions/STATES against LIVE signal bidirectionally (re-open on relapse, resolve on live recovery)
- MCP Google Workspace param is `page_size`, not `limit`/`max_results` → full body in `references/scanning-gotchas.md`
- **`get_events` param exception (confirmed 2026-07-23 finch:scan)** → full body in `references/scanning-gotchas.md`
- Email scan MUST paginate to completion (`page_token` loop) → full body in `references/scanning-gotchas.md`
- **Incremental email classification via message-ID watermark (confirmed 2026-07-24 finch:scan)** → full body in `references/scanning-gotchas.md`
- Sessions scan date-string workaround (`query="YYYY-MM-DD"`); mine interactive messages via direct `state.db` SQL, not session_search scroll
- Only report actual fixes, never stale/transient issues; interpreter-shutdown errors are always transient
- Never force model overrides on cron jobs; maintain skill index; push local changes to GitHub immediately (user directive)
- Disk-before-auth diagnostic (`df -h /` before OAuth); `execute_code` blocked in <profile> cron profile — use `terminal` python3
- Concurrent-write hazards on task-list.json / MEMORY.md / ANY shared prep file → full body in `references/scanning-gotchas.md`
- `read_file` view of a JSON file is NOT validation → full body in `references/scanning-gotchas.md`
- **Parallel `patch` edits to the same JSON file corrupt it** → full body in `references/scanning-gotchas.md`
- **Re-rank the task array with a script, not `patch` block-moves** → full body in `references/scanning-gotchas.md`
- **Cron health = read `jobs.json` directly** → full body in `references/scanning-gotchas.md`
- **`jobs.json` is a dict `{"jobs": [...], "updated_at"}`, NOT a bare list (confirmed 2026-07-23 finch:scan)** → full body in `references/scanning-gotchas.md`
- **Cron run-history evidence = `cron/output/<rid>/`, NOT `executions.db`** → full body in `references/scanning-gotchas.md`
- **Windowed mining/analysis cron = SILENT DATA-DROP trap (confirmed 2026-07-23, <other-ocas-skill>-miner)** → full body in `references/scanning-gotchas.md`
- **Transient-provider signature (Tencent "Upstream error… Retry once")** → full body in `references/scanning-gotchas.md`
- **`find` can return a STALE `jobs.json` snapshot under `state-snapshots/` — always pin the LIVE path** → full body in `references/scanning-gotchas.md`
- `skill_view(name, file_path=...)` linked-file fetch can itself throw the transient `DaemonThreadPoolExecutor object has no attribute '_initializer'` e → full body in `references/scanning-gotchas.md`
- Long single-line JSON string values defeat the `patch` fuzzy matcher → full body in `references/scanning-gotchas.md`
- **Inline `terminal python3 -c` with a LARGE payload = STREAM TIMEOUT (confirmed 2026-07-24 finch:scan)** → full body in `references/scanning-gotchas.md`
- **`patch` PREFIX match = SILENT corruption on long single-line JSON values** → full body in `references/scanning-gotchas.md`
- `jobs.json` for cron health when `cronjob` tool unavailable; `hermes cron list` hides disabled jobs. **NEVER report "cron health clean" without enumer → full body in `references/scanning-gotchas.md`
- **Cron-health "0 errors" is a HIGH-RISK false-negative — derive the claim from a FULL-OUTPUT grep, never from a prior scan's state** → full body in `references/scanning-gotchas.md`
- **False-recovery claim = false-positive, verify against live jobs.json (confirmed 2026-07-24 finch:work)** → full body in `references/scanning-gotchas.md`
- **Gateway-restart timing interprets a single interpreter-shutdown error (confirmed 2026-07-24 finch:work)** → full body in `references/scanning-gotchas.md`
- Provider HTTP 400 is MEDIUM (not transient) — classify by status; missing-script errors need path verification not debugging
- finch:scan is NOT a task executor; read_file tilde-expansion path doubling; `jobs.json` schedule fields are dicts not strings
- Gateway RSS growth tracking (3x = notable, >2GB = escalate)
- **`hermes cron list` has NO parseable JSON mode — and emits NO `last_status`/`consecutive_failures` columns** → full body in `references/scanning-gotchas.md`
- **write_file / read_file commons paths: use LITERAL `~/.hermes/commons/...`, NEVER a tilde `~/.hermes/commons/...`** → full body in `references/scanning-gotchas.md`

## Architecture

- **All finch jobs are pure LLM**

### Cron rebase breakage pattern
Confirmed 2026-07-22: multiple `ocas-*:update` jobs can fail simultaneously with the same `git rebase` conflict signature, indicating upstream sync publication introduced incompatible changes across multiple related repos/skills. Job descriptions often include `Removing references/...`, `Removing data/`, and `Dropped refs/stash@{0}`. Treat as one systemic sync breakage, not N independent failures.

**Role:** Session mining engine. Detects behavioral signals from conversation transcripts and routes them to durable modification targets (MEMORY.md, skill patches).

**Journal type:** Action Journal. Every finch run emits an Action Journal entry to `{agent_root}/commons/journals/ocas-finch/`.

**Cooperation:**
- Receives: Session transcripts (read-only, from the agent's session store)
- Reads: BehavioralSignal files from Chronicle (Corvus was merged into Chronicle)
- Emits: DecisionRecords to the Finch decision log
- Writes: MEMORY.md — via `scripts/memory_guard.py` **direct file write** (`--apply --file ~/.hermes/profiles/<profile>/memories/MEMORY.md`), NOT the built-in `memory` tool. The <profile> profile has a `pre_tool_call` shell hook (`agent-hooks/block-memory-tool.sh`, matcher `^memory$`) that BLOCKS the `memory` tool and redirects to this script, plus `memory.memory_enabled: false` so the built-in backend never auto-persists. Finch is therefore the SOLE maintainer of MEMORY.md. Never call the `memory` tool to edit it.

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
   - Update the task's description to include a work log with timestamp and summary of actions taken (e.g., `\n\n[Work log: At <timestamp> checked DNS for art.<agent-handle>.com - no records found (NXDOMAIN).]`)
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

Skip tasks where `action_required: false` AND `status: "in_progress"` — these are events happening now (e.g., <operator> is at the appointment). Only pick them if they transition to needing action.

If NO tasks have `action_required: true` and all remaining tasks are `pending` with `action_required: false`, pick the highest-priority one to validate/monitor (e.g., disk monitoring) and mark it `completed` with a resolution note. This prevents the list from accumulating stale low-priority items.

### Repeated check-and-close anti-pattern (work execution)

Detect and break the loop where a task is repeatedly checked and closed without a fix. Read `references/work-execution-procedures.md` (Repeated check-and-close anti-pattern (work execution)) when a task keeps reappearing across runs.

### Task actionability filter (cron context)

Decide whether a task can be acted on unattended in cron. Read `references/work-execution-procedures.md` (Task actionability filter (cron context)) when finch:work runs without a user present.

### Pipeline task resumption (ledger/state-based)

Resume a partially-completed pipeline task from its ledger instead of restarting. Read `references/work-execution-procedures.md` (Pipeline task resumption (ledger/state-based)) when a task was interrupted mid-pipeline.

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

Classify a signal as real / stale / transient before changing anything. Read `references/work-execution-procedures.md` (Signal triage before execution (WORK step)) before acting on any finch:work signal.

## Manual run & verification (when the user says "run finch")

"Run finch" means verify ALL deployed finch cron jobs are healthy and (optionally) force a run. The deployed job set (2026-07-07) is **FIVE jobs**, not the four in the design doc:

- **`finch`** — profile-root MEMORY.md compaction (runs `memory_guard.py` on the DEFAULT profile's MEMORY.md — NOT the <profile> profile's; guard the `--file` override or it compacts the wrong memory).
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

- **MCP-auth 401** (dead `[mcp_servers]` token): the cause is a **stale `[mcp_servers]` block in the profile `.env`** (`~/.hermes/profiles/<p>/.env`) shipping an invalid/expired token (e.g. a dead Discord token) that breaks ALL MCP calls. Fix: remove the `[mcp_servers]` section; the client falls back to valid config and MCP works.
- **Provider-auth 401** (LLM provider token): the run output shows `RuntimeError: Error code: 401` with `token_expired` ("Provided authentication token is expired") or `"Your API key is invalid, blocked or out of funds"` from `portal.nousresearch.com`. This is NOT the `[mcp_servers]` block. Confirmed 2026-07-12: finch jobs 401'd with Nous `token_expired`; `grep mcp_servers` on the <profile> `.env` returned nothing; the gateway was holding a stale provider credential. **Fix: restart the gateway** (kill the `--profile <profile> gateway run` process and let it respawn, or `hermes gateway run`) so it reloads the current valid provider token. After restart, post-restart runs (`finch:scan`, `finch:memory-guard-floor`) returned `ok`.

Diagnostic steps: (1) Read the actual run output / `jobs.json` `last_error` — `cronjob list` may display `last_error: None` even when jobs.json holds the 401, so don't trust the list's None. (2) `grep -n "mcp_servers" ~/.hermes/profiles/<p>/.env` — if absent, it's provider-auth, not MCP-auth. (3) If interactive sessions on the same `provider`/`model` work but cron 401s, the scheduler is holding a stale token → restart the gateway.

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

**Skill integration hygiene (confirmed 2026-07-14):** When adding external/upstream skills to the local library, prefer integrating relevant LEARNINGS into the closest existing skill rather than installing a new conflicting skill. For upstream skill repos <operator> shares: (1) determine if any capability overlaps an existing skill; (2) if yes, merge the valuable parts into that skill (including code-review patterns <operator> may say were "skipped"); (3) only install a new skill if it has no close match and won't conflict. <operator>: "Would any of these skills be useful in <other-profile> skill library, if so integrate them into the closest match don't install new skills that may conflict" and "You should integrate what makes sense in code review as well. The ones you skipped."

**Active-review mandate:** A review pass that finds no signal is a missed learning opportunity, not a neutral outcome. Most finch passes surface at least one skill update — even a small pitfall or support-file note. Prefer patching the skill that was IN PLAY this run over creating a new narrow skill.

## Gotchas

See `references/pitfalls.md` for the full consolidated pitfalls list.

## Gotchas (verbose bodies in `references/operational-gotchas.md`)

- `memory` tool may be unavailable in cron — fall back to direct file edit at the canonical profile memory path; re-read before write on sibling-warning
- MEMORY.md must contain only Tier 1 knowledge — no pointers to routed content; under 500 chars when well-compacted
- Directive consolidation — merge two directives sharing a principle, keep specific phrasing, list both dates
- FTS5 minimum token length (3-4 chars) drops short corrections (`No`, `Don't`) — mine without `query=`, use `role_filter=user`, scan visually
- Session source filtering — cron sessions drown interactive ones; under <profile> cron, `session_search` reads the DEFAULT profile store, so query `~/.hermes/profiles/<profile>/state.db` directly. Identify interactive first (source NOT LIKE 'cron%'), pull user messages via direct `state.db` SQL, drop `[CONTEXT COMPACTION — REFERENCE ONLY]` headers (false positives), parse JSON-array `content`. NOTE: interactive user messages carry `observed=0`, NOT `observed=1` — do NOT filter `observed=1` or you drop every real user message. Full recipe: Fallback to keyword queries before declaring "no interactive sessions".
- Skill usage analytics — cron sessions ARE the signal for state.db mining (opposite of behavioral mining); use JOIN + busy_timeout + Python JSON parse
- HERMES_HOME path resolution — three-branch logic, never hardcode `~/.hermes/MEMORY.md`; old two-branch double-nests. under <profile> cron, a bare `read_file('~/.hermes/MEMORY.md')` resolves to the DEFAULT profile memory (different path AND content) — always target `~/.hermes/profiles/<profile>/memories/MEMORY.md` explicitly. After writing MEMORY.md, RE-READ it and assert every intended block persisted (grep a unique substring per block) — a prior daily run recorded two Tier-1 blocks as 'routed to MEMORY.md' that were ABSENT from the live file next run (silent consolidation loss); recover any missing block rather than trusting the journal's `applied` self-report, which is not proof of persistence.md path trap.
- Two evals.json files (root + evals/) must stay in sync; root is canonical

## Support File Map

Full file-to-purpose map (when to read each reference, script, and data file) → `references/finch-support-map.md`.
## Scripts

Full detail (eviction priority, self_update wrapper contract, memory_state subcommands) in `references/operational-gotchas.md` § Scripts:

- `memory_guard.py` — deterministic MEMORY.md safety floor; mandatory post-guard Step 7.5 verification (Methodologies must outrank Course Changes in eviction)
- `self_update.py` / `self_update.sh` — real Python wrapper resolving skill dir from `Path(__file__).resolve().parents[1]`; `self_update.sh` is the GitHub fetch/install path
- `memory_state.py` — persisted reinforcement-state store (Ebbinghaus forgetting curve); `reinforce` / `check` / `route` / `decay-report` subcommands
- `gws_direct_puller.py` — FULL-CONTENT Google Workspace puller (Gmail metadata + optional `--full-text` body, Calendar events for a horizon, Drive most-recently-modified). Run via `<hermes-venv>/bin/python` (MCP venv has googleapiclient). Use when MCP absent and you must CLASSIFY actionable email/calendar/drive signals, not just confirm reachability. CRITICAL: use googleapiclient, NOT raw requests — the host egress filter 404s raw Calendar/Drive calls. Pair with `gws-direct-fallback.py` (count-probe).
- `verify_sepagree_signature.py` — reusable EMAIL-SEPAGREE (separation agreement) Docusign "unsigned" re-verifier for finch:work passes. Run via `terminal` python3 (NOT execute_code); counts Docusign "Completed"/signed notices + cross-checks the negotiation thread, prints VERDICT. Proven logic extracted 2026-07-16 from a working live Gmail API pass.
  **Recovery note (2026-07-16 finch:work pass):** the EMAIL-SEPAGREE task-list `meta`/`signal` referenced `<fs-root>/sepagree_verify.py`. That path is NO LONGER reliably absent — as of the 10th re-verify pass, STALE DUPLICATE copies now exist at `<fs-root>/sepagree_verify.py` AND `~/.hermes/profiles/<profile>/commons/data/ocas-finch/sepagree_verify.py`. Do NOT run either — they may diverge from the maintained script. The canonical, maintained verifier is `skills/ocas-finch/scripts/verify_sepagree_signature.py`. The Docusign recipe (1 begin-signing + 0 Completed = proof of non-signature) is the load-bearing check; re-running it is the correct finch:work action for the P1, not re-deriving the script each time.
  **Locator pattern:** to find the verifier (or any skill script) reliably in the <profile> cron profile, use `terminal find /root -iname 'verify_sepagree*' 2>/dev/null` rather than `search_files`, which returned transient `DaemonThreadPoolExecutor` framework errors on 3 consecutive attempts this run. `find` is the dependable fallback when `search_files` flakes — and the same `DaemonThreadPoolExecutor` error also hits `read_file` in bursts; for those, fall back to `terminal` (`python3` / `stat` / `cat` via `read_file` substitute).
  **NEW (2026-07-23):** pass `--since <RFC3339>` to run the BLOCK-CLEARANCE PROBE — enumerates all Docusign/Kim envelopes in the last 5d and reports any with `internalDate` AFTER that ts (a potential corrected/Section-3-15 envelope). If none, the external-party blocker is unchanged; the probe is the canonical replacement for the inline Gmail re-derivation historically done on the `docusign-separation-agreement` task.
  **PROHIBITION (reinforced 2026-07-23T13:34Z finch:work relapse):** do NOT hand-roll a new `verify-docusign-*.py` into `commons/data/ocas-finch/`. A 2026-07-23T13:34Z pass did exactly that (`commons/data/ocas-finch/verify-docusign-0723.py`) — it duplicated the canonical script's `--since` probe and created a stale-drift risk (the SAME class as the `sepagree_verify.py` duplicates the recovery note already warns about; `find` later returns multiple divergent copies). That redundant file SHOULD BE DELETED. If a probe case is missing from `verify_sepagree_signature.py`, EXTEND the canonical script (add the case + wire `--since`) — never author a sibling. The canonical script is the single source of truth for EMAIL-SEPAGREE/Docusign re-verify.

## Self-update

`finch.update` pulls the latest from GitHub. Runs silently unless version changed or error.

## Platform notes

Finch is designed for Hermes but degrades gracefully on other harnesses. Minimum viable platform: any harness with `write_file`, `read_file`, and `terminal` tools.