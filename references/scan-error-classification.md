# Scan-Side Error Classification (finch:scan)

When finch:scan reads cron health data, it must classify errored jobs into distinct failure categories before creating tasks. A single "cron errors" task with N affected jobs is not actionable — the work agent needs decomposed, root-cause-specific tasks.

## Classification Procedure

1. **Collect all errored jobs** — Read both `~/.hermes/cron/jobs.json` and `~/.hermes/profiles/indigo/cron/jobs.json`. Filter for `last_error != None` or `last_status == 'error'`.

2. **Extract error fingerprints** — For each errored job matching the detection logic above, extract the error signature:
   - `certifi.*CA bundle` → **certifi** category
   - `Script not found: <path>` → **missing-script** category
   - `Script exited with code 1` + `can't open file '<path>': [Errno 2]` → **missing-script** category (the script path in the cron config points to a file that does not exist — confirmed by running the script directly)
   - `HTTP 429` → **rate-limit** category
   - `cannot schedule new futures after interpreter shutdown` → **interpreter-shutdown** category (transient — self-resolves on next run)
   - `Script exited with code 1` → **script-exit** category (check stdout for detail)
   - `ModuleNotFoundError: No module named '<X>'` → **missing-module** category (Python dependency not installed in the runtime environment)
   - `RuntimeError: Provider returned error` → **provider-error** category (LLM provider transient failure — usually self-resolves on next run)
   - `HTTP 400` (not on oauth2.googleapis.com) → **provider-http400** category (LLM provider returning HTTP 400 — may indicate invalid API key, malformed request, or provider-side rejection. NOT OAuth-related. Check if multiple jobs fail simultaneously = provider-side issue, or one job = config/credential issue. Distinguish from oauth-token-expired by endpoint URL.)
   - `HTTPError 400.*oauth2.googleapis.com/token` or `invalid_grant.*expired or revoked` or `Token has been expired or revoked` → **oauth-token-expired** category (CRITICAL — Google OAuth refresh token expired/revoked. Not transient. Blocks all Google Workspace API including email:check cron, Gmail, Calendar, Drive. Also affects any Python script using `google_auth_mcp.py` or `google_auth.py` — including `ocas-tasks/tasks_monitor.py` which is called by `monitor:list`.)
   - `error: "None"` string with `failures > 0` → **investigate** category (ambiguous — could be transient or a real issue without error detail)
   - When classifying `script-exit-code-1` errors, **run the underlying script directly** (`timeout 15 python3 <script> --mode check 2>&1`) to capture stderr. The exit code alone does not reveal whether the failure is in the script's own logic or in a downstream dependency (e.g., `tasks_monitor.py` failing on OAuth). Confirmed 2026-06-29: `monitor:list` exit code 1 was actually `ocas-tasks/tasks_monitor.py` failing on `HTTPError 400` from `oauth2.googleapis.com/token` — same root cause as email:check.
   - Multiple cron jobs failing with `HTTPError 400` on the same token endpoint is a **single root cause with wide blast radius**  under ONE task listing all affected components. Do not create separate tasks per job.
   - Anything else → **other** category

   
   **Note:** A job can appear in multiple categories. When `error: "None"` is present with `failures > 0`, it means the job errored but no captured error message was recorded — check journal logs or rerun for diagnosis. Observed 2026-06-25: `weave-enrichment-health-check` had `error: "None"`, `failures: 1`, `state: "scheduled"`.

3. **Group by fingerprint** — Count jobs per category. Each category becomes a separate task.

