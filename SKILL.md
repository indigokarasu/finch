---
license: MIT
description: 'OCAS self-improvement orchestrator (Darwin''s finch — adaptive evolution).
  Mines session JSONL files to detect corrections, breakthroughs, methodologies, course-changes,
  and behavioral directives (Always/Never). Routes each finding to the optimal storage
  tier: MEMORY.md, skill files, reference files, or Chronicle KG. Compacts MEMORY.md
  by routing entries to the correct tier. Part of the OCAS System Evolution Layer
  alongside Mentor, Fellow, and Forge. NOT for real-time behavioral adaptation, skill
  evaluation, or skill creation.'
includes:
- references/**
- scripts/**
metadata:
  author: Indigo Karasu (indigokarasu)
  version: 2.15.3
  hermes:
    category: software-development
    tags:
    - self-improvement
    - session-mining
    - behavioral-adaptation
    - OCAS-core
name: ocas-finch
source: https://github.com/<agent-handle>/finch
tags:
- self-improvement
- session-mining
- behavioral-adaptation
- OCAS-core
triggers:
- self-improvement
- session mining
- behavioral adaptation
- skill evolution
- correction detection
- health scan
- finch scan
- system health
- cron errors
- task list
- memory full
- MEMORY.md at capacity
- memory compaction
- memory guard
---

# ocas-finch

Finch is the OCAS System Evolution Layer's self-improvement orchestrator. It runs as a set of cron jobs — see **Manual run & verification** below for the actual deployed job set (the design doc's `finch:work` is not currently a separate deployed cron). Jobs are primarily pure-LLM cron prompts, plus one `no_agent` script floor (`finch:floor`). Deprecated scripts are in `archive/`.

**Signal sources (7)**: cron health, email, calendar, sessions, Drive, kanban, system. See `references/scan-work-architecture.md` for the full table.


## Interactive Menu

When invoked interactively, present a two-level menu. See `references/interactive-menu.md` for the full two-level menu layout, Clarify timeout behavior, response parsing, and platform adaptation.

## Responsibility Boundary

ocas-finch owns its core domain operations.

ocas-finch does not own: trigger detection, session management, or cross-skill orchestration (those belong to the calling agent).

## When to Use

- Scheduled self-improvement: finch:scan (every 2h), finch:work (every 30 min), finch:daily (6am PT), finch:weekly (Sunday 8am PT)
- Manual session mining via `finch.mine` or `finch.run`
- After major sessions: auto-detect corrections, directives, breakthroughs, methodologies
- Memory at/near capacity (`memory` tool refuses edits, ~79%+ warning threshold): **RUN `finch.compact` / `memory_guard.py` — do NOT hand-edit MEMORY.md to dodge the cap.** Manual memory surgery (condensing entries into one giant block, dropping context to fit) is exactly the work Finch owns, and doing it by hand produces bloat (a single ~1,900-char entry where tier-routing would have moved procedure out to a skill/reference). The user's correction (2026-07-15): "Why are you manually cleaning up memory? You have Finch for that." If the `memory` tool refuses an edit at capacity, hand it to Finch (force `ocas-finch:daily` or run `memory_guard.py --file ~/.hermes/profiles/<profile>/memories/MEMORY.md`); do not fight the limit with manual `memory` writes. Finch owns compaction; this is the procedure, not "there is no skill."
- Skill library maintenance: route findings to SKILL.md patches

## When NOT to Use

- Real-time behavioral adaptation (Chronicle handles pattern detection)
- Skill evaluation scoring (Mentor handles OKR evaluation)
- Skill creation/architecting (Forge handles skill building)
- Entity identity resolution (Chronicle tools handle direct writes)

## Storage

See `references/storage-layout.md` for the full directory tree and skill package structure.

## Scanning Gotchas

The full operational detail for each item below lives in `references/scanning-gotchas.md` (one-line pointers, full bodies there):

- Verify tool availability before parallel batches (one bad tool name poisons the whole batch). **DEFERRED-MCP DIRECT CALL = WHOLE-BATCH KILL (confirmed 2026-07-23 finch:scan):** if a deferred MCP tool (`mcp__google_workspace__*`) is placed in a parallel batch as a DIRECT call (not routed through `tool_call`), the runtime returns `Skipped: another tool call in this turn used an invalid name` and DROPS THE ENTIRE BATCH — including the valid native calls (`terminal`, `read_file`) sharing that turn (they silently return nothing, no error beyond that one line). **Mitigation:** (1) never call a deferred MCP tool directly in a mixed batch; (2) discover it first via `tool_search` (returns `source: "mcp"`), confirm params via `tool_describe`, then invoke ONLY through `tool_call`; (3) keep MCP `tool_call`s in their OWN batch(es) AFTER the native-tool batches have already returned, so a deferred-tool failure can never veto working native reads. EXTEND to an UP-FRONT tool-surface probe: at the very start of each scan, run `tool_search` for the `mcp__google_workspace__*` namespace AND `hermes cron list` BEFORE dispatching any source call. MCP mount state varies run-to-run — sometimes the entire google-workspace namespace is ABSENT (not just misnamed via single-underscore/`cronjob` phantom calls). Knowing which of the 6 sources are even callable THIS run prevents wasted batches and immediately flags which sources must fall back to carry-forward state. (NOTE: the 2026-07-20 13:11Z scan hit an absent-namespace run; the SAME DAY's 15:15Z scan had the full `mcp__google_workspace__*` namespace present and live-scanned all of email/calendar/Drive — so absence is INTERMITTENT, never assume from the prior run. Re-probe every scan.)
- **Absent-namespace closure — `tool_call` ALSO fails, pivot immediately (re-validated 2026-07-23T19:48Z finch:scan):** the mitigation above assumes the namespace is merely NOT-directly-callable but IS mounted (so `tool_call` works). When the namespace is truly ABSENT this run, the failure signature differs: `tool_search` STILL returns the `mcp__google_workspace__*` names (they are discoverable by name), BUT the live callable tool surface does NOT expose them. A DIRECT call in a mixed batch returns `Tool 'mcp__google_workspace__search_gmail_messages' does not exist` and DROPS the whole batch (including valid `terminal`/`read_file` siblings), and routing via `tool_call` is ALSO impossible (the tools aren't mounted, so `tool_call` errors `'...' is not a deferrable tool` or likewise). **Decision rule when you see this:** do NOT retry MCP paths this run — the namespace is absent, not merely misnamed. Pivot IMMEDIATELY to the direct googleapiclient fallback: (1) cron health → read `~/.hermes/profiles/<profile>/cron/jobs.json` directly and grep `last_status=error`; (2) email/calendar/Drive → run `scripts/gws_direct_puller.py` (or `scripts/gws-direct-fallback.py` count-probe) with `<hermes-venv>/bin/python` against `<gworkspace-creds>/credentials/<email>.json` (use googleapiclient, NOT raw requests — the host egress filter 404s raw Calendar/Drive calls). This session re-validated that path end-to-end: 125 Gmail msgs/2d classified, calendar next-48h + drive-recent pulled, all 3 sources verified without MCP. The cost of NOT pivoting is a wasted turn re-attempting a tool that cannot resolve this run — and the mixed-batch drop silently loses the native reads you co-dispatched.
- **MCP-absent triage (distinguish mount-failure from config/cred failure):** When the `mcp__google_workspace__*` namespace is absent this run, determine WHICH failure class before deciding the closure — they imply different actions. (1) **Config check:** google-workspace is defined in the PROFILE config (`~/.hermes/profiles/<profile>/config.yaml` under `mcp_servers.google-workspace`, `enabled: true`), NOT the global `~/.hermes/config.yaml` (which has `mcp_servers: {}`). Don't waste time grepping the global file. (2) **Cred check:** `ls -la <gworkspace-creds>/credentials/<email>.json` — a recent mtime means creds are live. (3) **Log check:** `grep -iE 'google.workspace|workspace.mcp' ~/.hermes/logs/errors.log` — if ABSENT, the server never attempted/failed at the connection layer; the tools simply weren't mounted into this sub-agent (a `Tool does not exist` return is the tell). If config=enabled + creds=fresh + no gws error log ⇒ **intermittent agent-tool-attachment failure, NOT a credential/config problem.** Closure for this class: carry forward the 3 workspace sources' prior task state as UNVERIFIED (append a note in each task + `cycle_note`), AND CREATE a P3 task (e.g. `gws-mcp-flaky-<date>`) tracking the reliability gap so it isn't lost between scans. Recommended fix is infra-side (attach the MCP reliably to the finch:scan cron agent, or add a `gws` CLI / direct API fallback) — out of finch:scan execution scope. Confirmed 2026-07-22T15:06Z scan: all 3 `mcp_google_workspace_*` calls returned 'Tool does not exist', profile config showed `enabled: true`, creds touched 07-22T07:30, errors.log had only `hail` 404s — classified as mount-layer intermittent failure; gap task `gws-mcp-flaky-0722` created.
- **googleapiclient direct-fallback RESPONSE SHAPE (confirmed 2026-07-23 finch:scan):** when calling the Workspace APIs directly (MCP absent), the response schema differs from the MCP proxy return: (1) Gmail `messages().get(format="metadata")` puts From/Subject/Date in `payload.headers` (list of `{name,value}`), NOT top-level `message["headers"]` — indexing `m["headers"]` yields `{}` and silently drops sender/subject/date. (2) `messages().list()` items are ALREADY dicts `{id, threadId, ...}` — passing `m["id"]` into a fetch that itself does `mid["id"]` double-indexes and raises `TypeError: string indices must be integers`. Normalize once: `real_id = mid if isinstance(mid, str) else mid["id"]`, then index a single time. Build probes on these shapes (see `scripts/gws_direct_puller.py`); a wrong-shape parse yields a silent '0 actionable emails' false-negative — the inverse of the unreadable-source gap. Full schema notes in `references/gws-direct-fallback-pattern.md`.
- Unreachable workspace source = GAP, never "no signal". When the google-workspace MCP namespace is entirely absent from the tool list (not just failing on proxy invocation), there is NO fallback for email/calendar/Drive — carry forward the prior scan's state for those sources AND explicitly disclose the gap (e.g. "~8h of new mail unscanned") in `cycle_note` + journal. Never assert "no new email/events" from a run that could not read the source. This is the inverse of the cron "0 errors = false-negative" rule: an unreadable source is not evidence of an empty one.
- MCP tools reachable in cron via Composio (`COMPOSIO_MULTI_EXECUTE_TOOL`); attempt Calendar/Drive first, skip only on connection failure
- `tool_search` ≠ `tool_call` availability — probe a suspect MCP tool alone before batching; MCP load state is intermittent between runs
- **Google Workspace MCP = proxy invocation, not direct.** The tools surface as `mcp__google_workspace__<op>` (DOUBLE underscore between `mcp` and `google_workspace`). They are NOT first-class callable tools — invoking them directly (even with the correct name) returns "Tool does not exist." The only working path is `tool_describe(name="mcp__google_workspace__<op>")` → `tool_call(name="mcp__google_workspace__<op>", arguments={...})`. NOTE: the finch:scan cron prompt cites `mcp_google_workspace_search_gmail_messages` — that is WRONG (single underscore AND not directly callable). Use `mcp__google_workspace__search_gmail_messages`, `mcp__google_workspace__get_events`, `mcp__google_workspace__list_drive_items` etc. via `tool_call`. All Gmail/Drive/Calendar ops in a scan go through this proxy.
- **Large MCP batch responses persist to disk — parse with `terminal`, not inline.** `get_gmail_messages_content_batch` (and similar) for many messages exceeds inline limits and is saved to `/tmp/hermes-results/chatcmpl-tool-*.txt` as a JSON object whose `"result"` field is the big escaped string. Parse: `terminal python3 -c "import json,re; raw=open('<path>').read(); res=json.loads(raw)['result']; parts=re.split(r'\n\n---\n\n', res)"` then regex Subject/From/Date per block — BUT that `json.loads(raw)['result']` + `re.split(r'\n\n---\n\n', res)` form is WRONG: the `result` string carries LITERAL `\n` (two chars), so the split matches nothing and you silently parse 0 messages (false "no actionable email"). CORRECT recipe: treat the file as RAW TEXT, split on `Message ID: `, use a `(?:\n|\\n)`-tolerant field regex. Full working code + the email-noise-filter pitfall in **`references/finch-scan-email-batch-parsing.md`**.
  - **`get_gmail_messages_content_batch` 429 partial-failure (2026-07-22):** the call does NOT fail wholesale when some IDs rate-limit — it returns 200 with inline `⚠️ Message <id>: <HttpError 429 ...>` blocks for the missed IDs while other messages succeed. Scan each batch result for `⚠️ Message` lines, collect those IDs, and refetch them individually (single-id calls rarely 429). Do this per batch BEFORE concluding "no actionable email". Full recipe in **`references/finch-scan-email-batch-parsing.md`** (Gmail batch 429 partial-failure mode). `execute_code` is blocked in indigo cron — use `terminal` python3. Do NOT try to read these with `read_file` (truncated).
- Direct MCP credential-store fallback (`<gworkspace-creds>/credentials/<email>.json`) when dispatch rejects + legacy token is `deleted_client`
- **Host egress filter 404s RAW requests to Calendar/Drive — use googleapiclient (confirmed 2026-07-22 finch:scan)**: When the MCP namespace is absent and you call Google Workspace APIs directly, `requests`/`curl`/`AuthorizedSession` return HTML 404 for `calendar.googleapis.com`/`drive.googleapis.com` (the host egress filter only passes traffic with the googleapiclient UA / `x-goog-api-client` header). `googleapiclient.discovery.build(...)` WORKS. So the direct fallback MUST use googleapiclient, never raw requests. Use `scripts/gws_direct_puller.py` (full content) or `scripts/gws-direct-fallback.py` (count-probe), both run via `<hermes-venv>/bin/python`. This is the CLOSURE for the long-standing "3/6 sources unverifiable when MCP absent" gap: with the puller finch:scan verifies all 6 sources directly and can clear `sources_unverified_this_cycle`. Full pattern + transport note in `references/gws-direct-fallback-pattern.md`.
- Stale errors from `hermes cron list` — verify `Last run:` timestamp; `consecutive_failures` is the only reliable error gate
- Re-verify prior completions/STATES against LIVE signal bidirectionally (re-open on relapse, resolve on live recovery)
- MCP Google Workspace param is `page_size`, not `limit`/`max_results` — always `tool_describe` first. Batch content tools (`get_gmail_messages_content_batch`, `get_gmail_threads_content_batch`) ALSO require `user_google_email` explicitly — omitting it returns a pydantic `missing_argument` validation error, not a missing-tool error. (Confirmed 2026-07-17: first attempt without `user_google_email` failed; adding it succeeded.)
- **`get_events` param exception (confirmed 2026-07-23 finch:scan):** `get_events` does NOT accept `page_size` — it uses `max_results` (default 25) and `time_min`/`time_max` (RFC3339, e.g. `2026-07-22T00:00:00Z`); passing `page_size` raises `pydantic: Unexpected keyword argument [call[get_events]]`. `search_gmail_messages` and `list_drive_items` DO use `page_size`. Param names differ across the workspace tools, so always `tool_describe` the specific op before the first `tool_call` rather than assuming one param convention carries across all three.
- Email scan MUST paginate to completion (`page_token` loop) — page-1-only misses high-value items. The 2026-07-22 run needed 6 pages to surface 113 unique messages; page-1 alone (~25) would have missed ~60% including a Capital One double-charge and a Google Cloud action-required notice. After parsing all pages, run the actionable classifier in `references/finch-scan-email-actionable-classifier.md` (noise-domain regex + tag scheme) to separate ~100 noise messages from real signals — do NOT hand-scan subjects.
- **Incremental email classification via message-ID watermark (confirmed 2026-07-24 finch:scan):** `newer_than:2d` returns ~30 messages every cycle, but most are NOT new since the prior scan. Track the highest message-ID boundary from the prior cycle (recorded in `cycle_note`/`filtered_noise` as `boundary <old> -> <new>` — take the `<new>` as the watermark), fetch the full 2d batch, then classify ONLY ids lexically greater than the watermark (Gmail IDs are monotonic per-mailbox; `19f96…` > `19f95…`, compare as STRINGS not int). This avoids re-scanning ~28 stale messages every 2h and prevents duplicate task creation. Full recipe + why lexical-vs-numeric in `references/finch-scan-email-incremental-watermark.md`.
- Sessions scan date-string workaround (`query="YYYY-MM-DD"`); mine interactive messages via direct `state.db` SQL, not session_search scroll
- Only report actual fixes, never stale/transient issues; interpreter-shutdown errors are always transient
- Never force model overrides on cron jobs; maintain skill index; push local changes to GitHub immediately (user directive)
- Disk-before-auth diagnostic (`df -h /` before OAuth); `execute_code` blocked in indigo cron profile — use `terminal` python3
- Concurrent-write hazards on task-list.json / MEMORY.md / ANY shared prep file — a sibling subagent may modify the same file mid-write (e.g. `EXPORT-RUNBOOK.md`). On a sibling-modify warning, read the file back, confirm via `stat -c '%y'` mtime that your version is the latest on disk, and record the concurrency flag in the task note. Full procedure + `DaemonThreadPoolExecutor` fallback in `references/concurrent-write-recovery.md`.
- `read_file` view of a JSON file is NOT validation — it can display trailing-comma corruption as valid and misreport size; only `json.load()` catches it. Validate-after-edit with `terminal python3 -c "import json; json.load(open(...))"` (execute_code is blocked in indigo cron).
- **Parallel `patch` edits to the same JSON file corrupt it.** Batching multiple `patch` calls that touch one JSON file in a single assistant turn causes non-deterministic interleaving: one patch removes a block while a sibling patch (executed against the pre-edit copy) still expects it present, leaving a dangling `}`/`{` and a `JSONDecodeError`. Confirmed 2026-07-17 (finch:scan): 4 parallel patches to task-list.json each reported "success" but broke the file (a task's closing brace was consumed; a later block nested wrong); fixed by a single `terminal python3` script doing `json.load`→mutate→`json.dump`. **Rule: never batch >1 `patch` on one JSON file.** Serialize structural edits, or do all mutations in ONE python3 script.
- **Re-rank the task array with a script, not `patch` block-moves.** Priority re-sorting (P1<P2<P3<P4, `done` sinks within its priority) is a `json.load`→`sort(key=...)`→`json.dump` operation. Moving task blocks via `patch` (delete-here / insert-there) is exactly the pattern that triggers the parallel-corruption trap above even when serialized. Load task-list.json, sort by `(prio_rank, 0 if status=="done" else 1, added, id)`, dump back, then `json.load` to validate. Use the ready-made `scripts/finch_scan_tasklist_rerank.py` (run `terminal python3 scripts/finch_scan_tasklist_rerank.py [--merge new_tasks.json] [--dry]`) — it appends new ids, re-ranks, atomic-write + validates in one process. NEVER batch >1 `patch` on task-list.json.
- **Cron health = read `jobs.json` directly** (`~/.hermes/profiles/<profile>/cron/jobs.json`), NOT a `tool_call`/`tool_search`/`cronjob` tool (`tool_search(query="cronjob")` returns 0 matches; `tool_call("cronjob", ...)` errors `'cronjob' is not a deferrable tool`). `jobs.json` is authoritative — it surfaces `last_status=error` on PAUSED/disabled jobs that `hermes cron list` (terminal CLI) HIDES, so prefer the jobs.json enumeration procedure in `references/cron-health-validation.md`. NOTE: the deployed finch:scan JOB PROMPT still says `cronjob(action='list')` and single-underscore `mcp_google_workspace_*` direct calls — both stale vs the gotchas below; follow the gotchas, not the prompt's tool names, when they disagree.
- **`jobs.json` is a dict `{"jobs": [...], "updated_at"}`, NOT a bare list (confirmed 2026-07-23 finch:scan):** a naive `json.load(open(path))` then `for j in jobs:` throws `AttributeError: 'str' object has no attribute 'get'` because the top-level object is `{"jobs": [...], "updated_at": ...}`. Always do `jobs = json.load(open(path))["jobs"]` before iterating. Pair with the existing `find` stale-snapshot rule (pin `~/.hermes/profiles/<profile>/cron/jobs.json` explicitly, never trust the first `find` hit).
- **Cron run-history evidence = `cron/output/<rid>/`, NOT `executions.db`.** `executions.db` is trimmed/rotated and often has NO rows for a job even when it's healthy — a `SELECT` returning 0 rows proves nothing. The authoritative per-job run history is the artifact dir `~/.hermes/profiles/<profile>/cron/output/<rid or id>/` (one `.md`/`.txt` per run, `YYYY-MM-DD_HH-MM-SS.*`). To decide one-off-vs-recurring for a new `last_status=error`, `ls -la` that dir: a long clean history + a single trailing early-abort failure = transient (monitor); many clustered failures = real task. Full recipe in `references/cron-health-validation.md`.
- **Windowed mining/analysis cron = SILENT DATA-DROP trap (confirmed 2026-07-23, <other-ocas-skill>-miner).** A self-improvement/data-mining cron that filters events by a `now - N hours` cutoff reported `"0 events, nothing to do"` and was about to emit `[SILENT]` — but the real count was 7. Root cause: log timestamps were **timezone-naive** (no `Z`) while the cutoff was built **aware** (UTC); comparing naive ≥ aware raised `TypeError`, which a **bare `except:` swallowed**, silently dropping EVERY interactive row. This is a SUBTYPE of the cron-0-false-negative trap (a run that looks healthy and self-excuses). **Mitigations when writing/auditing any windowed miner:** (1) normalize naive timestamps to UTC (`ts.replace(tzinfo=timezone.utc)`) before comparing — never compare mixed naive/aware; (2) NEVER wrap a data-inclusion gate in a bare `except:` — at minimum log the error so a swallowed exception can't masquerade as "no data"; (3) after the miner reports 0 events, INDEPENDENTLY re-verify with corrected timezone handling before trusting "nothing to analyze" — a healthy-looking muted run is exactly the failure to suspect; (4) filter cron-source rows by the data's `source` COLUMN, not by assuming all rows are interactive. Full repro + recipe in **`references/cron-windowed-miner-silent-drop.md`**.
- **Transient-provider signature (Tencent "Upstream error… Retry once"):** `RuntimeError: Upstream error from Tencent: An internal error occurred. Retry once; if it persists, contact support with your request_id.` is a **provider 5xx transient**, NOT a code defect — the run artifact shows the failure at the model call (before any git/gh step), `consecutive_failures` is null/0, and prior history is clean. Classify P3 monitor (same class as autobio 429 / reach interpreter-shutdown); do NOT open a code-fix task. A genuine code crash instead has a Python traceback naming a local symbol and recurs every tick. Pattern + distinction in `references/cron-health-validation.md`.
- **`find` can return a STALE `jobs.json` snapshot under `state-snapshots/` — always pin the LIVE path.** A bare `find ~/.hermes/profiles/<profile> -name jobs.json -path '*cron*'` returns BOTH the live `~/.hermes/profiles/<profile>/cron/jobs.json` AND an old snapshot like `~/.hermes/profiles/<profile>/state-snapshots/preupdate-20260712-193656/cron/jobs.json`. The STALE snapshot still carries the error states from BEFORE a migration/update — this session it reported 86 phantom `last_status=error` jobs (incl. errors on jobs that are actually healthy), while the LIVE file reported 0. Rule: pin `jobs.json` to `~/.hermes/profiles/<profile>/cron/jobs.json` explicitly (or `grep -v state-snapshots`), NEVER trust the first `jobs.json` a `find` returns. Confirmed 2026-07-19 (finch:scan 09:06Z): stale 2026-07-12 snapshot showed 86 errors; live file showed 0; the 86-error claim was discarded as not live. This is a SUBTYPE of the false-negative trap above — a snapshot read looks like a full enumeration but is from the wrong point in time.
- `skill_view(name, file_path=...)` linked-file fetch can itself throw the transient `DaemonThreadPoolExecutor object has no attribute '_initializer'` error (same class as `read_file`/`search_files` bursts, observed 2026-07-17). Retry `skill_view`, or read the file directly; in a normal run `read_file`/`search_files` are available, with `terminal find`/`python3` as the hard fallback only when they flake.
- Long single-line JSON string values defeat the `patch` fuzzy matcher — a ~3KB one-line `signal` value in task-list.json returned "Could not find a match" on 3 correct attempts (no whitespace/anchor issue, just line length). Fallback for any task-list.json / long-line JSON edit: write a small `terminal python3` script that `json.load()`s the file, mutates the in-memory dict, and `json.dump()`s back (execute_code is blocked in indigo cron). Do NOT loop on `patch` for long JSON lines — switch to the script fallback immediately. **PAGINATED READ = REFUSAL LOOP (corrected 2026-07-23):** if you `read_file`'d the JSON with `offset`/`limit` (pagination), subsequent `patch` on a long-line value can REFUSE (`Could not find a match`) on a string that IS present, then hit the `same_tool_failure_warning` loop guard after 3 tries — blocking all further `patch` calls on that file for the turn. The legacy "non-blocking pagination warning" note in `references/patch-json-tool-behavior.md` is WRONG for this case: the warning can escalate to a hard refusal+loop. Rule: after ANY paginated `read_file` of a JSON file, do NOT `patch` it — go straight to the single `terminal python3` script path.
  - **Inline `terminal python3 -c` with a LARGE payload = STREAM TIMEOUT (confirmed 2026-07-24 finch:scan):** when you embed a multi-KB document (e.g. the full task-list.json content, or any big inline JSON/string) inside a `terminal python3 -c "..."` call so you can `json.load`→mutate→`json.dump` in one shot, the tool-call ARGUMENTS themselves can exceed the harness's ~8K-token delivery budget. The call is then dropped/truncated with a stream timeout — the mutation never executes and you get no usable output (the assistant-side error is "tool call too large and the stream timed out before it could be delivered"). **Mitigation (extends the patch-fallback rule above): offload large content to a file.** `write_file('/tmp/finch_*.py', script_text)` the full script (write_file has no such size cap on the body), then `terminal python3 /tmp/finch_*.py`. This keeps every tool call's arguments small and survives the stream limit. Applies to ANY cron edit that would otherwise inline a multi-KB JSON doc — and is the ONLY viable large-edit path, since `execute_code` is separately blocked in the indigo cron profile. The skill's standing "use terminal python3, not execute_code" guidance is necessary but NOT sufficient: the inline payload must also be small. Anchor on a unique short ASCII substring of the long value (never the whole line); the full-line matcher both fails on length AND risks the prefix-match silent-corruption trap.
- **`patch` PREFIX match = SILENT corruption on long single-line JSON values.** A `patch` whose `old_string` is a *prefix* of a long one-line value returns `"success": true` AND emits the non-blocking pagination `_warning` — but actually concatenates the unmatched tail onto your new value, breaking the file (subsequent `json.load()` fails). The `_warning` does NOT stop the write. This is distinct from the "Could not find a match" case above (that refuses; this applies-and-corrupts). **Rule: never `patch` a long single-line JSON string value with less than the FULL line as `old_string`.** On detection, validate with `terminal python3 -c "import json; json.load(open(...))"`, then repair by occurrence-based ASCII-anchor slicing (good-value-end + next real `,\n  "key": [` separator) in a `terminal python3` script — never by re-`patch`ing (each try adds another dangling copy). CRITICAL: JSON-escaped unicode (`\u2014`) is stored as 6 literal chars, so searching on the em-dash (real char OR re-escaped) fails — anchor on adjacent ASCII (`ALREADY HOTFIXED`, `All other open signals still active."`). Full repro + repair recipe in **`references/task-list-json-patch-prefix-corruption.md`**. Confirmed 2026-07-20 (finch:scan 09:21Z): partial-`old_string` patch on `cycle_note` silently duplicated the old note tail; ~15 patch/splice repair attempts failed (most on the literal-`\u2014` search mismatch) before ASCII-anchor slicing fixed it.
- `jobs.json` for cron health when `cronjob` tool unavailable; `hermes cron list` hides disabled jobs. **NEVER report "cron health clean" without enumerating ALL jobs from `jobs.json` and surfacing every `last_status=error` job — including paused/disabled ones a summary view hides.** Classification procedure (see `references/cron-health-validation.md` for the reusable parse script): (a) TRANSIENT/recovered if `consecutive_failures=0` AND a later run produced success output (check `cron/output/<jobid>/` for a subsequent ok file) — not a task; (b) PAUSED-BY-DESIGN if `state=paused` and `last_error` names a missing credential/OAuth the agent can't complete interactively (e.g. `<other-ocas-skill>:sync-spotify` needs <operator>'s interactive Spotify OAuth) — note as standing limitation, not a task; (c) REAL if `consecutive_failures>0` or the error recurs across ticks — create/escalate a task. **Anti-pattern (2026-07-17):** a prior scan reported "cron health clean" and missed `<other-ocas-skill>:journals` (transient, recovered next tick) and `<other-ocas-skill>:sync-spotify` (paused) because it relied on a summary-style view instead of full `jobs.json` error enumeration. Re-verify against `jobs.json` directly every scan.
- **Cron-health "0 errors" is a HIGH-RISK false-negative — derive the claim from a FULL-OUTPUT grep, never from a prior scan's state.** (Confirmed 2026-07-18, finch:scan 09:06Z): the 07:05Z scan's `cycle_note` asserted "all 150 ok / 0 error," but job `<cron-job-id>` (<other-ocas-skill> Escalation Handler) had been erroring EVERY 10m with `KeyError: 'HERMES_KANBAN_BOARD'` since 01:52Z — missed for 2 cycles. Root-cause class: the surface-grep was either run against a TRUNCATED `hermes cron list` view (e.g. piped through `tail -N`, which drops erroring jobs outside the visible window) or the "0 errors" claim was emitted without actually executing/trusting the grep. **Rule:** (1) Always grep the FULL `hermes cron list --profile indigo` output — `grep -iE "Last run:" | grep -viE " ok$"` — NEVER truncate (`tail`/head) before grepping. (2) The error-count in `cycle_note` MUST come from that grep's actual stdout, not a remembered or templated "all clean." (3) If the current scan finds errors a prior scan's `cycle_note` claimed absent, flag it as a CORRECTION (retrospective false-negative) in the new `cycle_note` — this both fixes the record and exposes scan-reliability drift. An actively-erroring every-10m job is a P2 by default. Full repro + canonical command + retrospective-correction recipe in `references/cron-health-false-negative.md`.
- **False-recovery claim = false-positive, verify against live jobs.json (confirmed 2026-07-24 finch:work):** a prior scan's task note asserted a state transition that had NOT happened — it claimed a 12:50PDT cron retry "has now FIRED and self-recovered" while ITS OWN payload admitted jobs.json still showed `last_status=error` for the 02:59 run, and live jobs.json confirmed `next_run_at` was STILL 12:50 (never executed). This is the INVERSE of the "0 errors" false-negative: a scan prematurely reported recovery. **Rule:** when re-evaluating any monitor/actionable task whose own notes assert a post-time-T transition (retry fired, self-recovered, resolved), DO NOT trust the note — verify `last_run_at` / `next_run_at` / `last_status` against the LIVE pinned jobs.json. If `next_run_at` is still in the future, the transition hasn't occurred; the note is a stale/false-positive claim. Flag the discrepancy in the new note so the record self-corrects. (Pairs with "Re-verify prior STATES against LIVE signal bidirectionally" — this is the missing subcase where the note claims recovery that live data contradicts.)
- **Gateway-restart timing interprets a single interpreter-shutdown error (confirmed 2026-07-24 finch:work):** `RuntimeError: cannot schedule new futures after interpreter shutdown` at job submission (scheduler.py:3007 submitting to a `_cron_pool` already torn down) is a gateway-teardown race, NOT a job code defect. To decide whether it's recurrable: check whether the LIVE gateway process started AFTER the error timestamp — `ps` for the `gateway run` PID (e.g. PID 18893) start time, cross-check `gateway-shutdown-diag.log`/`gateway-exit-diag.log` mtime. If gateway (re)started post-error, the error was the OLD instance's teardown and the CURRENT scheduler is healthy (confirm via 0 interpreter-shutdown lines in live `agent.log` + sibling crons running normally); the next scheduled tick is the real test. A monitor task ("escalate if retry also errors") is satisfied ONLY if that next tick's `last_status` stays error — if `next_run_at` is still future, the gate is unmet, apply NO preemptive guard (doing so exceeds the written task). See "Monitor re-evaluation discipline" under Core loop / Work.
- Provider HTTP 400 is MEDIUM (not transient) — classify by status; missing-script errors need path verification not debugging
- finch:scan is NOT a task executor; read_file tilde-expansion path doubling; `jobs.json` schedule fields are dicts not strings
- Gateway RSS growth tracking (3x = notable, >2GB = escalate)
- **`hermes cron list` has NO parseable JSON mode — and emits NO `last_status`/`consecutive_failures` columns.** Passing `--format json` returns a human text table (not JSON) — `json.load()` on its stdout raises `JSONDecodeError: Expecting value: line 1 column 1`. Parse the text directly: count jobs with `grep -cE "^  [a-f0-9]{12} \["` and surface non-ok runs with `grep -iE "Last run:" | grep -viE " ok$"`. Confirmed 2026-07-18 (finch:scan): `hermes cron list --format json | python3 -c "json.load(sys.stdin)"` failed with the decode error; fell back to text grep (150 jobs, 0 non-ok). CRITICAL QUIRK (confirmed 2026-07-23): the CLI text output carries NO `last_status` or `consecutive_failures` field — error state lives ONLY in the `Last run:` line's trailing token (`ok` vs `error: <msg>`). A parser that scans for `Last status:` lines finds ZERO matches and silently reports "0 errors" (false-negative trap). So gate on `Last run:` trailing text, NOT a `last_status` column (that field exists only in `jobs.json`). Full block structure + reusable parse snippet + CLI-vs-jobs.json comparison → **`references/cron-health-hermes-cli-parse.md`**. Do NOT rely on jobs.json alone — the list summary hides paused/disabled jobs (see jobs.json enumeration in `references/cron-health-validation.md`).
- **write_file / read_file `~` expands to the PROFILE home (`~/.hermes/profiles/<profile>/home`), NOT `/root`.** Terminal, `terminal python3`, and `$HOME` all resolve `~` to `/root` (canonical), but `write_file` and `read_file` resolve `~` to the Hermes profile home — so a journal written as `write_file(path='~/.hermes/commons/journals/...')` lands in the phantom tree `~/.hermes/profiles/<profile>/home/.hermes/commons/...` and is never read by anything. For finch task-list.json / Action Journal / commons data, ALWAYS use the absolute path `~/.hermes/commons/...` in write_file/read_file. Confirmed 2026-07-18 (finch:scan): journal written with `~` went to `~/.hermes/profiles/<profile>/home/.hermes/commons/journals/ocas-finch/2026-07-18/scan-0705.json`; had to rewrite to `~/.hermes/commons/journals/...` and `rm` the stray.

## Architecture
- finch:scan is NOT a task executor; read_file tilde-expansion path doubling; `jobs.json` schedule fields are dicts not strings
- Gateway RSS growth tracking (3x = notable, >2GB = escalate)
- **`hermes cron list` has NO parseable JSON mode — and emits NO `last_status`/`consecutive_failures` columns.** Passing `--format json` returns a human text table (not JSON) — `json.load()` on its stdout raises `JSONDecodeError: Expecting value: line 1 column 1`. Parse the text directly: count jobs with `grep -cE "^  [a-f0-9]{12} \["` and surface non-ok runs with `grep -iE "Last run:" | grep -viE " ok$"`. Confirmed 2026-07-18 (finch:scan): `hermes cron list --format json | python3 -c "json.load(sys.stdin)"` failed with the decode error; fell back to text grep (150 jobs, 0 non-ok). CRITICAL QUIRK (confirmed 2026-07-23): the CLI text output carries NO `last_status` or `consecutive_failures` field — error state lives ONLY in the `Last run:` line's trailing token (`ok` vs `error: <msg>`). A parser that scans for `Last status:` lines finds ZERO matches and silently reports "0 errors" (false-negative trap). So gate on `Last run:` trailing text, NOT a `last_status` column (that field exists only in `jobs.json`). Full block structure + reusable parse snippet + CLI-vs-jobs.json comparison → **`references/cron-health-hermes-cli-parse.md`**. Do NOT rely on jobs.json alone — the list summary hides paused/disabled jobs (see jobs.json enumeration in `references/cron-health-validation.md`).
- **write_file / read_file `~` expands to the PROFILE home (`~/.hermes/profiles/<profile>/home`), NOT `/root`.** Terminal, `terminal python3`, and `$HOME` all resolve `~` to `/root` (canonical), but `write_file` and `read_file` resolve `~` to the Hermes profile home — so a journal written as `write_file(path='~/.hermes/commons/journals/...')` lands in the phantom tree `~/.hermes/profiles/<profile>/home/.hermes/commons/...` and is never read by anything. For finch task-list.json / Action Journal / commons data, ALWAYS use the absolute path `~/.hermes/commons/...` in write_file/read_file. Confirmed 2026-07-18 (finch:scan): journal written with `~` went to `~/.hermes/profiles/<profile>/home/.hermes/commons/journals/ocas-finch/2026-07-18/scan-0705.json`; had to rewrite to `~/.hermes/commons/journals/...` and `rm` the stray.

## Architecture

- **All finch jobs are pure LLM**

### Cron rebase breakage pattern
Confirmed 2026-07-22: multiple `ocas-*:update` jobs can fail simultaneously with the same `git rebase` conflict signature, indicating upstream sync publication introduced incompatible changes across multiple related repos/skills. Job descriptions often include `Removing references/...`, `Removing data/`, and `Dropped refs/stash@{0}`. Treat as one systemic sync breakage, not N independent failures.

**Role:** Session mining engine. Detects behavioral signals from conversation transcripts and routes them to durable modification targets (MEMORY.md, skill patches).

**Journal type:** Action Journal. Every finch run emits an Action Journal entry to `{agent_root}/commons/journals/ocas-finch/`.

**Cooperation:**
- Receives: Session transcripts (read-only, from the agent's session store)
- Reads: BehavioralSignal files from Chronicle (Corvus was merged into Chronicle)
- Emits: DecisionRecords to the Finch decision log
- Writes: MEMORY.md (via memory tool), skill SKILL.md files (via skill_manage)

## File governance

See `references/file-governance.md` for write targets, read-only files, off-limits files, and creation criteria.

## Signal types

See `references/signal-types-table.md` for the full signal type table.

## Behavioral directives (priority 0)

When the user says "Always" or "Never", this is an explicit behavioral rule. **Priority 0** — highest priority. Apply immediately and prominently. Route to MEMORY.md under `## Always Rules` or `## Never Rules`. Never batch with lower-priority findings.

## Core loop

Finch operates as a continuous improvement cycle:

1. **Scan** (`finch:scan`, every 2h) — Read 7 signal sources (cron health, email, calendar, sessions, Drive, kanban, system). Validate existing tasks. Maintain prioritized task list at `task-list.json`.
2. **Work** (`finch:work`, every 30 min) — Pick top pending task. Load governing skill via `skill_view`. Execute ONE task per run. Before selecting, check for duplicate task IDs and clean up if found (see `references/duplicate-task-detection.md`). When completing a task:
   - Update the task's description to include a work log with timestamp and summary of actions taken (e.g., `\n\n[Work log: At <timestamp> checked DNS for art.<agent-handle>.com - no records found (NXDOMAIN).]`)
   - Set the task's status to `"done"`
   - Set the task's `done_at` timestamp to the completion time
   - Update the task's `updated_at` timestamp
   Route findings to MEMORY.md, skill patches, or reference files.

### Task selection priority (finch:work)

When multiple tasks are `pending`, select by:
1. **`action_required: true`** — tasks needing external action take absolute precedence
2. **Priority** — `high` > `medium` > `low`
3. **Due date urgency** — sooner due date wins within same priority
4. **Status** — `pending` tasks are picked before `in_progress` tasks (which are already being handled)

Skip tasks where `action_required: false` AND `status: "in_progress"` — these are events happening now (e.g., <operator> is at the appointment). Only pick them if they transition to needing action.

If NO tasks have `action_required: true` and all remaining tasks are `pending` with `action_required: false`, pick the highest-priority one to validate/monitor (e.g., disk monitoring) and mark it `completed` with a resolution note. This prevents the list from accumulating stale low-priority items.

### Repeated check-and-close anti-pattern (work execution)

When a task was completed and marked `done`, then re-opened by a subsequent scan for the same unresolved issue, **do NOT run another check-and-close cycle.** After the first re-open, the correct action is decisive resolution or escalation — not re-verifying the same fact.

**Symptoms:**
- Task description says "still NXDOMAIN" / "still unresolved" / "re-opened from prior done status"
- Task was previously marked done with a "checked, found X" work log but the underlying issue persists
- The work log shows N consecutive identical checks with no fix attempted

**Procedure when you encounter a re-opened task:**
1. **Classify the task** — Is this a verification-only task (monitor, check, validate) or an action task (fix, create, configure, deploy)?
   - Verification tasks that are repeatedly re-opened for the same stable condition should be downgraded to `watching` with a note: "Stable state — not actionable." Do not mark `done`; that triggers re-open.
   - Action tasks that were marked `done` without the action being taken should be escalated: the prior closure was premature. Execute the actual fix.
2. **Identify the decisive action** — What single action would close this task permanently? For DNS: create the record. For config: apply the fix. For monitoring: leave as `watching` (not `done`).
3. **Pick decisive execution over verification** — If the task title or description implies an action (e.g., "DNS... unresolved"), invest the first tool call in actually resolving it, not re-verifying. Verification was already done by the prior finch:run or finch:scan.
4. **If genuinely stuck** — Mark the task `watching` with a `blocked_reason` field explaining what's needed to unblock it (e.g., "needs <operator> to choose IP", "requires panel access to provision"). Do NOT mark `done`.

**Rationale:** Three cycles of check-and-close for one unmet DNS record cost ~9 tool calls over 12 hours. One decisive action costs 2 tool calls. The system learns nothing from re-verification; it only learns from resolution.

#### Monitor re-evaluation discipline (work execution)

When a `monitor`/actionable task carries an explicit re-evaluation instruction ("re-evaluate after time T", "apply fix if condition X", "escalate if retry also errors"), the finch:work pass MUST execute the gate against LIVE signal, not the task note:

1. **Read the authoritative live source** (pinned `jobs.json` for cron; direct API for email/calendar) — NEVER decide from the task note's prose, which may be a prior-scan false-positive (see Scanning Gotchas: false-recovery claim).
2. **Compute the gate against current wall-clock.** For a "re-evaluate after 12:50PDT" task, confirm current time is PAST 12:50 before concluding the retry fired. If `next_run_at` is still in the future, the retry has NOT executed — the recurrence condition is UNMET. Record this explicitly; do not infer from the note.
3. **Do NOT apply a preemptive fix.** If the gate is unmet (condition not yet observable), take NO code change — applying a guard "just in case" exceeds the written task and is the same error class as acting on a false note. The correct output is "condition unmet, re-eval next cycle."
4. **Root-cause the error class before deciding.** For interpreter-shutdown, check gateway-restart timing (see Scanning Gotchas) — a pre-restart error is a teardown race, and the next tick is the real test.
5. **Close only on live recovery.** Flip monitor→done only when live signal shows the error cleared (last_status=ok on the post-T tick); never on the note's assertion alone.

**Confirmed 2026-07-24 finch:work (`dispatch-summary-interpreter-shutdown-0724`):** eval ran at 12:33PDT, 17 min before the 12:50 retry; live jobs.json showed `next_run_at` still 12:50 + `last_status` error; the task note's "12:50 retry fired and self-recovered" claim was a false-positive. Gate unmet → no guard applied; monitor retained; discrepancy flagged in the note. This is the model behavior for re-eval-gated monitor tasks.

#### Constructive progress while blocked (work execution)

When a task is blocked on an external party (<operator> login, third-party OAuth, a human decision) but has an the agent-owned executable sub-component, **build that component now** rather than re-verifying the block. This converts a no-op check into durable, reusable tooling.

**Confirmed 2026-07-17 (finch:work, `relay-shutdown`):** The task was blocked on <operator>'s Relay login (actual export needed his credentials). Instead of another "still blocked" check, finch:work authored `verify.py` — a self-contained stdlib verifier that checks every `workflows/*.json` parses as JSON and every `tables/*.csv` has ≥1 data row, exiting non-zero on any failure. It was validated against fixtures (broken JSON / empty CSV / header-only CSV all FAIL; valid data PASSes) and wired into the runbook's step 8. The verifier is reusable the moment <operator> exports — no re-derivation needed.

**Procedure when a task is blocked but has an executable sub-component:**
1. Decompose the task into the blocked part (needs external actor) vs. the autonomous part (the agent can build now).
2. Build the autonomous part as a real, re-runnable artifact (script, fixture, template) — not a status note.
3. Validate it actually works (run it against fixtures / a dry target) before reporting done. A "created script" claim with no execution is the naming-without-fixing anti-pattern.
4. Wire it into the task's runbook/steps so the eventual unblock is one command, not re-analysis.
5. Report the block honestly — the verifier existing does NOT mean the underlying task is complete.

This is the inverse of the check-and-close anti-pattern: instead of burning tool calls re-confirming a stable block, invest them in tooling that makes the eventual execution one-shot.

### Task actionability filter (cron context)

When running as a cron job with no user present, **filter for autonomous actionability** before applying the priority selection. A task is autonomously actionable if it passes ALL of:

- [ ] **No external response required** — doesn't depend on someone else replying (e.g., "track response from X" is NOT actionable; "check if X responded" IS actionable as a monitoring check)
- [ ] **No business decision required** — doesn't require accepting/declining engagements, making commitments, or choosing between options with capital implications (e.g., "respond to consulting inquiry — accept or decline" is NOT actionable)
- [ ] **No authentication required** — doesn't need app login, OAuth, or credentials the agent doesn't have (e.g., "check One Medical app" is NOT actionable)
- [ ] **No user input required** — doesn't need the user to clarify, confirm, or choose

**When all pending tasks fail the actionability filter:** Pick the highest-priority task that CAN be executed (even if low-priority), execute it as a monitoring/validation check, and mark it done with a resolution note. Report that higher-priority tasks are blocked pending user input. This is preferable to returning "no tasks" — at minimum, validate system health signals.

**When a task becomes actionable later** (e.g., <contact-name> replies, <operator> provides input), finch:scan will create a new task or re-activate the existing one. The blocked status is not permanent — it's a reflection of current actionability, not importance.

#### Cascading dependency awareness (confirmed 2026-06-29)

When a critical infrastructure dependency fails, it blocks MANY tasks simultaneously — not just the task that names the failure. Before iterating through each pending task individually, check for cascading blockers:

1. **Identify infrastructure-level blockers first** — If any `critical` task names an infrastructure failure (OAuth revoked, disk full, gateway down, provider outage), assume ALL tasks depending on that infrastructure are blocked until it's resolved.
2. **Map the dependency graph mentally** — OAuth revocation blocks: email tasks, calendar tasks, Drive tasks, Takeout tasks, any task requiring Gmail API. Provider outages block: all LLM-dependent tasks. Disk full blocks: all write operations.
3. **Skip the blocked bulk** — Don't waste time evaluating each email task individually when OAuth is known-dead. Skip the entire dependency cluster in one decision.
4. **Find the first non-dependent task** — Look for tasks that don't depend on the broken infrastructure: cron health monitoring (uses `hermes cron list`, not Gmail), disk checks (`df -h`), system stats, web lookups, non-Google API calls.
5. **Execute the first actionable task** — Even if it's low-priority, a monitoring check that produces a useful signal (e.g., "provider errors recovered") is better than returning "no tasks."

**Confirmed 2026-06-29 (this session):** OAuth revoked (task_019) blocked 6+ email/Gmail tasks simultaneously (task_004, task_005, task_006, task_021, task_012, plus the OAuth task itself). Rather than evaluating each one, the correct move was to recognize the cascade, skip the entire cluster, and pick task_014 (cron provider error monitoring) which only needed `hermes cron list` — no Gmail dependency. **Total impact**: 8/140 cron jobs failed from one OAuth revocation event.

**Key insight:** The actionability filter's 4 conditions are per-task checks. Cascading dependency awareness is a pre-filter that eliminates entire clusters before per-task evaluation. It saves 5-10 tool calls per blocked cluster.

### Pipeline task resumption (ledger/state-based)

When an `in_progress` task involves a data pipeline that uses an idempotency ledger or state file (e.g., Chronicle ingest ledger, corpus processing), the original background process may have died while the pipeline was partially complete. Do NOT re-run from scratch — the ledger tracks completed windows.

**Resumption pattern:**
1. **Verify the process is dead** — `ps -p <PID>` or `ps aux | grep <script_name>`. Confirm the process is actually terminated, not still running silently.
2. **Check the ledger/state** — Read the pipeline's idempotency ledger (SQLite, JSONL, or similar) to determine which work units are already complete.
3. **Compare ledger to source data** — Identify which work units (months, files, batches) from the source data are NOT yet in the ledger.
4. **Run without limits** — The pipeline's ledger-based dedup will skip already-complete units automatically. Running `run_ingest.py --source X --file Y --apply` without `--limit` is safe — it processes only what's missing.
5. **Update task to done** — Once the ledger shows all units processed, mark the task `done` with a resolution noting the final completion timestamp.

**Confirmed 2026-06-29 (task_023):** Background PID 1663225 (Timeline ingest) was dead. Ledger showed 8/10 months complete (through 2026-04). Source data had 10 months (2025-09 through 2026-06). Ran `run_ingest.py --source timeline --file location-history.json --apply` without `--limit` — ledger correctly skipped the 8 completed months, processed 2026-05 and 2026-06 (2 documents written at 07:33Z). Task marked done.

**Key insight:** Pipeline tasks with idempotency ledgers are ALWAYS resumable. The `--limit N` parameter is only needed for initial testing. Once confirmed working, subsequent runs should omit `--limit` so the ledger handles dedup.

2. **Work** (`finch:work`, every 30 min) — Pick top pending task. Load governing skill via `skill_view`. Execute ONE task per run. Before selecting, check for duplicate task IDs and clean up if found (see `references/duplicate-task-detection.md`). Route findings to MEMORY.md, skill patches, or reference files.
2a. **Sessions scan — correct pattern**: When scanning recent sessions in finch:scan, call `session_search(limit=10, sort='newest')` WITHOUT `query` (FTS5 treats query as literal text, not a time filter — `query="last 24h"` matches sessions containing those words, not recent sessions). Manually check result timestamps. For finch:daily/weekly mining, follow the cron-skew filtering procedure in SKILL.md § "Session source filtering".
3. **Mine** (`finch:daily` / `finch:weekly`) — Process session JSONL files for signals: corrections, directives (Always/Never), course changes, breakthroughs, methodologies, stop signals. See `references/mining_methodology.md` for the full methodology.
4. **Route** — Direct each finding to the optimal storage tier: MEMORY.md (Tier 1: corrections, directives), skill SKILL.md/references/ (Tier 2: tool-usage, service gotchas), reference files (Tier 3: guides, paths, URLs), or Chronicle KG (Tier 4: entity facts). See `references/file-governance.md` for routing criteria and the tier model.
5. **Journal** — Every run emits Action Journal + DecisionRecord to `decisions.jsonl`.

### Failure-phase taxonomy (from arxiv:2508.13143)

When mining corrections and failures, categorize each by the task phase where the failure occurred. This taxonomy enables targeted skill patches instead of vague "be more careful" updates:

| Phase | Description | Example signal |
|-------|-------------|----------------|
| **Planning** | Wrong approach chosen, incorrect assumptions, missing prerequisites | "You should have checked X first" |
| **Execution** | Right plan but tool call/API/step failed, wrong parameters, timeout | "The command failed because..." |
| **Response** | Correct result but wrong format, verbosity, tone, or framing | "Too verbose" / "Wrong format" |

Route planning-phase corrections to skill preconditions/setup sections. Route execution-phase corrections to tool-usage/gotchas sections. Route response-phase corrections to output-formatting sections. This produces surgical patches instead of blanket directives.

### Elaborative interrogation (from Dunlosky et al. 2013)

When recording a correction or lesson, don't just capture WHAT was wrong — extract the underlying principle by asking "why" and "when":

- **Why was this wrong?** — What assumption was violated? What constraint was unknown?
- **When does this apply?** — What contexts trigger this pattern? What's the boundary condition?
- **What's the causal mechanism?** — Why does the correct approach work?

Format: `[CORRECTION] What: <what was wrong>. Why: <underlying principle>. When: <applicable context>`

This produces lessons that transfer across contexts, not just single-instance fixes.

### Signal triage before execution (WORK step)

A task on the list may aggregate multiple distinct failure modes under one title (e.g., "cron 429 errors" that actually mix transient rate limits, script timeouts, and path blocks). Before committing to a fix:

1. **Decompose the task** — List the distinct error signatures from logs/jobs.json. Group by root cause, not by symptom label.
2. **Classify each group** — Transient (will self-resolve), persistent (needs intervention), or already-fixed (mitigation in place).
3. **Handle each group appropriately** — Transient groups get "monitoring" with a 24h recheck. Persistent groups get fixes. Already-fixed groups get a note that the Tier 1 was already applied.
4. **Journal the decomposition** — Record the group counts so the next finch:scan can check recovery per group, not just per task.

Do NOT assume a task with N affected jobs has one root cause. The task title is a scan heuristic, not a diagnosis.

#### Already-fixed verification (resumed investigations)

When a task asks to "resume" or "complete" an interrupted investigation (e.g., "Session identified systemic issues but did not complete fixes"), do NOT assume the fixes are missing. The prior session may have produced findings that were already implemented, or the features may have existed under different names.

**Procedure:** Read the actual code at the relevant file:line locations. Map each claimed-missing feature to a function/class. Check for detection → classification → response → guard completeness. Run existing tests for those features. If all checks pass, mark the task `done` with specific file:line references and test counts as evidence. See `references/already-fixed-verification.md` for the full procedure and an example. For CI-failure tasks on a repo PR/branch, also consult `references/gh-ci-stale-run-verification.md` — a failing run is point-in-time and may already be superseded by a green run on the same head SHA.

#### Cron code-crash fix: the repair may already be uncommitted
When finch:scan flags a cron `last_status=error` with a Python traceback message (e.g. `'tuple' object has no attribute 'get'`), it's a genuine code defect, not transient. The committed (HEAD) version is what failed, BUT a working-tree modification may already repair it (`git status` shows ` M <file>`) — common when an interactive/sibling run patched the file but didn't commit, while the prior cron tick still ran broken HEAD. Procedure (full recipe + harness template in `references/cron-code-crash-fix.md`):
1. `git status --short` + `git diff HEAD -- <file>` — confirm whether the fix is already present uncommitted before assuming the crash is live.
2. Reproduce against the CURRENT working-tree code with a traceback harness (import `main()`, call inside `try/except: traceback.print_exc()`). OCAS scripts catch `Exception` at the top level and print only `FAIL: ...: <msg>` with NO line number, so `jobs.json` stderr alone won't name the broken line — the harness will.
3. If verified, COMMIT the fix (the fix file only; leave unrelated working-tree modifications uncommitted — they belong to other tasks). An uncommitted patch is fragile under cron: these repos carry many local commits ahead of upstream and get rebased/pulled, which discards or conflicts uncommitted changes, so the next scheduled tick would crash again. Committing makes it durable.
4. Clean verification side-effects: running `main()` appends a row to any append-only log it writes — dedupe to one deterministic row per key (e.g. per date; for mixed-type logs key on `(decision_type, date)`) so the data stays honest.

#### All-transient resolution (no fix needed)

When investigation reveals that ALL errors in a task are transient (provider errors with `consecutive_failures: 0`, missing-module errors where the package is actually installed, interpreter-shutdown errors), the correct action is:

1. **Verify** — Read `jobs.json`, check `last_status`, `last_error`, `consecutive_failures` for each affected job. Do NOT trust the task description alone.
2. **Mark task done** — Set `status: "done"`, add `resolved` timestamp, write `outcome` explaining what was checked and why no fix is needed.
3. **Downgrade priority if misclassified** — If a task was marked HIGH for interpreter-shutdown or provider errors, downgrade to LOW per the error taxonomy.
4. **Journal** — Record the resolution so finch:scan doesn't re-create the task on next scan.

**Confirmed 2026-06-28:** task_019 (provider errors + missing-module) — all jobs showed `consecutive_failures: 0` and `last_status: ok`. googleapiclient was already installed. No intervention required. task_014 (interpreter-shutdown) — also transient, downgraded HIGH→LOW.

MEMORY.md entries decay without reinforcement. During compaction:

1. **Reinforcement check**: For each existing entry, check if it was reinforced (re-encountered or re-applied) since last compaction. Entries reinforced within their expected half-life get a `§` durability marker.
2. **Concept classification**: Classify each entry by storage tier (see `references/forgetting_curve.md` § Storage Tier Model). Is this entry in the right tier?
3. **Tier routing**: Entries in the wrong tier get moved — tool-usage facts to skills (Tier 2), reference details to reference files (Tier 3), entity facts to Chronicle (Tier 4). Only evict if truly stale.
4. **Decay candidates**: Entries not reinforced in 3+ compaction cycles that cannot be routed to another tier are candidates for eviction.
5. **Priority for retention** (Tier 1 only): Directives (Always/Never) > Corrections with causal grounding > Bare corrections > Breakthroughs > Methodologies > Pointers to Tier 2/3 knowledge
6. **Consolidation**: Merge entries that share the same underlying principle into a single entry with multiple contexts. Within-tier only.

See `references/forgetting_curve.md` for the full compaction algorithm including the tier routing procedure.

See `references/scan-work-architecture.md` for signal source details and governance rules.

## Manual run & verification (when the user says "run finch")

"Run finch" means verify ALL deployed finch cron jobs are healthy and (optionally) force a run. The deployed job set (2026-07-07) is **FIVE jobs**, not the four in the design doc:

- **`finch`** — profile-root MEMORY.md compaction (runs `memory_guard.py` on the DEFAULT profile's MEMORY.md — NOT the indigo profile's; guard the `--file` override or it compacts the wrong memory).
- **`finch:floor`** — `no_agent` script safety floor (memory guard). Normally `enabled: false` but self-triggers; do NOT treat its disabled state as broken.
- **`finch:scan`** — every 2h, pure LLM.
- **`ocas-finch:daily`** — daily 6am PT, pure LLM.
- **`ocas-finch:weekly`** — Sunday 8am PT, pure LLM.

(NOTE: the design doc lists `finch:work` every 30min — that job was NOT present in deployment on 2026-07-07. Work execution is covered by the interactive `finch.work` command / `finch:scan`-driven task list, not a separate cron. Verify with `cronjob list` before assuming job names, since they drift.)

### Forcing an immediate run
`cronjob action='run'` does NOT force a scheduled **LLM** job to execute — it only bumps `next_run_at` to the next NATURAL tick (the job fires on its normal schedule, not immediately). To force execution NOW: **PAUSE the job first (`action='pause'`), then `run` (`action='run'`)** — the paused state triggers forced execution. `no_agent`/script jobs (e.g. `finch`, `finch:floor`) run on a plain `run` without pausing. After a forced run succeeds, the job returns to `state: scheduled` automatically.

**Verification gate:** A queued immediate run is not a completed run. After every manual trigger, re-read `jobs.json`/`cronjob list` and verify `last_run_at` advanced to the current run window and `last_status` is current. If `next_run_at` is in the past but `last_run_at` did not advance after a tick, report the job as **queued/not yet executed**, not completed. For `finch.scan`, `finch.work`, `daily`, and `weekly`, run deterministic sub-functions directly where available (for example `self_update.py`, `memory_guard.py`, task-list inspection, journal write) and distinguish those completed direct actions from still-queued LLM cron jobs.

### Mass 401 across finch (and other) jobs
If multiple finch jobs error with `401`, first classify WHICH 401 it is before acting:

- **MCP-auth 401** (dead `[mcp_servers]` token): the cause is a **stale `[mcp_servers]` block in the profile `.env`** (`~/.hermes/profiles/<p>/.env`) shipping an invalid/expired token (e.g. a dead Discord token) that breaks ALL MCP calls. Fix: remove the `[mcp_servers]` section; the client falls back to valid config and MCP works.
- **Provider-auth 401** (LLM provider token): the run output shows `RuntimeError: Error code: 401` with `token_expired` ("Provided authentication token is expired") or `"Your API key is invalid, blocked or out of funds"` from `portal.nousresearch.com`. This is NOT the `[mcp_servers]` block. Confirmed 2026-07-12: finch jobs 401'd with Nous `token_expired`; `grep mcp_servers` on the indigo `.env` returned nothing; the gateway was holding a stale provider credential. **Fix: restart the gateway** (kill the `--profile indigo gateway run` process and let it respawn, or `hermes gateway run`) so it reloads the current valid provider token. After restart, post-restart runs (`finch:scan`, `finch:memory-guard-floor`) returned `ok`.

Diagnostic steps: (1) Read the actual run output / `jobs.json` `last_error` — `cronjob list` may display `last_error: None` even when jobs.json holds the 401, so don't trust the list's None. (2) `grep -n "mcp_servers" ~/.hermes/profiles/<p>/.env` — if absent, it's provider-auth, not MCP-auth. (3) If interactive sessions on the same `provider`/`model` work but cron 401s, the scheduler is holding a stale token → restart the gateway.

See `cron-job-repair` for the model-routing 401 vs MCP-auth 401 distinction.

### Autonomy — take the action without being prompted
When a finch job (or any cron job) is failing and the fix is clear, DO NOT ask "continue?" or wait for the user to "say the word." Apply the fix, run all affected jobs, then report results in one message. The user explicitly requires the agent to take the needed action without prompting (stated 2026-07-07: "I shouldn't have to 'say the word' you should just take action that needs to be taken").

## Commands

- `finch.run` — Full daily pipeline
- `finch.mine` — Mine sessions for signals only
- `finch.compact` — Compact MEMORY.md only
- `finch.route` — Route mined findings
- `finch.dry-run` — Full pipeline without applying changes
- `finch.status` — Show recent stats
- `finch.scan` — Run scan manually
- `finch.work` — Run work manually

## Scheduled tasks

| Job | Frequency | Behavior |
|-----|-----------|----------|
| **finch:scan** | Every 2h | Scan 7 sources → maintain task list |
| **finch:work** | Every 30 min | Pick top item → execute. ONE task per run. |
| **finch:daily** | Daily 6am PT | Mine 24h → Compact → Route → Auto-apply low-risk |
| **finch:weekly** | Sunday 8am PT | Mine 7d → Compact → Route → Full plan |

## Recovery Behavior

This section defines error handling and recovery procedures for all finch jobs.

- **Evidence**: Every run writes to `evidence.jsonl` (including no-op runs with `not_activity_reason`).
- **Gap detection**: On every wake, checks evidence log. If gap exceeds expected cadence (2h for scan, 30min for work), logs `gap_detected` and runs compact remedial pass.
- **Degraded mode**: When behavioral signals unavailable from Chronicle, continues with available inputs. When session store unavailable, logs `degraded: session_store` and skips mining.
- **Log compaction**: Evidence/decision logs older than 30 days (no-op) or 90 days (error/gap) compacted. Last 7 days retained.

## OKRs

See `references/okrs.md` for targets (schedule adherence, data integrity).

|-----|--------|--------|
| `schedule_adherence` | ≥ 0.98 | 30 runs |
| `data_integrity` | 1.00 | 30 runs |

## Anti-patterns

See `references/anti-patterns.md` for the full list of 10 anti-patterns including declaration of victory and code fence pitfalls.

## Active review principle

See `references/active-review.md` for the full principle.

## Skill Library Maintenance

After every session, review the conversation for signals and update the skill library. See `references/skill-library-maintenance.md` for the full procedure including signals that warrant action, preference order for updates, and what NOT to capture.

**Skill integration hygiene (confirmed 2026-07-14):** When adding external/upstream skills to the local library, prefer integrating relevant LEARNINGS into the closest existing skill rather than installing a new conflicting skill. For upstream skill repos <operator> shares: (1) determine if any capability overlaps an existing skill; (2) if yes, merge the valuable parts into that skill (including code-review patterns <operator> may say were "skipped"); (3) only install a new skill if it has no close match and won't conflict. <operator>: "Would any of these skills be useful in KODA skill library, if so integrate them into the closest match don't install new skills that may conflict" and "You should integrate what makes sense in code review as well. The ones you skipped."

**Active-review mandate:** A review pass that finds no signal is a missed learning opportunity, not a neutral outcome. Most finch passes surface at least one skill update — even a small pitfall or support-file note. Prefer patching the skill that was IN PLAY this run over creating a new narrow skill.

## Gotchas

See `references/pitfalls.md` for the full consolidated pitfalls list.

## Gotchas (verbose bodies in `references/operational-gotchas.md`)

- `memory` tool may be unavailable in cron — fall back to direct file edit at the canonical profile memory path; re-read before write on sibling-warning
- MEMORY.md must contain only Tier 1 knowledge — no pointers to routed content; under 500 chars when well-compacted
- Directive consolidation — merge two directives sharing a principle, keep specific phrasing, list both dates
- FTS5 minimum token length (3-4 chars) drops short corrections (`No`, `Don't`) — mine without `query=`, use `role_filter=user`, scan visually
- Session source filtering — cron sessions drown interactive ones; under indigo cron, `session_search` reads the DEFAULT profile store, so query `~/.hermes/profiles/<profile>/state.db` directly. Identify interactive first (source NOT LIKE 'cron%'), pull user messages via direct `state.db` SQL, drop `[CONTEXT COMPACTION — REFERENCE ONLY]` headers (false positives), parse JSON-array `content`. NOTE: interactive user messages carry `observed=0`, NOT `observed=1` — do NOT filter `observed=1` or you drop every real user message. Full recipe: `references/session-mining-state-db-recipe.md`. Fallback to keyword queries before declaring "no interactive sessions".
- Skill usage analytics — cron sessions ARE the signal for state.db mining (opposite of behavioral mining); use JOIN + busy_timeout + Python JSON parse
- HERMES_HOME path resolution — three-branch logic, never hardcode `~/.hermes/MEMORY.md`; old two-branch double-nests. Under indigo cron, a bare `read_file('~/.hermes/MEMORY.md')` resolves to the DEFAULT profile memory (different path AND content) — always target `~/.hermes/profiles/<profile>/memories/MEMORY.md` explicitly. After writing MEMORY.md, RE-READ it and assert every intended block persisted (grep a unique substring per block) — a prior daily run recorded two Tier-1 blocks as 'routed to MEMORY.md' that were ABSENT from the live file next run (silent consolidation loss); recover any missing block rather than trusting the journal's `applied` self-report, which is not proof of persistence. See `references/session-mining-state-db-recipe.md` § MEMORY.md path trap.
- Two evals.json files (root + evals/) must stay in sync; root is canonical

## Support File Map

Full file-to-purpose map (when to read each reference, script, and data file) → `references/finch-support-map.md`.
## Scripts

Full detail (eviction priority, self_update wrapper contract, memory_state subcommands) in `references/operational-gotchas.md` § Scripts:

- `memory_guard.py` — deterministic MEMORY.md safety floor; mandatory post-guard Step 7.5 verification (Methodologies must outrank Course Changes in eviction)
- `self_update.py` / `self_update.sh` — real Python wrapper resolving skill dir from `Path(__file__).resolve().parents[1]`; `self_update.sh` is the GitHub fetch/install path
- `memory_state.py` — persisted reinforcement-state store (Ebbinghaus forgetting curve); `reinforce` / `check` / `route` / `decay-report` subcommands
- `gws_direct_puller.py` — FULL-CONTENT Google Workspace puller (Gmail metadata + optional `--full-text` body, Calendar events for a horizon, Drive most-recently-modified). Run via `<hermes-venv>/bin/python` (MCP venv has googleapiclient). Use when MCP absent and you must CLASSIFY actionable email/calendar/drive signals, not just confirm reachability. CRITICAL: use googleapiclient, NOT raw requests — the host egress filter 404s raw Calendar/Drive calls. Pair with `gws-direct-fallback.py` (count-probe). Full pattern in `references/gws-direct-fallback-pattern.md`.
- `verify_sepagree_signature.py` — reusable EMAIL-SEPAGREE (<employer> Separation Agreement) Docusign "unsigned" re-verifier for finch:work passes. Run via `terminal` python3 (NOT execute_code); counts Docusign "Completed"/signed notices + cross-checks the negotiation thread, prints VERDICT. Proven logic extracted 2026-07-16 from a working live Gmail API pass. See `references/email-thread-verification.md` § Docusign.
  **Recovery note (2026-07-16 finch:work pass):** the EMAIL-SEPAGREE task-list `meta`/`signal` referenced `<fs-root>/sepagree_verify.py`. That path is NO LONGER reliably absent — as of the 10th re-verify pass, STALE DUPLICATE copies now exist at `<fs-root>/sepagree_verify.py` AND `~/.hermes/profiles/<profile>/commons/data/ocas-finch/sepagree_verify.py`. Do NOT run either — they may diverge from the maintained script. The canonical, maintained verifier is `skills/ocas-finch/scripts/verify_sepagree_signature.py` (reconstruct from it or `references/email-thread-verification.md` § Docusign if it ever goes missing). The Docusign recipe (1 begin-signing + 0 Completed = proof of non-signature) is the load-bearing check; re-running it is the correct finch:work action for the P1, not re-deriving the script each time.
  **Locator pattern:** to find the verifier (or any skill script) reliably in the indigo cron profile, use `terminal find /root -iname 'verify_sepagree*' 2>/dev/null` rather than `search_files`, which returned transient `DaemonThreadPoolExecutor` framework errors on 3 consecutive attempts this run. `find` is the dependable fallback when `search_files` flakes — and the same `DaemonThreadPoolExecutor` error also hits `read_file` in bursts; for those, fall back to `terminal` (`python3` / `stat` / `cat` via `read_file` substitute). Full recovery procedure in `references/concurrent-write-recovery.md`.
  **NEW (2026-07-23):** pass `--since <RFC3339>` to run the BLOCK-CLEARANCE PROBE — enumerates all Docusign/Kim envelopes in the last 5d and reports any with `internalDate` AFTER that ts (a potential corrected/Section-3-15 envelope). If none, the external-party blocker is unchanged; the probe is the canonical replacement for the inline Gmail re-derivation historically done on the `docusign-separation-agreement` task. See `references/email-thread-verification.md` § Docusign "corrected envelope since last review" probe.
  **PROHIBITION (reinforced 2026-07-23T13:34Z finch:work relapse):** do NOT hand-roll a new `verify-docusign-*.py` into `commons/data/ocas-finch/`. A 2026-07-23T13:34Z pass did exactly that (`commons/data/ocas-finch/verify-docusign-0723.py`) — it duplicated the canonical script's `--since` probe and created a stale-drift risk (the SAME class as the `sepagree_verify.py` duplicates the recovery note already warns about; `find` later returns multiple divergent copies). That redundant file SHOULD BE DELETED. If a probe case is missing from `verify_sepagree_signature.py`, EXTEND the canonical script (add the case + wire `--since`) — never author a sibling. The canonical script is the single source of truth for EMAIL-SEPAGREE/Docusign re-verify.

## Self-update

`finch.update` pulls the latest from GitHub. Runs silently unless version changed or error.

## Platform notes

Finch is designed for Hermes but degrades gracefully on other harnesses. Minimum viable platform: any harness with `write_file`, `read_file`, and `terminal` tools.