#!/usr/bin/env python3
import os
OPERATOR_EMAIL = os.environ.get("OCAS_OPERATOR_EMAIL", "operator@example.com")
"""verify_sepagree_signature.py — Reusable EMAIL-SEPAGREE (<employer> Separation
Agreement) signature-status verifier for finch:work cron passes.

WHY THIS EXISTS:
  finch:work re-verifies the Docusign "unsigned" state on every pass that touches
  the P1 EMAIL-SEPAGREE task. Before this script existed, the Gmail API probe was
  hand-built inline each run (rebuilt 2x in a single 2026-07-16 scan cycle). This
  persisted asset removes that per-run derivation.

WHAT IT PROVES (without opening the envelope link):
  0 "Completed"/signed Docusign notices in the window  +  active negotiation thread
  (last message FROM the other party, awaiting their reply)  =  UNSIGNED, ball in
  their court. If a "Completed" notice appears, the envelope closed -> resolve task.

BLOCK-CLEARANCE PROBE (added 2026-07-23):
  When the operator asked for a CORRECTED envelope (e.g. Section 3/15 fixes) and the task's
  last_finch_review already confirmed the block, pass --since <RFC3339>. The script
  enumerates ALL Docusign/Kim envelopes in the window and reports any with
  internalDate AFTER that ts = a potential new corrected version. If NONE, the
  blocker is unchanged. This is the date-gated re-verify finch:work needs; do NOT
  re-derive it inline (that violates the "don't re-derive the verifier" rule).

USAGE:
  python3 verify_sepagree_signature.py
  python3 verify_sepagree_signature.py --email OPERATOR_EMAIL \
      --thread <thread-id> --days 4
  # block-clearance probe: did a NEW (corrected) envelope arrive since last review?
  python3 verify_sepagree_signature.py --since 2026-07-23T05:03:00Z

OUTPUT: prints the three probes + a one-line VERDICT, and exits 0 (still unsigned /
monitoring) or 0 with signed=True note. With --since, also prints the
block-clearance probe: count of Docusign/Kim envelopes AFTER the given RFC3339 ts.
Never sends mail. Read-only.

NOTE: run via `terminal` python3, NOT execute_code (blocked in indigo cron profile).
      Requires google.oauth2 + googleapiclient importable in the interpreter. If the
      default python3 lacks them, probe with `python3 -c "import google.oauth2"` and
      pick an interpreter that has them. (Interpreter path is environment-specific —
      treat as a probe, not a hardcoded rule.)
"""
import argparse
import json
import sys
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

DEFAULT_CRED_DIR = os.path.expanduser("~/.google_workspace_mcp/credentials")
DEFAULT_EMAIL = "OPERATOR_EMAIL"
DEFAULT_THREAD = "<thread-id>"   # the operator/Kim <counterparty> separation thread
SEP_QUERY = "<employer> separation"    # cross-check negotiation thread

# Envelopes to enumerate for the corrected-version probe
ENVELOPE_QUERIES = [
    "from:docusign.net",
    "from:counterparty@example.com",
    "subject:(Complete with Docusign)",
    "subject:(Please DocuSign)",
]


def build_service(email: str):
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


def block_clearance_probe(svc, since_iso: str):
    """Report Docusign/Kim envelopes newer than the given last_finch_review ts."""
    since = _iso_to_dt(since_iso)
    print(f"\n=== BLOCK-CLEARANCE PROBE (since {since_iso}) ===")
    seen = {}
    for q in ENVELOPE_QUERIES:
        # only look back far enough to include the since-ts comfortably
        for m in list_msgs(svc, f"{q} newer_than:5d"):
            seen.setdefault(m["id"], m)
    if not seen:
        print("  No Docusign/Kim separation envelopes found in last 5d.")
        return
    newest = None
    new_since = []
    for m in seen.values():
        if newest is None or m["internalDate"] > newest["internalDate"]:
            newest = m
        if m["internalDate"] > since:
            new_since.append(m)
    print(f"  Envelopes in window: {len(seen)}; newest = {newest['internalDate'].isoformat()} | {newest['from'][:40]}")
    if new_since:
        print(f"  *** {len(new_since)} NEW envelope(s) AFTER {since_iso}: ***")
        for m in sorted(new_since, key=lambda x: x["internalDate"]):
            print(f"    {m['internalDate'].isoformat()} | {m['from'][:40]} | {m['subject'][:50]}")
        print("  => BLOCKER MAY HAVE CLEARED: a corrected envelope arrived. the operator should")
        print("     open the NEW signing URL (a fresh envelope = new url; old url is for")
        print("     the uncorrected version) and sign alongside any requested docs.")
    else:
        print(f"  *** NO envelope newer than {since_iso}. Blocker UNCHANGED — still")
        print(f"      WAITING ON THE COUNTERPARTY. Re-ping signing URL; do not auto-sign. ***")


def main():
    ap = argparse.ArgumentParser(description="Verify <employer> Separation Agreement signature status.")
    ap.add_argument("--email", default=DEFAULT_EMAIL)
    ap.add_argument("--thread", default=DEFAULT_THREAD)
    ap.add_argument("--days", type=int, default=4, help="Docusign/signed search window")
    ap.add_argument("--since", default=None, help="RFC3339 ts; run block-clearance probe (corrected envelope since?)")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    svc = build_service(args.email)
    print(f"=== EMAIL-SEPAGREE live re-verify ({now}) ===\n")

    # (a) Separation thread: message count + last sender
    thr = svc.users().threads().get(userId="me", id=args.thread).execute()
    thr_msgs = thr.get("messages", [])
    last = thr_msgs[-1] if thr_msgs else None
    last_from = ""
    if last:
        meta = svc.users().messages().get(
            userId="me", id=last["id"], format="metadata",
            metadataHeaders=["From", "Date"],
        ).execute()
        last_from = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}.get("From", "")
    print(f"(a) SEPARATION THREAD {args.thread}: {len(thr_msgs)} message(s); last sender = {last_from[:50]}")
    awaiting_them = "<owner>" not in last_from.lower() if last_from else False

    # (b) Docusign signed/completed in window
    docusign = list_msgs(svc, f"from:docusign.net newer_than:{args.days}d")
    signed = [m for m in docusign if any(
        k in m["subject"].lower() for k in ("completed", "signed", "envelope"))]
    print(f"(b) DOCUSIGN from:docusign.net newer_than:{args.days}d: {len(docusign)} total; "
          f"signed/completed-type = {len(signed)}")

    # (c) Negotiation cross-check
    sep = list_msgs(svc, f'"{SEP_QUERY}" newer_than:{args.days}d')
    print(f'(c) "{SEP_QUERY}" newer_than:{args.days}d: {len(sep)} message(s)')

    signed_closed = len(signed) > 0
    verdict = "SIGNED (envelope closed)" if signed_closed else "UNSIGNED (ball in their court)"
    print(f"\nVERDICT: {verdict} | awaiting_their_reply = {awaiting_them}")
    print("ACTION: do NOT auto-sign; surface to the operator. Resolve task only if signed_closed=True.")

    if args.since:
        block_clearance_probe(svc, args.since)
    return 0


if __name__ == "__main__":
    sys.exit(main())
