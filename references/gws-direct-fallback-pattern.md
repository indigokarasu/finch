# GWS Direct Fallback Pattern (finch:scan, MCP-mount-absent runs)

## Problem
The `mcp__google_workspace__*` namespace is INTERMITTENTLY absent from the finch:scan
cron sub-agent (mount-layer failure, NOT a credential/config problem — config shows
`enabled: true`, creds are fresh, no gws error in errors.log). When absent, there is
NO MCP tool to call, so email/calendar/Drive are unreadable and must be carried forward
as UNVERIFIED (never assert "no new mail" from an unreadable source).

## Two-script fallback (canonical, maintained under ocas-finch/scripts/)

1. **`gws-direct-fallback.py`** — COUNT-PROBE only. Reports "N msgs / N events / N files"
   per source. Use to assert the credential + egress path is alive when you only need
   to know the 3 sources are reachable (fast, cheap).

2. **`gws_direct_puller.py`** — FULL-CONTENT puller. Returns real Gmail metadata (+ optional
   body text via `--full-text`), Calendar events for a horizon (default 48h), and Drive
   files (most-recently-modified). Use when you need to CLASSIFY actionable signals
   (e.g. "is this a Docusign to sign?", "is this a security alert?"), not just counts.

Both run with the MCP venv python (it has google-api-python-client + google-auth):
  <hermes-venv>/bin/python scripts/gws_direct_puller.py [--gmail-q "newer_than:2d"] [--cal-hours 48] [--drive-n 10]

## CRITICAL TRANSPORT GOTCHA (host egress filter)
The host egress filter returns **HTML 404** for `calendar.googleapis.com` and
`drive.googleapis.com` when the client does NOT send the googleapiclient UA /
`x-goog-api-client` header. This means:
- `requests` / `curl` / `google.auth.transport.requests.AuthorizedSession` → **404** for Calendar/Drive.
- `googleapiclient.discovery.build(...)` → **works** (it sets the correct UA/header automatically).
- Gmail is reachable either way, but use googleapiclient uniformly to avoid branching.

CONFIRMED 2026-07-22: raw `requests`/curl probes to Calendar/Drive returned HTML 404;
the same calls via `googleapiclient` (in the MCP venv) succeeded with real data.

## RESPONSE SHAPE GOTCHAS (confirmed 2026-07-23 finch:scan)
The googleapiclient return schema differs from the MCP-proxy return. A wrong-shape
parse yields a SILENT false-negative (e.g. "0 actionable emails") — the inverse of the
unreadable-source gap. Anchor all probes on these shapes:

- **Gmail `messages().get(userId, id, format="metadata")`**: From / Subject / Date live in
  `payload.headers` (a list of `{name, value}`), NOT in a top-level `message["headers"]`.
  ```python
  hdrs = {h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])}
  frm, subj, date = hdrs.get("From",""), hdrs.get("Subject",""), hdrs.get("Date","")
  ```
  Indexing `m["headers"]` (the top-level key doesn't exist) returns `{}` and silently
  drops all three fields.

- **Gmail `messages().list()` items are ALREADY dicts**: each element is `{id, threadId, ...}`,
  not a bare id string. If you then pass `m["id"]` into a `msg_meta(mid)` helper that itself
  indexes `mid["id"]`, you double-index and raise `TypeError: string indices must be integers`.
  Normalize ONCE at the call boundary:
  ```python
  def msg_meta(mid):
      real_id = mid if isinstance(mid, str) else mid["id"]
      m = service.users().messages().get(userId="me", id=real_id, format="metadata",
              metadataHeaders=["From","Subject","Date"]).execute()
      ...
  ```

- **Calendar `events().list()`**: events are in `result["items"]`; each event's start/end is
  `event["start"].get("dateTime") or event["start"].get("date")` (all-day events have `date`,
  timed events have `dateTime`). Don't assume `startTime`.

## Usage in finch:scan
At scan start, probe for the `mcp__google_workspace__*` namespace (tool_surface probe).
- If PRESENT → use MCP proxy (tool_describe → tool_call).
- If ABSENT → run `gws_direct_puller.py` for content, `gws-direct-fallback.py` for a quick
  reachability confirmation. Mark the 3 sources VERIFIED-DIRECT (not UNVERIFIED) in the
  cycle_note, and clear `sources_unverified_this_cycle`.

## Credential store
Tokens live at `<gworkspace-creds>/credentials/<email>.json`.
`ensure_fresh()` refreshes via `refresh_token` and rewrites the file. A recent mtime on
this file = creds are live (use as the "creds fresh?" check in MCP-absent triage).

## Locator
If the script path is ever lost, find it with `terminal find /root -iname 'gws_direct_puller*'`
(prefer `find` over `search_files`, which can throw transient `DaemonThreadPoolExecutor` errors).
