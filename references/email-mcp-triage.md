# Gmail MCP triage recipe (finch:scan email source)

Goal: scan `newer_than:2d` for ACTIONABLE messages without pulling 80+ full bodies.

## Steps (all calls via `tool_call` to `mcp__google_workspace__*` — NOT direct; describe-first)

1. **Paginate search to completion.**
   `search_gmail_messages(query="newer_than:2d", user_google_email="<user-google-email>", page_size=20)`
   → collect Message IDs. If result carries `page_token`, re-call with `page_token=` and repeat until none.
   (2026-07-20 run: 100 msgs across 5 pages of 20. A page-1 stop would have missed the Oracle OCI mail on page 3.)

2. **Batch-fetch METADATA only (Subject/From/Date/To).**
   `get_gmail_messages_content_batch(message_ids=[...up to 25...], user_google_email="...", format="metadata")`
   Split collected IDs into ≤25 chunks. Metadata is enough to triage ~95% of mail.

3. **Triage by metadata.**
   - DROP (noise): `info@`/`noreply@`/`no-reply@` + known bulk (amazon.com, chase.com, capitalone.com, cloudflare.com, myworkday.com, ashbyhq.com, booking.com, gofundme, klaviyomail, sparkpost) + any `Precedence: Bulk` / `List-Unsubscribe` header — UNLESS subject has an explicit action verb.
   - KEEP for full fetch: subjects like `Action Required`, `Complete Your Application`, `[Please Action]`, `Upgrade needed`, `Confirm`, `We Received Your Application`, expert-network invites (GLG/AlphaSights/<employer>), secure-message / legal notices.

4. **Pull full body only for KEPT IDs.**
   `get_gmail_messages_content_batch(message_ids=[kept_ids], format="full")` — typically ≤5 messages.

## Param notes
- `page_size` (NOT `limit`/`max_results`) for search; `message_ids` is a list for batch.
- Always `tool_describe` an unfamiliar MCP tool before first call — pydantic `unexpected_keyword_argument` means reachable-but-wrong-params (fix + retry), while `Tool '...' does not exist` means server not loaded this run (carry forward prior findings, do NOT treat as permanent).

## Why metadata-first
A 100-message window = ~4 full-body fetches instead of ~4 batches of 25 full bodies. Same signal coverage, far less token/SSL load. Confirmed 2026-07-20: caught the single NEW actionable (Oracle OCI V1→V2 audit-events, action by 2027-06-30) at the metadata stage via its `Action Required` subject.
