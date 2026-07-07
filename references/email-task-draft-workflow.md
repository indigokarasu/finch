# Email Task Draft Workflow (finch:work)

## When to Use

When finch:work picks a task with `source: "email"` and the action requires contacting a third party who is NOT already in the thread (e.g., "have X re-sign and send to Y", "ask Z to provide documents").

## Workflow

### 1. Fetch Source Thread
```
get_gmail_thread_content(thread_id=<source_thread>, user_google_email="jared.zimmerman@gmail.com", body_format="text")
```
Read the full thread to understand: who needs to do what, what document is involved, what's the deadline, what's the consequence of inaction.

### 2. Find Recipient Contact Info
```
search_contacts(query="<name>", user_google_email="jared.zimmerman@gmail.com")
```
Extract email addresses. Prefer the "Home" type email. If multiple emails exist, use the home address as primary.

### 3. Draft the Email
```
draft_gmail_message(
  to="<recipient_email>",
  subject="Re: <context-appropriate subject>",
  body="<clear, concise explanation of what's needed and why>",
  user_google_email="jared.zimmerman@gmail.com"
)
```

Draft body should include:
- Context: what document/situation this relates to
- Specific action needed: what the recipient must do
- Deadline/urgency: why it matters (e.g., "UCSF threatening to cancel procedures")
- Where to send: if they need to send something to a third party, include that email address

### 4. Update Task List
Mark the task `completed` with:
- `outcome`: "Drafted email to <recipient> (<email>) requesting <action>. Draft ID: <id>. Jared needs to review and send."
- `draft_id`: the draft ID from step 3

### 5. Journal
Write a journal entry to `commons/journals/ocas-finch/` documenting:
- What was drafted
- Who it was addressed to
- The draft ID
- That Jared must review and send

## Degraded Mode: Gmail Token Expired / Unavailable

When `get_gmail_thread_content` or `google_auth.py` fails with a refresh error (expired token, missing client credentials), the full draft workflow is blocked. Fall back to this degraded-mode sequence:

### 1. Check Cached Data
Search dispatch data stores for the thread ID before giving up:
- `search_files(pattern=<thread_id>, path=commons/data/ocas-dispatch/all_facts.jsonl)` — may contain subject, sender, snippet
- `search_files(pattern=<thread_id>, path=commons/data/ocas-dispatch/messages.jsonl)` — may contain cached message bodies
- `search_files(pattern=<keyword>, path=commons/data/ocas-dispatch/triage_results.jsonl)` — may have triage metadata with intent/classification

### 2. Draft Locally
If enough context exists from cached data to draft a meaningful response, write the draft directly to `drafts.jsonl`:
```python
draft = {
    "id": "draft_finch_work_<timestamp>_<slug>",
    "thread_id": "<thread_id>",
    "message_id": "<message_id>",
    "account": "jared",
    "recipient": "<from cached data>",
    "subject": "Re: <from cached data>",
    "content": "<drafted response>",
    "status": "pending_approval",
    "notes": "Gmail API token expired; draft stored locally for next interactive session."
}
# Append safely via Python open(path, "a") — NEVER write_file on JSONL
```

### 3. Update Task List
Mark the task as `done` with:
- `resolved`: "Drafted response locally (draft_finch_work_...). Gmail API token expired — draft will be pushed to Gmail during next interactive dispatch session."
- `note`: "Draft awaiting Gmail token refresh. Jared still needs to: approve draft, [complete registration/payment if applicable]."

### 4. Do NOT Block on OAuth
Do NOT:
- Attempt to generate OAuth URLs or ask Jared to re-auth (no user present in cron)
- Retry the same failed API call multiple times
- Declare the task impossible and skip it — the local draft is a valid completion

The draft will be picked up by the next interactive `dispatch.draft` session that has valid Gmail auth.

**Confirmed:** 2026-06-28 — task_001 RISD vineyard RSVP. Gmail token expired (May 2), `google_auth.py` refresh failed with "Could not determine client ID". Cached `all_facts.jsonl` contained thread ID, subject, sender. Drafted RSVP locally and saved to `drafts.jsonl`.

## What NOT to Do

- **Never send directly from cron** — always save as draft for Jared's review
- **Never CC Jared's own email** — the draft is FROM Jared, no need to CC him
- **Never load ocas-dispatch** for this pattern — `draft_gmail_message` is sufficient and dispatch adds unnecessary context overhead
- **Never assume the task description is accurate** — always read the actual thread content
- **Never retry a failed Gmail API call more than once** — if token refresh fails, fall back to cached data and local drafts immediately

## Variant: Stalled Thread Follow-Up (Existing Participant)

When the task is to follow up with someone **already in the thread** (not a new third party), the workflow differs:

### 1. Fetch Source Thread
Same as above — read the full thread.

### 2. Detect the Stall
Check if the last message is from Jared and is purely explanatory (no question, no proposed next step). If >24h with no response and a deadline is approaching, the thread is stalled.

### 3. Draft Within the Thread
```python
draft_gmail_message(
  to="<existing_participant_email>",
  subject="Re: <existing_subject>",
  body="<follow-up that asks a binary question or offers options>",
  thread_id="<existing_thread_id>",
  in_reply_to="<last_message_id>",
  user_google_email="jared.zimmerman@gmail.com"
)
```

**Key difference from main workflow:** Use `thread_id` and `in_reply_to` to keep the conversation in the same thread. Do NOT create a new email.

### 4. Draft Body Pattern for Stalled Threads
- "Following up on [topic]"
- One-sentence situation summary
- Binary question: "Is [current state] acceptable, or would you prefer [alternative]?"
- Deadline/urgency note
- Concrete offer: "I'm happy to [action] if needed"

### 5. Update Task List
Same as above — mark completed with draft_id and outcome.

## Confirmed Example (2026-06-26)

**Task:** COC proof for Shannon Badiee (task_004, high priority)
- Source thread: Ravon Logan said he didn't receive Shannon's signed COC
- Jared's last msg (Jun 25): "it was signed, but she signed it bigger, over the old signature."
- Stall: No response from Ravon since Jun 25. Last msg was explanatory, not interrogative.
- Effective date: 7/1/2026 (5 days away)
- Action: Drafted follow-up WITHIN the existing thread asking if the overlapping-signature version is acceptable or if Shannon should re-sign cleanly
- Draft ID: r-462268327478437913
- Outcome: Task marked completed, Jared must review and send

## Confirmed Example (2026-06-25)

**Task:** Bywater COC for Shannon Badiee (task_005, high priority)
- Source thread: Ravon Logan (Bywater compliance) said Shannon's signed COC wasn't received
- Problem: Shannon signed over old signature (illegible)
- Action: Drafted email to Shannon (thetopaz@gmail.com) asking her to re-sign cleanly and send to Ravon (rlogan@choosebywater.com)
- Draft ID: r1562145309459001139
- Outcome: Task marked completed, Jared must review and send
