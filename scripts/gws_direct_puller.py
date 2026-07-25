#!/usr/bin/env python3
import os
OPERATOR_EMAIL = os.environ.get("OCAS_OPERATOR_EMAIL", "operator@example.com")
"""
gws_direct_puller.py — Full-CONTENT Google Workspace puller for finch:scan
when the google-workspace MCP mount is absent/flaky in the cron sub-agent.

WHY THIS EXISTS (2026-07-22 finch:scan): The prior gws-direct-fallback.py only
returns COUNTS (probe). This script returns ACTUAL email/calendar/drive CONTENT
so finch:scan can classify actionable signals (not just "3 msgs exist").

CRITICAL TRANSPORT NOTE: Use googleapiclient, NOT raw requests/curl/
AuthorizedSession. The host egress filter returns HTML 404 for calendar.googleapis.com
and drive.googleapis.com when the client does NOT send the googleapiclient UA /
x-goog-api-client header. Raw requests 404; googleapiclient succeeds. Gmail is
reachable either way, but use googleapiclient uniformly.

Run with the MCP venv python (it has google-api-python-client + google-auth):
  <hermes-install>/.venv/bin/python scripts/gws_direct_puller.py [--acct ...] \
      [--gmail-q "newer_than:2d"] [--cal-hours 48] [--drive-n 10]

Prints a JSON object to stdout: {"gmail":[...], "calendar":[...], "drive":[...]}.
Exits 0 if at least one source returned data; non-zero on hard failure.
"""
import json, os, sys, argparse, base64
from datetime import datetime, timezone, timedelta

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    import googleapiclient.discovery as disc
except ImportError as e:
    print(f"FATAL: missing libs (need google-api-python-client + google-auth): {e}", file=sys.stderr)
    sys.exit(3)

CRED_DIR = os.path.expanduser("~/.google_workspace_mcp/credentials")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

def load_creds(acct):
    path = os.path.join(CRED_DIR, f"{acct}.json")
    if not os.path.exists(path):
        print(f"FATAL: no token file for {acct} at {path}", file=sys.stderr)
        sys.exit(4)
    d = json.load(open(path))
    creds = Credentials(
        token=d.get("token") or d.get("access_token"),
        refresh_token=d.get("refresh_token"),
        token_uri=d.get("token_uri"),
        client_id=d.get("client_id"),
        client_secret=d.get("client_secret"),
        scopes=d.get("scopes") or SCOPES,
    )
    return creds, d, path

def ensure_fresh(creds, d, path):
    if creds.valid:
        return creds
    if not creds.refresh_token:
        print(f"WARN: {path} has no refresh_token", file=sys.stderr)
        return creds
    creds.refresh(Request())
    d["token"] = creds.token
    d["access_token"] = creds.token
    d["expiry"] = creds.expiry.isoformat() if creds.expiry else None
    json.dump(d, open(path, "w"), indent=2)
    return creds

def _decode(body_b64):
    if not body_b64:
        return ""
    try:
        return base64.urlsafe_b64decode(body_b64 + "===").decode("utf-8", "ignore")
    except Exception:
        return ""

def pull_gmail(creds, q, n):
    svc = disc.build("gmail", "v1", credentials=creds, cache_discovery=False)
    ids = [m["id"] for m in svc.users().messages().list(userId="me", q=q, maxResults=n).execute().get("messages", [])]
    out = []
    for m in ids:
        full = svc.users().messages().get(userId="me", id=m, format="metadata",
                                          metadataHeaders=["From", "Subject", "Date"]).execute()
        hdr = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        out.append({"id": m, "from": hdr.get("From", ""), "subject": hdr.get("Subject", ""), "date": hdr.get("Date", "")})
    return out

def pull_gmail_full(creds, q, n):
    """Full-text body pull for actionable classification (use sparingly)."""
    svc = disc.build("gmail", "v1", credentials=creds, cache_discovery=False)
    ids = [m["id"] for m in svc.users().messages().list(userId="me", q=q, maxResults=n).execute().get("messages", [])]
    out = []
    for m in ids:
        full = svc.users().messages().get(userId="me", id=m, format="full").execute()
        hdr = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        parts = full.get("payload", {}).get("parts", [full.get("payload", {})])
        body = ""
        def grab(p):
            nonlocal body
            if p.get("mimeType") == "text/plain" and "data" in p.get("body", {}):
                body += _decode(p["body"]["data"])
            elif p.get("mimeType") == "text/html" and "data" in p.get("body", {}):
                body += _decode(p["body"]["data"])
            for sp in p.get("parts", []):
                grab(sp)
        grab(full.get("payload", {}))
        out.append({"id": m, "from": hdr.get("From", ""), "subject": hdr.get("Subject", ""),
                   "date": hdr.get("Date", ""), "body": body[:1200]})
    return out

def pull_calendar(creds, hours):
    svc = disc.build("calendar", "v3", credentials=creds, cache_discovery=False)
    now = datetime.now(timezone.utc)
    tmin = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    tmax = (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev = svc.events().list(calendarId="primary", timeMin=tmin, timeMax=tmax, maxResults=25,
                           orderBy="startTime", singleEvents=True).execute()
    return [{"summary": e.get("summary"), "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
             "status": e.get("status"), "id": e.get("id")} for e in ev.get("items", [])]

def pull_drive(creds, n):
    svc = disc.build("drive", "v3", credentials=creds, cache_discovery=False)
    fl = svc.files().list(pageSize=n, orderBy="modifiedTime desc",
                          fields="files(id,name,mimeType,modifiedTime,owners,shared)").execute()
    return [{"name": f.get("name"), "mime": f.get("mimeType"), "modified": f.get("modifiedTime"),
             "shared": f.get("shared")} for f in fl.get("files", [])]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--acct", default="OPERATOR_EMAIL")
    ap.add_argument("--gmail-q", default="newer_than:2d")
    ap.add_argument("--gmail-n", type=int, default=20)
    ap.add_argument("--cal-hours", type=int, default=48)
    ap.add_argument("--drive-n", type=int, default=10)
    ap.add_argument("--full-text", action="store_true", help="Pull Gmail body text (slower; for actionable classification)")
    args = ap.parse_args()

    creds, d, path = load_creds(args.acct)
    creds = ensure_fresh(creds, d, path)
    print(f"[auth] {args.acct} token {'valid' if creds.valid else 'STALE'}", file=sys.stderr)

    result = {}
    any_ok = False
    try:
        result["gmail"] = (pull_gmail_full if args.full_text else pull_gmail)(creds, args.gmail_q, args.gmail_n)
        any_ok = True
    except Exception as e:
        result["gmail"] = f"FAIL: {e}"
    try:
        result["calendar"] = pull_calendar(creds, args.cal_hours)
        any_ok = True
    except Exception as e:
        result["calendar"] = f"FAIL: {e}"
    try:
        result["drive"] = pull_drive(creds, args.drive_n)
        any_ok = True
    except Exception as e:
        result["drive"] = f"FAIL: {e}"

    print(json.dumps(result, indent=2))
    sys.exit(0 if any_ok else 6)

if __name__ == "__main__":
    main()
