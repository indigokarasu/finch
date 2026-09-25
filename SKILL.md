---
license: MIT
description: 'OCAS self-improvement orchestrator (Darwin''s finch — adaptive evolution).
  Mines session transcripts for corrections, breakthroughs, methodologies, and directives
  (Always/Never); routes each finding to MEMORY.md, skill files, references, or Chronicle
  KG; compacts MEMORY.md by tier routing. Part of the OCAS System Evolution Layer
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
      description: MEMORY.md path override.
      default: ""
    - key: HERMES_MEMORY_CHAR_LIMIT
      description: Hard cap memory_guard.py enforces.
      default: "2200"
    - key: HERMES_MEMORY_SOFT_TARGET
      description: Soft target for compaction routing.
      default: "500"
    - key: OCAS_OPERATOR_EMAIL
      description: Operator Gmail address.
      default: ""
    - key: OCAS_GOOGLE_CRED_DIR
      description: Google Workspace OAuth credential directory.
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
- cron errors
- task list
- memory full
- memory compaction
- memory guard
---

> **PUBLIC REPO — GENERICISE EVERY REFERENCE.** Use placeholders from
> `references/reference-file-workflow.md` ("Genericise Before You Write") — no real
> names, emails, ids, tokens or home paths; CI runs `scripts/check_no_pii.py`.
> **Route before you write:** this directory is for finch's OWN docs. A finding about
> another system (cron, MCP, Gmail, OAuth, git) belongs to that skill or to
> `<fs-root>/references/` (local, unpublished) — never here.

# ocas-finch

Finch is the OCAS System Evolution Layer's self-improvement orchestrator: pure-LLM cron jobs plus one `no_agent` script floor (`finch:floor`). Job names drift — enumerate the live registry; deployed set, forcing runs, and mass-401 triage: `references/manual-run-verification.md`.

**Signal sources (7)**: cron health, email, calendar, sessions, Drive, kanban, system — table in `references/scan-work-architecture.md`.

## When to Use

- Scheduled self-improvement: `finch:scan` (2h), `finch:work` (30m), `finch:daily` (6am PT), `finch:weekly` (Sunday 8am PT).
- Manual session mining via `finch.mine` / `finch.run`.
- After major sessions: detect corrections, directives, breakthroughs, methodologies.
- Memory at/near capacity: run `finch.compact` / `memory_guard.py` — never hand-edit MEMORY.md to dodge the cap; Finch owns compaction ("Why are you manually cleaning up memory? You have Finch for that.").
- Skill library maintenance: route findings to SKILL.md patches.

## When NOT to Use

- Real-time behavioral adaptation (Chronicle handles pattern detection).
- Skill evaluation scoring (Mentor handles OKR evaluation).
- Skill creation/architecting (Forge builds skills).
- Entity identity resolution (Chronicle tools handle direct writes).

## Interactive menu & responsibility boundary

Interactive invocation presents a two-level menu (layout, Clarify timeout, response parsing → `references/interactive-menu.md`). Finch owns its core domain operations; it does NOT own trigger detection, session management, or cross-skill orchestration (the calling agent does).

## Workflow — the core loop

1. **Scan** (`finch:scan`, every 2h) — read the 7 sources; update `task-list.json`. Cron health MUST come from the LIVE `jobs.json` via `references/cron-health-validation.md` — never `cronjob list` alone (hides paused/disabled errors). Re-validate prior tasks both directions (re-open on relapse, resolve on recovery).
2. **Work** (`finch:work`, every 30m) — pick the top pending task, load the governing skill, execute ONE. De-duplicate task IDs first (`references/duplicate-task-detection.md`). Then append `[Work log: <timestamp> <summary>]` and set `status: "done"`, `done_at`, `updated_at`.
3. **Route** — findings to MEMORY.md, skill patches, or references; proposed skill patches stage under `{agent_root}/commons/data/ocas-forge/staged/{skill}/` for `ocas-fellow` evaluation before production. Behavioral rules (priority 0) apply immediately.
4. **Journal** — every run emits an Action Journal entry under `{agent_root}/commons/journals/ocas-finch/`.

