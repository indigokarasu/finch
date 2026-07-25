# `patch` Tool Behavior on JSON Files (Confirmed 2026-06-29, corrected 2026-07-23)

## Escape-Drift Error

**Symptom:** `patch(mode='replace', ...)` fails with:
```
"success": false,
"error": "Escape-drift detected: old_string and new_string contain the literal sequence '\\\"' but the matched region of the file does not."
```

**Cause:** The tool-parameter serialization layer escapes JSON quotes as `\"` in the parameters, but the file on disk contains plain `"`. The patch tool detects this mismatch and refuses to apply.

**Fix:**
1. Re-read the file with `read_file` (which shows actual file bytes, unescaped)
2. Copy the exact text from `read_file` output
3. Use plain `"` (not `\"`) in both `old_string` and `new_string`

**Why it happens:** When you compose JSON patches from memory (without re-reading), you tend to write `\"` because that's how quotes appear in JSON literals. But `patch` expects the literal bytes from the file, which use plain `"`.

## Non-Blocking Pagination Warning (REFUTED IN PART — see below)

**Symptom:** `patch` succeeds but reports:
```json
"_warning": "/path/to/file.json was last read with offset/limit pagination (partial view). Re-read the whole file before overwriting it."
```

**Documented historical behavior (2026-06-29):** Treated as a **non-blocking warning** — the patch applied successfully.

**CORRECTION (2026-07-23 finch:work):** This is NOT reliably non-blocking. After a paginated `read_file` (offset/limit), repeated `patch` attempts on the SAME long-line JSON value can instead **refuse** with `Could not find a match` AND trigger a **same-tool-failure loop guard** (`[Tool loop warning: same_tool_failure_warning; count=3; patch has failed 3 times this turn...]`) that blocks further `patch` calls on the file for the rest of the turn. The refusal is on a string that exists in the file — the paginated partial view desyncs the matcher. So the pagination warning is a REAL hazard, not cosmetic.

**Rule:** If you previously read the JSON with `read_file` using `offset`/`limit` (pagination), do NOT attempt `patch` on it. Either (a) `read_file` the file fully first (no offset/limit), or (b) skip `patch` entirely and do the edit in ONE `terminal python3` script (`json.load` → mutate → `json.dump`, then `json.load` to validate). For any task-list.json / long-line JSON edit, the script path is the dependable default — see SKILL.md "Long single-line JSON string values defeat the `patch` fuzzy matcher" and "Parallel `patch` edits to the same JSON file corrupt it."

## Recommended Pattern for JSON Updates in Cron

For small, targeted updates (single field changes, status updates):
1. `read_file` the JSON file **in full** (no offset/limit)
2. `patch(mode='replace', old_string='<exact text from read_file>', new_string='<new text>')`
3. Use plain `"` from the `read_file` output

For multi-field updates or large JSON restructuring, OR if the file was read with pagination, OR if `patch` refuses on a long single-line value:
1. Do ALL mutations in ONE `terminal python3` script: `json.load(open(path))` → mutate the in-memory dict → `json.dump(open(path,'w'))` → `json.load` to validate.
2. `execute_code` is BLOCKED in the indigo cron profile — use `terminal` python3, never execute_code for JSON edits.
3. Validate-after-edit with `terminal python3 -c "import json; json.load(open('<path>')); print('VALID')"` — `read_file`'s view of a JSON file is NOT validation (it can display trailing-comma corruption as valid).

## Example (task-<id> resolution, 2026-06-29)

```json
// First attempt FAILED (escape-drift):
patch(mode='replace',
  old_string="      \"id\": \"task-<id>\",\n      \"source\": \"kanban\",\n      \"signal\": \"P4 Timeline...\", ...",
  new_string="      \"id\": \"task-<id>\",\n      ...new fields...")

// Second attempt SUCCEEDED (plain quotes from read_file):
patch(mode='replace',
  old_string=      "id": "task-<id>",
      "source": "kanban",
      "signal": "P4 Timeline live write (t_b8179ffa) is actively running...",
      "action": "Monitor P4 background process for completion...",
  new_string=      "id": "task-<id>",
      "source": "kanban",
      "signal": "P4 Timeline live write COMPLETE...",
      "action": "Done.",
      ...)
```

The second attempt succeeded because the text was copied verbatim from `read_file` output (plain `"`), not composed from memory with `\"`.

## Lesson from 2026-07-23 finch:work (docusign task-list update)

Attempted to `patch` the `notes` field of a task (long single-line JSON string) after a paginated `read_file`. Got `Could not find a match` x3 → loop guard fired → all subsequent `patch` calls on task-list.json blocked that turn. The string was present and correct. Recovery: performed the edit via a single `terminal python3` script (`raw.replace(anchor, append)` with a UNIQUE ASCII anchor, `json.loads` to validate, `open().write()`). **Anchor on a unique short ASCII substring of the long value, never the whole line** (long lines defeat the fuzzy matcher and can also trigger the prefix-match silent-corruption trap — see SKILL.md "patch PREFIX match = SILENT corruption"). When `patch` loops on a JSON file, STOP retrying and switch to the script fallback immediately.
