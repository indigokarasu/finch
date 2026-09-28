---
license: MIT
description: 'OCAS self-improvement orchestrator (Darwin''s finch — adaptive evolution).
  Mines session transcripts for agent/system corrections, breakthroughs, methodologies,
  and directives (Always/Never); routes each finding to MEMORY.md, skill files,
  references, or Chronicle KG; user-scoped relationship signals are routed to
  Chronicle/User Dreaming instead of becoming global behavior; compacts
  MEMORY.md by tier routing. Part of the OCAS System Evolution Layer
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

- User modeling or relationship adaptation. Chronicle owns durable user evidence; User Dreaming performs user-principal offline consolidation, including relationship patterns. Finch mines agent/system learning signals.
- Skill evaluation scoring (Mentor handles OKR evaluation).
- Skill creation/architecting (Forge builds skills).
- Entity identity resolution (Chronicle tools handle direct writes).

## Interactive menu & responsibility boundary

Interactive invocation presents a two-level menu (layout, Clarify timeout, response parsing → `references/interactive-menu.md`). Finch owns its core domain operations; it does NOT own trigger detection, session management, or cross-skill orchestration (the calling agent does).

## Workflow — the core loop

1. **Scan** (`finch:scan`, every 2h) — read the 7 sources; update `task-list.json`. Cron health MUST come from the LIVE `jobs.json` via `references/cron-health-validation.md` — never `cronjob list` alone (hides paused/disabled errors). Re-validate prior tasks both directions (re-open on relapse, resolve on recovery).
2. **Work** (`finch:work`, every 30m) — pick the top pending task, load the governing skill, execute ONE. De-duplicate task IDs first (`references/duplicate-task-detection.md`). Then append `[Work log: <timestamp> <summary>]` and set `status: "done"`, `done_at`, `updated_at`.
3. **Route** — first classify scope. A finding about this user's interaction preference or relationship with the agent routes to Chronicle/User Dreaming and MUST NOT become a global MEMORY.md rule or skill patch. Agent/system-general findings route to MEMORY.md, skill patches, or references; proposed skill patches stage under `{agent_root}/commons/data/ocas-forge/staged/{skill}/` for `ocas-fellow` evaluation before production. Only genuinely system-general behavioral rules (priority 0) apply immediately.
4. **Journal** — every run emits an Action Journal entry under `{agent_root}/commons/journals/ocas-finch/`.

**MANDATORY, BOTH STEPS 1 AND 2 — close the ledger's own clock before and after
writing: `python3 scripts/finch_ledger_guard.py` (`--repair` to fix, `--json` for
the `*_measured` flags).** No timestamp in `task-list.json` may be later than the
file's own mtime. The confirmed cause of violations is a pass stamping from the
scheduler's `next_run_at` instead of `datetime.now()` at write — the slot is
published in `jobs.json` and looks like a legitimate "this cycle" clock. A stamp
ahead of the write is a false-completion variant that corrupts scan ordering and
every "last reviewed" claim built on it, so it is a P1 finding, not a scan note.
Exit 0 = clean, 1 = forward stamps present, 2 = ledger unreadable (never treat 2
as clean). Full rationale and the journal-coherence findings:
`references/finch-scan-pitfalls.md` §11.

**Allocate the scan NUMBER, don't compute it.** The guard above fixes the STAMP;
the counter had the same class of bug and stayed unfixed until 2026-09-27. Never
write `scan_number = header + 1`: that field is a plain number each pass edits
by hand, with no lock, so two passes overlapping in wall-clock read the same
header and mint the same number. Observed live: `scan-174.json` and
`scan-2000.json` both carried 174 while the header sat at 173 — neither run
advanced it, which is the tell. Call
`python3 scripts/finch_scan_counter.py` FIRST and use the number it prints; it
flocks, floors on the max of (header, journals, journal prose, sidecar) so a
drifted header cannot re-mint a used number, and burns the number durably
before you write. BURNING rather than reserving is deliberate — a pass that dies
after allocating loses a number, which is safe; a reused number corrupts the
series. A collision you must adjudicate by hand gets `scan_number_suffix` in the
journal, which the guard excludes from the series and reports as ADJUDICATED
rather than re-reporting as an open duplicate.

**Task selection priority:** `action_required: true` first; then high > medium > low; then earliest due; `pending` before `in_progress`. Skip `action_required: false` + `in_progress` (events in flight). Nothing actionable → validate and close the top pending item.

**Work-execution rules** (details in `references/work-execution-procedures.md`): triage signal (real / stale / transient); actionability filter (unattended cron); pipeline resumption from the ledger; break repeated check-and-close loops; prescribed fixes may be wrong — verify self-recovery / fail-loud guards first (`references/work-prescribed-fix-selfrecovery-guard.md`).

