#!/usr/bin/env python3
"""finch scan #158 — live label verification for specific message ids."""
import json, os
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

IDS = [
    "1a0dbc680fe3a25a",   # Crosswalk reply (staged draft per task #85)
    "1a0dbc8aed6c465b",   # 'I survived foot surgery' (blank-subject watch)
    "1a0dbd97e5a0dbd1",   # Screens & Things invoice thread, Jared reply
    "1a0db38c91c68e7d",   # Abbott thread
    "1a0dbe141ae7ba32",   # Google: shared data with Mesh
    "1a0dc19d923648bd",   # Global Entry fwd, Jared reply
    "1a0dbafe9bd8b60b",   # 'Not a perfect fit, but do you know more about the role?'
    "1a0d9e0b3d8ecf74",   # Bolt PR reply
]
for mid in IDS:
    m = svc.users().messages().get(userId="me", id=mid,
                                   format="metadata").execute()
    h = {x["name"]: x["value"] for x in m["payload"]["headers"]
         if x["name"] in ("From", "To", "Subject", "Date")}
    print("%s\n  labels=%s" % (mid, m.get("labelIds")))
    print("  from=%s" % h.get("From"))
    print("  subj=%s" % h.get("Subject"))
    print("  date=%s" % h.get("Date"))

# Crosswalk thread sweep
print("\n--- CROSSWALK THREAD 1a06e0b361a9e654 ---")
th = svc.users().threads().get(userId="me", id="1a06e0b361a9e654").execute()
for m in th["messages"]:
    hh = {x["name"]: x["value"] for x in m["payload"]["headers"]
          if x["name"] in ("From", "Subject", "Date")}
    print("  %s %s | %s | %s" % (m["id"], hh.get("date"), hh.get("from"),
                                 m.get("labelIds")))

print("\n--- SCREENS & THINGS THREAD 1a0cb4d669684b5f ---")
th = svc.users().threads().get(userId="me", id="1a0cb4d669684b5f").execute()
for m in th["messages"][-5:]:
    hh = {x["name"]: x["value"] for x in m["payload"]["headers"]
          if x["name"] in ("From", "Subject", "Date")}
    print("  %s %s | %s | %s" % (m["id"], hh.get("date"), hh.get("from"),
                                 m.get("labelIds")))

print("\n--- BJAK THREAD 1a0d32b9121d6313 ---")
try:
    th = svc.users().threads().get(userId="me", id="1a0d32b9121d6313").execute()
    for m in th["messages"]:
        hh = {x["name"]: x["value"] for x in m["payload"]["headers"]
              if x["name"] in ("From", "Subject", "Date")}
        print("  %s %s | %s | %s" % (m["id"], hh.get("date"), hh.get("from"),
                                     m.get("labelIds")))
except Exception as e:
    print("  ERR", e)
