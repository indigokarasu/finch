#!/usr/bin/env python3
"""finch scan #158 — second probe: Abbott reply, foot-surgery thread, Mesh grant."""
import json, os, base64
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


def body(mid, maxlen=1200):
    m = svc.users().messages().get(userId="me", id=mid, format="full").execute()
    out = []
    def walk(p):
        if p.get("body", {}).get("data"):
            out.append(p["body"]["data"])
        for c in p.get("parts", []) or []:
            walk(c)
    walk(m["payload"])
    txt = ""
    for d in out:
        try:
            txt += base64.urlsafe_b64decode(d + "==").decode("utf-8", "ignore")
        except Exception:
            pass
    txt = " ".join(txt.split())
    return m, txt[:maxlen]


print("=== ABBOTT THREAD 1a0db38c91c68e7d ===")
th = svc.users().threads().get(userId="me", id="1a0db38c91c68e7d").execute()
for m in th["messages"]:
    print("  %s %s" % (m["id"], m.get("labelIds")))

print("\n=== FOOT SURGERY THREAD 1a0dbbd505c2fb94 ===")
try:
    th = svc.users().threads().get(userId="me", id="1a0dbbd505c2fb94").execute()
    print("  msgs=%d" % len(th["messages"]))
    for m in th["messages"]:
        h = {x["name"]: x["value"] for x in m["payload"]["headers"]
             if x["name"] in ("From", "To", "Subject", "Date")}
        print("  %s %s | from=%s | subj=%s | labels=%s" % (
            m["id"], h.get("date"), h.get("from"), h.get("subject"),
            m.get("labelIds")))
    if len(th["messages"]) == 1:
        m, t = body(th["messages"][0]["id"])
        print("  BODY: %s" % t[:600])
except Exception as e:
    print("  ERR", e)

print("\n=== GOOGLE / MESH GRANT ===")
m, t = body("1a0dbe141ae7ba32", 900)
print(t)

print("\n=== SCREENS & THINGS DRAFT (Jared reply) ===")
m, t = body("1a0dbd97e5a0dbd1", 900)
h = {x["name"]: x["value"] for x in m["payload"]["headers"]
     if x["name"] in ("From", "To", "Subject", "Date")}
print("  to=%s date=%s" % (h.get("To"), h.get("Date")))
print("  BODY: %s" % t[:600])

print("\n=== HOOBS / 475HOA / EDD / HooRii sweep (last 3d) ===")
for q in ["hoobs", "from:edd.ca.gov", "hoorii"]:
    r = svc.users().messages().list(userId="me", q="%s newer_than:3d" % q,
                                    maxResults=5).execute()
    print("  q=%s -> %d" % (q, len(r.get("messages", []))))
    for mm in r.get("messages", []):
        g = svc.users().messages().get(userId="me", id=mm["id"],
                                       format="metadata").execute()
        hh = {x["name"]: x["value"] for x in g["payload"]["headers"]
              if x["name"] in ("From", "Subject", "Date")}
        print("     %s %s | %s | %s" % (mm["id"], hh.get("date"),
                                         hh.get("from"), hh.get("subject")))
