#!/usr/bin/env python3
"""ucsf_mychart_invites.py — UCSF MyChart scheduling-invite watch (read-only).

WHY THIS EXISTS
  UCSF MyChart "New Invitation to Schedule an Appointment" notices arrive from
  a DO-NOT-REPLY address. There is nothing to reply to — they are pure
  notifications. Booking happens in MyChart (web/app) or by phone. Any
  briefing or task that describes them as "needs a reply" is wrong, and an
  agent that tries to answer one is answering a black hole.

  The notice body also carries NO clinic name, specialty, or reason — the only
  place that information exists is inside MyChart. So an email-side agent
  cannot determine WHAT is being requested, only THAT something is outstanding.

  This script answers the three questions that are answerable from the API:
    1. Are there outstanding invites, and are they still visible (INBOX) or
       already dismissed (archived / no INBOX label)?
    2. Is a filter auto-archiving UCSF mail (i.e. is the miss not Jared's)?
    3. Did the invite convert into a booked appointment (Confirmation mail or
       a calendar event)?

  Exit 0 always unless the Gmail/Calendar API is unreachable (exit 1), so it
  is cron-safe.

USAGE
  python3 ucsf_mychart_invites.py [--acct <email>] [--json] [--days 30]

  Default account is Jared's. Credentials are read from
  ~/.google_workspace_mcp/credentials/<acct>.json and the token self-refreshes.

  GOTCHA (do not use Credentials.from_authorized_user_file here): it raises
  AttributeError: 'float' object has no attribute 'rstrip' on these token
  files because `expiry` is persisted as a float epoch rather than RFC3339.
  Build Credentials from the raw dict, as gws_direct_puller.py::load_creds does.
"""
import argparse
import base64
import json
import re
import sys
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError as e:  # pragma: no cover
    print(f"FATAL: missing google-api-python-client / google-auth: {e}")
    sys.exit(1)

CRED_DIR = Path("/root/.google_workspace_mcp/credentials")
NOTIFY = "donotreplyucsfmychart@ucsf.edu"
BILLING = "donotreplyucsf@ucsf.edu"
INVITE_SUBJ = "New Invitation to Schedule an Appointment"
FOLLOWUP = "Follow-up|follow up|Follow Up"

# Cues that identify an outstanding-care thread in a calendar summary.
CARE_CUES = re.compile(
    r"ucsf|bayfront|ortho|podiatr|foot|ankle|saxena|mychart|schoenbeck", re.I
)


def load_creds(acct):
    raw = json.loads((CRED_DIR / f"{acct}.json").read_text())
    return Credentials(
        token=raw.get("token"),
        refresh_token=raw.get("refresh_token"),
        token_uri=raw.get("token_uri"),
        client_id=raw.get("client_id"),
        client_secret=raw.get("client_secret"),
        scopes=raw.get("scopes"),
    )


def headers(msg):
    return {h["name"]: h["value"] for h in msg["payload"]["headers"]}


def body_text(part):
    if part.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
    return "\n".join(body_text(p) for p in (part.get("parts") or []))


