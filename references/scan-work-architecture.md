# finch:scan / finch:work Architecture

## Problem

The finch anticipation system went through three architectural iterations in May 2026, each failing for a distinct reason:

### V1 — Single Prompt (Scan + Action)
- One cron prompt that scanned all signal sources AND executed tasks
- **Failure:** Scanning consumed the entire context window. The agent would read emails, calendar, sessions, cron health, etc., then run out of tokens before reaching the action phase. Result: lots of analysis, no action.

### V2 — Python Script + LLM
- Split into `anticipate.py` (Python scans, writes task list JSON) + cron agent (reads JSON, acts)
- **Failure:** The Python script was the scanner, so the LLM became a dumb executor with no judgment. As Jared put it: "You took the LLM out of the loop so it became useless." The interop overhead also added latency and failure modes.

### V3 — Two LLM Cron Jobs (Current)
- `finch:scan` (every 2h): Wide lens, prioritization intelligence. Scans all signal sources, maintains the ranked task list. Does NOT execute tasks.
- `finch:work` (every 30min): Narrow lens, execution intelligence. Picks top pending item, loads the governing skill, executes the task. ONE task per run.
- **Key insight:** Both sides must be LLM-powered. The difference is scope, not capability.

## Why This Works

1. **Bounded scanning:** The scan job has a wide lens but a single job — maintain the list.
2. **Focused execution:** The work job picks ONE item and goes deep.
3. **LLM both sides:** The scanner makes value judgments about priority. The worker makes value judgments about how to execute.
4. **No Python interop:** Pure cron prompts. No scripts between the LLM and the task list.
5. **Skill governance:** The work job loads the governing skill before executing.

## What To Never Do

- Never merge scan and action into one prompt (V1 failure)
- Never put a Python script between the LLM and the task list (V2 failure)
- Never make the worker "dumb" — it needs full LLM reasoning
- Never invoke `anticipate.py` or `task_list_builder.py` — they're deprecated
- Never use `delegate_task` from a cron job for finch work items
- Never include LinkedIn as a scan source — the LinkedIn MCP only accesses the agent's own LinkedIn, not Jared's
- Never call Gmail/Calendar/Drive MCP without `user_google_email="jared.zimmerman@gmail.com"`
- **Never skip a signal source during scanning — all 7 sources must be checked every run.** Use `COMPOSIO_MULTI_EXECUTE_TOOL` for Google Calendar and Drive (they work in cron). For Gmail, check toolkit connection status first — skip only if `has_active_connection: false`. When a source must be skipped, note the reason in the scan journal's `sources_scanned` section.
- **Never treat the existing task list as ground truth — always validate items are still active.** When finch:scan refreshes the task list, re-check each pending task's underlying signal. If the signal has self-resolved (cron job now healthy, OAuth now valid, appointment now passed), mark it done rather than carrying it forward. Stale pending tasks waste finch:work cycles on already-fixed issues.

  **Example (2026-07-06 scan):** Cron health check found 182 jobs with `last_status=error` but ALL had `consecutive_failures=0` (gate check) — zero active failures. Task list carried `owl_alpha_model_crisis` (owl-alpha model removed, 30+ jobs failing) marked `completed` from prior scan — correctly kept as done. `travel_provincetown_jul1` (trip ended Jul 5) marked `completed` with resolution note. `task_disk_monitor` (79% disk) kept as `watching` — signal still active. Validation prevented carrying forward 180+ stale error entries as tasks.

## Signal Sources Scanned by finch:scan

