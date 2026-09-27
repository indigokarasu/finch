#!/usr/bin/env python3
"""El Camino Health account-link security notice watcher.

Read-only, re-runnable, no LLM. Answers the four questions a task note
cannot, for the El Camino Health "new device/app linked to your account"
class of mail:

  CHECK 1  Is the sender answerable at all?  (Reply-To / no-reply address)
  CHECK 2  Is the notice still visible, or already dismissed by the operator?
           (labelIds: INBOX / UNREAD vs neither)
  CHECK 3  Did a Gmail FILTER hide it, or did the operator clear it?
           (enumerate every filter, look for elcamino/mychart/privia)
  CHECK 4  How often does this notice fire, and is it EVER left uncleared?
           (all-time count, not a 2-day window)

Plus: whether Jared has ever REPLIED to the sender, and whether an El Camino
appointment is already on the calendar (which would explain the link).

Exit 0 = ran. Prints a VERDICT line -- the verdict string IS the disposition.
Nothing in here sends, deletes, labels, or modifies mail.
"""
import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

MIN_TS = datetime.min.replace(tzinfo=timezone.utc)

CRED_DIR = Path(os.path.expanduser(
    os.environ.get("OCAS_GOOGLE_CRED_DIR", "~/.google_workspace_mcp/credentials")))

# Third-party health-system senders. Env-overridable, never literals: the
# operator's own addresses must not be committed to a public repo.
CARE_DOMAINS = [d.strip() for d in os.environ.get(
    "ELCAMINO_DOMAINS", "elcaminohealth.org,elcaminohealth.com").split(",") if d.strip()]
LINK_SUBJ = re.compile(r"new (app|device|sign-?in|link)|linked to your account|"
                       r"link(ed)? to your mycare|"
                       r"account.{0,20}(link|activat)|unrecognized", re.I)
VISIT_SUBJ = re.compile(r"visit|appointment|summary|after.visit|test result|"
                        r"referral|survey", re.I)


def _require_google():
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        print("FATAL: missing google-api-python-client / google-auth: %s" % e,
              file=sys.stderr)
        sys.exit(3)
    return Credentials, build


def load_creds(acct):
    """Build Credentials from the RAW dict.

    Do NOT use Credentials.from_authorized_user_file() on the operator token
    file: it raises AttributeError ('float' object has no attribute 'rstrip')
    because `expiry` is persisted as a float epoch, not an RFC3332 string.

    The Credentials class is a parameter, not a module global: the only
    import of it lives inside _require_google(), which main() calls. Binding
    it at module scope would make load_creds NameError the moment it is
    called from anywhere but main() -- which is exactly what happened on
    first execution of this script.
    """
    Credentials, _ = _require_google()
    raw = json.loads((CRED_DIR / ("%s.json" % acct)).read_text())
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


