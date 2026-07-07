# Systemic OAuth Failure Detection

When Google Workspace OAuth refresh token is revoked or expired, ALL dependent cron jobs fail simultaneously. This is not a collection of independent failures — it's one root cause with many symptoms.

## Fingerprint

- **4+ cron jobs fail within the same hour**
- All show `RuntimeError: HTTP 400: Provider returned error` or `requests.exceptions.HTTPError: 400 Client Error: Bad Request for url: https://oauth2.googleapis.com/token`
- Error traceback includes `_refresh_token` → `get_service` → `get_gmail_service`
- Affects any job that uses Gmail API, Calendar API, or Drive API

## Affected Jobs (typical)

| Job | Schedule | Uses |
|-----|----------|------|
| email:check | */10 * * * * | Gmail API |
| custodian:light | 0 * * * * | Gmail API (for monitoring) |
| haiku:follow-maintenance | 0 16 * * 1 | Gmail API |
| sands:conflict-scan | 0 14 * * * | Calendar API |
| dispatcher | */2 * * * * | Gmail API |
| Koda Dispatcher | every 5m | Gmail API |
| bower:scan | 0 9 * * * | Drive API (may show 429 instead of 400) |

## Diagnostic Steps

1. **Confirm systemic pattern**: Check if 4+ jobs failed with HTTP 400 in the same time window
2. **Read one output file**: `cat /root/.hermes/profiles/indigo/cron/output/<job-id>/<latest>.md` — look for `oauth2.googleapis.com/token` in the traceback
3. **Distinguish from transient**: Transient errors show `consecutive_failures: 0` in jobs.json. OAuth revocation shows `consecutive_failures > 0` and `last_status: error` persisting across multiple runs
4. **Check for rate-limit companion**: Some jobs may show HTTP 429 (rate limit) instead of 400 — this is a retry storm from the OAuth failure, not a separate issue

## Correct Response

- **ONE task, not N**: Create a single CRITICAL task listing all affected jobs
- **Action**: "Jared must re-authorize Google OAuth — desktop login or browser-based consent flow needed"
- **Dependent tasks**: Mark email/calendar/Drive tasks as blocked-by-OAuth (they cannot be investigated until auth is restored)
- **Do NOT**: Investigate each job individually, create separate tasks per job, or attempt to fix scripts (the scripts are fine — the credential is dead)

## Confirmed Instance

**2026-06-29**: 8/140 jobs in error. First detected 2026-06-27. Escalated to systemic assessment on 2026-06-29 when pattern became clear that all 8 failures shared one token revocation event.