| Source | What to look for | Tool |
|--------|-----------------|------|
| **Cron health** | Jobs with error status, jobs that haven't run when expected | Primary: `terminal('python3 -c \\\"import yaml; data=yaml.safe_load(open(\\'/root/.hermes/config.yaml\\')); [print(j.get(\\'id\\',\\'?\\')[:12], j.get(\\'name\\',\\'?\\')[:40], j.get(\\'last_status\\'), \\'|\\', \\'ERROR\\' if j.get(\\'last_status\\')==\\'error\\' or j.get(\\'last_delivery_error\\') else \\'ok\\') for j in data.get(\\'cron\\', data.get(\\'crons\\',[])) if isinstance(j,dict)]\"')` — parses config.yaml directly. Fallback: `terminal('cat /root/.hermes/cron/jobs.json')` for system jobs AND `terminal('cat /root/.hermes/profiles/indigo/cron/jobs.json')` for profile jobs. The `cronjob` tool does NOT exist in cron context. |
| **Email** | Unread/urgent messages needing response, actionable threads | `GMAIL_FETCH_EMAILS` via `COMPOSIO_MULTI_EXECUTE_TOOL` — **⚠️ Gmail toolkit may lack OAuth connection**: Check `has_active_connection` in search response. If `false`, skip email and use cached-data fallback (dispatch journals). If `true`, query normally with `query="newer_than:2d"` and `user_id="jared.zimmerman@gmail.com"`. |
| **Calendar** | Next 48h events, prep needs, travel gaps, conflicts | `GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS` via `COMPOSIO_MULTI_EXECUTE_TOOL` — **Works in cron** (active connection as of 2026-06-30). Query 48h window with `time_min`/`time_max` in RFC3339. |
| **Sessions** | Unfinished work from recent conversations | `session_search(limit=10, sort='newest')` WITHOUT `query` (FTS5 treats query as literal text, not time filter). Manually check timestamps. Check for pending user requests |
| **Drive** | Recently shared/modified files needing attention | `GOOGLEDRIVE_FIND_FILE` via `COMPOSIO_MULTI_EXECUTE_TOOL` — **Works in cron** (active connection as of 2026-06-30). Use `orderBy: "modifiedTime desc"` and `pageSize: 10`. |
| **Kanban** | Blocked tasks needing user approval, completed work ready for parent review, new pipeline stages to track | `hermes kanban ls --status blocked` + `hermes kanban ls --status todo` + `hermes kanban ls` (show all non-done). Parse for tasks blocked on user input or parent tasks ready for closure. Add tasks for blocked items awaiting Jared's decision. |
| **System** | Disk space, stale lock files, /tmp size, zombie processes | `terminal('df -h / && du -sh /tmp && ps aux --sort=-%mem \\| head -5')` |

### MCP-unreachable fallback pattern for email (cron-only)

**Updated 2026-06-30**: Calendar and Drive are now reachable in cron via Composio. Only Email/Gmail may be unreachable if the Gmail toolkit has no active OAuth connection. The fallback pattern below is ONLY for email when `has_active_connection: false`.

**Confirmed 2026-06-30**: `GOOGLECALENDAR_EVENTS_LIST_ALL_CALENDARS` and `GOOGLEDRIVE_FIND_FILE` work via `COMPOSIO_MULTI_EXECUTE_TOOL` in cron context. `GMAIL_FETCH_EMAILS` fails with "No Active connection for toolkit=gmail" if OAuth is not set up. Check connection status before attempting.

| MCP source | Fallback data | Path | Staleness |
|------------|---------------|------|-----------|
| **Email** (inbox check) | `last_email_check_jared_zimmerman_gmail_com.json` | `commons/data/ocas-dispatch/` | ~10 min (email:check cron) |
| **Email** (direct script) | `email_check.py` | `/root/.hermes/scripts/email_check.py` | Direct test script — fails on OAuth (HTTP 400) but file exists |
| **Email** (actionable threads) | `commitments.jsonl` (pending items) | `commons/data/ocas-dispatch/` | ~10 min |
| **Email** (thread content) | `messages.jsonl` + `threads.jsonl` | `commons/data/ocas-dispatch/` | ~10 min |
| **Calendar** | Vesper morning/evening journal → `decision.payload` | `commons/journals/ocas-vesper/YYYY-MM-DD/` | Up to 12h |
| **Drive** | No reliable fallback | — | — |

**Pattern (confirmed 2026-06-28):**
1. Attempt `mcp_google_workspace_*` calls first — they may work if MCP is registered
2. If "tool not found" or "module not found" errors, fall back to cached data
3. Read `last_email_check_*.json` for unread counts and thread summaries
4. Read `commitments.jsonl` for pending follow-ups and opportunities
5. Read latest `ocas-vesper` journal for calendar signal (the vesper briefing checks sands and reports events)
6. For Drive: note "drive: no fallback available" in source_details
7. Always report data staleness in the scan journal

### Google OAuth failure — critical scan finding

Google OAuth failures in scan context have TWO distinct root causes. Both produce the same outcome (no email/calendar/drive data) but require different descriptions and have different fixes:

#### Root Cause A: Credentials file missing (FileNotFoundError)

The `google_auth_mcp.py` helper (used by `email_check.py`, `monitor_email.py`, and other scripts) maps account aliases ("jared", "indigo") to email addresses, then looks for credential files. If the file is missing, `_load_creds` raises `FileNotFoundError: No credentials file for <alias>`.

