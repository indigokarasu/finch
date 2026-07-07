# Provider Error Deep Investigation (finch:work)

When finch:work picks a provider-error task and needs to determine root cause, severity, and whether intervention is required, use this investigation procedure.

## Prerequisite

The scan-error-classification reference already handles *grouping* errors by fingerprint at scan time. This doc covers the *work-side* investigation: reading logs, classifying failure mode, confirming recovery.

## Log Locations

| Log | Path | Contains |
|-----|------|----------|
| Agent errors | `logs/errors.log` (under profile dir) | Retry attempts, HTTP status details, rate limit metadata |
| Gateway log | `logs/gateway.log` (under profile dir) | 401/429 details, upstream provider messages, cert errors |

Profile log directory: `/root/.hermes/profiles/indigo/logs/`

## Key Log Patterns

### 1. OpenRouter rate limit (429)
```
HTTP 429: Provider returned error
openrouter/owl-alpha is temporarily rate-limited upstream. Please retry shortly.
```
**Classification:** Transient. Self-resolves. Severity: LOW.

### 2. Empty SSE stream
```
Provider returned an empty stream with no finish_reason (possible upstream error or malformed SSE response)
```
**Classification:** Transient. Usually a single-request glitch. Retry succeeds. Severity: LOW.

### 3. JSON injection into SSE stream
```
JSON error injected into SSE stream
```
**Classification:** Transient. Provider-side serialization issue. Retry succeeds. Severity: LOW.

### 4. Authentication failure (401)
```
HTTP 401: Authentication failed with upstream provider
```
**Classification:** May be transient (provider blip) or persistent (API key revoked). Check if other jobs in the same time window also hit 401. If isolated, transient. If broad, check API key status. Severity: LOW–HIGH depending on persistence.

### 5. Timeout
```
Request timed out.
```
**Classification:** Transient. Network/provider latency. Severity: LOW.

## Investigation Procedure

1. **Check `hermes cron list`** — Identify affected jobs, note their `Last run:` status and timestamp.

2. **Read `errors.log`** — Grep for the job ID (hex string from cron output) or job name:
   ```bash
   grep "<job_id_or_name>" /root/.hermes/profiles/indigo/logs/errors.log | tail -20
   ```

3. **Classify each error mode** — Match against the patterns above. A single task may contain multiple error types.

4. **Count errors by date** — Determine if errors are increasing, stable, or declining:
   ```bash
   grep -c "Provider returned error\|Rate limited\|HTTP 429\|empty stream\|JSON error injected" /root/.hermes/profiles/indigo/logs/errors.log | head
   # By date:
   grep "Provider returned error\|Rate limited\|HTTP 429" /root/.hermes/profiles/indigo/logs/errors.log | grep -oP '\d{4}-\d{2}-\d{2}' | sort | uniq -c
   ```

5. **Check current error rate** — If no errors in the last 2+ hours, the outage has likely passed.

6. **Verify job recovery** — Cross-reference with `hermes cron list` output. If `Last run: ok`, the job has recovered regardless of earlier errors.

7. **Check for secondary issues** — Some jobs may have bugs masked by provider errors (e.g., path resolution failures, `execute_code` blocks). These surface in the error log once the provider recovers and the job runs far enough to hit them.

## Resolution Template

When all errors are confirmed transient with recovery:

```
RESOLVED: TRANSIENT — <provider> upstream errors. Affected jobs: <list>.
Error modes: <429 rate limits, empty SSE streams, etc.>.
Error count by date: <date: count>.
No errors in last <N> hours. All jobs recovered on next scheduled run.
<Note any secondary issues discovered, e.g., "10khr-grind has a PATH BUG: double-nested cd at /root/.hermes/profiles/indigo/home/.hermes/profiles/indigo/skills/ocas-skilllab">
No action needed beyond continued monitoring.
```

## Subset-Failure Diagnostic Pattern (confirmed 2026-06-29)

When some LLM jobs fail with HTTP 400 while others with the **same skill and provider config** run successfully, the failure is **NOT a credential/auth issue**. Credential/auth failures are all-or-nothing — they affect every job using that credential.

**Diagnostic procedure:**

