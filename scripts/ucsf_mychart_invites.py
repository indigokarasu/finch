#!/usr/bin/env python3
"""ucsf_mychart_invites.py — MyChart-style scheduling-invite watch (read-only).

WHY THIS EXISTS
  Patient-portal "New Invitation to Schedule an Appointment" notices arrive from
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
    2. Is a filter auto-archiving the portal's mail (i.e. is the miss not the
       operator's)?
    3. Did the invite convert into a booked appointment (Confirmation mail or
       a calendar event)?

  Exit 0 always unless the Gmail/Calendar API is unreachable (exit 1), so it
  is cron-safe.

USAGE
  python3 ucsf_mychart_invites.py [--acct <email>] [--json] [--days 30]

  The account defaults to $OCAS_OPERATOR_EMAIL. Credentials are read from
  ~/.google_workspace_mcp/credentials/<acct>.json and the token self-refreshes.

  GOTCHA (do not use Credentials.from_authorized_user_file here): it raises
  AttributeError: 'float' object has no attribute 'rstrip' on these token
  files because `expiry` is persisted as a float epoch rather than RFC3339.
  Build Credentials from the raw dict, as gws_direct_puller.py::load_creds does.
"""
import argparse
import base64
import html
import json
import os
import re
import sys
from pathlib import Path

# The Google client libs are OPTIONAL at import time so `--help` works in a clean
# CI env with no third-party packages installed (same convention as
# gws_direct_puller.py and verify_sepagree_signature.py). Resolved on first
# real use; missing libs are a hard error only when actually run.
Credentials = None
build = None


def _require_google():
    """Import the Google client libs, or exit 3 with a clear message."""
    global Credentials, build
    if Credentials is not None:
        return
    try:
        from google.oauth2.credentials import Credentials as _Credentials
        from googleapiclient.discovery import build as _build
    except ImportError as e:  # pragma: no cover
        print(f"FATAL: missing google-api-python-client / google-auth: {e}",
              file=sys.stderr)
        sys.exit(3)
    Credentials, build = _Credentials, _build

CRED_DIR = Path(os.path.expanduser(
    os.environ.get("OCAS_GOOGLE_CRED_DIR", "~/.google_workspace_mcp/credentials")))

# The health system's own notification addresses. These are a THIRD PARTY's
# service endpoints, not a person, but they are still account-specific, so they
# come from the environment rather than being committed as literals. Point
# these at your provider's real senders.
NOTIFY = os.environ.get("CARE_NOTIFY_ADDR", "donotreply+mychart@example.com")
BILLING = os.environ.get("CARE_BILLING_ADDR", "donotreply+billing@example.com")
INVITE_SUBJ = "New Invitation to Schedule an Appointment"
SUMMARY_SUBJ = "New After Visit Summary Available"
FOLLOWUP = "Follow-up|follow up|Follow Up"

# The example.com defaults are PLACEHOLDERS. A run that leaves them in place
# queries a domain that cannot exist, matches nothing, and prints a confident
# "Outstanding invites: NONE" with EXIT 0. main() refuses to run in that state.
UNCONFIGURED_MARKER = "example.com"


def _cue_pattern():
    """Join only NON-EMPTY cue sources into one alternation.

    GOTCHA (finch:work #199, 2026-09-26): appending an empty $CARE_CUES_EXTRA
    left a TRAILING `|` in the compiled pattern. A trailing `|` is an EMPTY
    ALTERNATIVE, and an empty alternative matches every string — so
    `booked_care_events` listed EVERY calendar event in the window and reported
    it as booked care, with a plausible-looking count and EXIT 0. Verified live:
    "Tokyo Tea Room, Beach Vacation" and "Patrick Leahy's birthday" both matched
    on the empty branch. Never concatenate a possibly-empty alternation.
    """
    words = ["mychart", "appointment", "clinic", "ankle", "physical ?therapy"]
    # STEMS are cues that legitimately continue ("podiatr" -> podiatry,
    # "ortho" -> orthopedic). Anchor them on the LEFT only: \b alone would
    # refuse "Podiatry" and silently drop real specialty events, and a bare
    # unanchored form would match inside unrelated words ("twofoot").
    stems = ["ortho", "podiatr", "foot"]
    alt = [r"\b%s\b" % w for w in words] + [r"\b%s" % s for s in stems]
    extra = os.environ.get("CARE_CUES_EXTRA", "").strip()
    if extra:
        alt.append(extra)
    return "|".join(alt)


