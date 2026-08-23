# Email MCP triage (metadata-first, full-body-last)

When scanning `newer_than:2d`, do NOT batch-fetch `format=full` for every
message — most are noise (Amazon / Chase / CapitalOne / Cloudflare / job-ACKs /
marketing). Procedure (confirmed across multiple finch:scan runs):

1. **Paginate to completion.** Loop `search_gmail_messages` with `page_size`
   (default 10; the MCP tool uses `page_size`, NOT `max_results`) until no
   `page_token` is returned. Collect ALL Message IDs across pages. NEVER stop at
   page 1 and NEVER reuse a prior scan's page count as a ceiling — under-
   pagination is a recurring false-negative (see `scanning-gotchas.md`).
2. **Metadata first.** Fetch `get_gmail_messages_content_batch(message_ids=[...],
   format="metadata")` in pages of <=25. Returns Subject/From/Date/To — enough to
   triage. For parsing the persisted batch file, see
   `references/email-mcp-pagination-parsing.md`.
3. **Full body last.** Only pull `format="full"` for the handful whose metadata
   suggests actionability (non-`no-reply` sender + decision/action subject).

## Filtering rule

Drop `info@` / `noreply@` / `no-reply@` + known bulk domains + `Precedence: Bulk`
/ `List-Unsubscribe` headers UNLESS the subject carries an explicit action verb
(Complete / Action Required / Please Action / Upgrade needed / Confirm).

Examples caught at metadata stage (real finch:scan finds): a paid consult
invitation, an eBay return-ready notice, a DSN delivery-delay, a vendor V1->V2
action-required. These need the operator-level action; everything else is noise.

## Actionability verdict

Never assert "0 actionable" until EVERY page is fetched AND classified. An
"all noise" conclusion from a partial page set is the cron-0-false-negative trap
in email form.
