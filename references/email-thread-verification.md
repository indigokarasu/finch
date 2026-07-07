# Email Thread Verification Pattern (finch:work)

When a pending task involves an email exchange and the action is "track response" or "verify reply received," use this pattern to check thread state.

## Pattern

1. **Search for the thread** by sender or subject:
   ```
   search_gmail_messages(query="from:ever.solano@arbolus.com", user_google_email="jared.zimmerman@gmail.com")
   ```

2. **Fetch the full thread** to see the most recent message:
   ```
   get_gmail_thread_content(thread_id=<id>, body_format="text", user_google_email="jared.zimmerman@gmail.com")
   ```

3. **Check the last message's `From:` field**:
   - If the last message is FROM the external party → they responded. Check if their response addresses the action items.
   - If the last message is FROM Jared → he sent his part and is still waiting. Task remains pending.
   - If the thread has only 1 message → no response at all.

4. **Update the task** with findings in the `note` field, including:
   - Date of last check
   - Whether a response was received
   - Whether the response was substantive or generic
   - What's still needed

## Common patterns

- **Generic "apply via button" reply** → Does not count as a substantive response to specific questions (rate, scope, time). Task remains pending.
- **No reply within 48h** → Note in task. May need escalation or different contact method.
- **Reply addresses some questions but not all** → Note which gaps remain. Task remains pending.

## Fallback: google_auth.py when MCP Gmail tools are unavailable

The `mcp_google_workspace_*` tools are NOT registered in `config.yaml` (confirmed 2026-06-28). When running in cron context where these tools are unavailable, fall back to the `google_auth.py` script for direct Gmail API access.

### Pattern

```bash
cd /root/.hermes/scripts && python3 -c "
import sys
sys.path.insert(0, '/root/.hermes/scripts')
from google_auth import get_gmail_service

service = get_gmail_service('jared.zimmerman@gmail.com')
if service:
    # Search by sender
    results = service.users().messages().list(userId='me', q='from:sender@domain.com newer_than:7d', maxResults=5).execute()
    msgs = results.get('messages', [])
    print(f'Total messages: {len(msgs)}')
    for m in msgs:
        msg = service.users().messages().get(userId='me', id=m['id'], format='metadata', metadataHeaders=['Subject','From','Date']).execute()
        headers = {h['name']: h['value'] for h in msg['payload']['headers']}
        print(f'  From: {headers.get(\"From\",\"?\")}')
        print(f'  Date: {headers.get(\"Date\",\"?\")}')
        print(f'  Snippet: {msg.get(\"snippet\",\"\")[:150]}')

    # Fetch full thread
    thread = service.users().threads().get(userId='me', id=thread_id, format='metadata', metadataHeaders=['Subject','From','Date']).execute()
    print(f'Thread messages: {len(thread[\"messages\"])}')

    # Read a specific message's full text
    msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    import base64
    def get_text(payload):
        if payload.get('mimeType') == 'text/plain' and payload.get('body', {}).get('data'):
            return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='replace')
        for part in payload.get('parts', []):
            text = get_text(part)
            if text: return text
        return None
"
```

### Key points

- **Import path**: Must `sys.path.insert(0, '/root/.hermes/scripts')` before importing `google_auth`. The module is NOT on the default Python path.
- **Read-only operations only**: `messages().list()`, `messages().get()`, `threads().get()` are safe. NEVER send email from cron (hard rule from ocas-dispatch).
- **Quick status check**: Use `messages().list(q='from:X newer_than:7d')` to count messages, then fetch full thread only for threads that need investigation. This is faster than fetching all thread content.
- **Thread message count as diagnostic**: A thread with N messages shows N total messages in the conversation. If you know Jared replied once and the thread has exactly 2 messages, the external party has NOT replied. This avoids fetching full content for simple status checks.
- **Search for Jared's sent replies**: Use `q='to:domain.com'` to find messages Jared sent TO a specific domain, confirming whether he responded.

## Confirmed 2026-06-28

- task_005 (Arbolus): Jared asked for scope/time/rate on Jun 25. Ever's Jun 26 message was a duplicate resend of the original (same subject), NOT a reply to Jared's questions. Thread has 2 messages only (Ever's original + Jared's reply). No substantive response received. Task overdue (due Jun 29).
- task_006 (AlphaSights): Raphael sent inquiry Jun 26 with scheduling link. No reply from Jared. Task needs Jared's decision (not actionable from cron). Overdue (due Jun 29).
