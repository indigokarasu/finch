# `patch` Tool Behavior on JSON Files (Confirmed 2026-06-29)

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

## Non-Blocking Pagination Warning

**Symptom:** `patch` succeeds but reports:
```json
"_warning": "/path/to/file.json was last read with offset/limit pagination (partial view). Re-read the whole file before overwriting it."
```

**Behavior:** This is a **non-blocking warning**. The patch still applies successfully. It's informing you that the file was previously read with pagination (offset/limit), so you may not have seen the full file when composing the patch.

**When it's safe to ignore:** When you're doing a targeted `mode='replace'` on a unique string that you copied directly from `read_file` output, the patch is correct regardless of whether the file was read with pagination.

**When to re-read:** When doing structural changes (reordering fields, adding new keys between existing ones) or when the patch involves fields that may have been outside the paginated view.

## Recommended Pattern for JSON Updates in Cron

For small, targeted updates (single field changes, status updates):
1. `read_file` the JSON file
2. `patch(mode='replace', old_string='<exact text from read_file>', new_string='<new text>')`
3. Use plain `"` from the `read_file` output

For multi-field updates or large JSON restructuring:
1. `read_file` the JSON file
2. Parse and modify in reasoning context
3. `write_file` the complete updated JSON
4. Validate: `terminal("python3 -c \"import json; json.load(open('<path>')); print('VALID')\"")`

## Example (task_023 resolution, 2026-06-29)

```json
// First attempt FAILED (escape-drift):
patch(mode='replace',
  old_string="      \"id\": \"task_023\",\n      \"source\": \"kanban\",\n      \"signal\": \"P4 Timeline...\", ...",
  new_string="      \"id\": \"task_023\",\n      ...new fields...")

// Second attempt SUCCEEDED (plain quotes from read_file):
patch(mode='replace',
  old_string=      "id": "task_023",
      "source": "kanban",
      "signal": "P4 Timeline live write (t_b8179ffa) is actively running...",
      "action": "Monitor P4 background process for completion...",
  new_string=      "id": "task_023",
      "source": "kanban",
      "signal": "P4 Timeline live write COMPLETE...",
      "action": "Done.",
      ...
)
```

The second attempt succeeded because the text was copied verbatim from `read_file` output (plain `"`), not composed from memory with `\"`.
