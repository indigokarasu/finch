#!/usr/bin/env python3
"""vendor_welcome_watch.py -- read-only watcher for a vendor's expert-onboarding drip.

Genericised template (see references/reference-file-workflow.md): the published repo
carries no real vendor, account or path.  Supply them at RUNTIME:

    VENDOR=acme VENDOR_DOMAINS=acme.com,list.acme.com \
    CREDS=~/.google_workspace_mcp/credentials/me@example.json \
    python3 vendor_welcome_watch.py

Answers the four questions a task note cannot, and prints a VERDICT string that IS
the disposition:

  1. ACCOUNT ORIGIN  -- did the operator open this account himself (a Google sign-in
                        grant), or is it inbound/cold?  A task note may assume inbound.
  2. DRIP STATE      -- which onboarding steps have arrived, newest first, and how
                        many days since the last one (is the drip still live?).
  3. VISIBILITY      -- per message: still INBOX/UNREAD (NOT triaged) or cleared.
                        Cleared + no shadowing filter = the operator's own action.
  4. CONVERSION      -- did a reply ever go out, and did a welcome session ever land
                        on the calendar?

Read-only. No LLM. Loops page_token to completion. Exit 0 on a clean run.

Usage:  python3 vendor_welcome_watch.py [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

VENDOR = os.environ.get("VENDOR", "vendor")
# Server-side scoping only: query the sender, then match subjects in PYTHON.  Never
# concatenate a Python regex onto a GMAQL string -- a bare '|' is OR in Gmail's
# grammar and silently dissolves the intersection (see work-execution-procedures.md).
DOMAINS = tuple(
    d.strip() for d in os.environ.get("VENDOR_DOMAINS", f"{VENDOR}.com").split(",") if d.strip()
)
CRED = os.path.expanduser(
    os.environ.get("CREDS", "~/.google_workspace_mcp/credentials/operator@example.com.json")
)
FROM_QUERIES = tuple(f"from:{d}" for d in DOMAINS)
DASH = "-" * 78

# Subject fragments of any PRE-EXISTING relationship with the same vendor, which
# predates the account.  A 4-year-old thread in the same domain makes a naive
# 'to:<domain>' sweep report OUTBOUND=1 and imply engagement that never happened.
PREDRIP = tuple(
    s.strip().lower()
    for s in os.environ.get("PREDRIP_SUBJECTS", "interested in teaching a course").split("|")
    if s.strip()
)


def load_creds(path: str = CRED):
    """Build Credentials from the RAW dict.

    Credentials.from_authorized_user_file() raises AttributeError on this token
    file ('float' object has no attribute 'rstrip') because `expiry` is persisted
    as a float epoch rather than an RFC3339 string.
    """
    from google.oauth2.credentials import Credentials

    d = json.load(open(path))
    return Credentials(
        token=d.get("token"),
        refresh_token=d.get("refresh_token"),
        token_uri=d.get("token_uri"),
        client_id=d.get("client_id"),
        client_secret=d.get("client_secret"),
        scopes=d.get("scopes"),
    )


def parse_ts(date_header: str) -> datetime:
    """Parse the RFC-2822 Date header into an aware UTC datetime.

    NEVER sort on the raw header string: '8 Jan 2024 22:15:38 -0800' sorts AFTER
    '22 Sep 2026 06:24:27 -0700' lexicographically ('8' > '2'), which makes a
    4-day-old message report as years stale.
    """
    try:
        dt = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sweep(svc, query: str, cap: int = 40):
    """Page to completion. A next_page_token is not a finished sweep."""
    ids, tok = [], None
    while True:
        r = svc.users().messages().list(
            userId="me", q=query, maxResults=cap, pageToken=tok
        ).execute()
        ids.extend(m.get("id") for m in r.get("messages", []))
        tok = r.get("nextPageToken")
        if not tok:
            break
    return ids


def meta(svc, mid: str):
    f = svc.users().messages().get(
        userId="me", id=mid, format="metadata",
        metadataHeaders=["From", "To", "Subject", "Date"],
    ).execute()
    h = {x["name"]: x["value"] for x in f["payload"]["headers"]}
    return {
        "id": mid,
        "date_raw": h.get("Date", ""),
        "ts": parse_ts(h.get("Date", "")),
        "from": h.get("From", ""),
        "to": h.get("To", ""),
        "subject": h.get("Subject", ""),
        "labels": f.get("labelIds", []),
    }


def collect(svc):
    seen, rows = set(), []
    for q in FROM_QUERIES:
        for mid in sweep(svc, q):
            if mid in seen:
                continue
            seen.add(mid)
            rows.append(meta(svc, mid))
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows


def analyse(svc, cal_svc, now=None):
    now = now or datetime.now(timezone.utc)
    rows = collect(svc)
    drip = [r for r in rows if not any(p in r["subject"].lower() for p in PREDRIP)]

    # (1) account origin -- a Google sign-in grant naming the vendor is proof the
    # operator self-opened the account (it inverts a task note that assumed inbound)
    grant_q = "from:noreply-accounts@google.com"
    grants = [m for m in (meta(svc, i) for i in sweep(svc, grant_q)) if VENDOR in m["subject"].lower()]

    # (3) shadowing -- an unpaginated call; it takes NO pageToken (TypeError if given)
    filters = svc.users().settings().filters().list(userId="me").execute().get("filter", [])
    shadow = [f for f in filters if VENDOR in json.dumps(f).lower()]

    # (4) conversion.  The outbound count must EXCLUDE the pre-drip relationship
    # thread: a 2022 reply to a senior contact at the same vendor is evidence about
    # a different relationship, and counting it would report a false 'engaged' on a
    # drip the operator has never written to.
    outbound = []
    for q in tuple(f"to:{d}" for d in DOMAINS) + (f"{VENDOR} in:drafts",):
        for mid in sweep(svc, q):
            r = meta(svc, mid)
            if "SENT" not in r["labels"] and "DRAFT" not in r["labels"]:
                continue
            if any(p in r["subject"].lower() for p in PREDRIP):
                continue
            outbound.append(r)
    cal_hits, cal_total, tok = [], 0, None
    while True:
        page = cal_svc.events().list(
            calendarId="primary", maxResults=2500, singleEvents=True, pageToken=tok
        ).execute()
        cal_total += len(page.get("items", []))
        for it in page.get("items", []):
            if VENDOR in json.dumps(it).lower():
                cal_hits.append(it.get("summary", ""))
        tok = page.get("nextPageToken")
        if not tok:
            break

    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "drip": [{**r, "age_days": round((now - r["ts"]).total_seconds() / 86400, 2),
                  "in_inbox": "INBOX" in r["labels"], "unread": "UNREAD" in r["labels"]}
                 for r in drip],
        "predrip_count": len(rows) - len(drip),
        "self_opened": bool(grants),
        "grant": grants[0] if grants else None,
        "filter_count": len(filters),
        "shadowing_filters": len(shadow),
        "outbound": [{k: r[k] for k in ("id", "ts", "labels", "subject")} for r in outbound],
        "calendar_events_scanned": cal_total,
        "calendar_vendor_events": cal_hits,
    }


def verdict(a):
    live = [r for r in a["drip"] if r["age_days"] <= 7]
    outstanding = [r for r in a["drip"] if r["in_inbox"]]
    newest = a["drip"][0] if a["drip"] else None
    origin = "SELF-OPENED" if a["self_opened"] else "INBOUND"
    head = (
        f"{newest['subject'][:40]!r} @ {newest['date_raw'][:25]} ({newest['age_days']}d)"
        if newest else "none"
    )
    return (
        f"ORIGIN={origin} (Google sign-in grant present={a['self_opened']}); "
        f"DROP_MESSAGES={len(a['drip'])} (of which newer_than_7d={len(live)}); "
        f"NEWEST={head}; "
        f"STILL_IN_INBOX={len(outstanding)}; "
        f"SHADOWING_FILTERS={a['shadowing_filters']}/{a['filter_count']}; "
        f"OUTBOUND={len(a['outbound'])}; "
        f"SESSION_ON_CALENDAR={len(a['calendar_vendor_events'])}"
        f" (of {a['calendar_events_scanned']} events scanned) -> "
        "DECISION IS THE OPERATOR'S; NO EMAIL ACTION EXISTS (booking is a vendor web "
        "link, login-walled). " + (
            "No INBOX residue and no filter shadowing => the drip is routine and "
            "fully triaged by the operator himself; anti_churn."
            if not outstanding and not a["shadowing_filters"]
            else "INBOX residue present => genuinely untriaged."
        )
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    from googleapiclient.discovery import build

    creds = load_creds()
    svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
    cal = build("calendar", "v3", credentials=creds, cache_discovery=False)
    a = analyse(svc, cal)

    if args.json:
        print(json.dumps(a, indent=2, default=str))
        return 0

    print(DASH)
    print(f"{VENDOR.upper()} WELCOME-SESSION WATCH   generated_at={a['generated_at']}")
    print(DASH)
    print(f"ACCOUNT ORIGIN : "
          f"{'SELF-OPENED by the operator (Google sign-in grant present)' if a['self_opened'] else 'inbound / unknown'}")
    if a["grant"]:
        print(f"                grant: {a['grant']['date_raw'][:31]}  {a['grant']['subject'][:50]}")
    print(f"ONBOARDING DRIP: {len(a['drip'])} {VENDOR} messages "
          f"(+{a['predrip_count']} pre-2026 'teaching a course' thread, excluded)")
    for r in a["drip"]:
        flag = "INBOX/UNREAD" if r["in_inbox"] and r["unread"] else ("INBOX" if r["in_inbox"] else "cleared")
        print(f"   {r['ts']:%Y-%m-%d %H:%MZ}  {r['age_days']:>6.2f}d  [{flag:<10}]  "
              f"{r['subject'][:58]}")
    print(f"FILTER SHADOW : {a['shadowing_filters']} of {a['filter_count']} Gmail filters reference the vendor")
    print(f"CONVERSION    : {len(a['outbound'])} outbound/draft to {VENDOR}; "
          f"{len(a['calendar_vendor_events'])} calendar events naming the vendor "
          f"(of {a['calendar_events_scanned']} scanned)")
    for it in a["calendar_vendor_events"][:5]:
        print(f"                - {it[:70]}")
    print(DASH)
    print("VERDICT:", verdict(a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
