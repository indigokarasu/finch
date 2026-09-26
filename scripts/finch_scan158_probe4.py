#!/usr/bin/env python3
"""finch scan #158 — date+subject probe via internalDate (header workaround)."""
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


def show(q, n=4):
    r = svc.users().messages().list(userId="me", q=q, maxResults=n).execute()
    for mm in r.get("messages", []):
        g = svc.users().messages().get(userId="me", id=mm["id"],
                                       format="full").execute()
        hh = {x["name"].lower(): x["value"]
              for x in g["payload"].get("headers", [])}
        dt = datetime.datetime.utcfromtimestamp(
            int(g["internalDate"]) / 1000).strftime("%Y-%m-%d %H:%MZ")
        print("  [%s] %s | %s | %s" % (g["id"], dt, hh.get("from", "")[:52],
                                       hh.get("subject", "")[:60]))


for q in ["hoobs", "from:edd.ca.gov", "hoorii", "from:loox.io",
          "from:noreply-accounts@google.com newer_than:3d"]:
    print("q=%s" % q)
    show(q)
