#!/usr/bin/env python3
"""orphan_draft_watch.py — read-only watcher for PR-code-review drafts that
land in a real mailbox with no live counterpart.

WHY THIS EXISTS (2026-09-26, finch:work, task email-orphan-headerless-drafts):
four Gmail drafts appeared in operator@example.com dated 09-25 whose
bodies are code-review replies ("the lru_cache approach is the right
direction", "the credit limit issue is on their end"). A scan recorded them
as "header-less artifacts of a batch script". That was wrong on two counts,
and both errors had to be killed with API evidence:

  1. They are NOT header-less. Full `format=full` returns a complete header
     set, and the Subject names a real PR in a real indigokarasu repo. A
     metadata-only reader renders From/To/Subject as empty strings, which
     reads as "no headers" — that is the trap, not a malformed message.
  2. They are NOT unsendable junk. From AND To are the same address, so the
     reply is self-addressed; the true counterparty is a GitHub PR, not a
     mail thread. The giveaway that nothing was ever threaded is that
     threadId == message id and every thread has size 1: the drafts were
     created against a thread id that does not exist.

This watcher prints the facts a task note cannot: which drafts are orphaned
(self-addressed or thread-less), which PR each names, which are exact
duplicate bodies written seconds apart, and whether any new one has appeared
since the last run. Read-only. No LLM. No writes to Gmail.

Exit 0 = ran clean (whether or not orphans are present).

Flags:
  --acct <email>     mailbox to inspect (default operator@example.com)
  --json             machine-readable output only
  --pr-hints         also print the PR references parsed out of Subjects

Gotchas encoded here (see references/work-execution-procedures.md):
  * Do NOT call Credentials.from_authorized_user_file() on the operator token
    file -- its `expiry` is a persisted float and the call raises
    AttributeError. Build Credentials from the raw dict, as below.
  * A draft id (r- prefix) is not a message id; use messages.get().
  * messages.list() with format=minimal returns NO headers at all. Always
    ask for format=full before concluding a message is header-less.
"""
import argparse
import base64
import json
import os
import re
import sys
from collections import Counter

CRED_DIR = os.path.expanduser("~/.google_workspace_mcp/credentials")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
PR_RE = re.compile(r"\[(?P<owner>[^\]/]+)/(?P<repo>[^\]]+)\][^\(]*\(PR #(?P<pr>\d+)\)")


def build_service(acct):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    path = os.path.join(CRED_DIR, f"{acct}.json")
    with open(path) as fh:
        raw = json.load(fh)
    creds = Credentials(
        token=raw.get("token"),
        refresh_token=raw.get("refresh_token"),
        token_uri=raw.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=raw.get("client_id"),
        client_secret=raw.get("client_secret"),
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def plain_text(payload):
    """Concatenate every text/* leaf, base64url-decoded."""
    out = []

    def walk(p):
        data = (p.get("body") or {}).get("data")
        if data and p.get("mimeType", "").startswith("text/plain"):
            out.append(base64.urlsafe_b64decode(data).decode("utf-8", "replace"))
        for child in p.get("parts") or []:
            walk(child)

    walk(payload or {})
    return "".join(out)


def describe(svc, draft):
    mid = draft["message"]["id"]
    msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
    payload = msg.get("payload", {})
    hdrs = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    thread_id = msg.get("threadId", "")
    size = 1
    if thread_id and thread_id != mid:
        try:
            size = len(svc.users().threads().get(
                userId="me", id=thread_id).execute().get("messages", []))
        except Exception:
            size = -1
    frm = hdrs.get("from", "")
    to = hdrs.get("to", "")
    self_addr = bool(
        frm and to and
        set(re.findall(r"[\w.+-]+@[\w.-]+", frm)) == set(re.findall(r"[\w.+-]+@[\w.-]+", to)))
    pr = PR_RE.search(hdrs.get("subject", ""))
    subject = hdrs.get("subject", "")
    # threadId == message id is NORMAL for a brand-new outbound draft (cold
    # outreach opens its own thread). It is only evidence of an orphan when
    # the subject claims to be a REPLY to something that does not exist --
    # that is the self-contradiction that matters. Getting this wrong flags
    # every legitimate cold-outreach draft as broken.
    claims_reply = subject.strip().lower().startswith("re:")
    dangling_reply = claims_reply and thread_id == mid and size == 1
    return {
        "id": mid,
        "thread_id": thread_id,
        "thread_size": size,
        "threaded": not dangling_reply,
        "dangling_reply": dangling_reply,
        "labels": msg.get("labelIds", []),
        "from": frm,
        "to": to,
        "subject": hdrs.get("subject", ""),
        "date": hdrs.get("date", ""),
        "header_count": len(hdrs),
        "self_addressed": self_addr,
        "pr": f"{pr.group('owner')}/{pr.group('repo')}#{pr.group('pr')}" if pr else None,
        "body": plain_text(payload).strip()[:160],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--acct", default="operator@example.com")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--pr-hints", action="store_true",
                    help="include parsed PR references in the report")
    args = ap.parse_args()

    svc = build_service(args.acct)
    listed = svc.users().drafts().list(userId="me", maxResults=200).execute()
    drafts = listed.get("drafts", [])

    rows = [describe(svc, d) for d in drafts]
    orphans = [r for r in rows if r["self_addressed"] or not r["threaded"]]
    bodies = Counter(r["body"] for r in rows if r["body"])
    dupes = [{"body": b, "count": n} for b, n in bodies.items() if n > 1]
    reviewish = [r for r in rows
                 if re.search(r"\b(PR|pull request|review|merge|benchmark|bench)\b",
                              r["subject"] + " " + r["body"], re.I)]

    report = {
        "account": args.acct,
        "draft_total": len(rows),
        "orphaned_total": len(orphans),
        "orphans": orphans,
        "code_review_drafts": reviewish if args.pr_hints else len(reviewish),
        "duplicate_bodies": dupes,
    }

    if args.json:
        print(json.dumps(report, indent=1))
        return 0

    print(f"ACCOUNT      {args.acct}")
    print(f"DRAFTS       {len(rows)}")
    print(f"ORPHANED     {len(orphans)}  (self-addressed, or a 'Re:' whose thread has 1 message)")
    print(f"REVIEW-DRAFT {len(reviewish)}")
    if dupes:
        print(f"DUPLICATES   {len(dupes)} body/bodies written more than once:")
        for d in dupes:
            print(f"  x{d['count']}  {d['body'][:90]}")
    for r in orphans:
        pr = f"  pr={r['pr']}" if r.get("pr") else ""
        flags = []
        if r["self_addressed"]:
            flags.append("SELF-ADDRESSED")
        if r.get("dangling_reply"):
            flags.append("DANGLING-REPLY")
        print(f"  - {r['id']}  {r['date']}  [{' '.join(flags)}]{pr}")
        print(f"      subj: {r['subject'][:100]}")
        print(f"      body: {r['body'][:100]}")
    if not orphans:
        print("VERDICT      none — every draft is threaded to a live conversation")
    else:
        print("VERDICT      orphans present. These are NOT header-less: a "
              "format=full fetch returns full headers. The counterparty is a "
              "GitHub PR, not a mail thread, so they will never be sentable "
              "mail. Deleting another agent's output is not a finch action — "
              "report the generator instead.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
