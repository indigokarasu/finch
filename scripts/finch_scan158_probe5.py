#!/usr/bin/env python3
"""finch scan #158 — HOOBS vendor thread + reflection.ai/Amy context."""
import json, os, datetime
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CRED = os.path.expanduser(
    "~/.google_workspace_mcp/credentials/jared.zimmerman@gmail.com.json")
raw = json.load(open(CRED))
creds = Credentials(token=raw["token"])
if creds.expired and creds.refresh_token:
    creds.refresh(Request())
svc = build("gmail", "v1", credentials=creds, cache_discovery=False)

for q in ['"ticket #6361"', '6361', 'from:hoobslive OR from:hoobs.com OR subject:HOOBS']:
    r = svc.users().messages().list(userId="me", q=q, maxResults=6).execute()
    ids = r.get("messages", [])
    print("q=%s -> %d" % (q, len(ids)))
    for mm in ids:
        g = svc.users().messages().get(userId="me", id=mm["id"],
                                       format="full").execute()
        hh = {x["name"].lower(): x["value"]
              for x in g["payload"].get("headers", [])}
        dt = datetime.datetime.fromtimestamp(
            int(g["internalDate"]) / 1000, datetime.UTC).strftime("%m-%d %H:%MZ")
        print("   %s | %s | %s | %s | %s" % (
            g["id"], dt, hh.get("from", "")[:40], hh.get("subject", "")[:50],
            g.get("labelIds")))