def visibility(labels):
    if "INBOX" in labels:
        return "inbox"
    if "UNREAD" in labels:
        return "unread-archived"
    return "archived"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--acct", default="jared.zimmerman@gmail.com")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    creds = load_creds(args.acct)
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    cal = build("calendar", "v3", credentials=creds, cache_discovery=False)
    out = {"account": args.acct, "invites": [], "confirmations": [],
           "ucsf_filter": None, "booked_care_events": [], "notes": []}

    # 1. Outstanding invites, newest first.
    q = f"from:{NOTIFY} subject:\"{INVITE_SUBJ}\" newer_than:{args.days}d"
    for item in gmail.users().messages().list(
            userId="me", q=q, maxResults=25).execute().get("messages", []):
        m = gmail.users().messages().get(
            userId="me", id=item["id"], format="metadata").execute()
        h = headers(m)
        out["invites"].append({
            "id": m["id"], "thread": m["threadId"], "date": h.get("Date"),
            "labels": m["labelIds"], "visibility": visibility(m["labelIds"]),
        })

    # 2. Did any invite convert into a booked appointment?
    q = f'from:{NOTIFY} subject:"Appointment Confirmation" newer_than:{args.days}d'
    for item in gmail.users().messages().list(
            userId="me", q=q, maxResults=15).execute().get("messages", []):
        m = gmail.users().messages().get(userId="me", id=item["id"], format="full").execute()
        txt = body_text(m["payload"])
        flat = re.sub(r"\s+", " ", txt)
        date = re.search(r"Date:\s*<strong>([^<]+)", flat)
        time = re.search(r"Time:\s*<strong>([^<]+)", flat)
        prov = re.search(r"Provider:\s*<strong>([^<]+)", flat)
        out["confirmations"].append({
            "date": headers(m).get("Date"),
            "when": date.group(1) if date else None,
            "time": time.group(1) if time else None,
            "provider": prov.group(1) if prov else None,
        })

    # 3. Is a filter auto-archiving UCSF mail? Distinguishes "Jared missed it"
    #    from "the mailbox hid it" — the two demand different responses.
    try:
        filters = gmail.users().settings().filters().list(userId="me").execute().get("filter", [])
        for f in filters:
            if "ucsf" in json.dumps(f).lower():
                out["ucsf_filter"] = f
                break
        if out["ucsf_filter"] is None:
            out["notes"].append(
                "No Gmail filter references ucsf — archived invites were "
                "dismissed in a client, not auto-archived by a rule.")
    except Exception as e:  # settings scope may be absent
        out["notes"].append(f"filter check unavailable: {e}")

    # 4. Care events already on the calendar (an outstanding invite may already
    #    be covered by a visit booked through another channel).
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    ev = cal.events().list(calendarId="primary", timeMin=now.isoformat(),
                           timeMax=(now + datetime.timedelta(days=args.days)).isoformat(),
                           maxResults=50, singleEvents=True, orderBy="startTime").execute()
    for e in ev.get("items", []):
        if CARE_CUES.search(e.get("summary", "")):
            out["booked_care_events"].append({
                "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
                "summary": e.get("summary"),
            })

    # 5. Standing guidance, so no downstream agent re-derives it.
    out["notes"].append(
        f"{NOTIFY} is a DO-NOT-REPLY address: these notices cannot be "
        "answered by email. Booking is in MyChart (web/app) or by phone.")
    out["notes"].append(
        "Invite bodies name no clinic, specialty, or reason — the request "
        "content exists only inside MyChart, so an email-side check can report "
        "'outstanding' but never 'what for'.")

    if args.json:
        print(json.dumps(out, indent=2))
        return 0

    print(f"UCSF MyChart invite watch — {args.acct} (last {args.days}d)\n")
    if not out["invites"]:
        print("  Outstanding invites: NONE")
    for i in out["invites"]:
        print(f"  INVITE  {i['date'][:31]:31s} [{i['visibility']:16s}] {i['id']}")
    n_arch = sum(1 for i in out["invites"] if i["visibility"] != "inbox")
    if n_arch and len(out["invites"]) == n_arch:
        print("  -> ALL outstanding invites are no longer in the inbox.")
    if out["confirmations"]:
        print("\n  Booked (Appointment Confirmation):")
        for c in out["confirmations"]:
            print(f"    {c['when']} {c['time']}  {c['provider']}")
    if out["booked_care_events"]:
        print("\n  Care events already on calendar:")
        for e in out["booked_care_events"]:
            print(f"    {e['start']}  {e['summary'][:64]}")
    print("\n  Notes:")
    for n in out["notes"]:
        print(f"    - {n}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # cron-safe: never a traceback storm
        print(f"FAIL: {type(exc).__name__}: {exc}")
        sys.exit(1)