# Cues that identify an outstanding-care thread in a calendar summary.
# Generic specialty/word cues only. Do NOT add a clinician's or patient's
# surname here: a real name in this regex leaks the fact of a specific
# appointment to anyone who reads the repo. Add your own provider's specialty
# words, or extend it with $CARE_CUES_EXTRA at runtime.
CARE_CUES = re.compile(_cue_pattern(), re.I)


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
    """Concatenate the decodable TEXT parts.

    GOTCHA (finch:work #199, 2026-09-26): this harvested only text/plain, so
    the HTML-only notices this watcher exists to read decoded to ''. A caller
    doing a content search then saw "names no clinic" — a vacuous result
    presented as evidence. Handle text/html too (tags stripped, entities
    unescaped) and never return '' without saying which parts were present.
    """
    chunks = []

    def walk(p):
        mt = p.get("mimeType", "")
        data = (p.get("body") or {}).get("data")
        if data:
            try:
                raw = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            except Exception:
                raw = ""
            if mt == "text/plain":
                chunks.append(raw)
            elif mt == "text/html":
                raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
                raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", raw)
                chunks.append(html.unescape(re.sub(r"<[^>]+>", " ", raw)))
        for c in p.get("parts") or []:
            walk(c)

    walk(part)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", re.sub(r"[ \t\xa0]+", " ", "\n".join(chunks))).strip()


