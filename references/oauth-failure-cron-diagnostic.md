# OAuth Failure Diagnostic for finch:work (Cron Context)

## When to Use

When finch:work picks a task involving Google OAuth failure (HTTP 400 on `oauth2.googleapis.com/token`, `invalid_grant`, Gmail/Calendar/Drive tools failing) AND the task is running as a cron job with no user present.

This is the **cron-context degraded diagnostic** — it does NOT attempt re-auth (which requires browser interaction). It confirms the failure mode and reports to the user.

## Decision Flow

```
Task involves Google OAuth failure
  │
  ├─ Is there a credential file at /root/.google_workspace_mcp/credentials/<email>.json?
  │   ├─ NO → Never been authed. Mark task "blocked: never authenticated"
  │   └─ YES ↓
  │
  ├─ Does the file have all required fields? (token, refresh_token, client_id, client_secret, scopes)
  │   ├─ NO → Malformed credential file. Mark "blocked: credential file incomplete"
  │   └─ YES ↓
  │
  ├─ Read the cron output showing the error. What's the HTTP status?
  │   ├─ 401 → Usually invalid_client (wrong client/secret). Check client_id matches config.yaml.
  │   ├─ 400 → Usually refresh_token revoked or missing Content-Type. ↓
  │   ├─ 403 → Access denied (testing mode, user not in allowlist)
  │   └─ network error → Transient, mark "monitoring"
  │
  ├─ For HTTP 400: Is it "invalid_grant: Token has been expired or revoked"?
  │   ├─ YES → Refresh token is permanently dead. Requires full re-auth. ↓
  │   │         (a) Try direct refresh via terminal to confirm
  │   │         (b) If confirmed: mark task "blocked"
  │   │         (c) Generate OAuth auth URL for user (see URL generation below)
  │   │         (d) Report clearly: what's broken, what URL to visit, what scopes are needed
  │   └─ NO → Other 400 (e.g., missing Content-Type). Fixable. Patch google_auth_mcp.py.
  │
  └─ Conclusion: If refresh token is dead AND we're in cron context,
     the task is NOT autonomously actionable. Mark "blocked", report, move on.
```

## Quick Terminal Diagnostic (30 seconds)

```bash
# Read the credential file and test the refresh directly
python3 -c "
import json, urllib.request, urllib.parse
creds = json.load(open('/root/.google_workspace_mcp/credentials/mx.indigo.karasu@gmail.com.json'))
data = urllib.parse.urlencode({
    'client_id': creds['client_id'],
    'client_secret': creds['client_secret'],
    'refresh_token': creds['refresh_token'],
    'grant_type': 'refresh_token',
}).encode()
try:
    resp = urllib.request.urlopen('https://oauth2.googleapis.com/token', data=data, timeout=10)
    print('REFRESH OK — token works, problem is elsewhere')
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    err = body.get('error', '?')
    desc = body.get('error_description', '')
    print(f'REFRESH FAILED: HTTP {e.code} | {err}: {desc}')
    if err == 'invalid_grant':
        print('→ Refresh token is REVOKED. Only fix: full re-auth in browser.')
"
```

## Auth URL Generation (for reporting to user)

When the refresh token is confirmed dead, generate the auth URL so the user can re-authorize. **Do NOT attempt to exchange codes in cron context** — just generate and report.

### For mx.indigo.karasu@gmail.com (Indigo's MCP account)

```
https://accounts.google.com/o/oauth2/v2/auth
  ?client_id=<GOOGLE_OAUTH_CLIENT_ID>.apps.googleusercontent.com
  &redirect_uri=http://<HOST>:<PORT>/oauth2callback
  &response_type=code
  &scope=<url-encoded space-separated scopes>
  &access_type=offline
  &prompt=consent
  &include_granted_scopes=true
```

**Current Indigo scopes** (as of credential file):
- `https://www.googleapis.com/auth/gmail.modify`
- `https://www.googleapis.com/auth/calendar`
- `https://www.googleapis.com/auth/drive.readonly`
- `https://www.googleapis.com/auth/contacts`
- `https://www.googleapis.com/auth/tasks`
- `https://www.googleapis.com/auth/documents`
- `https://www.googleapis.com/auth/spreadsheets`
- `https://www.googleapis.com/auth/presentations`
- `https://www.googleapis.com/auth/chat.spaces`

### For jared.zimmerman@gmail.com

Use Jared's client: `<GOOGLE_OAUTH_CLIENT_ID>.apps.googleusercontent.com`
Redirect: `http://localhost:1` (paste-back method, no listener needed)

See `gcloud-cli` skill § "Quick Reauth (paste-back, no MCP needed)" for the full paste-back protocol.

## Task List Update Pattern

When OAuth failure is confirmed as "needs re-auth":

```json
{
  "status": "blocked",
  "blocked_reason": "Requires <email> to complete Google OAuth consent flow in browser — refresh token revoked, cannot auto-recover",
  "auth_url": "<generated URL for reporting>",
  "note": "Confirmed via direct token refresh test: HTTP 400 invalid_grant. All Google Workspace tools (Gmail, Calendar, Drive) are non-functional until re-auth."
}
```

**Key distinction:** Use `blocked` (not `pending`) for tasks requiring user auth action. `pending` means "waiting for something external to happen." `blocked` means "waiting for the user." This prevents finch:work from retrying every 30 min pointlessly.

## What NOT to Do

- **Do NOT retry the failed refresh token call** hoping it will recover. `invalid_grant` is permanent until re-auth.
- **Do NOT kill workspace-mcp processes** to fix a dead token. Multi-instance is Root Cause A; dead token is Root Cause B. Killing processes won't bring a revoked token back.
- **Do NOT ask the user to re-auth without first confirming the diagnosis.** Run the terminal diagnostic above to distinguish "token expired (auto-refreshes)" from "token revoked (needs re-auth)."
- **Do NOT report as "token expired"** when it's actually "refresh token revoked." These have different severity and different fixes.

## Related Skills

- `gcloud-cli` — Full OAuth lifecycle, re-auth scripts, paste-back protocol, client/scope details
- `gcloud-cli/references/workspace-oauth.md` — Root Cause A vs B diagnosis, pre-flight checklist
- `ocas-finch/references/gmail-token-expired-draft-workflow.md` — When OAuth failure blocks email tasks specifically (fallback to local drafts)
- `ocas-finch/references/scan-error-classification.md` — Error taxonomy for cron job failures

## Confirmed Cases

- **2026-06-28 task_019**: mx.indigo.karasu@gmail.com refresh token revoked. email:check cron (25c06979ccc7) failing every 10 min with HTTP 400. Confirmed via direct refresh test that token is invalid_grant. Marked task_019 as `blocked`. Auth URL generated for 9-scope set.
- **2026-06-29 task_019 (expanded)**: Same OAuth revocation now confirmed affecting `monitor:list` (39b7edc44b35) AND `ocas-tasks/tasks_monitor.py`. 3+ components failing from single token revocation. All recover once user re-authenticates.
