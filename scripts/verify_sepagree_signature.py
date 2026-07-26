#!/usr/bin/env python3
"""verify_sepagree_signature.py — reusable e-signature (Docusign) status verifier.

Proves whether a pending signature envelope is still UNSIGNED, without opening
the envelope link, so a cron pass can re-verify a blocked "awaiting signature"
task instead of re-deriving the Gmail probe inline every run.

WHAT IT PROVES:
  0 "Completed"/signed envelope notices in the window  +  an active negotiation
  thread whose last message is FROM the counterparty  =  UNSIGNED, ball in their
  court. If a "Completed" notice appears, the envelope closed -> resolve task.

BLOCK-CLEARANCE PROBE:
  When a CORRECTED envelope has been requested and a previous review already
  confirmed the block, pass --since <RFC3339>. The script enumerates every
  matching envelope in the window and reports any newer than that timestamp —
  i.e. a potential corrected version. If none, the blocker is unchanged.

CONFIGURATION — nothing identifying is hardcoded. Supply your own values:
  OCAS_OPERATOR_EMAIL   mailbox to query           (or --email)
  OCAS_SIG_THREAD_ID    negotiation thread id      (or --thread)
  OCAS_SIG_QUERY        cross-check search phrase  (or --query)
  OCAS_SIG_SENDERS      comma-separated Gmail queries identifying the envelope
                        sender(s)                  (or --sender, repeatable)

USAGE:
  export OCAS_OPERATOR_EMAIL=you@example.com
  python3 verify_sepagree_signature.py --thread <thread-id> --days 4
  python3 verify_sepagree_signature.py --since 2026-01-01T00:00:00Z

OUTPUT: three probes plus a one-line VERDICT. Read-only; never sends mail.

NOTE: requires google.oauth2 + googleapiclient importable. Imported lazily so
      --help works without the optional Google dependencies installed.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

DEFAULT_CRED_DIR = os.path.expanduser(
    os.environ.get("OCAS_GOOGLE_CRED_DIR", "~/.google_workspace_mcp/credentials"))

# Generic fallbacks. Real values come from env or CLI flags — never committed.
DEFAULT_EMAIL = os.environ.get("OCAS_OPERATOR_EMAIL", "")
DEFAULT_THREAD = os.environ.get("OCAS_SIG_THREAD_ID", "")
DEFAULT_QUERY = os.environ.get("OCAS_SIG_QUERY", "separation agreement")

# Gmail queries that identify the e-signature envelope. Override with
# OCAS_SIG_SENDERS / --sender to match your counterparty's sending address.
DEFAULT_SENDER_QUERIES = [
    q.strip() for q in os.environ.get(
        "OCAS_SIG_SENDERS",
        "from:docusign.net,subject:(Complete with Docusign),subject:(Please DocuSign)"
    ).split(",") if q.strip()
]


def build_service(email: str):
    """Build a read-only Gmail client. Imports Google libs lazily."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    cred_path = f"{DEFAULT_CRED_DIR}/{email}.json"
    with open(cred_path) as f:
        d = json.load(f)
    creds = Credentials(
        token=d.get("token") or d.get("access_token"),
        refresh_token=d.get("refresh_token"),
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d.get("client_id"),
        client_secret=d.get("client_secret"),
        scopes=d.get("scopes") or ["https://www.googleapis.com/auth/gmail.readonly"],
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _iso_to_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def list_msgs(svc, query: str, max_res: int = 20):
    out = []
    req = svc.users().messages().list(userId="me", q=query, maxResults=max_res)
    while req is not None:
        r = req.execute()
        for m in r.get("messages", []):
            msg = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            hdrs = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            dt = datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=timezone.utc)
            out.append({"id": m["id"], "subject": hdrs.get("Subject", ""),
                        "from": hdrs.get("From", ""), "date": hdrs.get("Date", ""),
                        "internalDate": dt})
        req = svc.users().messages().list_next(req, r) if r.get("nextPageToken") else None
    return out