**Mining frameworks** (`references/mining_methodology.md`): scope before transfer. User-scoped relationship corrections route to Chronicle/User Dreaming; only agent/system-general signals continue through Finch. For those, tag failures by phase — **Planning** → patch preconditions; **Execution** → patch gotchas; **Response** → patch output sections. Record corrections as `[CORRECTION] What / Why / When` so lessons transfer.

## Scanning gotchas (top traps)

Full bodies: `references/scanning-gotchas.md` (MCP/Gmail/cron-JSON) and `references/finch-scan-pitfalls.md` (task-list/cron state). The traps that bite most often:

- **Probe MCP tools ALONE before batching** — one bad tool name poisons the whole batch; MCP load state flips between runs (`tool_search` ≠ `tool_call`).
- **A connector/MCP tool is DEFERRED, not absent — probe `tool_describe` before recording a GAP.** A tool in the deferred catalog is not in the active tool list and invoking it directly returns "Tool does not exist" — which reads exactly like a missing capability. Before writing `degraded: <source>` or "absent from the tool catalog" for ANY MCP/connector tool, call `tool_describe` on the exact name; if it returns a schema, call it via `tool_call` and the source is live. Only report a GAP after `tool_describe` itself fails or is unavailable. Seven consecutive scans (#160–#166) recorded the whole google_workspace surface as absent and reported email/calendar/Drive UNVERIFIED when a single `tool_describe` would have proved otherwise. Same failure class as the metadata-only reads below: a partial read of the tool surface reported as a fact about the world instead of a fact about the read.
- **Resolve a cron delivery target under the PROFILE scope, not `$HERMES_HOME`** — `last_delivery_error` is stamped at the END of a run and only overwritten by the NEXT one, so on a weekly-ish job a since-fixed config reads as broken for days. The trap: `profiles/<profile>/cron/jobs.json` and `~/.hermes/cron/jobs.json` are ONE inode, but `load_gateway_config()` reads `$HERMES_HOME`. Under the ROOT home the telegram `PlatformConfig` is `enabled=False` and EVERY telegram-delivering job reports "platform 'telegram' not configured/enabled"; under the per-profile scope the same block is `enabled=True` and it resolves — which is what the live gateway does (multiplex serves a profile from the root process). Use `gateway.run._load_profile_secret_scope` + `_profile_runtime_scope(<profile_home>, secrets)` and resolve inside the `with`. Verified 2026-09-26: an out-of-scope probe reproduced the exact error for all 3 telegram jobs, in-scope resolved all 3. Also: a copied profile dir is NOT a registered profile — fixture-testing scope resolution by copying a tree falls back to root and proves nothing; validate both verdict directions in-process against the real profile instead. Watch: `scripts/ehcs_delivery_watch.py`.
- **`tool_describe` not_found is NOT sufficient either — `tool_search` must also fail to enumerate the source (hardened 2026-09-26, scan #176).** The rule above was still one probe short, and it cost a real false verdict: scan #171 got not_found on the three google_workspace names, correctly followed this rule, and then wrote "genuinely DEGRADED for the MCP path" into the task whose entire subject is false absence. Two scans later the same three tools answered normally (126 tools enumerated). A tool can be absent from `tool_describe` and still present in the deferred catalog, so the absence claim must survive BOTH probes: if `tool_search` enumerates the source with a non-zero tool_count, the tools are DEFERRED regardless of what `tool_describe` says. When the two disagree, pull the source by both paths (MCP tool AND direct API) and record `UNVERIFIED-MCP / VERIFIED-DIRECT` — never assert either one alone. Quote the counter-example in any future absence claim, not just the rule.
- **A returned `next_page_token` is not a completed sweep, and "126 messages over 2 pages" is a different claim from "30 results"** — walk pagination to exhaustion, and prefer `messages.list(maxResults=100)` + loop over paging MCP by hand; it is cheaper and it is exhaustive by construction. Reporting a page-1 read as a complete read is the same false-completion direction as any guard that logs a success as a failure.
- **The cheapest actionable-email signal is unread INBOX minus automated senders** — compute it directly (`INBOX` in labelIds AND `UNREAD` in labelIds AND sender matches no `noreply|no-reply|notification|donotreply|mailer|alerts@|...`). This gives one honest number instead of a prose judgement about subject lines, and it is what the report should lead with.
- **Allocate `scan_number` via `scripts/finch_scan_counter.py` before writing, every run** — it floors on header + journal numbers + prose numbers + the durable sidecar and burns under flock. Running `finch_ledger_guard.py` first AND last is the cheap half of the same discipline; read its exit code (0 clean / 1 forward-stamp / 2 unreadable) rather than its exit status alone, since a `2` looks like failure rather than "could not read".
- **A harvest that samples FIELDS or the FIRST match is a coverage claim, not a measurement — and two tools harvesting the same corpus differently is how it hides** (fixed 2026-09-27). The allocator floored on `run`/`source`/`summary` only, while the guard scanned whole documents, so 26 of 33 prose-carried numbers — up to #157 — were invisible to the floor while the guard saw every one; the guard's own `[COVERAGE]` count used `re.search` (FIRST prose number only) and a `(\d{2,3})` bound, so #91 was called lost and the series had already passed 176. Both now harvest the whole serialized document with `findall` and a loose bound, and the two patterns are asserted byte-identical by `test_finch_scan_counter.py`. The general rule: a floor may over-approximate safely (it only ever burns an unused number) and must never under-approximate; and when two tools read one corpus, assert their SETS AGREE on the real data instead of trusting each to be complete. Note the tests could not catch this because the fixture used `run`, the one field the old code did read — a test pinned to the fields that happen to work proves nothing about the ones that don't.
- **Adjudicate a duplicate scan_number as a COLLISION, never by merging or deleting — and check the references before renaming.** A duplicate means two runs minted one number; the evidence that decides which is which is (a) mtime order, earlier keeps the bare number, (b) payload identity — non-identical payloads mean two distinct runs, identical means one run written twice and nothing to adjudicate. `scan_number_suffix` in the journal body is what the guard keys on (`_adjudicated()`); renaming the FILE is a separate, riskier act. #132: `scan-0608.json` vs `scan-1000.json`, non-identical, 3h57m apart, so suffixed `132a` with the filename left alone because 6 files reference it by name — unlike `scan-174.json`, which was renamed to `scan-174a.json` because nothing did. Renaming a file that ingestion logs reference by name dangles every reference, and editing an append-only log to match falsifies a historical record.
- **Cron health only from `jobs.json`** — `hermes cron list` hides disabled/paused jobs and has no JSON mode; `consecutive_failures > 0` is the only reliable "broken now" gate; pin the LIVE path (never `state-snapshots/`).
- **`paused: true` is INERT on its own** — the gate is `cron/jobs.py:_has_pause_marker` (`state=='paused'` or `paused_at` non-null); the bare boolean is never read. Classify a job's real state on `paused` **OR** `enabled is false`, and import `is_job_runnable` rather than reimplementing the gate. Check with `scripts/pause_gate_watch.py`. Setting the boolean alone pauses nothing (this is how the 2026-09-17 load mitigation failed).
- **Diff registry snapshots OLDEST → NEWEST** — walking them newest→oldest while printing `prev→cur` as "removals" inverts the labels and will report a job as removed from a snapshot that contains it. If a removal set looks surprising, print an explicit containment map (present/absent per ordered state) before drawing any conclusion.
- **Test a `re_verify_trigger` against the FULL history, not just the edit it was written for** — `cron-bones-paused-error-cluster` clause 1 was checked only against the bones edit, so it read "nothing fires this" for 3 passes; walking the whole registry found a different, earlier removal it does match.
- **A clean `last_status`/`consecutive_failures` gate is a statement about the GATE, not about the world — it does not read `last_delivery_error`.** Observed 2026-09-27 (#955): 150/156 indigo jobs `last_status=ok`, `consecutive_failures=0` on every job, and BOTH live defects were sitting in `last_delivery_error` (a weekly telegram job with `platform 'telegram' not configured/enabled`; an hourly koda job at `last_status=delivery_failed` with `no delivery target resolved for deliver=all`). The reference script's error-gate returns 0 for both. A job that RUNS fine and fails to DELIVER is exactly the state a status-gate cannot see, so always ALSO enumerate every job carrying a non-null `last_delivery_error` / `last_delivery_unverified` and report it as a separate defect class. Field names in the live registry: `last_status`, `consecutive_failures`, `failure_streak`, `last_error`, `last_delivery_error`, `last_delivery_unverified`, `last_success_at` (frequently null even on healthy jobs — not a defect signal). `deliver: all` resolves to no target unless a catch-all channel exists; that is a one-field config defect recurring on every run of the job.
- **Never report "0 errors" from a summary or a prior scan** — derive it from a full-output grep of the live registry; verify recoveries against `last_run_at`.
- **A returned `next_page_token` is not a completed sweep** — `search_gmail_messages` returns ~30/page, and the token at the bottom of the response is easy to read as a footer. State the page count you actually pulled and which pages you deliberately skipped. A 2-day window that fits one page is complete; anything with unread pagination is a partial sweep and must be labelled `UNVERIFIED` (partial) rather than reported clean.
- **Email scan loops `page_token` to completion** — page-1-only misses high-value mail; classify metadata-first (`email-mcp-pagination-parsing.md`, `email-mcp-triage.md`).
- **Workspace MCP absent → pivot at once** to `scripts/gws_direct_puller.py` (googleapiclient; raw requests 404 through the host egress filter); record the source UNVERIFIED, never "no signal".
- **Never conclude "header-less" from `messages.list()`** — Gmail's `messages.list()` returns ids only; a `format=minimal` or metadata-only fetch renders From/To/Subject as empty strings, which reads as "no headers" but means *not requested*. Always `format='full'` before calling a message malformed. A real orphan is self-addressed (From == To) or a `Re:` whose thread holds exactly 1 message — threadId == messageId is NORMAL for a new outbound draft, so it is not an orphan test on its own (observed 2026-09-26: four "header-less" drafts were in fact fully-formed self-addressed PR-review replies).
- **Never batch >1 `patch` on one JSON file; `read_file` is not validation** — parallel patches interleave and corrupt; long single-line values defeat `patch`; only `json.load()` catches corruption.
- **`execute_code` is blocked in cron** — use `terminal python3`; write multi-KB scripts to a file first (inline payloads hit a stream timeout).
- **`python3 -c "<multi-statement body>"` is BLOCKED in cron too** — the Tirith scan rejects it as a "nested executable body [that] could not be resolved" because it cannot prove the inline body. This is a different block from `execute_code` and the error names neither, so it reads as a spurious scan failure rather than a policy. Write the snippet to `$TMPDIR/finch_*.py` and run `python3 <file>`. Every `python3 -c` that survives is a single simple expression; anything with a loop, a dict comprehension or several statements will be refused.
- **Do not reach for `git fsck --unreachable` to size a git repo's reclaim** — on a 900k-object repo it exceeds a 400s timeout. `git count-objects -vH` before and after, plus `du -sm .git`, answers "is there reclaimable space" far cheaper and is the measurement that belongs in a gate. Corollary for attribution: a drop in `du .git` with `garbage: 0 bytes` is a clean repack, and the packs that vanished are named in the before/after diff — no fsck needed.
- **Use absolute paths** — tilde expansion in `read_file`/`write_file` can double into a phantom `profiles/<p>/home/` tree; verify commons writes with `ls`/`readlink -f`; never delete a `commons/` file whose `realpath` is in the live tree.

## Storage & architecture

- Role: session mining engine — routes behavioral signals to durable targets (MEMORY.md, skill patches). Layout → `references/storage-layout.md`; signal types → `references/signal-types-table.md`.
- Cooperation: reads transcripts (read-only) + Chronicle BehavioralSignals; emits DecisionRecords; writes MEMORY.md **only** via `scripts/memory_guard.py` (`--apply --file ~/.hermes/profiles/<profile>/memories/MEMORY.md`).
- **MEMORY.md ownership**: a `pre_tool_call` hook (`agent-hooks/block-memory-tool.sh`, matcher `^memory$`) blocks the built-in `memory` tool (plus `memory.memory_enabled: false`); Finch is the sole maintainer.
- MEMORY.md = Tier 1 only — no pointers; ~500 chars when compacted; consolidate duplicate directives keeping the specific phrasing and both dates. After any write, re-read and grep a unique substring per intended block — a journal's `applied` count is not proof of persistence.

## Behavioral directives (priority 0)

"Always" / "Never" from the user is a priority-0 rule only when it is genuinely system-general: apply immediately and route to MEMORY.md under `## Always Rules` / `## Never Rules`, never batch with lower-priority findings. User-scoped directives route to Chronicle/User Dreaming and MUST NOT become global MEMORY.md rules.

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
| `finch_scan_counter.py` | flock-atomic scan-number allocator; max-floor over header/journals/prose/sidecar | `--peek`, `--floor`, `--json`; EXIT 0 / 1 unreadable / 2 lock held |
| `pause_gate_watch.py` | Claim-vs-enforcement check for the `paused` boolean (inert vs real markers) | `--json`, `--quiet`, `--tolerance N`; EXIT 0 ok / 1 unreadable / 2 drift |
| `check_no_pii.py` | PII gate CI runs before publish | `--quiet` |

Verify-script rules (canonical copy only; never hand-roll a sibling) → `references/sepagree-verify-rules.md`. Eviction priority + memory_state detail → `references/operational-gotchas.md` § Scripts.

## Self-update & platform notes

`finch.update` pulls the latest from GitHub; silent unless the version changed or it errors. Finch is designed for Hermes but degrades gracefully elsewhere — minimum viable platform: any harness with `write_file`, `read_file`, and `terminal`.
