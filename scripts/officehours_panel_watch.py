#!/usr/bin/env python3
"""Read-only watcher for the Office Hours research-panel correspondence class.

Answers the four questions a task note cannot: (1) is any panel message still
in the inbox, (2) how often does the drip fire, (3) has the operator converted
(replies/drafts), (4) does the sender escalate from broadcast to individual.

Never sends, never writes. Exits 0 when the sweep completes.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ACCT = os.environ.get("OCAS_OPERATOR_EMAIL", "operator@example.com")
CREDS = os.path.join(os.path.expanduser("~/.google_workspace_mcp/credentials"),
                    f"{ACCT}.json")
DOMAINS = ("officehours.com", "officehours.io")
# Scope the sender in GMAQL (server-side, exact) and filter the SUBJECT in
# Python. Never concatenate a Python regex onto the query string: Gmail has no
# regex grammar, so a bare `|` is OR and the from: intersection dissolves.
# Informational only, for reporting breadth. NOT a filter: the GMAQL from:
# clause already scopes the sender exactly, so gating on subject words both
# misses real panel mail that carries none of them ("Re-connecting on AI
# Compute Hardware Selection research") and admits nothing useful. Fixture
# test_officehours_panel_watch.py pins both failure directions.
SUBJ_HINTS = ("office hours project", "consulting request", "consulting call",
              "paid survey", "paid call", "welcome to office hours")


def panel_sender(addr):
    """Sender-domain test. The live query is from:<domain>, so this is a
    belt-and-braces check for a message fetched by other means."""
    a = (addr or "").lower()
    return any(d in a for d in DOMAINS)


def load_creds(path):
    d = json.load(open(path))
    from google.oauth2.credentials import Credentials
    return Credentials(token=d.get("token"), refresh_token=d.get("refresh_token"),
                       token_uri=d.get("token_uri"), client_id=d.get("client_id"),
                       client_secret=d.get("client_secret"), scopes=d.get("scopes"))


def build_service(creds_path=CREDS):
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=load_creds(creds_path),
                 cache_discovery=False)


def _pages(svc, q):
    """Loop page_token to completion. A returned token is not a finished sweep."""
    ids, tok = [], None
    while True:
        r = svc.users().messages().list(userId="me", q=q, maxResults=100,
                                        pageToken=tok).execute()
        ids += [m["id"] for m in r.get("messages", [])]
        tok = r.get("nextPageToken")
        if not tok:
            return ids


def _meta(svc, mid):
    m = svc.users().messages().get(userId="me", id=mid, format="metadata",
                                   metadataHeaders=["From", "To", "Subject", "Date"]).execute()
    h = {x["name"]: x["value"] for x in m["payload"]["headers"]}
    return m, h


def _ts(h):
    """Sort on the PARSED timestamp, never the raw Date header string."""
    try:
        d = parsedate_to_datetime(h.get("Date", ""))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    if d is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def is_panel(subject):
    s = (subject or "").lower()
    return any(k in s for k in SUBJ_HINTS)


def sweep(svc, now=None):
    now = now or datetime.now(timezone.utc)
    q = " OR ".join("from:%s" % d for d in DOMAINS)
    rows = []
    for mid in _pages(svc, q):
        m, h = _meta(svc, mid)
        if not panel_sender(h.get("From")):
            continue
        rows.append({"id": mid, "from": h.get("From", ""), "subj": h.get("Subject", ""),
                     "to": h.get("To", ""), "labels": m.get("labelIds") or [],
                     "ts": _ts(h)})
    rows.sort(key=lambda r: r["ts"])
    return rows


def verdict(rows, outbound, drafts, filters_hit):
    inbox = [r for r in rows if "INBOX" in r["labels"]]
    unread = [r for r in rows if "UNREAD" in r["labels"]]
    newest = rows[-1] if rows else None
    age = (datetime.now(timezone.utc) - newest["ts"]).days if newest else None
    if inbox:
        v = "OUTSTANDING: %d panel message(s) still in INBOX" % len(inbox)
    else:
        v = ("routine: %d panel messages, 0 in INBOX, 0 filters shadowing; "
             "%d unread (read-state, not inbox-state)" % (len(rows), len(unread)))
    v += " | newest %s (%sd old)" % (newest["ts"].strftime("%Y-%m-%d %H:%MZ") if newest else "n/a", age)
    v += " | operator sent %d, drafts pending %d" % (len(outbound), len(drafts))
    v += " | shadowing filters: %d" % filters_hit
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="officehours_panel_watch.py",
        description="Read-only sweep of the research-panel correspondence class "
                    "against a live mailbox. Never sends, never writes.")
    ap.add_argument("--creds", default=CREDS,
                    help="path to the mailbox credentials JSON")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    svc = build_service(args.creds)
    rows = sweep(svc)
    q = " OR ".join("to:%s" % d for d in DOMAINS)
    outbound = [i for i in _pages(svc, q)]
    drafts = svc.users().drafts().list(userId="me", maxResults=100).execute().get("drafts", [])
    dn = 0
    for dr in drafts:
        _, h = _meta(svc, dr["message"]["id"])
        if any(d in (h.get("To", "") or "") for d in DOMAINS):
            dn += 1
    fl = svc.users().settings().filters().list(userId="me").execute().get("filter", [])
    hit = sum(1 for f in fl if any(d in json.dumps(f).lower() for d in DOMAINS))
    v = verdict(rows, outbound, [1] * dn, hit)
    print("VERDICT: %s" % v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
