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
  version: "3.2.1"
  hermes:
    category: software-development
    tags:
    - self-improvement
    - session-mining
    - behavioral-adaptation
    - OCAS-core
    config:
    - key: FINCH_MEMORY_FILE
      description: MEMORY.md path override for memory_state.py.
      default: ""
    - key: HERMES_MEMORY_CHAR_LIMIT
      description: Hard character cap memory_guard.py enforces on MEMORY.md.
      default: "2200"
    - key: HERMES_MEMORY_SOFT_TARGET
      description: Soft target under the cap that triggers compaction routing.
      default: "500"
    - key: OCAS_OPERATOR_EMAIL
      description: Operator Gmail address for Workspace pulls and signature re-verification.
      default: ""
    - key: OCAS_GOOGLE_CRED_DIR
      description: Directory of per-account Google Workspace OAuth JSON credentials.
      default: ~/.google_workspace_mcp/credentials
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

> **PUBLIC REPO — GENERICISE EVERY REFERENCE.** Use placeholders from
> `references/reference-file-workflow.md` ("Genericise Before You Write") — no real
> names, emails, employers, ids, tokens or home paths. CI runs
> `python3 scripts/check_no_pii.py` before publish.
> **Route before you write:** this directory is for finch's OWN docs. A finding about
> another system (cron, MCP, Gmail, patch, OAuth, git) belongs to that skill or to
> `<fs-root>/references/` (local, unpublished) — never here.

# ocas-finch

Finch is the OCAS System Evolution Layer's self-improvement orchestrator: pure-LLM cron jobs plus one `no_agent` script floor (`finch:floor`). Enumerate the live registry before assuming a job name (they drift); deployed set, forcing runs, and mass-401 triage: `references/manual-run-verification.md`.

**Signal sources (7)**: cron health, email, calendar, sessions, Drive, kanban, system — table in `references/scan-work-architecture.md`.

## When to Use

- Scheduled self-improvement: `finch:scan` (2h), `finch:work` (30m), `finch:daily` (6am PT), `finch:weekly` (Sunday 8am PT).
- Manual session mining via `finch.mine` / `finch.run`.
- After major sessions: detect corrections, directives, breakthroughs, methodologies.
- Memory at/near capacity (`memory` tool refuses edits, ~79% warning): run `finch.compact` / `memory_guard.py` — do NOT hand-edit MEMORY.md to dodge the cap. Manual surgery is Finch's work and it produces bloat (an example: one ~1,900-char mega-entry where tier-routing would have moved the procedure to a skill).
- Skill library maintenance: route findings to SKILL.md patches.

## When NOT to Use

- Real-time behavioral adaptation (Chronicle handles pattern detection).
- Skill evaluation scoring (Mentor handles OKR evaluation).
- Skill creation/architecting (Forge builds skills).
- Entity identity resolution (Chronicle tools handle direct writes).

## Interactive menu & responsibility boundary

Interactive invocation presents a two-level menu (layout, Clarify timeout, response parsing → `references/interactive-menu.md`). Finch owns its core domain operations; it does NOT own trigger detection, session management, or cross-skill orchestration (the calling agent does).

## Workflow — the core loop

1. **Scan** (`finch:scan`, every 2h) — read the 7 signal sources. Cron health MUST be enumerated from the LIVE `jobs.json` (`~/.hermes/profiles/<profile>/cron/jobs.json`) with the parse script in `references/cron-health-validation.md` — never `cronjob(action='list')` / `hermes cron list` alone; both hide paused/disabled error jobs. Re-validate prior tasks BOTH directions (re-open on relapse, resolve on live recovery). Maintain `task-list.json`.
2. **Work** (`finch:work`, every 30m) — pick the top pending task, load the governing skill, execute ONE task. Check for duplicate task IDs first (`references/duplicate-task-detection.md`). On completion append `[Work log: <timestamp> <summary>]` and set `status: "done"`, `done_at`, `updated_at`.
3. **Route** — findings go to MEMORY.md, skill patches, or reference files. Stage proposed skill patches under `{agent_root}/commons/data/ocas-forge/staged/{skill}/` for `ocas-fellow` evaluation before production. MEMORY.md behavioral rules (priority 0) apply immediately.
4. **Journal** — every run emits an Action Journal entry to `{agent_root}/commons/journals/ocas-finch/`.

**Task selection priority:** `action_required: true` first; then high > medium > low priority; then earliest due date; `pending` before `in_progress`. Skip `action_required: false` + `in_progress` (events in flight). If nothing needs action, validate the highest-priority pending item and close it with a resolution note.

