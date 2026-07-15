# Email MCP Pagination + Parsing Recipe (finch:scan)

Confirmed working pattern from finch:scan run 2026-07-13T22:09 PDT (indigo cron profile).

## Step 1 — Fetch all pages

`search_gmail_messages` caps at `page_size` (default 10; use 25). The result contains a
`page_token` when more pages exist. Loop until no `page_token`.

```
page1 = tool_call(mcp__google_workspace__search_gmail_messages,
                  {query:"newer_than:2d", user_google_email:"jared.zimmerman@gmail.com", page_size:25})
collect ids from page1["result"]  # 25 Message IDs
if page1 has page_token:
    page2 = tool_call(..., {page_token: page1["page_token"], page_size:25})
    collect ids from page2
    # repeat while page_token present
```

**Why this matters:** `newer_than:2d` returned 50 messages across 2 pages. The P1
D.E.Shaw consulting reply (TASK-020) was on **page 2**. A page-1-only fetch would have
missed it and reported stale "UNVERIFIED" carried tasks as still-unverified.

## Step 2 — Batch-fetch content for ALL collected IDs

```
tool_call(mcp__google_workspace__get_gmail_messages_content_batch,
          {message_ids: ALL_IDS_ACROSS_PAGES, user_google_email:"jared.zimmerman@gmail.com"})
```

This returns a large body. The runtime may save it to a temp `.txt` file and return a
preview. Read that file (not the preview) for full content.

## Step 3 — Parse the saved batch-result file

The saved file is a **JSON object** `{"result": "...escaped..."}`, and the result string
is JSON-escaped (literal `\\n`, not newlines). Raw regex on the file fails. Decode in
two steps:

```python
import json, re
raw = open("/tmp/hermes-results/chatcmpl-tool-XXXX.txt", encoding="utf-8", errors="replace").read()
obj = json.loads(raw)          # {"result": "..."}
txt = obj["result"].encode().decode("unicode_escape")   # un-escape \n etc.
blocks = re.split(r"Message ID:\s*", txt)[1:]
for b in blocks:
    subj = re.search(r"Subject:\s*(.+?)\n", b)
    frm  = re.search(r"From:\s*(.+?)\n", b)
    # ...
```

## Step 4 — Classify actionable vs automated

Filter `frm` against an auto-pattern list (noreply@, no-reply@, info@, -donotreply,
robinhood.com, google.com, calendar@, github.com, noreply@<domain>, etc.).
Non-matching senders are human/actionable candidates. Always inspect bodies for the
carried-task keywords (deshaw, glg, mealtrain, etc.) to confirm VERIFIED status.

## Gotcha — wrong param name looks like "tool not loaded"

Passing `max_results`/`limit` to `search_gmail_messages` raises pydantic
`unexpected_keyword_argument`. That means the tool IS reachable — only the param name is
wrong. Use `page_size`. Do NOT conclude the MCP server is unavailable from a pydantic
validation error; that is the wrong failure mode (see SKILL.md "REALITY CHECK" correction).

## Step 1b — Collapse automated noise BEFORE fetching content (saves a giant batch call)

The `newer_than:2d` result is dominated by automated/promotional mail (Alpaca, Philo,
Strike, Schoolhouse, Substack, real-estate, my own cron monitors). Fetching full content
for all of them wastes a 24-message batch call and floods the saved result file. Pre-filter
with Gmail's `-from:` exclusion operators so the residual set is mostly human senders:

    search_gmail_messages({
      query: "newer_than:2d -from:(noreply OR no-reply OR info@ OR notifications@ OR do-not-reply@ OR mailer-daemon)",
      page_size: 25, user_google_email: "jared.zimmerman@gmail.com"})

This collapses the 50-75 message set to the handful of human/unknown-sender threads.
STILL loop the `page_token` to completion (noise excluded, but real human mail on later
pages is possible). Then batch-fetch content ONLY for the residual IDs.

**Caveat:** `-from:` exclusion is a heuristic, not a guarantee — a human sender on a
matching domain (rare) or a delegated sender (e.g. `docusign.net` for a human signer)
can be mis-excluded. Always eyeball the residual From/Subject list; do not treat exclusion
as proof of "no human mail."

## Step 1c — Strip residual batch to From/Subject/Date via terminal (avoid context flood)

The content-batch result file can be 140KB+. Do NOT read it into context. Parse it in
`terminal` and print only `ID | FROM | SUBJECT | DATE`:

    import re, json
    raw = open("/tmp/hermes-results/<saved>.txt", encoding="utf-8", errors="replace").read()
    obj = json.loads(raw)                 # {"result": "..."}
    txt = obj["result"]                    # already a normal multi-line string; do NOT double-decode
    for b in re.split(r"Message ID:\s*", txt)[1:]:
        mid = b.split("\n",1)[0].strip()
        frm = re.search(r"From:\s*(.+)", b)
        sub = re.search(r"Subject:\s*(.+)", b)
        dt  = re.search(r"Date:\s*(.+)", b)
        print(mid, "|", (frm.group(1) if frm else "?")[:55], "|",
              (sub.group(1) if sub else "?")[:50], "|", (dt.group(1) if dt else "?")[:30])

**PITFALL — do NOT apply `.encode().decode("unicode_escape")` to `obj["result"]` when it is
already a plain multi-line string.** Step 3 above used that decode for an escaped case, but
on 2026-07-14 the saved file was already a normal multi-line string, and re-escaping
corrupted embedded unicode — From/Subject lines rendered as one concatenated blob because
`\\n` inside the string was re-escaped. If `json.loads(raw)["result"]` is already a normal
string, use it directly. Only un-escape if the raw file shows literal `\\n` sequences
(the Step 3 escaped case).

## Monitoring proof — `from:<addr> newer_than:Nd` = 0 means "no reply yet"

For monitor-only tasks awaiting a specific sender's reply, prove the negative cheaply
without fetching threads:

    search_gmail_messages({query:"from:Kimberly.saied@innovaccer.com newer_than:1d", page_size:10, ...})
    # -> "No messages found"  => sender has NOT replied in the window

This returned 0 for the SepAgreement thread even though a Docusign envelope from the same
person had been sent — because Docusign is the reply channel, not a personal email. Combine
the negative-search proof with a direct thread/Docusign check before declaring "still
awaiting reply." The negative search alone is NOT sufficient when the sender may use a
delegated/third-party sending domain (docusign.net, sendgrid, etc.).
