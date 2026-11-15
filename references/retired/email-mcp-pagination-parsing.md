# Email MCP batch-response parsing (confirmed working recipe)

When `get_gmail_messages_content_batch` returns more than the inline limit, Hermes
persists the result to `/tmp/hermes-results/chatcmpl-tool-*.txt`. The file is a
JSON object whose `"result"` field is a big STRING — its newlines are stored as
LITERAL `\n` (two characters: backslash + n), not real newlines.

## Confirmed-working parse (2026-07-26 finch:scan)

```python
import json, re
path = "/tmp/hermes-results/chatcmpl-tool-XXXX.txt"
with open(path) as f:
    raw = f.read()
data = json.loads(raw)          # decodes \n -> real newlines
text = data["result"]
blocks = re.split(r"\nMessage ID:\s*", text)   # split on the per-message separator
for b in blocks[1:]:
    mid  = b.split("\n", 1)[0].strip()
    subj = re.search(r"\nSubject:\s*(.+)", b)
    frm  = re.search(r"\nFrom:\s*(.+)", b)
    s  = subj.group(1).strip() if subj else "?"
    fr = frm.group(1).strip()  if frm  else "?"
    print(f"{mid} | {fr} | {s}")
```

This recovered all 20 messages with correct Subject/From.

## CORRECTIONS to the earlier scanning-gotcha

The `scanning-gotchas.md` "Large MCP batch responses" entry marks
`json.loads(raw)['result']` as part of the **WRONG** form. That framing is
misleading. **`json.loads(raw)['result']` is the correct first step** — it turns
the literal `\n` sequences into real newlines. The actual bug in the documented
"WRONG" form was the SPLIT DELIMITER (`\n\n---\n\n`), not the `json.loads`.
Splitting on `\nMessage ID:` (the real inter-message boundary) works every time.

Two equivalent correct forms:
1. `json.loads` first, then `re.split(r"\nMessage ID:\s*", decoded_text)` — PREFERRED, robust.
2. Raw-text form: skip `json.loads`, `re.split(r"\\nMessage ID:\s*", raw)` on the
   file bytes (the `\n` are literal, so match them literally). Also works.

## Why the naive split fails

Until `json.loads` decodes it, the `result` string carries LITERAL `\n`. A regex
that expects a real `\n\n---\n\n` on the RAW text matches nothing → 0 messages
parsed → silent false-negative ("no actionable email"). Always split on a
delimiter that actually exists in the (decoded) string: the per-message
`Message ID:` boundary is the reliable anchor.

## Pair with pagination

This parses ONE batch file. The full scan must first loop `page_token` to fetch
ALL pages (see the EMAIL UNDER-PAGINATION rule in `scanning-gotchas.md`), collect
every message ID, batch-fetch content, THEN parse. Do not assert "0 actionable"
until every page is fetched and parsed.
