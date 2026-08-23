# Scan-Side Error Classification (finch:scan)

When finch:scan reads cron health data, it must classify errored jobs into distinct failure categories before creating tasks. A single "cron errors" task with N affected jobs is not actionable — the work agent needs decomposed, root-cause-specific tasks.

## Classification Procedure

1. **Collect all errored jobs** — Read both `~/.hermes/cron/jobs.json` and `~/.hermes/profiles/<profile>/cron/jobs.json`. Filter for `last_error != None` or `last_status == 'error'`.

2. **Extract error fingerprints** — For each errored job matching the detection logic above, extract the error signature:
   - `certifi.*CA bundle` → **certifi** category
   - `Script not found: <path>` → **missing-script** category
   - `Script exited with code 1` + `can't open file '<path>': [Errno 2]` → **missing-script** category (the script path in the cron config points to a file that does not exist — confirmed by running the script directly)
   - `HTTP 503` → **provider-capacity** category (HTTP 503 from upstream capacity limits — different from `provider-error` which is a generic `RuntimeError`. 503s are transient but self-resolve slower than 429s. When 10+ jobs fail simultaneously with HTTP 503, it's a systemic provider capacity event — classify as one task, not per-job)
   - `HTTP 429` → **rate-limit** category (transient, self-resolves)
   - `RuntimeError: Provider returned error` (no HTTP status) → **provider-error** category (LLM provider transient failure — usually self-resolves on next run)
   - `HTTP 400` (not on oauth2.googleapis.com) → **provider-http400** category (LLM provider returning HTTP 400 — may indicate invalid API key, malformed request, or provider-side rejection. NOT OAuth-related. Check if multiple jobs fail simultaneously = provider-side issue, or one job = config/credential issue. Distinguish from oauth-token-expired by endpoint URL.)
   - `HTTPError 400.*oauth2.googleapis.com/token` or `invalid_grant.*expired or revoked` or `Token has been expired or revoked` → **oauth-token-expired** category (CRITICAL — Google OAuth refresh token expired/revoked. Not transient. Blocks all Google Workspace API including email:check cron, Gmail, Calendar, Drive. Also affects any Python script using `google_auth_mcp.py` or `google_auth.py` — including `ocas-tasks/tasks_monitor.py` which is called by `monitor:list`.)
   - `cannot schedule new futures after interpreter shutdown` → **interpreter-shutdown** category (transient — self-resolves on next run)
   - `Script exited with code 1` → **script-exit** category (check stdout for detail)
   - `ModuleNotFoundError: No module named '<X>'` → **missing-module** category (Python dependency not installed in the runtime environment)
   - `error: "None"` string with `failures > 0` → **investigate** category (ambiguous — could be transient or a real issue without error detail)
   - When classifying `script-exit-code-1` errors, **run the underlying script directly** (`timeout 15 python3 <script> --mode check 2>&1`) to capture stderr. The exit code alone does not reveal whether the failure is in the script's own logic or in a downstream dependency (e.g., `tasks_monitor.py` failing on OAuth). Confirmed 2026-06-29: `monitor:list` exit code 1 was actually `ocas-tasks/tasks_monitor.py` failing on `HTTPError 400` from `oauth2.googleapis.com/token` — same root cause as email:check.
   - Multiple cron jobs failing with `HTTPError 400` on the same token endpoint is a **single root cause with wide blast radius** under ONE task listing all affected components. Do not create separate tasks per job.
   - Anything else → **other** category

   **Note:** A job can appear in multiple categories. When `error: "None"` is present with `failures > 0`, it means the job errored but no captured error message was recorded — check journal logs or rerun for diagnosis. Observed 2026-06-25: `weave-enrichment-health-check` had `error: "None"`, `failures: 1`, `state: "scheduled"`.

3. **Group by fingerprint** — Count jobs per category. Each category becomes a separate task.

4. **Classify severity**:
   - **oauth-token-expired**: CRITICAL — blocks all Google Workspace API access (Gmail, Calendar, Drive) AND causes dependent cron jobs to fail. Not transient — requires user re-authentication. Scan must report this as a persistent blocker every run until resolved.
   - **certifi**: HIGH — blocks all LLM-dependent jobs system-wide
   - **missing-script**: HIGH — indicates deployment/path regression
   - **provider-capacity**: LOW — HTTP 503 upstream capacity limits. Transient but may persist for hours. Monitor next cycle; if 10+ jobs affected simultaneously, flag as systemic. Does not self-resolve as fast as 429s.
   - **rate-limit**: LOW — transient, self-resolves, monitoring only
   - **interpreter-shutdown**: LOW (was MEDIUM, corrected 2026-06-28) — **always transient**. Python `concurrent.futures` raises this when an executor schedules work during interpreter shutdown (process cleanup). The executor state resets between runs, so the next scheduled run succeeds without intervention. Confirmed: 3 jobs hit this on Jun 23 (single gateway restart), all recovered on next run. Create a monitoring task at most — never HIGH or MEDIUM. Only escalate to MEDIUM if 3+ CONSECUTIVE failures persist after the job has re-run at least once.
   - **missing-module**: MEDIUM — a Python package required by a cron script is not importable in the runtime environment. Not transient (won't self-resolve). **However**: always verify the module is actually missing before attempting a fix — check `python3 -c "import <module>"` in the venv. The scan may report a ModuleNotFoundError that was transient (package was installed between scan and work). Fix (if confirmed missing): `pip install <module>` in the venv that runs the cron. Confirmed 2026-06-28: `email:check` (25c06979ccc7) was reported as missing `googleapiclient`, but `python3 -c "from googleapiclient.errors import HttpError"` succeeded — the error was transient. Job had `last_status: ok`, `consecutive_failures: 0`.
   - **provider-error**: LOW — `RuntimeError: Provider returned error` indicates the LLM provider (e.g., OpenRouter) returned a transient error. These self-resolve on the next run. Only escalate to MEDIUM if the same job fails with this error for 3+ consecutive runs. Confirmed 2026-06-28: haiku:morning-scan, taste:scan, and 10khr-grind all hit this simultaneously — suggests a provider-side outage, not individual job issues.
   - **provider-http400**: MEDIUM — HTTP 400 from LLM provider endpoints (NOT OAuth). Distinct from `provider-error` (RuntimeError) and `oauth-token-expired` (HTTP 400 on oauth2.googleapis.com). When 4+ jobs fail simultaneously with HTTP 400, it suggests a systemic provider credential or configuration issue (e.g., API key expired, account billing issue, provider rejecting request format). Escalate to HIGH if it persists across consecutive runs. Confirmed 2026-06-29: 4 jobs (<other-ocas-skill>:light, sands:conflict-scan, dispatcher, <other-profile> Dispatcher) failed simultaneously with HTTP 400 — NOT OAuth-related, NOT RuntimeError.
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
| certifi CA bundle | 5 | HIGH | haiku:morning-scan, haiku:follow-maintenance, scout:research, <other-ocas-skill>:scan, scout:sources-refresh | `cacert.pem` missing from venv path |
| missing-script / path-not-found | 6 | HIGH | monitor:email, monitor:<other-profile>-issues, monitor:list, monitor:styx, gens:sync, dispatch:triage-morning | Script file not found at configured path |
| delivery-error | 2 | HIGH | dispatch:briefing-deliver, (monitor:email also has delivery_err) | Job ran but output could not be delivered to destination |

## Provider capacity pattern (new — 2026-07-27)

11 jobs hitting HTTP 503 simultaneously from the same provider (OpenRouter). All share the identical error message: "HTTP 503: The requested model is temporarily unavailable due to upstream capacity limits." This is a systemic provider capacity event, not N independent failures.

| Category | HTTP Status | When to use | Severity |
|---|---|---|---|
| `provider-capacity` | 503 | `upstream capacity` in error message | LOW (transient, self-resolves) |

Key distinctions:
- `provider-capacity` (503) is a capacity limit — the provider is up but throttling. Self-resolves when capacity frees. Slower to resolve than rate-limit (429).
- `provider-error` (RuntimeError, no HTTP status) is a generic provider failure — may be a different class (timeout, format error, etc.).
- `rate-limit` (429) is per-key throttling — usually resolves quickly (minutes).
- `provider-http400` (400, non-OAuth) is a configuration or format issue — does NOT self-resolve.

When 10+ jobs fail simultaneously with HTTP 503, group as ONE task under `provider-capacity` with the count and list of affected jobs. Do NOT create 11 separate tasks. Check provider status page if it persists >2 cycles.

Key observations — systemic 503:
1. All affected jobs share the identical error string — this is a single root cause with wide blast radius, same pattern as `provider-http400` but at lower severity (503 = capacity, 400 = config/format).
2. `consecutive_failures` may be 0 or null for 503s — the error marker persists from prior runs even though the job is healthy. Always gate on `consecutive_failures > 0` before creating tasks.
3. This pattern recurs periodically with provider capacity fluctuations — do not escalate to HIGH unless 503s persist across 2+ consecutive scan cycles.

## Example: 2026-07-27 Scan — Systemic 503 (new)

11 errored jobs decomposed into:

| Category | Count | Severity | Affected Jobs | Root Cause |
|---|---|---|---|---|
| provider-capacity | 11 | LOW | bower:scan, mentor:deep, vesper:morning, vesper:evening, ocas-finch:daily, bones:research, Koda Dispatcher ×3, menu-monitor-weekly | HTTP 503 upstream capacity (OpenRouter) |
| rate-limit | 1 | LOW | weave:overnight-enrichment | HTTP 429 rate limit |
| script-exit | 3 | varies | praxis:review, bones:market-monitor, bones:position-tracker | Script exited code 1 — check stdout for detail |
| interpreter-shutdown | 2 | LOW | reach:api-mine, sands:travel-check | RuntimeError interpreter shutdown (transient) |
| degraded | 1 | P3 | rally:pipeline-watchdog | DEGRADED (1_new_connectivity_issues) |

## Key rules (unchanged from prior versions)

- **oauth-token-expired is CRITICAL, not transient** — it will never self-resolve. Report it every scan until the user re-authenticates. Do not downgrade or mark as stale.
- **consecutive_failures: 0 is the health signal** — a job with `last_error` set AND `consecutive_failures: 0` is healthy. Do not create error tasks for recovered jobs.
- **Never create one task for all errors** — decompose by fingerprint
- **provider-http400 is MEDIUM, not LOW** — HTTP 400 from LLM provider endpoints (not OAuth) is distinct from `provider-error` (RuntimeError) and `oauth-token-expired` (HTTP 400 on oauth2.googleapis.com). A 400 means the request was rejected as malformed/unauthorized — it will NOT self-resolve on the next run. Check API key validity and account status. If 4+ jobs fail simultaneously, it's a systemic credential issue (expired key, billing problem, provider migration). Escalate to HIGH if persistent.
- **rate-limit errors are LOW severity** — they self-resolve, create "watching" not "pending"
- **interpreter-shutdown errors are LOW severity** — they self-resolve on next run, same category as rate-limit. Do NOT create investigation tasks for these.
- **certifi errors are HIGH** — they block all LLM work until fixed
- **"Script exited with code 1" is not always an error** — check stdout. Some scripts exit 1 for "nothing to do" (idempotent no-op)
- **Check both jobs.json paths** — system jobs and profile jobs are separate files (base path has 3, profile has 136+)
- **Stale errors vs active** — `consecutive_failures: 0` with `last_error` set to a non-null string means the error marker persists from a prior run but the job has since recovered. Check `consecutive_failures > 0` to confirm active vs stale.
- **`error: "None"` (string) is ambiguous** — In older data, the text "None" was used to mean no error. In current schema, `last_error: null` (JSON null) = no error, any non-null string = error occurred. Always cross-check with `consecutive_failures > 0` to determine if something is actually failing.

## jobs.json Structure

The <profile> file at `~/.hermes/profiles/<profile>/cron/jobs.json` has ~168 jobs with structure:
```
{"jobs": [<array of job objects>], "updated_at": "<timestamp>"}
```

Each job object has:
- `name` — unique identifier (e.g., `"haiku:morning-scan"`)
- `last_error` — error message string (JSON `null` when no error; string like `"RuntimeError: Provider returned error"` when errored)
- `last_status` — `"ok"`, `"error"`, etc. from the most recent run
- `consecutive_failures` — integer, 0 = recovered/no streak
- `enabled` — boolean
- `state` — `"scheduled"`, `"paused"`, etc.

**Note:** Earlier versions of this doc referenced `error`, `failures`, and `deliver` fields. The actual field names are `last_error`, `consecutive_failures`, and `last_delivery_error`. Always use the actual schema.

### Error detection logic (actual, tested 2026-06-28)

A job has an active error if ANY of:
1. `last_error` is a non-null string (JSON null means no error)
2. `consecutive_failures > 0` (consecutive failure count)
3. `last_status == "error"`

**Most reliable single indicator:** `consecutive_failures`. A job with `last_error` set to a non-null string but `consecutive_failures: 0` has already recovered — the error string persists as a stale artifact from a previous failed run. Confirmed 2026-06-28: haiku:morning-scan, taste:scan, 10khr-grind all had `last_error: "RuntimeError: Provider returned error"` but `consecutive_failures: 0` — all recovered.