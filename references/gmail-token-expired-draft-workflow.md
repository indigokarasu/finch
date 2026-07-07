# Gmail Token Expired: Local Draft Workflow for finch:work

## When to Use

When finch:work picks a task with `source: "email"` and Gmail API is unavailable (token expired, client credentials missing from environment, `google_auth.py` refresh fails).

This complements the dispatch skill's `draft_fallback_pattern.md` (which assumes `inbox_classified.json` and `last_triage.json` exist). This workflow works with whatever cached dispatch data IS available.

## Diagnostic Sequence

1. **Try `get_gmail_thread_content`** or `google_auth.py` — most reliable if token works
2. **If refresh fails with "Could not determine client ID"** — token is expired AND client credentials not in env. This is a hard block for Gmail API access.
3. **Check token expiry**: `google_oauth.json` has `expires` field (epoch ms). If `expires/1000 < time.time()`, token is stale.
4. **Do NOT retry** the failed call. Move to cached-data fallback immediately.

## Cached Data Sources (in priority order)

| Source | What it contains | How to search |
|--------|-----------------|---------------|
| `all_facts.jsonl` | Contact emails, thread subjects, snippets, dates | `search_files(pattern=<thread_id>, path=commons/data/ocas-dispatch/all_facts.jsonl)` |
| `messages.jsonl` | Full cached message metadata (from, to, subject, date, snippet) | `search_files(pattern=<keyword>)` |
| `triage_results.jsonl` | Intent classification, priority, action classification | `search_files(pattern=<keyword>)` |
| `threads.jsonl` | Thread state, participants, notes | `search_files(pattern=<thread_id>)` |
| `decisions.jsonl` | Previous dispatch decisions about this thread | `search_files(pattern=<thread_id>)` |
| `drafts.jsonl` | Existing drafts (check for duplicates before creating new) | `search_files(pattern=<thread_id>)` |

**Note:** Some files may be empty or not contain the target thread. Try `all_facts.jsonl` first — it's the most consistently populated.

## Drafting from Cached Data

When you have enough context (at minimum: recipient, subject, and the action needed from the task description), draft directly to `drafts.jsonl`:

```python
import json
from datetime import datetime, timezone

draft = {
    "id": f"draft_finch_work_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{slug}",
    "thread_id": "<thread_id>",
    "message_id": "<message_id>",  # may be same as thread_id for single-message threads
    "account": "jared",
    "recipient": "<from all_facts or messages>",
    "recipient_name": "<sender name>",
    "subject": "Re: <subject from cached data>",
    "content": "<drafted response based on task description and cached context>",
    "status": "pending_approval",
    "intent": "<rsvp|follow_up|decline|etc>",
    "priority": <from task>,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "run_id": "finch_work_<timestamp>",
    "identity": "jared_zimmerman",
    "source_task": "<task_id>",
    "notes": "Gmail API token expired; draft stored locally for next interactive session when token can be refreshed."
}

path = "/root/.hermes/profiles/indigo/commons/data/ocas-dispatch/drafts.jsonl"
with open(path, "a") as f:
    f.write(json.dumps(draft) + "\n")
```

**CRITICAL:** Use Python `open(path, "a")` to append to JSONL. NEVER use `write_file` on a JSONL file — it truncates the entire file.

## When Cached Data is Insufficient

If `all_facts.jsonl` and `messages.jsonl` have NO entry for the thread, and the Gmail API is blocked, the task cannot be completed autonomously. Actions:

1. **Update the task** with `status: "pending"` and add a note: "Gmail API token expired; no cached data for thread. Requires interactive session with valid auth."
2. **Do NOT mark done** — the task genuinely needs Gmail access
3. **Do NOT fabricate** recipient info, subject lines, or draft content from the task description alone — the task description is a summary, not the original email content

## Task List Update Pattern

When draft IS created locally:
```json
{
    "status": "done",
    "resolved": "Drafted response locally (draft_finch_work_...). Gmail API token expired — draft will be pushed to Gmail during next interactive dispatch session.",
    "note": "Draft awaiting Gmail token refresh. Jared still needs to: approve draft, [specific next step]."
}
```

When draft CANNOT be created (no cached data):
```json
{
    "status": "pending",
    "note": "Gmail API token expired; no cached data for thread. Blocked until next interactive session with valid auth."
}
```

## Cross-reference

- Dispatch skill: `references/draft_fallback_pattern.md` — full fallback cascade when `inbox_classified.json` exists
- Dispatch skill: `references/token-failure-patterns.md` — token recovery procedures  
- Email task draft workflow: `references/email-task-draft-workflow.md` — normal (non-degraded) email draft workflow

## Recipient Verification Pitfall

When drafting from cached data, **always verify the recipient email against the actual thread data** (`threads.jsonl`, `chronicle_queue.jsonl`, or `messages.jsonl`). Do NOT rely on task descriptions or prior drafts for recipient info — they may be wrong.

**Confirmed 2026-06-28 task_004**: A prior draft (Jun 24) for the COC proof thread was addressed to `rayvon@ucsf.edu` — but the actual recipient was Ravon Logan at `rlogan@choosebywater.com`. The task description did not contain the recipient email. Only by searching `chronicle_queue.jsonl` for the thread ID was the correct recipient identified. Sending to the wrong address would have delayed a time-sensitive medical document (CoC proof due Jul 1).

**Rule:** Before creating any draft, search cached data for the thread ID and extract the actual `from` / `to` addresses from the thread's messages. If the recipient in your draft doesn't match any cached message's sender, stop and investigate.

## Confirmed Cases

- **2026-06-28 task_001**: RISD vineyard RSVP. Gmail token expired May 2. `all_facts.jsonl` contained thread ID `19eae32b72b571cc`, sender `risd-club-of-silicon-valley@connect.risd.edu`, subject. Successfully drafted RSVP locally and appended to `drafts.jsonl`.
- **2026-06-28 task_004**: COC proof follow-up for Shannon Badiee. Gmail OAuth revoked (invalid_grant). Thread `19ef6f2457ace9c0` with Ravon Logan (rlogan@choosebywater.com). Ravon confirmed Jun 25 they did NOT receive Shannon's signed doc. CoC effective date Jul 1 (next day). Drafted urgent follow-up to correct recipient (prior Jun 24 draft was wrongly addressed to rayvon@ucsf.edu). Draft stored as `draft-2026-06-28-coc-shannon-resend` in drafts.jsonl.
