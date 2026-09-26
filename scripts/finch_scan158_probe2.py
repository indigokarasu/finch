#!/usr/bin/env python3
"""finch scan #158 — body/thread probe over caller-supplied ids.

GENERICISED (public repo): the original probe hardwired real Gmail thread and
message ids from a live mailbox. Those are per-account identifiers, so the
caller now supplies them:

    export OCAS_OPERATOR_EMAIL=you@example.com
    export SCAN158_THREADS=thread-1,thread-2
    export SCAN158_MESSAGES=msg-1,msg-2
    export SCAN158_QUERIES=hoobs,from:example.com
    python3 finch_scan158_probe2.py

With nothing set it explains what it needs and exits 0. It must never need
credentials or the network just to answer --help.
"""
import argparse
import base64
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


def _headers(m, wanted=("From", "To", "Subject", "Date")):
    return {x["name"]: x["value"] for x in m["payload"]["headers"]
            if x["name"] in wanted}


def _body(svc, mid, maxlen=1200):
    """Return (message, decoded body text truncated to maxlen)."""
    m = svc.users().messages().get(userId="me", id=mid, format="full").execute()
    chunks = []

    def walk(p):
        if p.get("body", {}).get("data"):
            chunks.append(p["body"]["data"])
        for c in p.get("parts", []) or []:
            walk(c)

    walk(m["payload"])
    txt = ""
    for d in chunks:
        try:
            txt += base64.urlsafe_b64decode(d + "==").decode("utf-8", "ignore")
        except Exception:
            pass
    return m, " ".join(txt.split())[:maxlen]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--threads", default="", help="comma-separated thread ids "
                    "(default: $SCAN158_THREADS)")
    ap.add_argument("--messages", default="", help="comma-separated message ids "
                    "(default: $SCAN158_MESSAGES)")
    ap.add_argument("--search", default="", help="comma-separated Gmail queries "
                    "to sweep (default: $SCAN158_QUERIES)")
    ap.add_argument("--maxlen", type=int, default=900)
    args = ap.parse_args()

    def _split(var, arg):
        vals = [x.strip() for x in os.environ.get(var, "").split(",") if x.strip()]
        return vals or [x.strip() for x in arg.split(",") if x.strip()]

    threads = _split("SCAN158_THREADS", args.threads)
    messages = _split("SCAN158_MESSAGES", args.messages)
    queries = _split("SCAN158_QUERIES", args.search)
    if not (threads or messages or queries):
        print("Nothing to do: set $SCAN158_THREADS / $SCAN158_MESSAGES / "
              "$SCAN158_QUERIES (or pass the matching flags) with ids from "
              "your own mailbox.")
        return 0
    if not ACCT:
        print("FATAL: set $OCAS_OPERATOR_EMAIL to the mailbox to query.",
              file=sys.stderr)
        return 2

    svc = service()

    for tid in threads:
        print("=== THREAD %s ===" % tid)
        try:
            th = svc.users().threads().get(userId="me", id=tid).execute()
        except Exception as e:  # one stale id must not abort the sweep
            print("  ERR %s" % e)
            continue
        for m in th["messages"]:
            h = _headers(m)
            print("  %s %s | from=%s | subj=%s | labels=%s" % (
                m["id"], h.get("date"), h.get("from"), h.get("subject"),
                m.get("labelIds")))

    for mid in messages:
        print("\n=== MESSAGE %s ===" % mid)
        try:
            m, txt = _body(svc, mid, args.maxlen)
        except Exception as e:
            print("  ERR %s" % e)
            continue
        h = _headers(m)
        print("  to=%s date=%s" % (h.get("To"), h.get("Date")))
        print("  BODY: %s" % txt)

    for q in queries:
        r = svc.users().messages().list(userId="me", q=q, maxResults=5).execute()
        print("\n  q=%s -> %d" % (q, len(r.get("messages", []))))
        for item in r.get("messages", []):
            g = svc.users().messages().get(userId="me", id=item["id"],
                                           format="metadata").execute()
            hh = _headers(g, ("From", "Subject", "Date"))
            print("     %s %s | %s | %s" % (item["id"], hh.get("date"),
                                            hh.get("from"), hh.get("subject")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
