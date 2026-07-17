#!/usr/bin/env python3
"""verify_sepagree_signature.py — Reusable EMAIL-SEPAGREE (Innovaccer Separation
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

USAGE:
  python3 verify_sepagree_signature.py
  python3 verify_sepagree_signature.py --email jared.zimmerman@gmail.com \
      --thread 19f62275fed9da72 --days 4

OUTPUT: prints the three probes + a one-line VERDICT, and exits 0 (still unsigned /
monitoring) or 0 with signed=True note. Never sends mail. Read-only.

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

DEFAULT_CRED_DIR = "/root/.google_workspace_mcp/credentials"
DEFAULT_EMAIL = "jared.zimmerman@gmail.com"
DEFAULT_THREAD = "19f62275fed9da72"   # Jared/Kim Saied separation thread
SEP_QUERY = "Innovaccer separation"    # cross-check negotiation thread


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
            out.append({"id": m["id"], "subject": hdrs.get("Subject", ""),
                        "from": hdrs.get("From", ""), "date": hdrs.get("Date", "")})
        req = svc.users().messages().list_next(req, r) if r.get("nextPageToken") else None
    return out


def main():
    ap = argparse.ArgumentParser(description="Verify Innovaccer Separation Agreement signature status.")
    ap.add_argument("--email", default=DEFAULT_EMAIL)
    ap.add_argument("--thread", default=DEFAULT_THREAD)
    ap.add_argument("--days", type=int, default=4, help="Docusign/signed search window")
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
    awaiting_them = "jared" not in last_from.lower() if last_from else False

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
    print("ACTION: do NOT auto-sign; surface to Jared. Resolve task only if signed_closed=True.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