1. **Identify the failing jobs** — Note which specific jobs show HTTP 400
2. **Find working jobs with the same skill** — Query `jobs.json` for jobs sharing the `skill` field with failing jobs. If `custodian:light` (ocas-custodian) fails but `custodian:deep` (ocas-custodian) succeeds, the skill/auth config is fine.
3. **Compare model/provider fields** — If both failing and working jobs have `model: null, provider: null` (use global default), the issue is NOT in the job config.
4. **Conclusion** — Subset failure = transient provider-side issue affecting specific worker sessions, not a systemic credential problem.

**Common misdiagnosis:** Linking provider HTTP 400 errors to Google OAuth revocation. OAuth revocation affects Google Workspace APIs (Gmail, Calendar, Drive), NOT LLM provider calls (OpenRouter, etc.). These are completely separate systems. If 50+ LLM jobs are running fine while 5 fail, OAuth is not the cause.

**jobs.json anomaly:** Failing jobs may show `last_run: null, next_run: null` in `jobs.json` while `hermes cron list` shows recent timestamps. This means the error occurs before state persistence — the provider rejects the request immediately, before the job can record a start time.

**Resolution:** Monitor for auto-recovery. Same pattern on June 27 (task_014) self-resolved within hours. If 4+ jobs fail simultaneously with HTTP 400 for 2+ hours, check provider dashboard for account-level issues.

## When to Escalate

- **Same job fails 3+ consecutive runs** with provider error → MEDIUM severity, potential provider-side issue requiring workaround (fallback model, reduced cadence)
- **429 errors persist across 24h+** → Provider may have changed rate limits. Check OpenRouter status page.
- **401 errors are consistent** → API key may need rotation. This requires user action.
- **Secondary bugs discovered** → Create a separate task for each distinct bug found during investigation.
- **Subset failure persists 2+ hours** → Escalate from MEDIUM to HIGH. Check provider dashboard for API key status, billing, or account issues.

## Hermes Cron CLI Pitfalls

- `hermes cron log <id>` — DOES NOT EXIST. No log subcommand available.
- `hermes cron status <id>` — DOES NOT EXIST at the top level. Must use `hermes cron list` and scan text output.
- Use direct file reads on the logs directory for detailed error investigation.

## Confirmed Investigation: 2026-06-28

task_022: 3 jobs (haiku:morning-scan, taste:scan, 10khr-grind) with RuntimeError: Provider returned error.
- All traced to OpenRouter owl-alpha transient upstream failures
- Error modes: 429 rate limits, empty SSE streams, JSON injection errors  
- Error count: 36 (Jun 25), 49 (Jun 26), 95 (Jun 27 peak), 28 (Jun 28 through ~09:00)
- All 3 jobs recovered on next scheduled run
- Secondary finding: 10khr-grind has a double-nested cd path bug
- Resolution: TRANSIENT, no action needed

## Confirmed Investigation: 2026-06-29 (subset-failure pattern)

task_023: 5 jobs (custodian:light, sands:conflict-scan, dispatcher, Koda Dispatcher—BOOK, Koda Dispatcher—jaredzimmerman.com) with HTTP 400 from LLM provider.
- **Key finding:** 50+ other LLM jobs running fine simultaneously (custodian:deep, haiku:*, vesper:*, mentor:*, taste:*, etc.)
- **Misdiagnosis corrected:** task_019 incorrectly linked these to Google OAuth revocation. OAuth affects Google APIs, not LLM provider calls.
- **Root cause:** Transient provider-side issue affecting specific worker sessions. Same pattern as June 27 (task_014) which self-resolved.
- **Diagnostic evidence:** custodian:deep (ocas-custodian skill) ran OK at 14:12 while custodian:light (same skill) failed at 14:00 — proves it's not a credential/config issue.
- **jobs.json anomaly:** All failing jobs showed `last_run: null, next_run: null` in jobs.json while `hermes cron list` showed recent timestamps — error occurs before state persistence.
- bower:scan hit HTTP 429 (separate transient rate limit) at 09:03.
- Resolution: MONITOR for auto-recovery. If persists 2+ hours, escalate to HIGH and check provider dashboard.