**Task selection priority:** `action_required: true` first; then high > medium > low; then earliest due; `pending` before `in_progress`. Skip `action_required: false` + `in_progress` (events in flight). Nothing actionable → validate and close the top pending item.

**Work-execution rules** (details in `references/work-execution-procedures.md`): triage signal (real / stale / transient); actionability filter (unattended cron); pipeline resumption from the ledger; break repeated check-and-close loops; prescribed fixes may be wrong — verify self-recovery / fail-loud guards first (`references/work-prescribed-fix-selfrecovery-guard.md`).

**Mining frameworks** (`references/mining_methodology.md`): tag failures by phase — **Planning** → patch preconditions; **Execution** → patch gotchas; **Response** → patch output sections. Record corrections as `[CORRECTION] What / Why / When` so lessons transfer.

## Scanning gotchas (top traps)

Full bodies: `references/scanning-gotchas.md` (MCP/Gmail/cron-JSON) and `references/finch-scan-pitfalls.md` (task-list/cron state). The traps that bite most often:

- **Probe MCP tools ALONE before batching** — one bad tool name poisons the whole batch; MCP load state flips between runs (`tool_search` ≠ `tool_call`).
- **Cron health only from `jobs.json`** — `hermes cron list` hides disabled/paused jobs and has no JSON mode; `consecutive_failures > 0` is the only reliable "broken now" gate; pin the LIVE path (never `state-snapshots/`).
- **Never report "0 errors" from a summary or a prior scan** — derive it from a full-output grep of the live registry; verify recoveries against `last_run_at`.
- **Email scan loops `page_token` to completion** — page-1-only misses high-value mail; classify metadata-first (`email-mcp-pagination-parsing.md`, `email-mcp-triage.md`).
- **Workspace MCP absent → pivot at once** to `scripts/gws_direct_puller.py` (googleapiclient; raw requests 404 through the host egress filter); record the source UNVERIFIED, never "no signal".
- **Never batch >1 `patch` on one JSON file; `read_file` is not validation** — parallel patches interleave and corrupt; long single-line values defeat `patch`; only `json.load()` catches corruption.
- **`execute_code` is blocked in cron** — use `terminal python3`; write multi-KB scripts to a file first (inline payloads hit a stream timeout).
- **Use absolute paths** — tilde expansion in `read_file`/`write_file` can double into a phantom `profiles/<p>/home/` tree; verify commons writes with `ls`/`readlink -f`; never delete a `commons/` file whose `realpath` is in the live tree.

## Storage & architecture

- Role: session mining engine — routes behavioral signals to durable targets (MEMORY.md, skill patches). Layout → `references/storage-layout.md`; signal types → `references/signal-types-table.md`.
- Cooperation: reads transcripts (read-only) + Chronicle BehavioralSignals; emits DecisionRecords; writes MEMORY.md **only** via `scripts/memory_guard.py` (`--apply --file ~/.hermes/profiles/<profile>/memories/MEMORY.md`).
- **MEMORY.md ownership**: a `pre_tool_call` hook (`agent-hooks/block-memory-tool.sh`, matcher `^memory$`) blocks the built-in `memory` tool (plus `memory.memory_enabled: false`); Finch is the sole maintainer.
- MEMORY.md = Tier 1 only — no pointers; ~500 chars when compacted; consolidate duplicate directives keeping the specific phrasing and both dates. After any write, re-read and grep a unique substring per intended block — a journal's `applied` count is not proof of persistence.

## Behavioral directives (priority 0)

"Always" / "Never" from the user is a priority-0 rule: apply immediately, route to MEMORY.md under `## Always Rules` / `## Never Rules`, never batch with lower-priority findings.

## Failure modes & error handling

| Symptom | Response |
|---------|----------|
| Job errors, cause unclear | Classify (`references/scan-error-classification.md`: HTTP 400 = MEDIUM, interpreter-shutdown = transient); `consecutive_failures` > 0 = real. |
| Multiple jobs 401 at once | MCP-auth (stale `[mcp_servers]` in the profile `.env`) vs provider-auth (restart the gateway) — `references/manual-run-verification.md`. |
| Workspace source unreadable | Record a GAP; carry prior state forward as UNVERIFIED — never "no signal". |
| Signal source down | Degraded mode: continue with remaining inputs, log `degraded: <source>`. |
| Memory write rejected | Run `finch.compact` / `memory_guard.py` — never hand-edit to dodge the cap. |

