# finch:scan — Gmail batch parsing (CORRECTED recipe)

The SKILL.md scanning-gotcha "Large MCP batch responses persist to disk" gives a parsing
recipe that **FAILS** on the real `get_gmail_messages_content_batch` output. This file holds
the working version, distilled from a 2026-07-20 finch:scan run that burned ~8 tool calls
re-discovering it. Read this BEFORE writing any email-batch parser in a scan.

## Why the documented recipe breaks

`tool_call(mcp__google_workspace__get_gmail_messages_content_batch)` returns a JSON blob
persisted to `/tmp/hermes-results/chatcmpl-tool-*.txt`:

    {"result": "Retrieved 25 messages:\n\nMessage ID: 19f....\nSubject: ..."}

The `result` string is JSON-escaped: the separators inside it are LITERAL `\n` (backslash + `n`,
two characters), NOT real newlines. So `json.loads(raw)['result']` yields a string whose message
boundaries are `\n` (two chars). The documented `re.split(r'\n\n---\n\n', res)` (real newlines)
matches NOTHING, and every `Subject`/`From`/`Date` regex written against real `\n` also fails.
Result: **0 parsed messages and a false "no actionable email" conclusion** — a silent miss that
drops real tasks (in the 2026-07-20 run this skipped GLG consult #3 + 4 job-application receipts
until a second pass found them).

## Robust recipe (terminal python3 — execute_code is BLOCKED in indigo cron)

```python
import re
files = ["chatcmpl-tool-XXXX.txt", "chatcmpl-tool-YYYY.txt"]  # the 2 batch files
rows = []
for p in files:
    data = open(p, encoding="utf-8", errors="replace").read()
    for c in data.split('Message ID: ')[1:]:
        mid = re.match(r'([0-9a-f]{14,16})', c)   # 16-char hex id (tolerant of leading '19')
        if not mid:
            continue
        mid = mid.group(1)
        subj = re.search(r'Subject: (.*?)(?:\n|\\n)', c)
        frm  = re.search(r'From: (.*?)(?:\n|\\n)', c)
        date = re.search(r'Date: (.*?)(?:\n|\\n)', c)
        rows.append((mid,
                     subj.group(1).strip() if subj else "?",
                     frm.group(1).strip()  if frm  else "?",
                     date.group(1).strip()[:25] if date else "?"))
```

Key points:
- Split on the literal marker `Message ID: ` — NOT the JSON key. The id is 14–16 hex chars; match
  with a tolerant `re.match` so the `19` prefix is captured.
- Field regex `(.*?)(?:\n|\\n)` tolerates BOTH real newlines AND the literal `\n` the file actually
  contains. **This tolerance is the fix.**
- Do NOT `json.loads` the file first — treat it as raw text. `read_file` truncates; use `terminal`
  python3 (execute_code is blocked in cron).
- The two 25-message batch files BOTH contain the full 50-message set (overlap) — dedupe by `mid`.
- Pagination: `search_gmail_messages` returns a `page_token`; loop it to completion. Page-1-only
  misses high-value items.

## Email triage — do NOT blanket-filter consult / recruiting / HR senders as noise

A naive sender-domain "skip list" (<employer>.com, *@myworkday.com, ashbyhq.com, <employer>.com,
collective2.com, labaton.com, checkr.com, …) will SILENTLY DROP the most actionable items in a
finch:scan. Those exact domains are the source of standing tasks (glg-*, <employer>-*, abbott-*,
collective2-*, powerschool-classaction, …). A 2026-07-20 run's first pass did this and missed
GLG #3 + 4 job-application receipts; only a second keyword-targeted pass caught them.

Correct filtering:
- **GENUINE noise** = automated notifications only: `info@`/`noreply@`/`no-reply@`, market-updates
  (Zillow), promo (lululemon/Schoolhouse/Compass), product-update blasts (Anarlog), self-sent the agent
  dream/BOOK emails, bulk job-board blasts (hackajob/Mercor) with no specific role, statement/payment
  confirmations (Citi/Hilton stay) UNLESS they carry an explicit action.
- **ACTIONABLE even from "corporate" domains:** GLG/<employer> expert-network invites; job-application
  RECEIPTS (MasterCard/Tempus/Odyssey/Superhuman "thank you for applying" = confirm COMPLETE
  submission — contrast Abbott "Complete Your Application" = still PARTIAL); proxy-vote / class-action
  / background-check notices; secure-message alerts.
- **When unsure, run a SECOND targeted pass** over the non-noise set on keywords:
  `glg, <employer>, consult, opportunit, screen, profound, paid, invite, interview, application,
  interaction, mastercard, tempus, abbott, recruiter`. This reliably surfaces items the domain filter
  hid.

## Gmail batch 429 partial-failure mode (added 2026-07-22)

`get_gmail_messages_content_batch` with a 25-id list does NOT fail the whole call when some IDs
rate-limit. Instead it returns HTTP 200 with a `result` string where SOME message blocks are replaced
by inline warning blocks:

    ⚠️ Message <thread-id>: <HttpError 429 when requesting https://gmail.googleapis.com/gmail/v1/users/me/messages/<thread-id>?format=full&alt=json returned "Too many concurrent requests for user." ...>

The successful messages are STILL present; only the 429'd IDs are absent. If you stop at the batch
output you silently lose those messages — and the missed set can contain the one needle (a security
alert or time-sensitive notice).

Recovery (cheap, reliable):
- After each batch, scan the `result` text for `⚠️ Message` lines. Extract the id via `⚠️ Message (\S+):`.
  Collect them.
- Refetch the missed IDs individually (or in a small batch) via a SECOND `get_gmail_messages_content_batch`
  call. A single-id call rarely 429s. In the 2026-07-22 run, 2 of 25 missed on the first batch and both
  succeeded on individual refetch.
- Do this per batch BEFORE concluding "no actionable email."
- This is INDEPENDENT of the pagination rule: paginate `search_gmail_messages` to completion AND refetch
  any 429'd IDs within each content batch. Together they guarantee full coverage.
