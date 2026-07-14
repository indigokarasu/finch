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