## Manual run & verification

"Run finch" = verify ALL deployed jobs are healthy and force runs where needed. Force an LLM job by **pausing, then running**; `no_agent` jobs run directly. A queued run is not a completed run — confirm `last_run_at` advanced. Job set, verification gate, 401 triage, cron-rebase breakage, and the autonomy directive: `references/manual-run-verification.md`.

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

- **Evidence**: every run writes `evidence.jsonl` (no-ops included); a gap beyond cadence (2h/30m) logs `gap_detected` and triggers a remedial pass.
- **Degraded mode**: missing Chronicle signals → continue; missing session store → log `degraded: session_store`, skip mining.
- **Log compaction**: no-op >30d, error/gap >90d compacted; last 7 days retained.

## OKRs, anti-patterns, review

OKR targets → `references/okrs.md`, evaluated at `finch:weekly`. 10 anti-patterns → `references/anti-patterns.md`. Active-review principle → `references/active-review.md`: no signal found is a missed learning — patch the skill in play, don't create a narrow new one.

## Skill library maintenance & gotchas

After every session, review for signals and update the skill library — procedure (signals, preference order, what NOT to capture, integration hygiene) in `references/skill-library-maintenance.md`. Consolidated pitfalls → `references/pitfalls.md`; operational set (memory-tool fallback, directive consolidation, FTS5 short-token loss, session-source filtering, analytics, HERMES_HOME resolution, evals.json sync) → `references/operational-gotchas.md`.

## Support file map

| File | When to read |
|------|--------------|
| `references/finch-support-map.md` | Full file-to-purpose map — start here for an unfamiliar file |
| `references/scanning-gotchas.md` + `finch-scan-pitfalls.md` + `cron-health-validation.md` | Any scan: MCP/Gmail/cron-JSON traps; task-list corruption; cron-health script |
| `references/scan-error-classification.md` | Classifying errored cron jobs |
| `references/email-mcp-triage.md` (+ `email-mcp-pagination-parsing.md`) | Pulling or classifying email |
| `references/work-execution-procedures.md` + `work-prescribed-fix-selfrecovery-guard.md` | Before any finch:work task; prescribed-fix checks |
| `references/manual-run-verification.md` | "Run finch" / mass-401 triage / forced runs |
| `references/signal-triage-before-fix.md` + `already-fixed-verification.md` | Multi-failure task, or resuming an interrupted one |
| `references/pitfalls.md` + `operational-gotchas.md` + `file-governance.md` + `forgetting_curve.md` | Before any finch op; routing targets; compaction |
| `references/mining_methodology.md` + `skill-library-maintenance.md` | Before mining / after a session produces a learning |

## Scripts

| Script | Purpose | Key flags |
|--------|---------|-----------|
| `memory_guard.py` | MEMORY.md safety floor (cap, atomic write) | `--apply --file <path>`, `--emit-decision`, `--json` |
| `memory_state.py` | Reinforcement-state store (forgetting curve) | `reinforce`, `check`, `route`, `decay-report` |
| `gws_direct_puller.py` | Workspace pull when MCP absent (googleapiclient; `<hermes-venv>/bin/python`) | `--full-text` |
| `verify_sepagree_signature.py` | Docusign EMAIL-SEPAGREE "unsigned" re-verifier; prints VERDICT | `--since <RFC3339>` probe |
| `finch_hooks_plugin.py` | Hooks: signal capture, memory guard, subagent tracking | `--extract-signals`, `--check-tool` |
| `finch_scan_tasklist_rerank.py` | Safe re-rank + validation for task-list.json | (positional path) |
| `check_no_pii.py` | PII gate CI runs before publish | `--quiet` |

Verify-script rules (canonical copy only; never hand-roll a sibling) → `references/sepagree-verify-rules.md`. Eviction priority + memory_state detail → `references/operational-gotchas.md` § Scripts.

## Self-update & platform notes

`finch.update` pulls the latest from GitHub; silent unless the version changed or it errors. Finch is designed for Hermes but degrades gracefully elsewhere — minimum viable platform: any harness with `write_file`, `read_file`, and `terminal`.