4. **Classify severity**:
   - **oauth-token-expired**: CRITICAL — blocks all Google Workspace API access (Gmail, Calendar, Drive) AND causes dependent cron jobs to fail. Not transient — requires user re-authentication. Scan must report this as a persistent blocker every run until resolved.
   - **certifi**: HIGH — blocks all LLM-dependent jobs system-wide
   - **missing-script**: HIGH — indicates deployment/path regression
   - **rate-limit**: LOW — transient, self-resolves, monitoring only
   - **interpreter-shutdown**: LOW (was MEDIUM, corrected 2026-06-28) — **always transient**. Python `concurrent.futures` raises this when an executor schedules work during interpreter shutdown (process cleanup). The executor state resets between runs, so the next scheduled run succeeds without intervention. Confirmed: 3 jobs hit this on Jun 23 (single gateway restart), all recovered on next run. Create a monitoring task at most — never HIGH or MEDIUM. Only escalate to MEDIUM if 3+ CONSECUTIVE failures persist after the job has re-run at least once.
   - **missing-module**: MEDIUM — a Python package required by a cron script is not importable in the runtime environment. Not transient (won't self-resolve). **However**: always verify the module is actually missing before attempting a fix — check `python3 -c "import <module>"` in the venv. The scan may report a ModuleNotFoundError that was transient (package was installed between scan and work). Fix (if confirmed missing): `pip install <module>` in the venv that runs the cron. Confirmed 2026-06-28: `email:check` (25c06979ccc7) was reported as missing `googleapiclient`, but `python3 -c "from googleapiclient.errors import HttpError"` succeeded — the error was transient. Job had `last_status: ok`, `consecutive_failures: 0`.
   - **provider-error**: LOW — `RuntimeError: Provider returned error` indicates the LLM provider (e.g., OpenRouter) returned a transient error. These self-resolve on the next run. Only escalate to MEDIUM if the same job fails with this error for 3+ consecutive runs. Confirmed 2026-06-28: haiku:morning-scan, taste:scan, and 10khr-grind all hit this simultaneously — suggests a provider-side outage, not individual job issues.
   - **provider-http400**: MEDIUM — HTTP 400 from LLM provider endpoints (NOT OAuth). Distinct from `provider-error` (RuntimeError) and `oauth-token-expired` (HTTP 400 on oauth2.googleapis.com). When 4+ jobs fail simultaneously with HTTP 400, it suggests a systemic provider credential or configuration issue (e.g., API key expired, account billing issue, provider rejecting request format). Escalate to HIGH if it persists across consecutive runs. Confirmed 2026-06-29: 4 jobs (custodian:light, sands:conflict-scan, dispatcher, Koda Dispatcher) failed simultaneously with HTTP 400 — NOT OAuth-related, NOT RuntimeError.
   - **investigate** (error=None with failures>0): LOW — transient or no-detail, monitor
   - **script-exit**: varies — check stdout for root cause

5. **Create tasks per category** — Each gets its own task with:
   - Affected job count
   - Specific error message
   - Suggested fix or "monitoring" status
   - Source: "cron"

## Example: 2026-06-24 Scan (updated 2026-06-24 22:00)

13 errored jobs decomposed into:

| Category | Count | Severity | Affected Jobs | Root Cause |
|----------|-------|----------|---------------|------------|
| certifi CA bundle | 5 | HIGH | haiku:morning-scan, haiku:follow-maintenance, scout:research, bower:scan, scout:sources-refresh | `cacert.pem` missing from venv path |
| missing-script / path-not-found | 6 | HIGH | monitor:email, monitor:koda-issues, monitor:list, monitor:styx, gens:sync, dispatch:triage-morning | Script file not found at configured path |
| delivery-error | 2 | HIGH | dispatch:briefing-deliver, (monitor:email also has delivery_err) | Job ran but output could not be delivered to destination |

**Key observation:** The `monitor:email` job appears in BOTH missing-script AND delivery-error categories — it failed at the script stage AND had a delivery error recorded. When a job has both `last_status='error'` AND `last_delivery_error` set, the delivery error may be a secondary symptom (the script failed, so nothing was delivered). Always check `last_delivery_error` separately and note overlap.

**Two distinct root causes requiring different fixes:**
1. **certifi** → `pip install --force-reinstall certifi openai httpx` (5 jobs)
2. **Script path / deployment regression** → Verify script files exist at configured paths, fix paths or restore files (6 jobs)
3. **Delivery errors** → Check delivery configuration (webhook URL, channel). May resolve when script errors are fixed (2 jobs)

## Example: 2026-06-28 Scan (updated 2026-06-28 23:03)

5 errored jobs decomposed into:

| Category | Count | Severity | Affected Jobs | Root Cause |
|----------|-------|----------|---------------|------------|
| provider-error | 3 | LOW | haiku:morning-scan, taste:scan, 10khr-grind | `RuntimeError: Provider returned error` — simultaneous failure suggests provider-side outage. **All recovered** — `consecutive_failures: 0`, `last_status: ok` on next run. |
| oauth-token-expired | 1 | CRITICAL | email:check | `HTTPError 400 Bad Request` on `oauth2.googleapis.com/token` — Google refresh token expired/revoked. Blocks all Google Workspace API access (Gmail, Calendar, Drive). |
| script-exit-code-1 | 1 | MEDIUM | monitor:list | `Script exited with code 1` — check stdout for root cause. Not classified further without output. |

**Key observations:**
1. 3 provider errors hitting at once (different jobs, different schedules) is a classic provider-side signal — not 3 independent job failures. Group as a single transient event, create one LOW task, and check recovery on next run. **Confirmed recovered** on next run.
2. OAuth token expiry is a persistent (non-transient) error — it will NOT self-resolve. Requires user action (re-authentication). Severity is CRITICAL because it blocks 3 signal sources (email, calendar, drive) AND causes a cron job failure.
3. `monitor:list` exit code 1 is a new signature — investigate stdout to classify further.

**Action items:**
- oauth-token-expired → User must re-authorize Google OAuth. No programmatic fix available.
- provider-error → resolved (all 3 jobs recovered). Mark task done.
- script-exit-code-1 → Investigate `monitor:list` script output to determine root cause.

## Example: 2026-06-29 Scan (updated 2026-06-29 22:01)

2 errored jobs decomposed into:

| Category | Count | Severity | Affected Jobs | Root Cause |
|----------|-------|----------|---------------|------------|
| oauth-token-revoked | 2 | CRITICAL | email:check, monitor:list | `HTTPError 400` on `oauth2.googleapis.com/token`. Both confirmed as SAME root cause: Google OAuth refresh token revoked. monitor:list's underlying `tasks_monitor.py` (ocas-tasks skill) also fails on token refresh. |

**Key observations — OAuth blast radius expanded:**
1. The OAuth revocation now affects **3 distinct components**: `email:check` cron, `monitor:list` cron, AND the `ocas-tasks/tasks_monitor.py` script (called by monitor:list). The tasks monitor also cannot access Google Tasks API.
2. When classifying OAuth errors, check the underlying script of `monitor:*` jobs — many fail not from their own logic but from the Python library they invoke. Run the underlying script directly (`timeout 15 python3 <script> --mode check`) to see if the error is in the wrapper or the downstream dependency.
3. Multiple cron jobs failing with `HTTPError 400` on the same URL (`oauth2.googleapis.com/token`) is a **single root cause with a wide blast radius** — do NOT create separate tasks per job. Group under one task and note all affected components in the `signal` field.
4. `monitor:list` was previously classified as `script-exit-code-1` — but the exit code 1 was actually from `tasks_monitor.py` failing on OAuth. When investigating "exit code 1" errors, always run the script directly to capture the actual stderr — the traceback reveals the true root cause.

**Action items:**
- oauth-token-revoked → Same resolution as task_019. User must re-authorize Google OAuth. All 3+ affected components recover automatically once token is restored.
- **missing-script (email:check, historical)** → In earlier scans, the cron job `25c06979ccc7` was reported as pointing to a non-existent `email_check.py`. This was incorrect — the script exists at `/root/.hermes/scripts/email_check.py` and fails with `HTTPError 400` from OAuth revocation, not a missing file. The actual email scanning scripts in the ocas-dispatch skill directory are `gmail_scan.py` and `check_unread.py`. When investigating "missing script" errors, always verify with `ls -la <path>` before concluding the file doesn't exist — the error may be a downstream import failure (e.g., `google_auth_mcp.py` failing on token refresh) rather than the script file itself being missing.

## Example: 2026-06-29 Scan #3 (17:11 UTC)

3 errored jobs decomposed:

| Category | Count | Severity | Affected Jobs | Root Cause |
|----------|-------|----------|---------------|------------|
| oauth-token-revoked | 2 | CRITICAL | email:check (25c06979ccc7), monitor:list (39b7edc44b35) | `HTTPError 400` on `oauth2.googleapis.com/token`. Single root cause, wide blast radius. |
| missing-script (historical) | 1 | HIGH | email:check (25c06979ccc7) | ~~Script `email_check.py` does not exist~~ INCORRECT — the script exists at `/root/.hermes/scripts/email_check.py` but fails on OAuth. This was a misclassification in earlier scans. The job's true error is oauth-token-revoked. |
| rate-limit | 1 | LOW | bower:scan (d751b1530df5) | `HTTP 429` — transient provider rate limit. |

**Key observations — email:check double-counting:**
1. `email:check` appears in BOTH oauth-token-revoked AND missing-script categories. The script file doesn't exist, so it exits code 1 before even attempting OAuth. The OAuth error on this job is from a previous run when the script existed but the token was already revoked.
2. When a job appears in multiple categories, the **script-level error takes precedence** — fix the script path first, then re-evaluate whether the OAuth error persists.
3. The fix for `email:check` is trivial: update the cron's `script` field to point to `gmail_scan.py` or `check_unread.py` (whichever is the correct email scanning script), or remove the job if it's redundant with another email-checking cron.

**Action items:**
- oauth-token-revoked → Same resolution as task_019. User must re-authorize Google OAuth. All affected components recover automatically once token is restored.
- ~~missing-script → Update email:check script path. 30-second fix.~~ INCORRECT — the script exists; the real error is OAuth. The missing-script classification was wrong.
- rate-limit → Monitor.

## Example: 2026-06-29 Scan #2 (07:05 UTC)

2 errored jobs decomposed:

| Category | Count | Severity | Affected Jobs | Root Cause |
|----------|-------|----------|---------------|------------|
| oauth-token-revoked | 2 | CRITICAL | email:check (25c06979ccc7), monitor:list (39b7edc44b35) | Both refreshed error at 00:02:52 today. Same `HTTPError 400` on `oauth2.googleapis.com/token`. OAuth still unresolved from previous scan. |

**Key insight — task consolidation**: The `monitor:list` job was previously classified as a separate `script-exit-code-1` task (task_022). Investigation confirmed it shares the exact same root cause as `email:check` — both fail on `google_auth_mcp._refresh_token` → `HTTPError 400`. **Correct action**: Mark the duplicate task (task_022) as `done` with resolution "duplicate of task_019." Do NOT create separate tasks for each job when the error fingerprint is identical.

**Workflow signal**: The P4 Timeline live write (kanban task `t_b8179ffa`) is actively running as a background process (PID via `ps aux | grep run_ingest`). This is an in-progress session that should be noted but not interrupted.

## Example: 2026-07-06 Scan (15:14 PT) — Gate Rule Working

140 jobs checked across both jobs.json files. **182 jobs** showed `last_status: "error"` with non-null `last_error` strings. **ALL 182 had `consecutive_failures: 0`** — zero active failures.

**Result:** Correctly reported "cron health: all clear" and created **zero error tasks**. No CRITICAL or HIGH tasks generated despite 182 jobs with stale error markers.

**Key validation:** The `consecutive_failures > 0` gate prevented the exact misdiagnosis pattern from Scan #13 (2026-06-30). The 182 stale errors were all from jobs that had recovered on subsequent runs (error strings persist as artifacts but consecutive_failures resets to 0).

**One exception noted:** `weave:sync-google` had `last_error: "RuntimeError: Error code: 402 - This request requires more credits..."` but `consecutive_failures: 0`. Since this is a credits/billing error (not transient provider error), it warrants monitoring but not a CRITICAL task. Created `weave_sync_google_credits` as MEDIUM priority task for investigation, separate from the provider-error classification.

**Action items:**
- No CRITICAL/HIGH tasks created (gate held)
- weave:sync-google credits issue → MEDIUM task for investigation
- All other error markers confirmed stale

5 errored jobs decomposed:

| Category | Count | Severity | Affected Jobs | Root Cause |
|----------|-------|----------|---------------|------------|
| provider-http400 | 4 | MEDIUM | custodian:light, sands:conflict-scan, dispatcher, Koda Dispatcher | HTTP 400 from LLM provider — NOT OAuth, NOT RuntimeError. 4 jobs simultaneously = systemic credential/config issue. |
| rate-limit | 1 | LOW | bower:scan | HTTP 429 — transient provider rate limit. |

**Key observations — new error fingerprint (provider-http400):**
1. These are HTTP 400 errors from LLM provider endpoints (e.g., OpenRouter `/chat/completions`), NOT from `oauth2.googleapis.com/token`. The error message format is `RuntimeError: HTTP 400: Provider returned error` or similar.
2. Distinct from `provider-error` (RuntimeError without HTTP status) and `oauth-token-expired` (HTTP 400 specifically on Google's token endpoint).
3. When 4+ unrelated jobs fail simultaneously with HTTP 400, the root cause is likely: expired API key, billing issue, provider-side migration, or request format change.
4. **Action**: Check provider dashboard for API key status, billing, and request format changes. Do NOT assume transient — HTTP 400 will not self-resolve like HTTP 429 or RuntimeError.
5. The OAuth revocation (task_019) is a separate issue — it blocks Google Workspace API, not LLM provider calls.
6. **Subset-failure diagnostic (confirmed 2026-06-29):** If some jobs with the SAME skill succeed while others fail with HTTP 400, it is NOT a credential issue (those are all-or-nothing). This was confirmed when `custodian:deep` (ocas-custodian) ran OK at 14:12 while `custodian:light` (same skill) failed at 14:00. Credential/auth failures affect ALL jobs using that credential uniformly. Subset failure = transient provider-side issue affecting specific sessions.

**Action items:**
- provider-http400 → Check LLM provider API key and account status. Escalate to HIGH if not resolved by next scan.
- rate-limit → Monitor (transient).

## jobs.json Structure (2026-06-28 update)

The indigo profile file at `~/.hermes/profiles/indigo/cron/jobs.json` has ~136 jobs with structure:
```
{"jobs": [<array of job objects>], "updated_at": "<timestamp>"}
```

Each job object has:
- `name` — unique identifier (e.g., `"haiku:morning-scan"`)
- `last_error` — error message string (JSON `null` when no error; string like `"RuntimeError: Provider returned error"` when errored)
- `last_status` — `"ok"`, `"error"`, etc. from the most recent run
- `consecutive_failures` — integer, 0 = recovered/no streak
- `enabled` — boolean

**Note:** Earlier versions of this doc referenced `error` and `failures` fields. The actual field names are `last_error` and `consecutive_failures`. Always use the actual schema.

### Error detection logic (actual, tested 2026-06-28)

A job has an active error if ANY of:
1. `last_error` is a non-null string (JSON null means no error)
2. `consecutive_failures > 0` (consecutive failure count)
3. `last_status == "error"`

**Most reliable single indicator:** `consecutive_failures`. A job with `last_error` set to a non-null string but `consecutive_failures: 0` has already recovered — the error marker persists from a prior run but the job is healthy now. Confirmed 2026-06-28: haiku:morning-scan, taste:scan, 10khr-grind all had `last_error: "RuntimeError: Provider returned error"` but `consecutive_failures: 0` — all recovered.

## CRITICAL RULE: consecutive_failures gates task creation (Confirmed 2026-06-30)

**Never create a CRITICAL or HIGH task based solely on `last_status: "error"` or `last_error != null`.** Always check `consecutive_failures` first.

### The Misdiagnosis Pattern (Scan #13 → #14, June 30)

**What happened:** Scan #13 read jobs.json, saw 3 jobs with `last_status: "error"` and HTTP 400/429 error messages, and created task_019 (CRITICAL: "Google OAuth refresh token revoked") and task_014 (CRITICAL: "Provider errors blocking all Google Workspace"). These tasks persisted for 24+ hours, blocking email/calendar/drive inspection. **All 3 jobs actually had `consecutive_failures: 0`** — the errors were transient LLM provider issues (owl-alpha/OpenRouter HTTP 400/429) that had already self-resolved.

**The rule that was violated:** The doc already stated "most reliable single indicator is consecutive_failures" but didn't make it a hard gate on task creation. A job with `consecutive_failures: 0` is **healthy** — the `last_error` string is a stale artifact from a previous failed run.

### Corrected Decision Gate

Before creating any task from cron error data:

1. **Filter for `consecutive_failures > 0`** — only these are active errors. Jobs with `consecutive_failures: 0` are healthy regardless of `last_error` or `last_status` values.
2. jobs have `consecutive_failures > 0`** — report "cron health: all clear" and do NOT create error tasks, even if some jobs show `last_status: "error"`.
3. **If `consecutive_failures > 0` exists on OAuth-dependent jobs** — THEN classify as `oauth-token-expired` (CRITICAL) or `provider-http400` (MEDIUM) per the fingerprint table above.

**Confirmed 2026-06-30 (Scan #14):** All 140 jobs show `consecutive_failures: 0`. The 4 jobs with `last_status: "error"` (haiku:follow-maintenance, sands:conflict-scan, bower:scan, custodian:light) all had `consecutive_failures: 0` — indicating transient, already-recovered errors. Correct action: mark the stale CRITICAL tasks as done, report "all clear."

## Key Rules

- **oauth-token-expired is CRITICAL, not transient** — it will never self-resolve. Report it every scan until the user re-authenticates. Do not downgrade or mark as stale.
- **consecutive_failures: 0 is the health signal** — a job with `last_error` set AND `consecutive_failures: 0` is healthy. Do not create error tasks for recovered jobs.
- **Never create one task for all errors** — decompose by fingerprint
- **provider-http400 is MEDIUM, not LOW** — HTTP 400 from LLM provider endpoints (not OAuth) is distinct from `RuntimeError: Provider returned error`. A 400 means the request was rejected as malformed/unauthorized — it will NOT self-resolve on the next run. Check API key validity and account status. If 4+ jobs fail simultaneously, it's a systemic credential issue (expired key, billing problem, provider migration). Escalate to HIGH if persistent.
- **rate-limit errors are LOW severity** — they self-resolve, create "watching" not "pending"
- **interpreter-shutdown errors are LOW severity** — they self-resolve on next run, same category as rate-limit. Do NOT create investigation tasks for these.
- **certifi errors are HIGH** — they block all LLM work until fixed
- **"Script exited with code 1" is not always an error** — check stdout. Some scripts exit 1 for "nothing to do" (idempotent no-op)
- **Check both jobs.json paths** — system jobs and profile jobs are separate files (base path has 3, profile has 136)
- **Stale errors vs active** — `consecutive_failures: 0` with `last_error` set to a non-null string means the error marker persists from a prior run but the job has since recovered. Check `consecutive_failures > 0` to confirm active vs stale.
- **`error: "None"` (string) is ambiguous** — In older data, the text "None" was used to mean no error. In current schema, `last_error: null` (JSON null) = no error, any non-null string = error occurred. Always cross-check with `consecutive_failures > 0` to determine if something is actually failing.