**Work-execution rules** — read the named section of `references/work-execution-procedures.md` before acting: signal triage (classify real / stale / transient before changing anything); actionability filter (what may run unattended in cron); pipeline resumption (resume from the ledger, don't restart); repeated check-and-close (break the loop when a task keeps reappearing); prescribed-fix may be wrong (verify self-recovery and fail-loud guards first — `references/work-prescribed-fix-selfrecovery-guard.md`).

**Mining frameworks** (full text in `references/mining_methodology.md`): tag each mined failure by phase — **Planning** (wrong approach/prereqs → patch preconditions), **Execution** (tool/API/param failure → patch tool-usage gotchas), **Response** (format/tone/verbosity → patch output sections); and record corrections as `[CORRECTION] What: <wrong>. Why: <violated assumption>. When: <context>` so lessons transfer.

## Scanning gotchas (top traps)

Full bodies: `references/scanning-gotchas.md` (MCP/Gmail/cron-JSON) and `references/finch-scan-pitfalls.md` (task-list/cron state). The traps that bite most often:

- **Probe MCP tools ALONE before batching** — one invalid tool name poisons the whole batch; MCP load state flips between runs (`tool_search` ≠ `tool_call`).
- **Cron health only from `jobs.json`** — `hermes cron list` hides disabled/paused jobs and has no JSON mode; `consecutive_failures > 0` is the only reliable "broken now" gate; pin the LIVE path (never `state-snapshots/`).
- **Never report "0 errors" from a summary or a prior scan** — derive it from a full-output grep of the live registry; verify recovery claims against `last_run_at` / `next_run_at`.
- **Email scan loops `page_token` to completion** — page-1-only misses high-value mail; classify metadata-first, full-body only for candidates (`email-mcp-pagination-parsing.md`, `email-mcp-triage.md`).
- **Workspace MCP absent → pivot at once** to `scripts/gws_direct_puller.py` (googleapiclient; raw requests 404 through the host egress filter) and record the source UNVERIFIED, never "no signal".
- **Never batch >1 `patch` on one JSON file** — parallel patches interleave and corrupt it; use one `terminal python3` `json.load` → mutate → `json.dump` script. Long single-line values defeat `patch` (prefix matches silently corrupt).
- **`read_file` is not validation** — only `json.load()` catches corruption; re-read shared files after writes, merge on sibling-modification warnings.
- **`execute_code` is blocked in cron** — use `terminal python3`; keep inline payloads small (multi-KB inline scripts hit a stream timeout; write the script to a file first).
- **Use absolute paths** — tilde expansion in `read_file`/`write_file` can double into a phantom `profiles/<p>/home/` tree; verify commons writes with `ls`/`readlink -f`; never delete a `commons/` file whose `realpath` is in the live tree.
- **Classify before acting** — provider HTTP 400 is MEDIUM (not transient), interpreter-shutdown always transient, missing-script errors need a path fix not debugging (`references/scan-error-classification.md`).

## Storage & architecture

- Role: session mining engine — detects behavioral signals and routes them to durable targets (MEMORY.md, skill patches). Layout → `references/storage-layout.md`; signal types → `references/signal-types-table.md`.
- Cooperation: reads transcripts (read-only) + Chronicle BehavioralSignals; emits DecisionRecords to the finch decision log; writes MEMORY.md **only** via `scripts/memory_guard.py` (`--apply --file ~/.hermes/profiles/<profile>/memories/MEMORY.md`).
- **MEMORY.md ownership**: a `pre_tool_call` hook (`agent-hooks/block-memory-tool.sh`, matcher `^memory$`) BLOCKS the built-in `memory` tool and redirects here, plus `memory.memory_enabled: false`. Finch is the sole maintainer.
- MEMORY.md holds only Tier 1 knowledge — no pointers to routed content; ~500 chars when well compacted. Consolidate duplicate directives keeping the specific phrasing and both dates. After any write, re-read and grep a unique substring per intended block — a journal's `applied` count is not proof of persistence.

## Behavioral directives (priority 0)

"Always" / "Never" from the user is a priority-0 rule: apply immediately, route to MEMORY.md under `## Always Rules` / `## Never Rules`, never batch with lower-priority findings.

## Failure modes & error handling

| Symptom | Response |
|---------|----------|
| Job errors, cause unclear | Classify via `references/scan-error-classification.md`; `consecutive_failures > 0` = real, 0 = recovered/stale. |
| Multiple jobs 401 at once | MCP-auth (stale `[mcp_servers]` block in the profile `.env`) vs provider-auth (restart the gateway) — `references/manual-run-verification.md`. |
| Workspace source unreadable | Record a GAP, carry prior state forward as UNVERIFIED — never "no signal". |
| Signal source down | Degraded mode: continue with remaining inputs, log `degraded: <source>`. |
| Memory write rejected | Run `finch.compact` / `memory_guard.py` — never hand-edit to dodge the cap. |

## Manual run & verification

"Run finch" = verify ALL deployed jobs are healthy and force runs where needed. Force an LLM job by **pausing, then running**; `no_agent` jobs run directly. A queued run is not a completed run — verify `last_run_at` advanced. Job set, verification gate, mass-401 triage, cron-rebase breakage, and the autonomy directive ("take the action without being prompted") are in `references/manual-run-verification.md`.

## Commands

`finch.run` (full pipeline) · `finch.mine` (signals only) · `finch.compact` (MEMORY.md) · `finch.route` · `finch.dry-run` (no changes) · `finch.status` · `finch.scan` · `finch.work`.

## Scheduled tasks

| Job | Frequency | Behavior |
|-----|-----------|----------|
| **finch:scan** | Every 2h | Scan 7 sources → task list |
| **finch:work** | Every 30 min | Pick top item → ONE task |
| **finch:daily** | Daily 6am PT | Mine 24h → compact → route |
| **finch:weekly** | Sunday 8am PT | Mine 7d → compact → route → plan |

## Recovery behavior

- **Evidence**: every run writes `evidence.jsonl` (no-ops included, with `not_activity_reason`). If the evidence gap exceeds cadence (2h scan / 30m work), log `gap_detected` and run a remedial pass.
- **Degraded mode**: missing Chronicle signals → continue with available inputs; missing session store → log `degraded: session_store`, skip mining.
- **Log compaction**: no-op logs >30d, error/gap logs >90d compacted; last 7 days retained.

## OKRs, anti-patterns, review

OKR targets (schedule adherence, data integrity) → `references/okrs.md`, evaluated at `finch:weekly`. 10 anti-patterns (incl. declaration of victory, code-fence pitfalls) → `references/anti-patterns.md`. Active-review principle → `references/active-review.md`: a pass with no signal is a missed learning opportunity — patch the skill in play rather than create a narrow new one.

## Skill library maintenance & gotchas

After every session, review for signals and update the skill library — full procedure (signals, preference order, what NOT to capture, integration hygiene) in `references/skill-library-maintenance.md`. Consolidated pitfalls → `references/pitfalls.md`; operational set (memory-tool fallback in cron, directive consolidation, FTS5 short-token loss, session-source filtering, skill-usage analytics, HERMES_HOME resolution, evals.json sync) → `references/operational-gotchas.md`.

## Support file map

| File | When to read |
|------|--------------|
| `references/finch-support-map.md` | Full file-to-purpose map — start here for an unfamiliar file |
| `references/scanning-gotchas.md` | Any scan touching MCP, Gmail, cron JSON |
| `references/finch-scan-pitfalls.md` | When task-list.json or cron-task state looks wrong |
| `references/cron-health-validation.md` | During the scan cron-health step (parse script) |
| `references/scan-error-classification.md` | When classifying errored cron jobs |
| `references/email-mcp-triage.md` (+ `email-mcp-pagination-parsing.md`) | When pulling or classifying email |
| `references/work-execution-procedures.md` | Before executing any finch:work task |
| `references/work-prescribed-fix-selfrecovery-guard.md` | When a task prescribes a specific fix |
| `references/manual-run-verification.md` | When the user says "run finch" or jobs 401 |
| `references/signal-triage-before-fix.md` + `already-fixed-verification.md` | Before fixing a multi-failure or resuming an interrupted task |
| `references/pitfalls.md` + `operational-gotchas.md` | Before any finch operation |
| `references/mining_methodology.md` + `skill-library-maintenance.md` | Before mining / after a session produces a learning |
| `references/file-governance.md` + `forgetting_curve.md` | Before routing findings / during MEMORY.md compaction |

## Scripts

| Script | Purpose | Key flags |
|--------|---------|-----------|
| `memory_guard.py` | MEMORY.md safety floor (cap, directive protection, atomic write) | `--apply --file <path>`, `--emit-decision`, `--json` |
| `memory_state.py` | Reinforcement-state store (forgetting curve) | `reinforce`, `check`, `route`, `decay-report` |
| `gws_direct_puller.py` | Gmail/Calendar/Drive pull when MCP absent (googleapiclient; run via `<hermes-venv>/bin/python`) | `--full-text` |
| `verify_sepagree_signature.py` | Docusign EMAIL-SEPAGREE "unsigned" re-verifier; prints VERDICT | `--since <RFC3339>` probe |
| `finch_hooks_plugin.py` | Hooks plugin: signal capture, memory-tool guard, subagent tracking | `--extract-signals`, `--check-tool` |
| `finch_scan_tasklist_rerank.py` | Safe re-rank + validation for task-list.json | (positional path) |
| `check_no_pii.py` | PII gate CI runs before publish | `--quiet` |

Verify-script rules (canonical copy only; never hand-roll a sibling) → `references/sepagree-verify-rules.md`. Eviction priority + memory_state detail → `references/operational-gotchas.md` § Scripts.

## Self-update & platform notes

`finch.update` pulls the latest from GitHub; silent unless the version changed or it errors. Finch is designed for Hermes but degrades gracefully elsewhere — minimum viable platform: any harness with `write_file`, `read_file`, and `terminal`.