def block_clearance_probe(svc, since_iso: str, sender_queries):
    """Report envelopes newer than the given last-review timestamp."""
    since = _iso_to_dt(since_iso)
    print(f"\n=== BLOCK-CLEARANCE PROBE (since {since_iso}) ===")
    seen = {}
    for q in sender_queries:
        for m in list_msgs(svc, f"{q} newer_than:5d"):
            seen.setdefault(m["id"], m)
    if not seen:
        print("  No signature envelopes found in last 5d.")
        return
    newest = None
    new_since = []
    for m in seen.values():
        if newest is None or m["internalDate"] > newest["internalDate"]:
            newest = m
        if m["internalDate"] > since:
            new_since.append(m)
    print(f"  Envelopes in window: {len(seen)}; newest = "
          f"{newest['internalDate'].isoformat()} | {newest['from'][:40]}")
    if new_since:
        print(f"  *** {len(new_since)} NEW envelope(s) AFTER {since_iso}: ***")
        for m in sorted(new_since, key=lambda x: x["internalDate"]):
            print(f"    {m['internalDate'].isoformat()} | {m['from'][:40]} | {m['subject'][:50]}")
        print("  => BLOCKER MAY HAVE CLEARED: a corrected envelope arrived. Open the")
        print("     NEW signing URL (a fresh envelope has a new url; the old url points")
        print("     at the uncorrected version).")
    else:
        print(f"  *** NO envelope newer than {since_iso}. Blocker UNCHANGED —")
        print("      still awaiting the counterparty. Re-ping; do not auto-sign. ***")


def main():
    ap = argparse.ArgumentParser(
        description="Verify e-signature envelope status (read-only Gmail probe).")
    ap.add_argument("--email", default=DEFAULT_EMAIL,
                    help="mailbox to query (env OCAS_OPERATOR_EMAIL)")
    ap.add_argument("--thread", default=DEFAULT_THREAD,
                    help="negotiation thread id (env OCAS_SIG_THREAD_ID)")
    ap.add_argument("--query", default=DEFAULT_QUERY,
                    help="cross-check search phrase (env OCAS_SIG_QUERY)")
    ap.add_argument("--sender", action="append", default=None,
                    help="Gmail query identifying the envelope sender; repeatable "
                         "(env OCAS_SIG_SENDERS, comma-separated)")
    ap.add_argument("--days", type=int, default=4, help="search window in days")
    ap.add_argument("--since", default=None,
                    help="RFC3339 ts; run the block-clearance probe")
    args = ap.parse_args()

    if not args.email:
        print("No mailbox configured. Set OCAS_OPERATOR_EMAIL or pass --email.",
              file=sys.stderr)
        return 2
    if not args.thread:
        print("No thread configured. Set OCAS_SIG_THREAD_ID or pass --thread.",
              file=sys.stderr)
        return 2

    sender_queries = args.sender or DEFAULT_SENDER_QUERIES
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    svc = build_service(args.email)
    print(f"=== signature re-verify ({now}) ===\n")

    # (a) Negotiation thread: message count + last sender
    thr = svc.users().threads().get(userId="me", id=args.thread).execute()
    thr_msgs = thr.get("messages", [])
    last = thr_msgs[-1] if thr_msgs else None
    last_from = ""
    if last:
        meta = svc.users().messages().get(
            userId="me", id=last["id"], format="metadata",
            metadataHeaders=["From", "Date"],
        ).execute()
        last_from = {h["name"]: h["value"]
                     for h in meta.get("payload", {}).get("headers", [])}.get("From", "")
    print(f"(a) THREAD {args.thread}: {len(thr_msgs)} message(s); "
          f"last sender = {last_from[:50]}")
    # "awaiting them" = the last message did not come from our own mailbox
    own = (args.email or "").split("@")[0].lower()
    awaiting_them = bool(last_from) and own not in last_from.lower()

    # (b) Signed/completed envelopes in window
    envelopes = []
    for q in sender_queries:
        envelopes.extend(list_msgs(svc, f"{q} newer_than:{args.days}d"))
    uniq = {m["id"]: m for m in envelopes}
    signed = [m for m in uniq.values()
              if any(k in m["subject"].lower() for k in ("completed", "signed", "envelope"))]
    print(f"(b) ENVELOPES newer_than:{args.days}d: {len(uniq)} total; "
          f"signed/completed-type = {len(signed)}")

    # (c) Cross-check on the negotiation phrase
    sep = list_msgs(svc, f'"{args.query}" newer_than:{args.days}d')
    print(f'(c) "{args.query}" newer_than:{args.days}d: {len(sep)} message(s)')

    signed_closed = len(signed) > 0
    verdict = "SIGNED (envelope closed)" if signed_closed else "UNSIGNED (ball in their court)"
    print(f"\nVERDICT: {verdict} | awaiting_their_reply = {awaiting_them}")
    print("ACTION: do NOT auto-sign; surface to the operator. "
          "Resolve the task only if signed_closed=True.")

    if args.since:
        block_clearance_probe(svc, args.since, sender_queries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
