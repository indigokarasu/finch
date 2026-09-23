# Already-Fixed Verification (finch:work)

When a finch:work task asks to "resume" or "complete" an interrupted investigation, the fixes may already be in the codebase. Before writing new code, verify whether the diagnosis was already applied.

## The Pattern

A session identifies systemic issues (e.g., "no circuit breaker", "wrong crash classification", "no auto-recovery") and the task list records these as pending fixes. But the code may have already been patched — the investigation session produced findings that were implemented before the task was picked up, or the features existed and the investigation was working from stale assumptions.

## Procedure

1. **Read the actual code** — Don't trust the task description's claim that something is missing. Open the file and check. The task is a scan heuristic, not a diagnosis.
2. **Map each claimed issue to a code location** — For each issue the prior session identified, find the function/module that would contain the fix.
3. **Check for the fix pattern** — Look for:
   - Function names matching the issue (e.g., `_record_task_failure` for circuit breaker, `_classify_worker_exit` for crash classification)
   - Comments referencing the specific bug (e.g., "protocol violation", "rate-limit recovery", "clean_exit after rate limit")
   - Test files covering the exact scenario
4. **Run the relevant tests** — If tests exist for the claimed-missing feature, run them. If they pass, the feature is implemented.
5. **Verify the full chain** — A fix may exist but be incomplete. Check:
   - Detection: Does the code detect the condition correctly?
   - Classification: Does it categorize it properly?
   - Response: Does it take the right action (requeue, skip failure count, etc.)?
   - Guard: Does it prevent the bad outcome (e.g., breaker trip on rate-limit)?
6. **Mark done with evidence** — If all checks pass, mark the task done with specific file:line references and test results.

## Example (2026-06-29, task-<id>)

**Claimed issues:** "no circuit breaker, wrong crash classification (rc=0 after rate limit should signal rate_limited not crashed), no auto-recovery, wrong assignee routing, load balancing gap"

**Verification:**
- Circuit breaker: `_record_task_failure()` at kanban_db.py:5547 — trips after `failure_limit` consecutive failures, auto-blocks with `gave_up` event. ✅
- Crash classification: `_classify_worker_exit()` at kanban_db.py:5743 — handles `rate_limited` kind. `detect_crashed_workers()` at lines 6366-6412 — recovers rc=0 rate-limit exits from worker log. ✅
- Rate-limit without failure counting: Lines 6428-6447 — rate-limited exits skip `_record_task_failure`. ✅
- Task routing: `_dispatch_once_locked()` at kanban_db.py:7002 — default_assignee, per-profile caps, profile-existence checks. ✅
- Auto-recovery: `check_respawn_guard()` with rate-limit cooldown. ✅
- Tests: 392 kanban tests pass (223 + 169). ✅

**Outcome:** All 5 issues already fixed. Task marked done with evidence.

## Key Decision Rule

When a task says "implement X" and you find X already exists, the correct outcome is NOT "nothing to do" — it's "verify and close." The verification IS the work. Document what you checked so the next scan doesn't re-create the task.

## Distinction from Signal Triage

Signal triage (see `references/signal-triage-before-fix.md`) decomposes a task into distinct root causes. Already-fixed verification checks whether the code already implements the requested fix. Use signal triage when the task says "fix these errors." Use already-fixed verification when the task says "implement this feature" or "investigate this systemic issue."

## Mirror case: repair already landed while the task prose says "no progress"

Scan-side progress claims ("no repair progress in last-24h sessions") lag reality — a fix can land between the last signal update and the current run, and the applying actor may leave no message trace. Close repair tasks against the ARTIFACT's own evidence boundaries, not the task note:

1. **File boundary** — `stat` the file(s) the fix must have touched. An mtime inside the failure window, plus a named snapshot/backup (`.bak-*` carrying the fix label), is a fix fingerprint.
2. **Log boundary** — find the last-bad → first-good transition in the artifact's own operational log, and confirm the change time sits between the two runs that produced it.
3. **Live state files** — status/signature files the fixed component maintains (e.g. an alert's current status + dedup signature both reading OK).
4. **Live probe** — where a probe is cheap and side-effect-free, exercise the fixed path end-to-end.

If the boundaries line up, close as verified-fixed citing the boundary evidence — do not re-apply or "improve" the landed fix. If the artifact shows no change, only then treat the repair as outstanding. This beats actor attribution: state transitions cannot be misremembered.
