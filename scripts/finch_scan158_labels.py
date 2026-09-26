#!/usr/bin/env python3
"""finch scan #158 — live label verification for specific message ids.

GENERICISED (public repo): the original scan hardwired real Gmail message and
thread ids from a live mailbox. Those are per-account identifiers — meaningless
on another machine and identifying here — so they are now supplied by the
caller. Supply comma-separated ids, or a name=value list, via the environment.

    export OCAS_OPERATOR_EMAIL=you@example.com
    export SCAN158_IDS=msg-1,msg-2,...
    export SCAN158_THREADS=thread-1,thread-2,...
    python3 finch_scan158_labels.py

With nothing set the script explains what it needs and exits 0 — it must never
need credentials just to answer --help.

For each id: the labels, From, Subject and Date. Labels are load-bearing:
SENT vs DRAFT is the whole point of this scan.
"""
import argparse
import json
import os
import sys

ACCT = os.environ.get("OCAS_OPERATOR_EMAIL", "")
CRED_DIR = os.path.expanduser(
    os.environ.get("OCAS_GOOGLE_CRED_DIR", "~/.google_workspace_mcp/credentials"))
# The Google client libs are optional at import time so --help works without
# them (same convention as gws_direct_puller.py). Resolved on first real use.
Credentials = None
Request = None
build = None


def _require_google():
    """Import the Google client libs, or exit 3 with a clear message."""
    global Credentials, Request, build
    if Credentials is not None:
        return
    try:
        from google.oauth2.credentials import Credentials as _Credentials
        from google.auth.transport.requests import Request as _Request
        from googleapiclient.discovery import build as _build
    except ImportError as e:  # pragma: no cover
        print(f"FATAL: missing google-api-python-client + google-auth: {e}",
              file=sys.stderr)
        sys.exit(3)
    Credentials, Request, build = _Credentials, _Request, _build


def service():
    """Build a read-only Gmail client for $OCAS_OPERATOR_EMAIL."""
    _require_google()
    with open(os.path.join(CRED_DIR, f"{ACCT}.json")) as fh:
        raw = json.load(fh)
    creds = Credentials(token=raw["token"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _ids(var):
    return [x.strip() for x in os.environ.get(var, "").split(",") if x.strip()]


def _headers(m, wanted=("From", "To", "Subject", "Date")):
    return {x["name"]: x["value"] for x in m["payload"]["headers"]
            if x["name"] in wanted}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--messages", default="", help="comma-separated message ids "
                    "(default: $SCAN158_IDS)")
    ap.add_argument("--threads", default="", help="comma-separated thread ids "
                    "(default: $SCAN158_THREADS)")
    args = ap.parse_args()

    messages = _ids("SCAN158_IDS") or [x for x in args.messages.split(",") if x]
    threads = _ids("SCAN158_THREADS") or [x for x in args.threads.split(",") if x]
    if not messages and not threads:
        print("Nothing to do: set $SCAN158_IDS / $SCAN158_THREADS (or pass "
              "--messages / --threads) with the ids from your own mailbox.")
        return 0
    if not ACCT:
        print("FATAL: set $OCAS_OPERATOR_EMAIL to the mailbox to query.",
              file=sys.stderr)
        return 2

    svc = service()

    for mid in messages:
        m = svc.users().messages().get(userId="me", id=mid,
                                       format="metadata").execute()
        h = _headers(m)
        print("%s\n  labels=%s" % (mid, m.get("labelIds")))
        print("  from=%s" % h.get("From"))
        print("  subj=%s" % h.get("Subject"))
        print("  date=%s" % h.get("Date"))

    for tid in threads:
        print("\n--- THREAD %s ---" % tid)
        try:
            th = svc.users().threads().get(userId="me", id=tid).execute()
        except Exception as e:  # a stale id must not abort the whole sweep
            print("  ERR %s" % e)
            continue
        for m in th["messages"]:
            hh = _headers(m, ("From", "Subject", "Date"))
            print("  %s %s | %s | %s" % (m["id"], hh.get("date"), hh.get("from"),
                                         m.get("labelIds")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
