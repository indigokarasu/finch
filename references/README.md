# Finch reference index

Every reference file, grouped by the job it supports. `SKILL.md` carries the steering entries; this is the full map. Read only the group for the step you are on.

## Start here: what Finch does now

| File | Read when |
|------|-----------|
| `inflight-tracker.md` | Running or changing `finch:track` (projects, in-flight tasks, todos; records only) |
| `workflow_the_core_loop.md` | Learning the job loop and what Finch owns versus Mentor and Forge |
| `scan-work-architecture.md` | Configuring the scheduled jobs (its `finch:work` sections are historical) |
| `manual-run-verification.md` | The user says "run finch", or jobs 401 at once |
| `manual_run_commands_recovery.md` | Forcing a run, commands, recovery after a failed run |
| `interactive-menu.md` | Finch is invoked interactively with a `/` command |
| `okrs.md` | `finch:weekly` and any review of Finch health |

## Session mining and skill updates

| File | Read when |
|------|-----------|
| `mining_methodology.md` | Before a mining run |
| `signal_patterns.md` | Matching corrections, directives, breakthroughs, methodologies |
| `signal-types-table.md` | Deciding what a signal is and where it goes |
| `active-review.md` | A review pass is about to report "nothing found" |
| `skill-library-maintenance.md` | After a session that produced a learning |
| `skill-update-directive.md` | End-of-session skill review |
| `skill-update-methodology.md` | Deciding what to save after a session and where |
| `skill-audit-methodology.md` | Auditing a skill's structure |

## Memory, routing and storage

| File | Read when |
|------|-----------|
| `forgetting_curve.md` | MEMORY.md compaction: reinforcement, tiers, eviction |
| `file-governance.md` | Routing a finding: write targets, tiers, off-limits files |
| `storage-layout.md` | Inspecting data directories or the package layout |
| `storage_behavioral_directives.md` | Any MEMORY.md write (only via `memory_guard.py`) |
| `reference-file-workflow.md` | Writing a reference file: genericise before you write (public repo) |

## Scan, cron health and verdicts

| File | Read when |
|------|-----------|
| `scanning-traps.md` | Before a `degraded:`, "absent" or "0 errors" verdict, or any count reported as complete |
| `scanning-gotchas.md` | Per-source scan mechanics (email and calendar parts are historical) |
| `finch-scan-pitfalls.md` | Traps seen running `finch:scan` against the live cron registry |
| `cron-health-validation.md` | Parsing `jobs.json` for the cron-health source |
| `scan-error-classification.md` | Grouping errored cron jobs by root-cause fingerprint |
| `cron_worker_shell_blocks_tirith_adapt_do_not_retry.md` | A cron-context shell command is blocked |
| `mail-self-reference-and-zero-vacuity.md` | Building any mail watcher, or quoting a zero |
| `rate-window-label-covers-published-number.md` | Publishing a rate or a windowed number |

## Ledger and scripts

| File | Read when |
|------|-----------|
| `ledger-and-clock-protocol.md` | Before any ledger, journal or scan-number write |
| `record-loss-and-identity-keys.md` | Changing a ledger writer or its identity keys |
| `retired-writer-class.md` | A script writes shared state on any invocation |
| `scripts-reference.md` | Before running or changing a script: flags, exit codes, tests |

## Pitfalls

| File | Read when |
|------|-----------|
| `pitfalls.md` | Before any Finch operation |
| `anti-patterns.md` | Before any Finch operation |
| `operational-gotchas.md` | Script details and operational traps |

## Platform

| File | Read when |
|------|-----------|
| `hermes-hooks-integration.md` | Using Hermes Agent Hooks for real-time capture |
| `security_architecture.md` | Reading a skills security audit result |

## Retired (`retired/`)

Historical only. Finch no longer runs the task executor (`finch:work`) or reads email, calendar or Drive (retired in 3.3.0). Keep these for context; never run their procedures.

| File | Was used for |
|------|--------------|
| `retired/work-execution-procedures.md` | `finch:work` triage and execution |
| `retired/work-prescribed-fix-selfrecovery-guard.md` | Checking a prescribed fix against self-recovery |
| `retired/already-fixed-verification.md` | Resuming an interrupted `finch:work` investigation |
| `retired/signal-triage-before-fix.md` | Splitting a task into root causes |
| `retired/duplicate-task-detection.md` | De-duplicating task-list IDs in `finch:work` |
| `retired/email-mcp-triage.md` | Inbox scan triage |
| `retired/email-mcp-pagination-parsing.md` | Paginating Gmail MCP results |
| `retired/gmail-content-batch-call-shape.md` | Gmail content-batch call shape |
