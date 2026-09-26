#!/usr/bin/env python3
"""finch scan #158 — HOOBS / EDD / HooRii / Fantom date probe."""
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

for q in ["hoobs", "from:edd.ca.gov", "hoorii", "from:loox.io"]:
    r = svc.users().messages().list(userId="me", q=q, maxResults=5).execute()
    ids = r.get("messages", [])
    if not ids:
        print("q=%s -> 0" % q)
        continue
    g = svc.users().messages().get(
        userId="me", id=ids[0]["id"], format="full",
        metadataHeaders=["From", "Subject", "Date"]).execute()
    hh = {x["name"]: x["value"] for x in g["payload"].get("headers", [])
          if x["name"] in ("From", "Subject", "Date")}
    print("q=%s  latest_of_%d  %s  %s  %s  labels=%s" % (
        q, len(ids), hh.get("date"), hh.get("from"), hh.get("subject"),
        g.get("labelIds")))

# Google OAuth grants in last 3 days
print("\n--- Google account-data grants, last 3d ---")
r = svc.users().messages().list(
    userId="me", q="from:noreply-accounts@google.com newer_than:3d",
    maxResults=15).execute()
for mm in r.get("messages", []):
    g = svc.users().messages().get(
        userId="me", id=mm["id"], format="metadata",
        metadataHeaders=["Subject", "Date"]).execute()
    hh = {x["name"]: x["value"] for x in g["payload"].get("headers", [])
          if x["name"] in ("Subject", "Date")}
    print("  %s  %s  |  %s" % (mm["id"], hh.get("date"), hh.get("subject")))
