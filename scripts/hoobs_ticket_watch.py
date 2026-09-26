#!/usr/bin/env python3
"""Read-only watcher for HOOBS support ticket #6361 (Jared Zimmerman).

Answers four questions a task-list note cannot, without an LLM:
  1. How long has the refund been outstanding, and how long since the vendor moved?
  2. Is the vendor in a template loop (identical bodies) or genuinely escalating?
  3. Did Jared's latest message actually SEND, or is it sitting in Drafts?
  4. Has any terminal signal arrived (refund confirmation, tracking, cancellation)?

Exit 0 always (read-only, unattended). Prints a VERDICT line.
Re-run to diff. Never sends, never writes to Gmail.
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CRED = '/root/.google_workspace_mcp/credentials/jared.zimmerman@gmail.com.json'
THREAD = '1a00b9ddab5be0cd'          # ticket 6361 main thread
ORIGIN_ASK = '2024-11-10T15:05:00Z'  # Jared's first refund ask, per vendor quote

# Terminal signals: any of these means the dispute is actually closed.
TERMINAL = re.compile(
    r'refund (?:has been |was )?(?:processed|issued|completed)|'
    r'transaction (?:id|number)|receipt for your refund|'
    r'tracking (?:number|#)|your order has shipped|'
    r'we have (?:issued|processed) a (?:refund|credit)|'
    r'chargeback (?:has been )?(?:opened|filed|submitted)',
    re.I)

# Templated non-answers. Same body = automation, not a human answering.
TEMPLATE = re.compile(
    r'in queue for our office to handle|'
    r'forwarded your request to our back office|'
    r'escalated for further review|'
    r'experiencing more than normal request',
    re.I)


def load():
    d = json.load(open(CRED))
    creds = Credentials(token=d.get('token'), refresh_token=d.get('refresh_token'),
                         token_uri=d.get('token_uri'), client_id=d.get('client_id'),
                         client_secret=d.get('client_secret'), scopes=d.get('scopes'))
    return build('gmail', 'v1', credentials=creds, cache_discovery=False)


def parse_date(h):
    from email.utils import parsedate_to_datetime
    return parsedate_to_datetime(h)


def body_text(payload):
    out = []
    if 'body' in payload and payload['body'].get('data'):
        import base64
        out.append(base64.urlsafe_b64decode(payload['body']['data']).decode('utf8', 'replace'))
    for p in payload.get('parts', []) or []:
        if p.get('mimeType') in ('text/plain', 'text/html'):
            if p.get('body', {}).get('data'):
                import base64
                out.append(base64.urlsafe_b64decode(p['body']['data']).decode('utf8', 'replace'))
    return '\n'.join(out)


def main():
    svc = load()
    msgs = svc.users().threads().get(userId='me', id=THREAD, format='full').execute()['messages']
    recs = []
    for m in msgs:
        h = {x['name']: x['value'] for x in m['payload']['headers']}
        dt = parse_date(h['Date'])
        body = body_text(m['payload'])
        recs.append({
            'id': m['id'], 'ts': dt.astimezone(timezone.utc),
            'from': h.get('From', ''), 'labels': set(m.get('labelIds', [])),
            'body': body,
            'is_jared': 'jared.zimmerman@gmail.com' in h.get('From', '').lower(),
        })
    recs.sort(key=lambda r: r['ts'])
    now = datetime.now(timezone.utc)

    vendor = [r for r in recs if not r['is_jared']]
    jared = [r for r in recs if r['is_jared']]

    # --- 1. duration ------------------------------------------------------------
    origin = datetime.fromisoformat(ORIGIN_ASK.replace('Z', '+00:00'))
    days_total = (now - origin).days
    last_vendor = vendor[-1]['ts'] if vendor else None
    days_silent = (now - last_vendor).days if last_vendor else -1

    # --- 2. template loop -------------------------------------------------------
    norm = lambda b: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', b))[:220]
    vendor_bodies = Counter(norm(r['body']) for r in vendor)
    top_body, top_n = vendor_bodies.most_common(1)[0]
    templated = sum(n for b, n in vendor_bodies.items() if TEMPLATE.search(b))
    escalating = any('escalated for further review' in b.lower() for b in vendor_bodies)

    # --- 3. send-state ----------------------------------------------------------
    jared_sent = [r for r in jared if 'SENT' in r['labels']]
    jared_draft = [r for r in jared if 'DRAFT' in r['labels']]
    latest_sent = jared_sent[-1] if jared_sent else None
    latest_draft = jared_draft[-1] if jared_draft else None
    unanswered = bool(latest_sent and last_vendor and latest_sent['ts'] > last_vendor)

    # --- 4. terminal signal -----------------------------------------------------
    terminal = [r for r in vendor if TERMINAL.search(r['body'])]

    print('=' * 72)
    print('HOOBS ticket #6361 — refund dispute watcher')
    print('=' * 72)
    print(f'run_at_utc            {now.isoformat(timespec="seconds")}')
    print(f'thread_messages       {len(recs)}  (vendor {len(vendor)} / jared {len(jared)})')
    print(f'first_refund_ask      {origin.date()}  ->  {days_total} days outstanding')
    print(f'last_vendor_motion    {last_vendor.isoformat(timespec="seconds") if last_vendor else "none"}'
          f'  ->  {days_silent} days silent')
    print()
    print('--- vendor behaviour ---')
    print(f'distinct_bodies      {len(vendor_bodies)}  (templated non-answers: {templated}/{len(vendor)})')
    print(f'most_repeated_body    x{top_n} :: {top_body[:110]}')
    print(f'escalation_language   {"YES (09-23 vendor reply)" if escalating else "no"}')
    print()
    print('--- jared send-state ---')
    print(f'last_SENT             {latest_sent["ts"].isoformat(timespec="seconds") if latest_sent else "none"}')
    print(f'last_SENT_preview     {(latest_sent["body"][:90] if latest_sent else "-")}')
    print(f'UNSENT_DRAFT          {latest_draft["ts"].isoformat(timespec="seconds") if latest_draft else "none"}')
    print(f'unsent_draft_preview  {(latest_draft["body"][:90] if latest_draft else "-")}')
    print(f'vendor_owes_reply     {"YES" if unanswered else "no"}')
    print()
    print('--- terminal signals ---')
    if terminal:
        for r in terminal:
            print(f'  CLOSED? {r["ts"].date()} :: {r["body"][:100]}')
    else:
        print('  none — no refund confirmation, no tracking number, no chargeback notice')

    if terminal:
        verdict = 'VERDICT: CLOSED_SIGNAL_PRESENT — verify then close the task'
    elif unanswered:
        verdict = 'VERDICT: OPEN_VENDOR_BALL — finch-executable action: none (draft a reply if it helps)'
    else:
        verdict = 'VERDICT: OPEN_BALL_WITH_JARED — action is sending the staged draft'
    print()
    print(verdict)
    return 0


if __name__ == '__main__':
    sys.exit(main())