- **Credential file locations** (two systems, both must be checked):
  1. `/root/.google_workspace_mcp/credentials/<email>.json` — primary location for workspace-mcp scripts
  2. `/root/.hermes/credentials/<email>.json` — secondary location used by some older scripts
- **Detection**: Run `python3 /root/.hermes/scripts/email_check.py --account jared` in terminal. `FileNotFoundError` = missing credentials file. `RefreshError: invalid_grant` = revoked token (Root Cause B).
- **Action**: Create a `critical` priority task with signal "Google OAuth credentials file missing — FileNotFoundError." Jared must re-authenticate via the paste-back flow in `gcloud-cli` skill (`scripts/google_reauth_url.py` + `scripts/google_oauth_finish.py`). The agent cannot fix this autonomously.
- **Confirmed 2026-06-28**: Both credential paths were empty/missing. `email_check.py` returned `FileNotFoundError: No credentials file for jared`.

#### Root Cause B: Refresh token revoked (invalid_grant)

The credential file exists but the refresh token has been revoked server-side. Google rejects it with `google.auth.exceptions.RefreshError: invalid_grant: Token has been expired or revoked`.

- **Root cause**: The OAuth refresh token stored in the credentials file has been revoked. The file still exists and contains a `refresh_token` field, but Google rejects it.
- **Impact**: ALL Google API access is blocked — Gmail, Calendar, Drive. Affects every cron job that depends on Google APIs.
- **Detection**: Attempt a lightweight API call (e.g., `service.users().messages().list(userId='me', maxResults=1)`) and catch `RefreshError` with `invalid_grant`.
- **Credential file location**: `/root/.google_workspace_mcp/credentials/<email>.json` — this file has `client_id`, `client_secret`, `refresh_token`, `token_uri`, `scopes` including `gmail.modify`, `calendar`, `drive.readonly`.
- **Action**: Create a `critical` priority task. Jared must re-authenticate via paste-back flow. The agent cannot fix this autonomously.

#### Root Cause C: MCP server binary broken (DEPRECATED — Composio bypasses this)

**Updated 2026-06-30**: When using Composio tools (`COMPOSIO_MULTI_EXECUTE_TOOL`), the MCP server binary is NOT involved. This root cause only applies to the old `workspace-mcp-fixed` / `mcp_google_workspace_*` tool path. If you're using the Composio path (recommended), ignore this section.

The `workspace-mcp-fixed` wrapper script chains to `workspace-mcp` which invokes `/root/hermes-agent/.venv/bin/python -m main`. If the Python package providing `main` is not installed in that venv, the binary fails with `No module named main` — distinct from OAuth issues.

