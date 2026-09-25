## Support File Map

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
|| `references/forgetting_curve.md` | During MEMORY.md compaction — reinforcement scan, tier routing, consolidation, eviction ||
|| `references/file-governance.md` | Before routing findings — write targets, tier model, off-limits files, creation criteria ||
|| `references/signal-triage-before-fix.md` | Before executing any finch:work task — decompose multi-failure tasks into distinct root causes ||
|| `references/already-fixed-verification.md` | When finch:work asks to "resume" or "complete" an interrupted investigation — verify whether the code already implements the requested fixes before writing new code ||
|| `references/scan-error-classification.md` | During finch:scan when grouping errored cron jobs by root cause fingerprint (certifi, missing-script, missing-module, rate-limit, interpreter-shutdown, provider-error, provider-http400) ||
|| `references/cron-health-validation.md` | During finch:scan cron-health source — parse `jobs.json` directly, surface ALL `last_status=error` (incl. paused), classify transient/recovered vs paused-by-design vs real. Use when a scan might otherwise report "cron health clean" |
|| `references/email-mcp-pagination-parsing.md` | When finch:scan fetches Gmail via MCP — paginate to completion (page_token loop), pre-filter automated noise with `-from:()` before content fetch, strip residual batch to From/Subject/Date in terminal (avoid context flood; do NOT double-decode unicode_escape), and use `from:<addr> newer_than:Nd=0` as a "no reply" proof ||
|| `references/duplicate-task-detection.md` | When reading task-list.json in finch:work — detect and clean up duplicate task IDs |
|| `references/signal-types-table.md` | Before mining — signal type definitions and routing ||
|| `references/interactive-menu.md` | When invoked interactively via `/` command — two-level menu layout, Clarify timeout, response parsing, platform adaptation |
|| `scripts/memory_guard.py` | Deterministic safety floor for MEMORY.md — hard cap enforcement, directive protection, pointer stripping, atomic locked write. Run as final step of finch.compact or via finch:memory-guard-floor cron. ||
|| `scripts/verify_sepagree_signature.py` | When finch:work picks EMAIL-SEPAGREE (separation agreement) — reusable Docusign "unsigned" re-verifier; run via `terminal` python3, prints VERDICT. |
|| `scripts/finch_hooks_plugin.py` | Hermes Agent Hooks plugin for real-time signal capture, memory tool guard, subagent delegation tracking, and prompt section registration. ||
|| `references/hermes-hooks-integration.md` | When optimizing Finch for Hermes Agent Hooks — lifecycle events, plugin/shell/gateway hook patterns, real-time signal observation, memory tool interception, subagent monitoring. ||

## Additional files

| File | Notes |
|------|-------|
| `references/security_architecture.md` | Security Architecture Reference |
| `references/skill-audit-methodology.md` | Skill Audit Methodology |
| `references/manual-run-verification.md` | When the user says "run finch", jobs 401 en masse, or you must force a cron run |
| `references/sepagree-verify-rules.md` | When finch:work picks EMAIL-SEPAGREE — canonical-script rules for Docusign re-verification |
| `references/email-mcp-triage.md` | During email triage — metadata-first classification, full-body only for candidates |
| `references/work-execution-procedures.md` | Before executing any finch:work task — triage, actionability, resumption, anti-patterns |
| `references/work-prescribed-fix-selfrecovery-guard.md` | When a task prescribes a specific fix — check self-recovery / fail-loud guards first |
| `references/reference-file-workflow.md` | Before writing any reference file — genericisation placeholders and write workflow |
| `scripts/finch_scan_tasklist_rerank.py` | finch_scan_tasklist_rerank.py - safe re-rank + validate for ocas-finch task-list.json. WHY: finch:scan must... |
