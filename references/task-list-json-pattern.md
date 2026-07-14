# Task List JSON Read/Write Pattern (finch:scan cron)

## File location
`/root/.hermes/commons/data/ocas-finch/task-list.json`

## Actual schema (as of 2026-06-30)

The task-list.json uses a richer schema than the minimal "scan signal" format. Tasks can include detailed metadata for action packets, system health snapshots, and travel prep.

```json
{
  "last_updated": "ISO timestamp",
  "scan_number": 16,
  "scan_time": "ISO timestamp (UTC)",
  "scan_time_local": "ISO timestamp (local)",
  "critical_finding": "One-line summary of the most urgent finding",
  "tasks": [
    {
      "id": "task_NNN",
      "title": "Human-readable task title",
      "priority": 1-5 (1=highest),
      "status": "active|completed",
      "created": "YYYY-MM-DD",
      "last_seen": "YYYY-MM-DD",
      "description": "Full context including affected items, root cause, fix paths",
      "affected_jobs_scripts": ["list", "of", "script", "job", "names"],
      "affected_jobs_llm": ["list", "of", "LLM", "job", "names"],
      "root_cause": "Underlying cause",
      "fix_paths": ["numbered", "list", "of", "possible", "fixes"],
      "tier_1_finding": "One-line impact assessment",
      "completed_at": "ISO timestamp (if completed)",
      "resolution": "How it was resolved (if completed)"
    }
  ],
  "system_health": {
    "disk_pct": 77,
    "disk_free_gb": 23,
    "tmp_mb": 43,
    "gateway_rss_mb": 1264,
    "dashboard_rss_mb": "1228 (PID 1263780)",
    "total_cron_jobs": 140,
    "error_jobs": 5,
    "jobs_down_since": "ISO timestamp",
    "jobs_down_hours": 7,
    "python_interpreter": "path info",
    "venv_status": "status string"
  },
  "previous_tasks_still_pending": [
    {
      "id": "task_NNN",
      "note": "Why this is still pending"
    }
  ],
  "actions_blocked": "None or description"
}
```

**Key field notes:**
- `priority`: 1=critical, 2=high, 3=medium, 4=low, 5=info (different from original `high/medium/low`)
- `status`: `active` (not `pending`), `completed` (not `done`)
- `system_health` is included in every scan for trend tracking
- `previous_tasks_still_pending` carries forward items that were deprioritized but not resolved

## Read pattern in cron (execute_code blocked)
```python
import json
from hermes_tools import terminal
result = terminal("python3 -c \"import json; print(json.dumps(json.load(open('/root/.hermes/commons/data/ocas-finch/task-list.json')),indent=2))\"")
task_list = json.loads(result["output"])
```

## Write pattern in cron
Use Python serialization (`json.load` → mutate dict → `json.dump`) rather than hand-composing JSON in context.

Preferred options:
- `execute_code` with ordinary Python file I/O when available in the cron profile.
- `terminal` with a `python3 << 'PYEOF'` heredoc as the reliable fallback, especially after repeated `execute_code` mistakes or when you need direct shell-side validation.
- `write_file` only for small, fully-visible JSON blobs.

Terminal heredoc pattern (confirmed 2026-06-27):
```bash
python3 << 'PYEOF'
import json, os
from datetime import datetime

task_path = os.path.expanduser("~/.hermes/commons/data/ocas-finch/task-list.json")
with open(task_path, 'r') as f:
    task_list = json.load(f)

# Update metadata
task_list["last_scan"] = datetime.utcnow().isoformat() + "Z"
task_list["scan_count"] = task_list.get("scan_count", 0) + 1

# Modify tasks as needed...

with open(task_path, 'w') as f:
    json.dump(task_list, f, indent=2)
print(f"Scan #{task_list['scan_count']} written")
PYEOF
```

**Note:** Older runs treated `execute_code` as blocked in cron, but this is no longer universally true. Do not encode a blanket refusal. If `execute_code` fails repeatedly because of script mistakes or profile quirks, switch to the terminal Python-heredoc pattern and validate with `json.load`.

## Reopening or revalidating previously resolved tasks

When finch:scan reactivates a task that was previously `done`/`completed`/resolved, clear contradictory completion fields during the upsert. A task must not be both `status: "pending"` and carry `resolved`, `done_at`, `completed_at`, `resolution`, or `outcome` from an earlier closure.

**Pattern:**
```python
if new_status in {"pending", "active", "in_progress", "watching"}:
    for k in ["resolved", "done_at", "completed_at", "resolution", "outcome"]:
        task.pop(k, None)
```

**Why:** On 2026-07-09, scan correctly re-opened disk pressure and Braun redesign tasks but initially left stale `resolved` fields in place. The JSON was syntactically valid but semantically contradictory, which can mislead finch:work selection and user reports.

**Bash heredoc anti-pattern (confirmed 2026-06-28)**: Do NOT use `cat > file << 'EOF' ... EOF` to write JSON files. Bash heredocs:
1. Fail silently on JSON syntax errors (no validation at write time)
2. Break on single quotes inside JSON values even with `'EOF'` quoting
3. Require exact delimiter matching (missing trailing delimiter = file not written)

