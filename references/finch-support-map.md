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
|| `references/email-task-draft-workflow.md` | When finch:work picks an email task requiring contact with a third party not in the thread — full draft workflow (fetch thread → find contact → draft → save → mark done) ||| `references/email-thread-verification.md` | When finch:work picks an email "track response" task — search + fetch thread → check last sender → determine if substantive reply received → update note field. Includes `google_auth.py` fallback AND a direct `Credentials`-from-live-store-JSON alternative for when MCP Gmail tools are unavailable in cron; plus the Docusign "unsigned" verification recipe (0 "Completed" + 1 begin-signing = proof of non-signature) for the recurring EMAIL-SEPAGREE P1. ||| `references/gmail-token-expired-draft-workflow.md` | When finch:work picks an email task but Gmail API token is expired/unavailable — cached data search, local draft creation in drafts.jsonl, task-list update pattern for degraded mode. ||
|| `references/oauth-failure-cron-diagnostic.md` | When finch:work picks an OAuth failure task in cron context — diagnostic flow (token expired vs. revoked vs. malformed), auth URL generation for reporting, task-list update pattern for `blocked` status. Distinguishes "auto-refreshing" from "needs re-auth" from "never authed". ||
|| `references/systemic-oauth-failure-detection.md` | When 4+ cron jobs fail simultaneously with HTTP 400 on oauth2.googleapis.com/token — systemic revocation pattern, fingerprint, affected jobs list, correct response (one task, not N). Confirmed 2026-06-29. ||| `references/disk-monitoring-pattern.md` | When a finch:work task involves disk usage investigation — cascade from `df -h` down to specific large files, with known consumers table and cleanup commands ||
|| `references/custodian-error-investigation.md` | When a finch:work task involves a custodian error (e.g., custodian:deep Broken pipe) — investigation pattern for journal files and issues.jsonl ||
|| `references/composio-cron-tool-pattern.md` | When finch:scan needs email/calendar/drive data in cron context — how to call Google APIs via COMPOSIO_SEARCH_TOOLS + COMPOSIO_MULTI_EXECUTE_TOOL |
|| `references/scan-error-classification.md` | During finch:scan when grouping errored cron jobs by root cause fingerprint (certifi, missing-script, missing-module, rate-limit, interpreter-shutdown, provider-error, provider-http400) ||
|| `references/cron-health-validation.md` | During finch:scan cron-health source — parse `jobs.json` directly, surface ALL `last_status=error` (incl. paused), classify transient/recovered vs paused-by-design vs real. Use when a scan might otherwise report "cron health clean" |
|| `references/runaway-process-pattern.md` | When finch:scan detects a process consuming >50% CPU for >5 min — diagnosis, decision tree, and resolution for stuck background processes from kanban tasks ||
|| `references/email-mcp-pagination-parsing.md` | When finch:scan fetches Gmail via MCP — paginate to completion (page_token loop), pre-filter automated noise with `-from:()` before content fetch, strip residual batch to From/Subject/Date in terminal (avoid context flood; do NOT double-decode unicode_escape), and use `from:<addr> newer_than:Nd=0` as a "no reply" proof ||
|| `references/session-20260629-finch-work-cascade-skip.md` | When finch:work faces multiple pending tasks and a critical infrastructure failure (OAuth, disk, provider) — skip the entire dependent cluster without per-task evaluation |
|| `references/duplicate-task-detection.md` | When reading task-list.json in finch:work — detect and clean up duplicate task IDs |
|| `references/session-20260630-scan12-mcp-unreachable.md` | When finch:scan cannot access email/calendar/drive MCP tools in cron context — confirms MCP is LLM-session-only, no CLI workaround, cached-data fallback required. Also covers kanban board systemic failure patterns and gateway RSS growth tracking. || `references/stale-cron-task-detection.md` | When finch:work picks a task referencing cron jobs — verify jobs still exist before attempting fixes ||
|| `references/patch-json-tool-behavior.md` | When using `patch` on JSON files — escape-drift errors, non-blocking pagination warnings, recommended patterns for cron context ||
|| `references/cron-json-edit-pattern.md` | Cron-scope JSON edits without execute_code — patch-lint-doesn't-block, trailing-comma/backslash corruption, validate-after-edit, batch-probe rule for untrusted MCP tools ||
|| `references/signal-types-table.md` | Before mining — signal type definitions and routing ||
|| `references/session-mining-state-db-recipe.md` | When `session_search` drowns interactive sessions in cron noise or fails — exact `state.db` SQL recipe (indigo profile store, read-only + busy_timeout), JSON `content` parse, context-compaction-header false-positive filter, and the MEMORY.md profile-path trap ||
|| `references/interactive-menu.md` | When invoked interactively via `/` command — two-level menu layout, Clarify timeout, response parsing, platform adaptation |
|| `scripts/memory_guard.py` | Deterministic safety floor for MEMORY.md — hard cap enforcement, directive protection, pointer stripping, atomic locked write. Run as final step of finch.compact or via finch:memory-guard-floor cron. ||
|| `scripts/verify_sepagree_signature.py` | When finch:work picks EMAIL-SEPAGREE (Innovaccer Sep Agreement) — reusable Docusign "unsigned" re-verifier; run via `terminal` python3, prints VERDICT. |
|| `references/concurrent-write-recovery.md` | When a write_file/read_file warns of a sibling-subagent concurrent modify, OR read_file/search_files throw `DaemonThreadPoolExecutor` — read-back + `stat` mtime check, `terminal` fallback. ||

