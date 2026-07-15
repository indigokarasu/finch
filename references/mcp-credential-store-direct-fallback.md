# MCP Credential-Store Direct Fallback (Gmail / Calendar / Drive)

**When to use:** A finch:scan (or any cron/headless run) needs Google Workspace data but BOTH normal paths fail:
1. MCP `google_workspace_*` tools are **rejected at dispatch** — `Tool 'mcp__google_workspace__...' does not exist` (the server is indexed by `tool_search` but NOT loaded in this runtime's available-tools list). This is failure mode (b) from the Scanning Gotchas `REALITY CHECK` entry.
2. The legacy skill token (`$HERMES_HOME/google_token.json`, often a symlink) is bound to a **`deleted_client`** — so `google_api.py calendar/drive` fails with `google.auth.exceptions.RefreshError: ('deleted_client: ...')`.

In that situation the **live** credential is the MCP server's per-account JSON store, which the MCP server refreshes autonomously on its own cron. `mcp_gmail_read.py` already uses it for Gmail; the same store serves Calendar and Drive if you build the `Credentials` object yourself.

**Store path:** `/root/.google_workspace_mcp/credentials/<email>.json` (e.g. `jared.zimmerman@gmail.com.json`). Confirmed live 2026-07-15 (refreshed 07-14 23:35, usable 07-15 00:08).

## Gmail (reuse existing script)
```bash
cd /root/.hermes/profiles/indigo/skills/productivity/google-workspace/scripts
python3 mcp_gmail_read.py --search "newer_than:2d" --max 40 \
  --cred /root/.google_workspace_mcp/credentials/jared.zimmerman@gmail.com.json
```

## Calendar + Drive (direct API against the same store)
Save as a `.py` and run with the hermes venv python (`/root/hermes-agent/.venv/bin/python`):
```python
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CRED = "/root/.google_workspace_mcp/credentials/jared.zimmerman@gmail.com.json"
d = json.load(open(CRED))
creds = Credentials(
    token=d.get("access_token") or d.get("token"),
    refresh_token=d.get("refresh_token"),
    token_uri=d.get("token_uri"),
    client_id=d.get("client_id"),
    client_secret=d.get("client_secret"),
    scopes=d.get("scopes"),
)

# Calendar — next 48h
cal = build("calendar", "v3", credentials=creds)
evs = cal.events().list(
    calendarId="primary",
    timeMin="2026-07-15T00:00:00-07:00",
    timeMax="2026-07-17T00:00:00-07:00",
    singleEvents=True, orderBy="startTime", maxResults=50,
).execute()
for e in evs.get("items", []):
    s = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
    print(f"- {e.get('summary')} | {s}")

# Drive — recently modified
drv = build("drive", "v3", credentials=creds)
files = drv.files().list(
    q="modifiedTime > '2026-07-13T00:00:00'",
    pageSize=15,
    fields="files(id,name,mimeType,modifiedTime,webViewLink,owners)",
    orderBy="modifiedTime desc",
).execute()
for f in files.get("files", []):
    print(f"- {f.get('name')} | mod={f.get('modifiedTime')}")
```
No interactive OAuth, no legacy token touched. The MCP server keeps the store valid, so this outlives a `deleted_client` on the legacy path.

## Diagnosis flow (scan context)
1. Probe ONE MCP `google_workspace` tool with a real `tool_call`. If `Tool '...' does not exist` → server not loaded this run → treat Workspace as UNVERIFIED, carry forward prior findings.
2. If you instead try `google_api.py calendar/drive` and get `deleted_client` → legacy token dead; switch to the direct-store script above.
3. Verify the store file exists and was recently modified before trusting it (`ls -la /root/.google_workspace_mcp/credentials/`).
4. Prefer this over declaring email/calendar/drive "broken" — the MCP store is usually the live one on indigo-style profiles.

**Confirmed 2026-07-15 finch:scan:** both MCP-dispatch and legacy-token paths failed; the direct-store script recovered Calendar (3 events / next 48h) and Drive (1 recently-modified item) successfully. Gmail via `mcp_gmail_read.py` returned 40 hits.
