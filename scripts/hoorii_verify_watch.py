#!/usr/bin/env python3
"""HooRii / ClawStage account + vendor-thread watcher.

Read-only, re-runnable, no LLM. Written for the finch task
`email-hoorii-verify-account`, whose recorded premise ("HooRii Stage App
account verification pending") turned out to be unfalsifiable from the mailbox
AND superseded by a later event the task never registered.

It answers the four notification-sender triage checks, plus the question that
actually matters for this counterparty -- is a substantive report from Jared
still unanswered?

  CHECK 1  Is the sender answerable at all?           (Reply-To / no-reply)
  CHECK 2  Is the verification notice visible, or already dismissed?
  CHECK 3  Did a Gmail FILTER hide it, or did the operator clear it?
  CHECK 4  How often does a verify notice fire, and is EVER one left uncleared?
  CHECK 5  Has the operator ever written to this vendor, and is anything
           they wrote still unanswered?              (the live signal)

HARD LIMIT, stated rather than papered over: whether the ClawStage account is
actually ACTIVATED lives inside the app (the code is typed into a Register
button in the TestFlight build). Gmail cannot observe it. This script therefore
reports `verification_state_measured: false` with the reason, rather than
emitting an empty section that would read as "verified" / "not verified".

Exit 0 = ran. Prints a VERDICT line -- the verdict string IS the disposition.
Nothing here sends, deletes, labels, or modifies mail.
"""
import argparse
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

# Vendor domains, env-overridable: the operator's own addresses must never be
# committed to a public repo.
VENDOR_DOMAINS = [d.strip() for d in os.environ.get(
    "HOORII_DOMAINS", "hoorii.io").split(",") if d.strip()]
VENDOR_TERMS = r"hoorii|clawstage|claw stage|stage\.app"
VERIFY_SUBJ = re.compile(r"verify your account|verification code|activate your|"
                         r"confirm your email", re.I)
ANY_VENDOR = re.compile(VENDOR_TERMS, re.I)


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
    file: `expiry` is persisted as a float epoch there, not an RFC3332 string,
    so the factory raises AttributeError('float' object has no attribute
    'rstrip').

    Credentials is a PARAMETER here, not a module global: the only import of
    it lives inside _require_google(). Binding it at module scope makes
    load_creds NameError the moment it is called from anywhere but main().
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


def _headers(msg):
    return {h["name"]: h["value"] for h in msg["payload"]["headers"]}


