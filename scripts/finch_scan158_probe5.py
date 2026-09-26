#!/usr/bin/env python3
"""finch scan #158 — vendor-thread context probe over caller-supplied queries.

GENERICISED (public repo): the original probe hardwired real Gmail queries from
a live mailbox (a vendor domain and a ticket number). The queries are now the
caller's to supply:

    export OCAS_OPERATOR_EMAIL=you@example.com
    export SCAN158_QUERIES='"ticket #1234"',from:example.com
    python3 finch_scan158_probe5.py

Unlike the other probes this one prints the internalDate timestamp, which is the
reliable date on these messages when headers are unreliable.

With nothing set it explains what it needs and exits 0. It must never need
credentials or the network just to answer --help.
"""
import argparse
import datetime
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--search", default="", help="comma-separated Gmail queries "
                    "(default: $SCAN158_QUERIES)")
    ap.add_argument("--max", type=int, default=6)
    args = ap.parse_args()

    queries = [x.strip() for x in os.environ.get("SCAN158_QUERIES", "").split(",")
               if x.strip()]
    if not queries:
        queries = [x.strip() for x in args.search.split(",") if x.strip()]
    if not queries:
        print("Nothing to do: set $SCAN158_QUERIES (or pass --search) with the "
              "Gmail queries from your own mailbox.")
        return 0
    if not ACCT:
        print("FATAL: set $OCAS_OPERATOR_EMAIL to the mailbox to query.",
              file=sys.stderr)
        return 2

    svc = service()
    for q in queries:
        r = svc.users().messages().list(userId="me", q=q,
                                        maxResults=args.max).execute()
        ids = r.get("messages", [])
        print("q=%s -> %d" % (q, len(ids)))
        for item in ids:
            g = svc.users().messages().get(userId="me", id=item["id"],
                                           format="full").execute()
            hh = {x["name"].lower(): x["value"]
                  for x in g["payload"].get("headers", [])}
            dt = datetime.datetime.fromtimestamp(
                int(g["internalDate"]) / 1000, datetime.UTC).strftime("%m-%d %H:%MZ")
            print("   %s | %s | %s | %s | %s" % (
                g["id"], dt, hh.get("from", "")[:40], hh.get("subject", "")[:50],
                g.get("labelIds")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
