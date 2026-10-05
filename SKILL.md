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
  version: "3.2.2"
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
- memory compaction
- memory full / memory guard
---

> **PUBLIC REPO — GENERICISE EVERY REFERENCE** (`references/reference-file-workflow.md`,
> "Genericise Before You Write"); CI runs `scripts/check_no_pii.py`. **Route before
> you write:** this directory is for finch's OWN docs — a finding about another
> system (cron, MCP, Gmail, OAuth, git) belongs to that skill, never here.

# ocas-finch

Finch is the OCAS System Evolution Layer's self-improvement orchestrator: pure-LLM cron jobs plus one `no_agent` script floor (`finch:floor`). It mines 7 signal sources (cron health, email, calendar, sessions, Drive, kanban, system) and routes what it finds to durable targets.

Job names drift — enumerate the live registry, never a remembered set: `references/manual-run-verification.md`. Source table → `references/scan-work-architecture.md`.

## When to Use

- Scheduled self-improvement: `finch:scan` (2h), `finch:work` (30m), `finch:daily` (6am PT), `finch:weekly` (Sunday 8am PT).
- Manual session mining via `finch.mine` / `finch.run`; after major sessions, to detect corrections, directives, breakthroughs, methodologies.
- Memory at/near capacity: `finch.compact` / `memory_guard.py` — never hand-edit MEMORY.md to dodge the cap; Finch owns compaction.
- Skill library maintenance: route findings to SKILL.md patches.

### finch:scan checklist

Before each scan, verify the run is actually executing (not a no-op):

- [ ] Enumerate the live job registry from `jobs.json` — never rely on a remembered job-name set (names drift; see `references/manual-run-verification.md`)
- [ ] Confirm each signal source is reachable before declaring it `degraded:` or `absent` — an unreachable source is a GAP, not a zero
- [ ] Read `references/scanning-traps.md` and match the trap group for the step you are about to report on
- [ ] For any count reported as complete: prove the denominator is non-vacuous (see `references/mail-self-reference-and-zero-vacuity.md` for the mail case)
- [ ] Classify every errored job by fingerprint (`references/scan-error-classification.md`); `consecutive_failures > 0` = real, not transient

**Input → Output example.** A `finch:scan` run reads 7 signal sources (cron health, email, calendar, sessions, Drive, kanban, system) and produces a ledger entry with a `scan_number` (allocated by `finch_scan_counter.py`), a per-source status line, and a routing list of findings. A clean scan writes `scan_number: N` with zero findings; a degraded scan writes `degraded: <source>` alongside the findings it did collect. Never write `0 errors` without first confirming the source answered — a silent source and a clean source differ only in the ledger, and conflating them is the trap `references/scanning-traps.md` exists to prevent.

### finch:work checklist

Before executing any `finch:work` task:

- [ ] Triage the task against `references/work-execution-procedures.md` — is it actionable, resumable, or an anti-pattern?
- [ ] If the task prescribes a specific fix, read `references/work-prescribed-fix-selfrecovery-guard.md` first — check whether the fix is already self-recovering
- [ ] If resuming an interrupted investigation, read `references/already-fixed-verification.md` — verify the code already implements the requested fix before writing new code
- [ ] Decompose multi-failure tasks into distinct root causes (`references/signal-triage-before-fix.md`)
- [ ] Route each finding to its durable target per `references/file-governance.md`; user-scoped signals go to Chronicle/User Dreaming, never global behavior
- [ ] After the write, run the relevant test suite and confirm the ledger forward-stamp is clean (`finch_ledger_guard.py`)

## Why these rules hold

- **Never hand-edit MEMORY.md to dodge the cap.** `memory_guard.py` enforces a hard cap (`HERMES_MEMORY_CHAR_LIMIT`, default 2200) and a soft target (`HERMES_MEMORY_SOFT_TARGET`, default 500). Hand-editing bypasses the cap's directive protection and pointer stripping, so a later compaction pass can silently lose the very entries the edit was meant to preserve. Finch owns compaction because only it runs the full tier-routing pipeline (`references/forgetting_curve.md`); a manual edit is a partial compaction that leaves the reinforcement state inconsistent.
- **All scripts answer `--help` and exit 0 before doing any work.** This is load-bearing, not cosmetic: an audit that probes `--help` must not run a watcher, sweep a mailbox, or create a fixture tree. Three separate suites failed this check and, in one case, an unguarded `--help` created real directories in `/root` on every probe. The guard goes before any measurement, tempdir, subprocess, or write. **A WRITER that violates this is worse than a watcher**, because watchers publish wrong numbers and writers corrupt state: the per-profile `scripts/finch_update_tasklist.py` (retired 2026-10-05, `references/retired-writer-class.md`) had no argv handling at all and rewrote `as_of`, `last_work_cycle` and a whole task body on every invocation, including `--help`. Recovered only because it backed up first. **Never probe an unfamiliar script by running it — `read_file` it.** Absence of a guard is invisible to a static check that only looks for misplaced guards, and the per-profile `scripts/` dir is a second script surface no gate covered until #1193 extended `check_help_guard_placement.py` to it.
- **An idempotency guard needs a marker unique to the cycle.** `if TASK_ID in json.dumps(work_log)` matches every entry, because every entry embeds `task_id` — the write is then silently skipped forever and the record looks absent rather than skipped. Use a per-cycle nonce written into the entry; assert it is absent before the first write and present after.
- **Job names drift — enumerate the live registry, never a remembered set.** The cron daemon rewrites scheduler fields (`next_run_at`, `pending_slot`, `fire_claim`) on every fired job, and job names are reassigned across versions. A remembered set goes stale within a week and produces false `degraded:` verdicts.
- **A zero must be proved non-vacuous before it is quoted.** Finch's own output contains keyword probes that match finch's own mail watchers (see `references/mail-self-reference-and-zero-vacuity.md`). A "0 findings" result is only meaningful if the probe could have matched something.

