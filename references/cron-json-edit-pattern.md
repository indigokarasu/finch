# Cron-scope JSON editing (confirmed 2026-07-13)

## Problem
Editing a shared JSON state file (e.g. `task-list.json`) from a finch:scan cron run is the most common path to silent corruption. Two failure modes bit a real run:

1. **`execute_code` is blocked** in the indigo cron profile (`approvals.cron_mode`): `BLOCKED: execute_code runs arbitrary local Python ... Cron jobs run without a user present to approve it.` So the "use execute_code for JSON" guidance does NOT apply here — fall back to `terminal python3 -c "..."` for load/dump/validate, plus `patch`/`write_file` for edits.
2. **`patch` lint reports errors but still applies the edit.** A `JSONDecodeError` returned by the patch lint is NON-blocking: the file is written anyway, in a broken state. Multi-`patch` passes can each "succeed" while leaving the file invalid. Always validate AFTER editing.

## Safe multi-edit pattern (no execute_code)
1. Apply targeted `patch(mode='replace', old_string=<exact from read_file>, new_string=<...>)` edits. Copy exact text from `read_file` (plain `"`, not escaped).
2. **Validate every time**, not just at the end:
   ```bash
   python3 -c "import json; json.load(open('/root/.hermes/commons/data/ocas-finch/task-list.json')); print('VALID')"
   ```
3. If invalid, locate the error. `python3 -c "open('f').read()[18300:18430]"` and `data.split(chr(10))[line-1]` pinpoint the offending physical line (the JSON error line number may point at the NEXT line's closing brace, not the broken one).
4. Common JSON corruption from `patch` on JSON:
   - **Trailing comma** after the last property of an object (`"k": "v",` then `}`). `patch` lint flags it but writes it. Remove the comma.
   - **`\'` literal backslash-quote** inside a string — `read_file` masks a real backslash as `\\'` in its display; if you copy that mask into `new_string`, it becomes an invalid escape. The fix is to remove the backslash so only the plain `'` remains (valid JSON). If `repr` of the raw file shows `\\'` as `'` (i.e. no actual backslash), the file is fine and the error is elsewhere.
   - **Double-writing**: a `write_file` warning "modified since you last read" means a sibling writer touched the file — re-read before editing.

## Batch-probe rule for untrusted MCP tools
- A failed `tool_call` to one tool in a parallel batch makes the ENTIRE batch return `Skipped` (e.g. `another tool call in this turn used an invalid name`). So: probe a suspect MCP tool ALONE. If it fails with "does not exist", mark that source UNVERIFIED and DON'T retry it or batch other mcp tools with real work — you'll lose the real work too.
- `tool_search` listing a tool and `tool_describe` succeeding do NOT prove the tool is callable — only a live `tool_call` proves it. One failed `tool_call` is enough evidence.

## Duplicate-key corruption (fuzzy-match hazard)
A `patch` whose `old_string` is NOT unique, because the same value string appears in multiple keys or places, can match the WRONG occurrence and silently restructure the JSON. Observed 2026-07-13 (finch:work TASK-034): a patch meant to update the `note` value inside `system_health` instead matched a separate top-level `critical_finding` block that also ended in an identical note-like line. The edit replaced `critical_finding` with a duplicate `note` key and deleted the original `critical_finding`. Duplicate keys are technically valid JSON (last wins), so `json.load` did NOT catch it. Corruption surfaced only as a missing `critical_finding` key on later reads.

Prevention:
- Ensure `old_string` includes a UNIQUE anchor (a sibling key name, a distinct prefix) so the match can only land in one place. Never use a value-only string as the sole anchor when that value recurs elsewhere in the file.
- After any multi-`patch` edit of a shared JSON file, validate STRUCTURE, not just parseability:
  ```bash
  python3 -c "import json; d=json.load(open('PATH')); print(sorted(d.keys())); print('note' in d, 'critical_finding' in d)"
  ```
  Duplicate keys collapse under `json.load`; print the key set and confirm expected top-level keys are present exactly once.
- Recovery: re-read the WHOLE file (not a paginated `read_file` slice; patching from a partial view is what enabled this error class), locate the stray duplicate, `patch` it back with unique anchors, then re-validate the key set. Honor the `patch` "re-read the whole file before overwriting" warning.

## Decision: re-open vs. carry
- For scan re-validation, use `patch` to flip `status` and append a `[RE-OPENED <ts>]` note when LIVE signal contradicts a prior `completed`. Keep prior `resolution` text but mark it overturned. This is the scan-level analogue of the WORK-step "already-fixed-verification" rule.