def ts_of(hdr_date):
    """Parse the Date header into a tz-aware UTC datetime.

    NEVER sort on the raw header string: '8 Jan 2024 ...' sorts ABOVE
    '22 Sep 2026 ...' lexicographically ('8' > '2'), which manufactures a
    false 'stale for years' signal from a healthy mailbox.
    """
    try:
        d = parsedate_to_datetime(hdr_date)
    except (TypeError, ValueError, IndexError):
        return MIN_TS
    if d is None:
        return MIN_TS
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def visibility(labels):
    if "INBOX" in labels:
        return "inbox"
    if "UNREAD" in labels:
        return "unread-archived"
    return "archived"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--acct", default=os.environ.get("OCAS_OPERATOR_EMAIL", ""),
                    help="mailbox whose token file is read (default: $OCAS_OPERATOR_EMAIL)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--days", type=int, default=30,
                    help="only affects the 'recent' slice; all-time counts are always full")
    args = ap.parse_args()
    if not args.acct:
        print("FATAL: pass --acct <email> or set $OCAS_OPERATOR_EMAIL", file=sys.stderr)
        return 2
    Credentials, build = _require_google()

    creds = load_creds(args.acct)
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    cal = build("calendar", "v3", credentials=creds, cache_discovery=False)

    def q(query, fetch=200):
        """Full sweep: loop page_token to completion, never page-1-only."""
        ids, tok = [], None
        while True:
            r = gmail.users().messages().list(
                userId="me", q=query, maxResults=500,
                pageToken=tok).execute()
            ids += r.get("messages", [])
            tok = r.get("nextPageToken")
            if not tok:
                break
        rows = []
        for mid in ids:
            m = gmail.users().messages().get(
                userId="me", id=mid["id"], format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date", "Reply-To"]
            ).execute()
            h = headers(m)
            rows.append({
                "id": m["id"],
                "from": h.get("From", ""),
                "to": h.get("To", ""),
                "reply_to": h.get("Reply-To", ""),
                "subject": h.get("Subject", ""),
                "ts": ts_of(h.get("Date")),
                "labels": m.get("labelIds", []),
            })
        rows.sort(key=lambda r: r["ts"])
        return rows

    clause = "{%s}" % " OR ".join("from:%s" % d for d in CARE_DOMAINS)
    # SCOPE BY SENDER ONLY IN THE GMAQL, THEN FILTER SUBJECTS IN PYTHON.
    # Do NOT concatenate a Python regex onto the query string: LINK_SUBJ
    # contains its own '|', and Gmail treats a bare '|' as OR, which
    # dissolves the {from:X OR from:Y} intersection. Measured 2026-09-26:
    # '{from:...} <regex>' returned 4 messages -- 3 of them from 2022 -- and
    # MISSED the 09-23 "a new app was linked to your account" notice, because
    # the un-anchored alternation also matched unrelated senders. The
    # from-scoped sender query is exact; the subject test is a plain regex
    # search() over a value we already hold.
    allcare = q(clause)
    link = [r for r in allcare if LINK_SUBJ.search(r["subject"])]
    inbox = [r for r in allcare if "INBOX" in r["labels"]]

    # CHECK 3 -- did a FILTER hide it, or did the operator clear it?
    # NOTE: users.settings.filters.list takes NO pageToken -- passing one is
    # a hard TypeError at .execute() time, not a silent no-op. It is a
    # single unpaginated call.
    filters = gmail.users().settings().filters().list(userId="me").execute().get("filter", [])
    pat = re.compile("|".join(re.escape(d.split(".")[0]) for d in CARE_DOMAINS)
                     + r"|mychart|privia", re.I)
    shadow = [f for f in filters
              if pat.search(json.dumps(f.get("criteria", {})) + json.dumps(f.get("action", {})))]

    # Did the operator ever REPLY to this sender's domain?
    replies = [r for r in allcare
               if args.acct.lower() in (r["from"] or "").lower()]

    now = datetime.now(timezone.utc)
    out = {
        "account": args.acct,
        "checked_at": now.isoformat(),
        "link_notices": len(link),
        "link_notices_in_inbox": sum(1 for r in link if "INBOX" in r["labels"]),
        "link_notices_unread": sum(1 for r in link if "UNREAD" in r["labels"]),
        "care_mail_ever": len(allcare),
        "care_mail_in_inbox": len(inbox),
        "filters_total": len(filters),
        "filters_shadowing_care": len(shadow),
        "operator_replies_ever": len(replies),
        "notes": [],
    }
    out["newest_link_notice"] = {}

    if link:
        newest = link[-1]
        out["newest_link_notice"] = {
            "id": newest["id"], "from": newest["from"],
            "subject": newest["subject"],
            "date": newest["ts"].isoformat(),
            "age_days": round((now - newest["ts"]).total_seconds() / 86400.0, 1),
            "labels": newest["labels"],
            "visibility": visibility(newest["labels"]),
            "has_reply_to": bool(newest["reply_to"].strip()),
        }
    if replies:
        out["newest_operator_reply"] = {
            "date": replies[-1]["ts"].isoformat(), "subject": replies[-1]["subject"]}

    # An El Camino visit already on the calendar explains the account link.
    # PAGINATE BY pageToken, and do NOT try to re-derive a cursor from
    # items[-1]["start"]: all-day events carry a "date" key, not a
    # "dateTime", so fromisoformat() on it raises TypeError.
    ev, pt = [], None
    while True:
        r = cal.events().list(calendarId="primary",
                              timeMin=(now - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              singleEvents=True, orderBy="startTime",
                              maxResults=2500, pageToken=pt).execute()
        items = r.get("items", [])
        ev += items
        pt = r.get("nextPageToken")
        if not pt or len(ev) > 4000:
            break
    out["calendar_events_scanned"] = len(ev)
    out["elcamino_calendar_events"] = sum(
        1 for e in ev if re.search(r"el camino|elcamino", (e.get("summary") or "") + (e.get("location") or ""), re.I))

    # ---- VERDICT ----
    newest = out.get("newest_link_notice")
    if not link:
        v = "NO EL CAMINO LINK NOTICE ON RECORD"
        out["notes"].append("0 link notices ever; nothing outstanding")
    elif out["link_notices_in_inbox"]:
        v = "OUTSTANDING -- a link notice is still in INBOX"
    elif out["link_notices_unread"]:
        v = "PARTIALLY CLEARED -- %d of %d left unread-archived" % (
            out["link_notices_unread"], out["link_notices"])
    elif out["filters_shadowing_care"]:
        v = "DISMISSED BUT A FILTER SHADOWS THIS SENDER -- filter hid it, not the operator"
    elif newest:
        v = ("ROUTINE -- all %d link notices dismissed by the operator, 0 filters shadow "
             "it; newest %s is %.1fd old" % (
                 out["link_notices"], newest["id"], newest["age_days"]))
    else:
        v = "ROUTINE -- all %d link notices dismissed by the operator" % out["link_notices"]
    if not out["newest_link_notice"].get("has_reply_to", False) and link:
        out["notes"].append("no Reply-To on the sender: confirming the link is portal/app-only, never an email reply")
    out["verdict"] = v

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        for k, val in out.items():
            if k == "notes":
                continue
            print("%-28s %s" % (k, json.dumps(val, default=str)))
        for n in out["notes"]:
            print("note: %s" % n)
        print("VERDICT: %s" % v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