**Always use `python3 << 'PYEOF'` with `json.dump()`**, or `write_file` directly. Both validate syntax before the call returns. See `references/pitfalls.md` § "Bash heredocs break on JSON".

**`patch` escape-drift on JSON (confirmed 2026-06-27)**: The `patch` tool can fail with "Escape-drift detected" when `old_string`/`new_string` contain `\"` (escaped quotes from tool-parameter serialization) but the file on disk has plain `"`. If you must use `patch` on task-list.json, re-read the file first and use plain `"` in your parameters. However, the recommended approach remains the Python heredoc above — it avoids the issue entirely. See `references/patch-json-tool-behavior.md` for the full escape-drift + pagination warning pattern.

## Concurrent-Write Hazard (confirmed 2026-06-29)

When multiple finch:scan cron jobs overlap (or a sibling subagent writes to task-list.json concurrently), `write_file` will emit a warning: *"sibling subagent '<id>' modified this file... Read the file before writing."* If you ignore this warning and write anyway, you will **overwrite the sibling's changes** and potentially **corrupt the JSON** (truncated values, dropped delimiters).

**Symptoms of concurrent-write corruption:**
- JSON parse error on next read: `Expecting ',' delimiter (line N, column M)`
- Truncated values like `"2026-0604:19:100resolved"` (missing closing quote + comma)
- Missing tasks that were added by the sibling

**Recovery pattern:**
1. **Read the file first** — `read_file` to see current state
2. **Identify the corruption** — look for truncated JSON, missing quotes, merged fields
3. **Use `patch` for surgical repair** — `patch` with `mode='replace'` is the correct tool for fixing a single corrupted field without risking the rest of the file. It validates the match before applying.
4. **Validate** — `python3 -c "import json; json.load(open('<path>')); print('VALID')"`

**Example (2026-06-29):** A sibling subagent wrote `"created": "2026-0604:19:100resolved": "Daily limit reset..."` (missing closing quote and comma). Fixed with:
```
patch(mode='replace', oldcreated": "2026-0604:19:100resolved": "Daily limit reset at Jun 28 00:00 UTC"',
      new_string='      "created": "2026-06-27T04:19:00Z",\n      "resolved": "Daily limit reset at Jun 28 00:00 UTC"')
```

**Prevention:** When `write_file` warns about sibling modification, do NOT proceed with the write. Read the file, merge your changes into the current state, then write the merged result.

## Self-Inflicted JSON Corruption (confirmed 2026-06-29)

When the assistant generates a large JSON blob in reasoning context and a string value gets truncated mid-content (e.g., context-length limits cutting a value), `write_file` will write the corrupt data. The lint check (`python3 -json` validation) fires AFTER the write, leaving a partially-written corrupt file on disk.

**Symptoms:**
- `write_file` reports `"lint": {"status": "error", "output": "JSONDecodeError: Expecting ',' delimiter (line N, column M)"}`
- The file on disk contains truncated values like `"signal": "Dinner @ Kokkari — Jun  "action": "Event occurred Jun 26"` (missing closing quote + comma between fields)
- The linter catches it, but the file is already written — the write is NOT rolled back on lint failure

**Root cause:** Context-length or token generation limits truncating string values in JSON content the assistant is composing. Most likely with large files (>50 lines) and long string values.

**Recovery pattern:**
1. **Use `patch`** — the same recovery tool as for concurrent-write corruption. Identify the truncated location and replace the corrupt segment.
2. **Validate** — `python3 -c "import json; json.load(open('<path>')); print('VALID')"`
3. **Iterate if needed** — there may be multiple corruption points in one write

**Prevention for large JSON writes:**
- For task-list.json (8+ tasks, 200+ lines), prefer the `terminal` heredoc with `json.dump()` pattern shown in the "Write pattern in cron" section above. `json.dump()` serializes from a Python dict, so truncation in reasoning context cannot produce invalid JSON — the dict is either complete (valid JSON) or incomplete (Python error before any write).
- Reserve `write_file` for smaller JSON blobs (<50 lines) where the full content can be verified in context before writing.
- When you MUST use `write_file` for large JSON, validate the content string mentally before sending: count `{` vs `}` and `"` parity.

## Action Journal location
`/root/.hermes/commons/journals/ocas-finch/YYYY-MM-DD/scan-HHMM.json`

**IMPORTANT**: Use the absolute path above. Do NOT use `os.path.expanduser("~/.hermes/commons/...")` — in cron context, `~` resolves to `/root/.hermes/profiles/indigo/home`, producing a triple-nested non-existent path. Also copy to `/root/.hermes/profiles/indigo/commons/journals/ocas-finch/YYYY-MM-DD/` for profile-scoped scans.

## Sorting tasks
When sorting tasks by `due` date in the write script, tasks with `due: null` cause `TypeError` in Python. Always provide a default: `key=lambda t: (0 if t['status']=='pending' else 1, priority_order.get(t.get("priority","info"), 9), t.get("due") or "9999")`.