## When NOT to Use

- User modeling or relationship adaptation — Chronicle owns durable user evidence and User Dreaming consolidates it; Finch mines agent/system learning signals.
- Skill evaluation scoring (Mentor), skill creation/architecting (Forge), entity identity resolution (Chronicle tools).
- Real-time behavioral adaptation — Finch operates on scheduled batches, not live interception; for that use Hermes Agent Hooks (`scripts/finch_hooks_plugin.py`, `references/hermes-hooks-integration.md`).

See `references/cron_worker_shell_blocks_tirith_adapt_do_not_retry.md` for details.
See `references/workflow_the_core_loop.md` for details.
See `references/storage_behavioral_directives.md` for details.

## Failure modes & error handling

| Symptom | Response |
|---------|----------|
| Job errors, cause unclear | Classify (`references/scan-error-classification.md`: HTTP 400 = MEDIUM, interpreter-shutdown = transient); `consecutive_failures` > 0 = real. |
| Multiple jobs 401 at once | MCP-auth (stale `[mcp_servers]` in the profile `.env`) vs provider-auth (restart the gateway). |
| Workspace source unreadable | Record a GAP; carry prior state forward as UNVERIFIED — never "no signal". |
| Signal source down | Degraded mode: continue with remaining inputs, log `degraded: <source>`. |
| Memory write rejected | `finch.compact` / `memory_guard.py` — never hand-edit to dodge the cap. |

See references/manual_run_commands_recovery.md for details.
## Support file map

Steering entries only — every other file is in `references/finch-support-map.md`.

| File | When to read |
|------|--------------|
| `references/finch-support-map.md` | Any file not listed here — full per-file map |
| `references/scanning-traps.md` | Before writing a `degraded:`/"absent"/"0 errors" verdict, or any count you will report as complete — 43 dated traps in 7 groups; read the one matching your step |
| `references/ledger-and-clock-protocol.md` | Before any ledger, journal, or scan-number write, and before changing a clock rule |
| `references/scripts-reference.md` | Before running or changing a script — flags, exit codes, tests to run first |
| `references/scanning-gotchas.md` · `finch-scan-pitfalls.md` · `cron-health-validation.md` · `scan-error-classification.md` · `email-mcp-triage.md` | During a scan — per-source mechanics and error classification |
| `references/mail-self-reference-and-zero-vacuity.md` | Building or running ANY mail watcher — a keyword probe here matches finch's own output, and a zero must be proved non-vacuous before it is quoted |
| `references/work-execution-procedures.md` · `work-prescribed-fix-selfrecovery-guard.md` · `signal-triage-before-fix.md` · `already-fixed-verification.md` | Before any finch:work task, and before honouring a prescribed fix |
| `references/pitfalls.md` · `operational-gotchas.md` · `file-governance.md` · `forgetting_curve.md` · `mining_methodology.md` · `manual-run-verification.md` | Before any finch op; routing targets; compaction; mining; "run finch" and 401 triage |

## Scripts

Flags, exit codes, and the tests to run before changing any script:
`references/scripts-reference.md`. The four you will actually run are
`finch_ledger_guard.py` (gate every ledger write), `finch_scan_counter.py`
(allocate `scan_number`), `finch_ledger_write.py` (sanctioned write choke
point), and `memory_guard.py` (the only sanctioned MEMORY.md writer). All
answer `--help` and exit 0 **before doing any work** — that is load-bearing,
not cosmetic: an audit that probes `--help` must not run a watcher or create a
fixture tree.

## Self-update & platform notes

`finch.update` pulls the latest from GitHub; silent unless the version changed or it errors. Finch is designed for Hermes but degrades gracefully elsewhere — minimum viable platform: any harness with `write_file`, `read_file`, and `terminal`.
