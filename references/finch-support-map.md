## Support File Map

Every file in this skill, with the condition that triggers reading it. SKILL.md holds
the steering entries only; read this file when the steering entries don't cover the
file you need.

| File | When to read |
|------|-------------|
| `references/active-review.md` | Before scanning for signals |
| `references/signal_patterns.md` | Before mining sessions |
| `references/mining_methodology.md` | Before first mining run |
| `references/scan-work-architecture.md` | Before configuring scan/work jobs |
| `references/skill-library-maintenance.md` | After any session that produces a learning |
| `references/skill-update-directive.md` | During end-of-session skill review |
| `references/pitfalls.md` | Before any finch operation |
| `references/anti-patterns.md` | Before any finch operation — 10 anti-patterns including declaration of victory and code fence pitfalls |
| `references/okrs.md` | During OKR evaluation |
| `references/storage-layout.md` | When inspecting data directories or skill package structure |
| `references/forgetting_curve.md` | During MEMORY.md compaction — reinforcement scan, tier routing, consolidation, eviction |
| `references/file-governance.md` | Before routing findings — write targets, tier model, off-limits files, creation criteria |
| `references/signal-triage-before-fix.md` | Before executing any finch:work task — decompose multi-failure tasks into distinct root causes |
| `references/already-fixed-verification.md` | When finch:work asks to "resume" or "complete" an interrupted investigation — verify whether the code already implements the requested fixes before writing new code |
| `references/scan-error-classification.md` | During finch:scan when grouping errored cron jobs by root cause fingerprint (certifi, missing-script, missing-module, rate-limit, interpreter-shutdown, provider-error, provider-http400) |
| `references/cron-health-validation.md` | During finch:scan cron-health source — parse `jobs.json` directly, surface ALL `last_status=error` (incl. paused), classify transient/recovered vs paused-by-design vs real. Use when a scan might otherwise report "cron health clean" |
| `references/email-mcp-pagination-parsing.md` | When finch:scan fetches Gmail via MCP — paginate to completion (page_token loop), pre-filter automated noise with `-from:()` before content fetch, strip residual batch to From/Subject/Date in terminal (avoid context flood; do NOT double-decode unicode_escape), and use `from:<addr> newer_than:Nd=0` as a "no reply" proof |
| `references/duplicate-task-detection.md` | When reading task-list.json in finch:work — detect and clean up duplicate task IDs |
| `references/signal-types-table.md` | Before mining — signal type definitions and routing |
| `references/interactive-menu.md` | When invoked interactively via `/` command — two-level menu layout, Clarify timeout, response parsing, platform adaptation |
| `scripts/memory_guard.py` | Deterministic safety floor for MEMORY.md — hard cap enforcement, directive protection, pointer stripping, atomic locked write. Run as final step of finch.compact or via finch:memory-guard-floor cron |
| `scripts/verify_sepagree_signature.py` | When finch:work picks EMAIL-SEPAGREE (separation agreement) — reusable Docusign "unsigned" re-verifier; run via `terminal` python3, prints VERDICT |
| `scripts/finch_hooks_plugin.py` | Hermes Agent Hooks plugin for real-time signal capture, memory tool guard, subagent delegation tracking, and prompt section registration |
| `references/hermes-hooks-integration.md` | When optimizing Finch for Hermes Agent Hooks — lifecycle events, plugin/shell/gateway hook patterns, real-time signal observation, memory tool interception, subagent monitoring |
| `references/security_architecture.md` | Security Architecture Reference |
| `references/skill-audit-methodology.md` | Skill Audit Methodology |
| `references/manual-run-verification.md` | When the user says "run finch", jobs 401 en masse, or you must force a cron run |
| `references/sepagree-verify-rules.md` | When finch:work picks EMAIL-SEPAGREE — canonical-script rules for Docusign re-verification |
| `references/email-mcp-triage.md` | During email triage — metadata-first classification, full-body only for candidates |
| `references/work-execution-procedures.md` | Before executing any finch:work task — triage, actionability, resumption, anti-patterns |
| `references/work-prescribed-fix-selfrecovery-guard.md` | When a task prescribes a specific fix — check self-recovery / fail-loud guards first |
| `references/reference-file-workflow.md` | Before writing any reference file — genericisation placeholders and write workflow |
| `scripts/finch_scan_tasklist_rerank.py` | finch_scan_tasklist_rerank.py - safe re-rank + validate for ocas-finch task-list.json. WHY: finch:scan must not silently corrupt the task list it reads |
| `references/finch-workflow.md` | Before writing a `degraded:`/"absent"/"0 errors" verdict, or any count you will report as complete — 43 dated traps in 7 groups; read the one matching your step |
| `references/ledger-and-clock-protocol.md` | Before any ledger, journal, or scan-number write, and before changing a clock rule |
| `references/scripts-reference.md` | Before running or changing a script — flags, exit codes, tests to run first |
| `references/scanning-gotchas.md` · `references/finch-scan-pitfalls.md` · `references/cron-health-validation.md` · `references/scan-error-classification.md` · `references/email-mcp-triage.md` | During a scan — per-source mechanics and error classification |
| `references/mail-self-reference-and-zero-vacuity.md` | Building or running ANY mail watcher — a keyword probe here matches finch's own output, and a zero must be proved non-vacuous before it is quoted |
| `references/finch-manual-run.md` · `references/work-execution-procedures.md` · `references/work-prescribed-fix-selfrecovery-guard.md` · `references/already-fixed-verification.md` | Before any finch:work task, and before honouring a prescribed fix |
| `references/finch-storage-directives.md` · `references/pitfalls.md` · `references/operational-gotchas.md` · `references/file-governance.md` · `references/forgetting_curve.md` · `references/mining_methodology.md` · `references/manual-run-verification.md` | Before any finch op; routing targets; compaction; mining; "run finch" and 401 triage |
| `references/workflow_the_core_loop.md` | Before writing a `degraded:`/"absent"/"0 errors" verdict, or any count you will report as complete |
| `references/manual_run_commands_recovery.md` | Before executing any finch:work task, and before honouring a prescribed fix |
| `references/cron_worker_shell_blocks_tirith_adapt_do_not_retry.md` | During finch:scan when evaluating cron job commands |
| `references/storage_behavioral_directives.md` | When inspecting data directories or skill package structure |