def ts_of(hdr_date):
    """Parse the Date header into a tz-aware UTC datetime.

    NEVER sort on the raw header string: '8 Jan 2024 ...' sorts ABOVE
    '22 Sep 2026 ...' lexicographically ('8' > '2'), manufacturing a false
    'stale for years' signal from a healthy mailbox.
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


def _visibility(labels):
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
    ap.add_argument("--cal-days", type=int, default=400,
                    help="calendar lookback for vendor residue")
    args = ap.parse_args()
    if not args.acct:
        print("FATAL: pass --acct <email> or set $OCAS_OPERATOR_EMAIL", file=sys.stderr)
        return 2
    Credentials, build = _require_google()

    creds = load_creds(args.acct)
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    cal = build("calendar", "v3", credentials=creds, cache_discovery=False)

    def sweep(query):
        """Full sweep: loop page_token to completion, never page-1-only."""
        ids, tok = [], None
        while True:
            r = gmail.users().messages().list(
                userId="me", q=query, maxResults=500, pageToken=tok).execute()
            ids += r.get("messages", [])
            tok = r.get("nextPageToken")
            if not tok:
                break
        return [x["id"] for x in ids]

    def meta(mid):
        m = gmail.users().messages().get(
            userId="me", id=mid, format="metadata",
            metadataHeaders=["From", "To", "Cc", "Subject", "Date", "Reply-To"]
        ).execute()
        h = _headers(m)
        return {"id": m["id"], "thread": m.get("threadId"), "from": h.get("From", ""),
                "to": h.get("To", ""), "cc": h.get("Cc", ""),
                "reply_to": h.get("Reply-To"), "subject": h.get("Subject", ""),
                "ts": ts_of(h.get("Date")), "labels": m.get("labelIds", [])}

    # SCOPE BY SENDER ONLY IN THE GMAQL, THEN FILTER SUBJECTS IN PYTHON.
    # Never concatenate a Python regex onto the query string: its own '|'
    # is read by Gmail as OR, which dissolves the {from:X} intersection and
    # silently under-counts (measured on the El Camino watcher, #195).
    clause = "{%s}" % " OR ".join("from:%s" % d for d in VENDOR_DOMAINS)
    inbound = sorted((meta(i) for i in sweep(clause)), key=lambda r: r["ts"])

    verify = [r for r in inbound if VERIFY_SUBJ.search(r["subject"])]
    outbox = sorted((meta(i) for i in sweep("to:{%s}" % " ".join(VENDOR_DOMAINS))),
                    key=lambda r: r["ts"])

    # CHECK 3 -- users.settings.filters.list takes NO pageToken (passing one is
    # a hard TypeError at .execute(), not a silent no-op). Single call.
    filters_measured = True
    try:
        filters = gmail.users().settings().filters().list(userId="me").execute().get("filter", [])
    except Exception as e:                      # noqa: BLE001 -- report, do not fake
        filters, filters_measured = [], False
        filter_error = str(e)
    else:
        filter_error = None
    shadow = [f for f in filters
              if ANY_VENDOR.search(json.dumps(f.get("criteria", {}))
                                   + json.dumps(f.get("action", {})))]

    # CHECK 5 -- is anything the operator WROTE still unanswered?
    # TWO directions, and both matter:
    #   (a) inbound AFTER the operator's last write = the operator is behind;
    #   (b) the operator's last write with NO inbound after it = the VENDOR is
    #       behind. (b) is the one this task actually rests on, and a watcher
    #       that only checks (a) reports ROUTINE on a thread where the operator
    #       filed a substantive report and got silence. Checked only one way,
    #       it read as "no open signal" -- the same false-negative-in-the-safe-
    #       direction class the NOT MEASURED guard exists to prevent.
    last_out = outbox[-1]["ts"] if outbox else MIN_TS
    vendor_behind = [r for r in inbound if r["ts"] > last_out]
    operator_behind = outbox[-1] if outbox else None
    unanswered_by_vendor = bool(operator_behind) and not vendor_behind

    # Drafts: drafts.get() accepts NO metadataHeaders kwarg (TypeError at
    # .execute()). It returns {message: {...}} with no headers, so the header
    # read must be a second call to messages.get(msg_id, ...).
    drafts_measured = True
    try:
        dids, tok = [], None
        while True:
            r = gmail.users().drafts().list(userId="me", maxResults=100, pageToken=tok).execute()
            dids += [d["id"] for d in r.get("drafts", [])]
            tok = r.get("nextPageToken")
            if not tok:
                break
        vendor_drafts = []
        for did in dids:
            d = gmail.users().drafts().get(userId="me", id=did, format="minimal").execute()
            m = meta(d["message"]["id"])
            # default=str is REQUIRED: m["ts"] is a datetime, and a bare
            # json.dumps(m) raises TypeError on it. That failure was real --
            # it shipped in the first run and turned the draft count into a
            # self-reported NOT MEASURED, which is how the bug surfaced.
            if ANY_VENDOR.search(json.dumps(m, default=str)):
                vendor_drafts.append(m)
    except Exception as e:                      # noqa: BLE001
        vendor_drafts, drafts_measured = [], False
        draft_error = str(e)
    else:
        draft_error = None

    now = datetime.now(timezone.utc)
    out = {
        "account": args.acct,
        "checked_at": now.isoformat(),
        "vendor_mail_ever": len(inbound),
        "verify_notices_ever": len(verify),
        "verify_notices_in_inbox": sum(1 for r in verify if "INBOX" in r["labels"]),
        "verify_notices_unread": sum(1 for r in verify if "UNREAD" in r["labels"]),
        "operator_messages_to_vendor_ever": len(outbox),
        "filters_total": len(filters) if filters_measured else "NOT MEASURED",
        "filters_measured": filters_measured,
        "filters_shadowing_vendor": len(shadow) if filters_measured else "NOT MEASURED",
        "drafts_measured": drafts_measured,
        "vendor_drafts": len(vendor_drafts),
        "inbound_after_operator_last_write": len(vendor_behind),
        "notes": [],
    }

    # The honest bound: in-app activation is NOT observable from a mailbox.
    out["verification_state_measured"] = False
    out["verification_state_reason"] = (
        "activation happens in the ClawStage app (code typed into a Register "
        "button); no mail artifact reflects the account's activated state")

    if verify:
        n = verify[-1]
        out["newest_verify_notice"] = {
            "id": n["id"], "from": n["from"], "subject": n["subject"],
            "date": n["ts"].isoformat(),
            "age_days": round((now - n["ts"]).total_seconds() / 86400.0, 2),
            "labels": n["labels"], "visibility": _visibility(n["labels"]),
            "has_reply_to": bool((n["reply_to"] or "").strip()),
        }
        out["verify_notice_age_days"] = round((now - n["ts"]).total_seconds() / 86400.0, 2)
    if outbox:
        o = outbox[-1]
        out["newest_operator_write"] = {
            "date": o["ts"].isoformat(), "subject": o["subject"], "to": o["to"]}
        out["days_since_operator_write"] = round((now - o["ts"]).total_seconds() / 86400.0, 2)
    if vendor_behind:
        u = vendor_behind[-1]
        out["newest_unanswered_inbound"] = {
            "id": u["id"], "from": u["from"], "subject": u["subject"],
            "date": u["ts"].isoformat()}
        out["days_operator_behind"] = round((now - u["ts"]).total_seconds() / 86400.0, 2)
    if unanswered_by_vendor:
        out["vendor_behind"] = True
        out["days_operator_write_unanswered"] = out.get("days_since_operator_write", 0.0)

    # Calendar residue, paginated by pageToken (all-day events carry "date",
    # not "dateTime" -- never re-derive a cursor from items[-1]["start"]).
    cal_measured = True
    ev, pt = [], None
    try:
        while True:
            r = cal.events().list(calendarId="primary",
                                  timeMin=(now - timedelta(days=args.cal_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                  singleEvents=True, orderBy="startTime",
                                  maxResults=2500, pageToken=pt).execute()
            ev += r.get("items", [])
            pt = r.get("nextPageToken")
            if not pt or len(ev) > 5000:
                break
    except Exception as e:                      # noqa: BLE001
        ev, cal_measured = [], False
        cal_error = str(e)
    else:
        cal_error = None
    out["calendar_measured"] = cal_measured
    out["calendar_events_scanned"] = len(ev) if cal_measured else "NOT MEASURED"
    out["vendor_calendar_events"] = (
        sum(1 for e in ev if ANY_VENDOR.search(
            (e.get("summary") or "") + (e.get("location") or "") + (e.get("description") or "")))
        if cal_measured else "NOT MEASURED")

    if not filters_measured:
        out["notes"].append("Gmail filters NOT MEASURED: %s" % filter_error)
    if not drafts_measured:
        out["notes"].append("drafts NOT MEASURED: %s" % draft_error)
    if not cal_measured:
        out["notes"].append("calendar NOT MEASURED: %s" % cal_error)

    # ---- VERDICT ----
    # An unanswered OPERATOR report outranks the verification notice. The notice
    # is a 15-minute code that cannot still be satisfied, so "verify pending"
    # is not a durable state; a vendor that has gone quiet after a substantive
    # report is a real open thread that does persist.
    if vendor_behind:
        v = ("OPERATOR BEHIND -- %d vendor message(s) arrived after the operator's last "
             "write; newest unanswered %.1fd old" % (
                 len(vendor_behind), out.get("days_operator_behind", 0.0)))
    elif unanswered_by_vendor:
        v = ("VENDOR BEHIND -- the operator's last message (%.1fd old) has had no reply; "
             "verify notice itself is %d and long expired" % (
                 out.get("days_operator_write_unanswered", 0.0),
                 out.get("verify_notices_ever", 0)))
    elif out["verify_notices_in_inbox"]:
        v = "OUTSTANDING -- a verification notice is still in INBOX"
    elif out["verify_notices_unread"]:
        v = "PARTIALLY CLEARED -- %d of %d verify notices left unread-archived" % (
            out["verify_notices_unread"], out["verify_notices_ever"])
    elif not verify:
        v = "NO VERIFICATION NOTICE ON RECORD"
        out["notes"].append("0 verify notices ever; nothing outstanding")
    elif not out["filters_measured"]:
        v = "INCONCLUSIVE -- verify notice dismissed, but filter state NOT MEASURED"
    elif shadow:
        v = "DISMISSED BUT A FILTER SHADOWS THIS SENDER -- filter hid it, not the operator"
    else:
        v = ("ROUTINE -- all %d verify notice(s) dismissed by the operator, 0 filters "
             "shadow the sender; newest %.1fd old and its code long expired" % (
                 out["verify_notices_ever"], out.get("verify_notice_age_days", 0.0)))
    if verify and not out.get("newest_verify_notice", {}).get("has_reply_to", False):
        out["notes"].append(
            "no Reply-To on the sender: verification is app-only, never an email reply")
    out["notes"].append(
        "account activation state is NOT MEASURED by this script -- it lives in the "
        "ClawStage app, and an empty/true result here would be a false negative")
    out["verdict"] = v

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        for k, val in out.items():
            if k == "notes":
                continue
            print("%-36s %s" % (k, json.dumps(val, default=str)))
        for n in out["notes"]:
            print("note: %s" % n)
        print("VERDICT: %s" % v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
