# Composio Tools in Cron Context

## Discovery (2026-06-30, confirmed 2026-07-06)

The `COMPOSIO_SEARCH_TOOLS` and `COMPOSIO_MULTI_EXECUTE_TOOL` meta-tools work in cron context, enabling access to Google Calendar, Gmail, and Drive APIs without interactive OAuth flows. This contradicts the earlier assumption that "MCP tools are completely unreachable in cron."

**Confirmed 2026-07-06 (finch:scan):** Calendar and Drive tools executed successfully via `COMPOSIO_MULTI_EXECUTE_TOOL` in cron context. Gmail toolkit reported `has_active_connection: false` — fallback to cached dispatch journal data (8 days stale) was used. Calendar returned 17 events across 6 calendars for 48h window. Drive returned 1 recently modified file. Both returned structured JSON via `summary_view` (Calendar) and `files[]` (Drive).

## How It Works

1. **COMPOSIO_SEARCH_TOOLS** — pass `queries` array with `use_case` + `known_fields`. Returns tool slugs, input schemas, and toolkit connection status.
2. **COMPOSIO_MULTI_EXECUTE_TOOL** — pass `tools` array with `tool_slug` + `arguments`. Executes up to 50 tools in parallel. Returns structured outputs.
3. **Connection status** — search response includes `toolkit_connection_statuses` with `has_active_connection` and `status_message` per toolkit.

## Example: Calendar in Cron

```
Search: queries=[{use_case: "get calendar events for next 48 hours", known_fields: "user_google_email:jared.zimmerman@gmail.com"}]
→ Returns GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS with input_schema
→ Execute: tools=[{tool_slug: "GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS", arguments: {"time_min": "...", "time_max": "..."}}]
→ Returns structured event data
```

## Example: Drive in Cron

```
Search: queries=[{use_case: "list Drive items recently modified", known_fields: "user_google_email:jared.zimmerman@gmail.com"}]
→ Returns GOOGLEDRIVE_FIND_FILE with input_schema
→ Execute: tools=[{tool_slug: "GOOGLEDRIVE_FIND_FILE", arguments: {"orderBy": "modifiedTime desc", "pageSize": 10}}]
→ Returns file list with metadata
```

## Key Patterns

- **Always search first** to get the tool slug and verify connection status
- **Batch independent calls** into a single `COMPOSIO_MULTI_EXECUTE_TOOL` call (up to 50 tools)
- **Gmail may fail** if `has_active_connection: false` — check before attempting
- **Calendar and Drive** have active connections as of 2026-06-30
- **Results are structured JSON** — no need to parse text output
- **Set `session_id`** on all calls (returned from search response)

## Batch Isolation

Composio tools use a different backend than `terminal`/`read_file`. If you batch them together in one `COMPOSIO_MULTI_EXECUTE_TOOL` call, a failure in one tool does NOT poison the others (unlike the old parallel tool batching gotcha). However, it's still good practice to separate:
- **Batch A**: Composio tools (search + execute) — isolated backend
- **Batch B**: Local tools (terminal, read_file, session_search) — different failure modes

## Pitfalls

- **Don't invent tool slugs** — always get them from `COMPOSIO_SEARCH_TOOLS` first
- **Don't hardcode connection status** — check `has_active_connection` every run (tokens expire)
- **Gmail `user_id` must be the email address**, not "me", when using non-default accounts
- **Calendar timestamps** must be RFC3339 with timezone offset
- **Drive queries** use Google Drive query syntax (e.g., `modifiedTime > '2026-06-28T00:00:00' and trashed = false`)