- **Symptom**: Running `workspace-mcp-fixed` directly produces `/root/hermes-agent/.venv/bin/python: No module named main`. The MCP tools are not registered AND the binary cannot even start.
- **Detection**: `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | timeout 10 /usr/local/bin/workspace-mcp-fixed` → fails with module error.
- **Distinction from OAuth**: OAuth errors produce `HTTPError 400` or `invalid_grant`. A broken binary fails before any HTTP call. If the binary can't start, OAuth is irrelevant — fix the binary first.
- **Fix**: Install the missing Python package in the venv: `/root/hermes-agent/.venv/bin/pip install <package>`. Then restart the gateway. After the binary works, re-test OAuth.
- **Impact**: Same as MCP-unavailable for finch:scan (can't access email/calendar/drive). But also affects any cron job that invokes the MCP server via the binary.
- **Confirmed 2026-06-29**: `workspace-mcp-fixed` binary broken (`No module name main`). Even if OAuth were restored, the MCP server would not function until the venv package is installed.

#### Distinguishing OAuth failures from MCP-unavailable from MCP binary broken

- **MCP not configured**: The `mcp_google_workspace_*` tools aren't registered in `config.yaml`. Tool calls return "tool not found." Only finch:scan is affected. The MCP server binary itself may still work — just not exposed as agent tools.
- **MCP binary broken (Root Cause C)**: `workspace-mcp-fixed` fails to start with `No module named main`. Both finch:scan tools AND cron jobs using the binary are blocked. Diagnose by running the binary directly.
- **OAuth credentials missing (Root Cause A)**: `FileNotFoundError` from `google_auth_mcp.py`. ALL Google-dependent cron jobs are blocked. More severe than MCP-unavailable.
- **OAuth token revoked (Root Cause B)**: `invalid_grant` from Google. Same impact as Root Cause A. More severe than MCP-unavailable.
- **Diagnosis order**: (1) Check if MCP tools are registered. (2) Check if the MCP server binary starts (`workspace-mcp-fixed`). (3) Check if credential files exist at both paths. (4) If files exist, test the refresh token. This four-step diagnosis reliably identifies which root cause is in play.

**Confirmed 2026-06-28 (scan 15:07)**: Google OAuth token was revoked (Root Cause B). Created task_019 as critical.
**Confirmed 2026-06-28 (scan 19:02)**: Google OAuth credentials files were missing entirely (Root Cause A). `FileNotFoundError: No credentials file for jared` from `email_check.py`.

**Limitations:**
- Cannot see brand-new emails that arrived after the last `email:check` run
- Calendar events added since the last vesper briefing won't appear
- Cannot read Drive files at all without MCP
- Thread content in `messages.jsonl` may have HTML entities (`&amp;`, `&#39;`) — decode before analysis

**NOTE:** LinkedIn is NOT a valid scan source for Jared's account.

## Governance Model

Each task item has a `governed_by` field. The work job loads the corresponding skill before executing:

| governed_by | Skill rules |
|---|---|
| `ocas-dispatch` | Draft-only in cron. Never send email directly. |
| `private/headhunter` | Quality over speed. No repeats. CDO/VP/SVP/CPO only. $500k+ base. |
| `ocas-sands` | Calendar management rules from ocas-sands SKILL.md |
| `ocas-rally` | Portfolio research rules from ocas-rally SKILL.md |
| `ocas-odds` | Prediction market rules from ocas-odds SKILL.md |
| `ocas-weave` | Contact management rules from ocas-weave SKILL.md |
| `ocas-sift` | Research rules from ocas-sift SKILL.md |
| `system` | General system maintenance. No special skill rules. |

NEVER create a task that asks the work agent to violate its governing skill's rules.

### Cron task: check for redundancy before fixing

When a finch:work task involves a failing cron job, before investing effort in debugging the script:
1. Check if another working job (or pipeline of jobs) already produces the same output
2. If yes, the failing job is redundant — disable it rather than fix it
3. Set `enabled=False` + `paused_reason` in `jobs.json` (the `hermes cron pause` CLI can't find profile-specific jobs — edit the file directly)

Confirmed 2026-06-27: `brief:email-morning` and `brief:email-evening` were failing but redundant with the working `sands:*-brief` → `dispatch:briefing-deliver` pipeline.

### Dispatch journal as fallback data source

When a finch:work task requires checking the status of an external service but you lack API credentials (e.g., no `CLOUDFLARE_API_TOKEN`, no wrangler auth, no OAuth token), the `ocas-dispatch` journal at `~/.hermes/commons/journals/ocas-dispatch/YYYY-MM-DD/` may contain ingested alert/notification emails that provide the answer. Search the journal files for the service name or error type.

**Example (2026-06-28):** Task was "check Cloudflare Workers usage." No API token available. Searched dispatch journal for `Cloudflare.*Workers.*daily` → found two Cloudflare alert emails (75% at 10:06 UTC, 82% at 00:05 UTC). No 100%/exceeded alert → limit was NOT hit. Task resolved without API access.

**Pattern:**
1. Check if relevant API credentials exist in `.env` or CLI auth
2. If not, search dispatch journal: `search_files(path="~/.hermes/commons/journals/ocas-dispatch", pattern="<service keyword>", file_glob="*.json")`
3. Alert/notification emails from the service often contain usage stats, threshold warnings, or status snapshots
4. Absence of a critical alert (e.g., no "100% exceeded" email) can itself be positive evidence

This is especially useful for: Cloudflare, AWS, GCP billing alerts, domain expiry notices, SSL certificate warnings, and similar automated service notifications.

### Physical-world action tasks — aggregate a complete action packet

When a task requires Jared to physically visit a location (studio, office, store, event venue), the agent cannot perform the action. The agent's value is in surfacing a **complete action packet**: every detail Jared needs to act efficiently without further research.

**Action packet fields** (include all that are available):
- **Deadline** — the specific date/time by which action must be taken
- **What happens if missed** — consequence of inaction (e.g., "items on shelves will be discarded")
- **Location address** — full street address
- **Access details** — gate codes, door codes, parking notes, entry instructions
- **Hours** — when the location is accessible (open hours, access windows)
- **What to look for** — specific items, shelves, or areas Jared should check
- **Contact** — email/phone for questions about the deadline or process
- **Break/closure dates** — any dates the location is closed between now and the deadline

**Data sources for assembling the packet:**
1. Dispatch `messages.jsonl` — business newsletters, Substack emails, booking confirmations typically contain deadlines, closure dates, contact info
2. Prior session history (`session_search`) — welcome emails, logistics emails from the business often contain codes, hours, access details
3. Calendar events — booking confirmations show location, price, staff name
4. Web search — current hours, address, contact if not in dispatch data

**Confirmed 2026-06-28:** Clayroom SoMa studio closing task. Dispatch Substack email had deadlines (June 30 shelf cleanout, July 7 clay cleanout). Prior session history had gate code (2686), door code (4853), and hours from a welcome email 7 days earlier. Calendar had the class booking with location. Aggregated into a single report with all access details, saving Jared from needing to search his own email for codes.

**Do NOT just say "there's a deadline."** That forces Jared to do the research himself. The agent's value is pre-assembling everything so Jared can just go.

### Email task default: review, not send

For `source: "email"` tasks where the action is "read and report" (stale detection, summarization, verification), the work job does NOT need to load `ocas-dispatch`. Loading dispatch for a review-only task wastes context and risks unnecessary draft generation. Only load `ocas-dispatch` if the task explicitly requires drafting a reply AND the user has pre-approved automated sending for that thread. For tasks where Jared may have already replied, the governing pattern is: fetch thread → check last sender → mark done if already replied.

### Third-party communication tasks (action_required: true, new recipient)

When a task requires Jared to contact someone NOT already in the existing thread (e.g., "have X do Y and send to Z"), the work job should:
1. Fetch the source thread for context (`get_gmail_thread_content`)
2. Look up the recipient's email via `search_contacts`
3. Draft an email from Jared to the recipient explaining the needed action
4. Save as draft via `draft_gmail_message` — **never send directly from cron**
5. Mark task `completed` with draft ID and a note for Jared to review/send

This pattern applies when the task's `action` field implies coordinating with a third party who is not the original sender. The work job does NOT need to load `ocas-dispatch` for this — `draft_gmail_message` is sufficient. See `references/pitfalls.md` for the confirmed 2026-06-25 example (Bywater COC — Shannon Badiee).

## Task List Schema

> **NOTE (2026-06-20):** The actual `task-list.json` file on disk uses a slightly different schema than what was originally documented below. The file is ground truth — update this doc to match the file, not vice versa.

### Actual schema (as of 2026-06-28)

```json
{
  "tasks": [
    {
      "id": "task_NNN",
      "source": "email|calendar|cron|sessions|drive|system",
      "signal": "Human-readable description of what triggered the task",
      "action": "What should be done",
      "priority": "high|medium|low|info",
      "status": "pending|done",
      "due": "ISO timestamp or null",
      "created": "ISO timestamp",
      "updated": "ISO timestamp (optional)",
      "resolved": "Reason resolved (optional)"
    }
  ],
  "last_scan": "ISO timestamp",
  "scan_count": 9
}
```

Key differences from original doc:
- Top-level: `tasks` (not `items`), no `refreshed`/`done_count`
- Per-task: `priority` (not `severity`), `created`/`updated`/`resolved` timestamps (not `created_at`/`last_seen`), `signal` (not `title`/`description`), NO `governed_by`
- Status values: `pending`, `done` (not `in_progress`/`cancelled`/`blocked`/`needs_review`)

**Observed in practice (2026-07-06):** Additional status values used: `completed` (resolved with resolution note), `watching` (signal active but no action required), `active` (event in progress). The core workflow uses `pending` → `done`; the others are transitional/informational states that scan validation manages.
- **`description` metadata accuracy**: Scan-generated descriptions can be wrong about sender, company, contact person, and URL. Confirmed 2026-06-23: a task attributed to "Mason Paulen <mpaulen@glgroup.com>" actually came from Ever Solano at Arbolus. Data-mining skills (email, sessions) must verify the actual content before paraphrasing the description as fact.

### Original documented schema (superseded)

## Superseded: Delegation Pattern

The previous delegation pattern (orchestrator cron → `delegate_task` → sub-agent) was replaced by the scan/work architecture. The finch:scan job IS the orchestrator. The finch:work job IS the executor. No `delegate_task` from cron jobs. See `archive/delegation-pattern.md` in earlier versions for historical reference.