def visibility(labels):
    if "INBOX" in labels:
        return "inbox"
    if "UNREAD" in labels:
        return "unread-archived"
    return "archived"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--acct", default=os.environ.get("OCAS_OPERATOR_EMAIL", ""),
                    help="mailbox address whose token file is read (default: "
                         "$OCAS_OPERATOR_EMAIL, e.g. you@example.com)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    if not args.acct:
        print("FATAL: pass --acct <email> or set $OCAS_OPERATOR_EMAIL",
              file=sys.stderr)
        return 2
    # Fail loud on the placeholder defaults. A run that keeps them queries
    # example.com, matches nothing, and reports an empty mailbox with EXIT 0 --
    # indistinguishable from a genuinely clean portal. That is the false-clean
    # failure mode, so it is a non-zero exit, not a footnote.
    # (finch:work #199, 2026-09-26: verified -- the default invocation returned
    # "Outstanding invites: NONE" and 4 bogus care events while 2 real invites
    # were open and 1 real confirmation existed.)
    if UNCONFIGURED_MARKER in NOTIFY.lower():
        print("FATAL: the portal sender is still the example.com placeholder. Set "
              "$CARE_NOTIFY_ADDR (and $CARE_BILLING_ADDR) to the real senders, or "
              "pass the correct addresses, then re-run. Refusing to report a "
              "possibly-empty mailbox.", file=sys.stderr)
        return 4
    _require_google()

    creds = load_creds(args.acct)
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    cal = build("calendar", "v3", credentials=creds, cache_discovery=False)
    out = {"account": args.acct, "invites": [], "summaries": [], "confirmations": [],
           "portal_filter": None, "booked_care_events": [], "notes": []}

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

    # 1b. After-visit summaries. Same portal, different notice class: these
    # announce that a visit summary is READY in MyChart. They are unread for a
    # reason unrelated to scheduling, so they are counted separately -- a
    # "portal is clear" verdict that silently folds them into the invite count
    # understates what Jared has not yet read.
    q = f"from:{NOTIFY} subject:\"{SUMMARY_SUBJ}\" newer_than:{args.days}d"
    for item in gmail.users().messages().list(
            userId="me", q=q, maxResults=25).execute().get("messages", []):
        m = gmail.users().messages().get(userId="me", id=item["id"], format="full").execute()
        out["summaries"].append({
            "id": m["id"], "date": headers(m).get("Date"),
            "labels": m["labelIds"], "visibility": visibility(m["labelIds"]),
            "body_chars": len(body_text(m["payload"])),
        })
    n_unread_sum = sum(1 for s in out["summaries"]
                      if s["visibility"] in ("inbox", "unread-archived"))
    if n_unread_sum:
        out["notes"].append(
            f"{n_unread_sum} After Visit Summary notice(s) not yet cleared by the "
            "operator. The summary CONTENT lives only in MyChart -- the notice body "
            "names no clinic, specialty, or provider.")

    # 2. Did any invite convert into a booked appointment?
    q = f'from:{NOTIFY} subject:"Appointment Confirmation" newer_than:{args.days}d'
    for item in gmail.users().messages().list(
            userId="me", q=q, maxResults=15).execute().get("messages", []):
        m = gmail.users().messages().get(userId="me", id=item["id"], format="full").execute()
        flat = re.sub(r"\s+", " ", body_text(m["payload"]))

        def field(name):
            """Read 'Name: value' from the flattened body.

            The <strong>-anchored pattern this replaces depended on raw HTML
            surviving body_text(); now that tags are stripped it would return
            None on every confirmation while still exiting 0 -- a null field
            read as 'no provider named'. Match the label, then take up to the
            next capitalised label.
            """
            if name == "Location":
                # An address is bounded by its ZIP; the notice continues with
                # cancel/reschedule boilerplate that no label delimits. Without
                # this the field reads "... CA 94158 If you wish to cancel..."
                z = re.search(r"Location:\s*(.+?\b\d{5})(?!\d)", flat)
                if z:
                    return z.group(1).strip()
            m2 = re.search(rf"{name}:\s*(.+?)(?=\s+[A-Z][A-Za-z]+:|\s*$)", flat)
            return m2.group(1).strip() if m2 else None

        out["confirmations"].append({
            "date": headers(m).get("Date"),
            "when": field("Date"),
            "time": field("Time"),
            "provider": field("Provider"),
            "location": field("Location"),
        })
    if out["confirmations"] and not any(c["provider"] for c in out["confirmations"]):
        out["notes"].append(
            "A confirmation was found but no Provider field parsed -- the body "
            "layout changed, so do NOT read the null fields as 'no provider named'.")

    # 3. Is a filter auto-archiving the portal's mail? Distinguishes "the
    #    operator missed it" from "the mailbox hid it" — the two demand
    #    different responses.
    try:
        filters = gmail.users().settings().filters().list(userId="me").execute().get("filter", [])
        for f in filters:
            if NOTIFY.split("@")[-1].lower() in json.dumps(f).lower():
                out["portal_filter"] = f
                break
        if out["portal_filter"] is None:
            out["notes"].append(
                "No Gmail filter references the portal sender — archived invites were "
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

    print(f"Patient-portal invite watch — {args.acct} (last {args.days}d)\n")
    if not out["invites"]:
        print("  Outstanding invites: NONE")
    for i in out["invites"]:
        print(f"  INVITE  {i['date'][:31]:31s} [{i['visibility']:16s}] {i['id']}")
    n_arch = sum(1 for i in out["invites"] if i["visibility"] != "inbox")
    if n_arch and len(out["invites"]) == n_arch:
        print("  -> ALL outstanding invites are no longer in the inbox.")
    for s in out["summaries"]:
        print(f"  SUMMARY {s['date'][:31]:31s} [{s['visibility']:16s}] {s['id']}")
    if out["summaries"]:
        n_unread = sum(1 for s in out["summaries"]
                       if s["visibility"] in ("inbox", "unread-archived"))
        print(f"  -> {n_unread} of {len(out['summaries'])} after-visit summaries "
              "not yet cleared.")
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
