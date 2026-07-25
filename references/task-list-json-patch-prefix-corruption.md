# `patch` Prefix-Match Silent Corruption on Long One-Line JSON Values

## Symptom

You `patch` a long single-line JSON string value (e.g. `cycle_note` in task-list.json) with a *partial* `old_string`. The tool returns `"success": true` (and even a `_warning` about pagination — which is **non-blocking**). The file looks one line and "current," but `json.load()` now fails:

```
JSONDecodeError: Expecting ',' delimiter (line 5, column N)
JSONDecodeError: Expecting property name enclosed in double quotes (line 5, column N)
```

What happened: `patch` matched your `old_string` as a **prefix** of the long line and replaced just that prefix. The unmatched **tail** of the old line is left *dangling in place* — still sitting in the file, now orphaned outside any string/key. The result is structurally broken but still reads as one continuous line.

This is **distinct** from the "Could not find a match" long-line failure (that one refuses to apply; this one applies and corrupts).

## When it happens

- You patch a long JSON string value and your `old_string` is shorter than the full value.
- The value is a single line (no newlines to anchor on).
- The `_warning` "last read with offset/limit pagination" fires — it is NON-BLOCKING, so the bad write still lands.

## Detection

Always validate-after-edit. Never trust `read_file`'s pretty display or the `patch` "success" flag for JSON:

```bash
terminal python3 -c "import json; json.load(open('~/.hermes/commons/data/ocas-finch/task-list.json')); print('VALID')"
```

(`execute_code` is blocked in indigo cron — use `terminal`.)

## Repair recipe (occurrence-based ASCII slicing)

Do NOT keep patching — you'll only add more dangling copies. Switch to `terminal python3` and rebuild the file by slicing around the corruption using **unambiguous ASCII anchors**, because:

- The good value ends at a known ASCII string (e.g. `All other open signals still active."`).
- The dangling tail begins at a known ASCII string (e.g. `ALREADY HOTFIXED` — see the literal-`\uXXXX` pitfall below).

```python
import json
path = '~/.hermes/commons/data/ocas-finch/task-list.json'
raw = open(path, encoding='utf-8').read()

# 1) Good value end (ASCII anchor, inclusive of closing quote):
good_note = 'All other open signals still active."'
gstart = raw.index(good_note)
good_end = gstart + len(good_note)

# 2) Next REAL key start (the separator that should follow the value):
sep = ',\n  "tasks": ['
send = raw.index(sep)

# 3) Drop everything between good_end and send (the dangling tail), keep the rest:
raw2 = raw[:good_end] + raw[send:]

# 4) Validate before mutating further / inserting new tasks:
d = json.loads(raw2)            # raises if still corrupt
print('parse OK, tasks:', len(d['tasks']))

# 5) ... insert new task, bump metadata, dump back ...
with open(path, 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)

json.loads(open(path, encoding='utf-8').read())   # final VALID check
```

### The literal-`\uXXXX` search pitfall (load-bearing)

JSON-escaped unicode (e.g. `\u2014` for —) is stored in the file as **six literal characters**: `\` `u` `2` `0` `1` `4`. So:

- A Python search string written as `'.", \u2014 ALREADY'` (a real em-dash in your source) will **NOT match** — the file has no real em-dash, it has the 6-char escape.
- Under shell/Python `-c` quoting, an escaped `\\u2014` search term also fails because the layer keeps re-escaping it.

**Workaround:** anchor your cut points on the **ASCII text immediately adjacent** to the escape, never on the escape itself:
- Use `All other open signals still active."` (pure ASCII, before the dangling tail).
- Use `ALREADY HOTFIXED` (pure ASCII, inside the dangling tail) — `raw.index('ALREADY HOTFIXED')` works reliably.
- Or just find the good-value-end and the next real `,\n  "key": [` separator and slice between them (the recipe above). This sidesteps the escape entirely.

## Prevention (the real rule)

Never `patch` a long single-line JSON string value with anything less than the **full line** as `old_string`. For any task-list.json / long-line JSON edit, prefer the `terminal python3` `json.load -> mutate -> json.dump` script (execute_code is blocked in indigo cron) — it is structurally incapable of this failure because you mutate a parsed dict, not a raw substring.

Confirmed 2026-07-20 (finch:scan 09:21Z): a `patch` of `cycle_note` with a partial `old_string` returned success yet concatenated the old note tail onto the new value; ~15 repair attempts via `patch`/`terminal` string-splicing failed (most on the literal-`\u2014` search mismatch) before the occurrence-based ASCII-anchor slice above repaired it cleanly.

## Sibling pitfall: repeated-value disambiguation + `same_tool_failure_warning` loop-guard (confirmed 2026-07-25 finch:scan)

When a field value is **identical across many objects**, `patch` cannot anchor on it alone. Example: in a 97KB task-list.json, `"last_finch_review": "2026-07-25T03:24:21Z"` appeared **53×**. A `patch` whose `old_string` ended on that line returned `Found 53 matches for old_string. Provide more context to make it unique, or use replace_all=True` and REFUSED.

- **Fix:** include the object's **unique** adjacent line in `old_string` — the task's `"id": "spotify-pause-standing",` line — so the match resolves to exactly one object. (Beware `replace_all=True` here: it would stamp the same edit on all 53 objects.)
- **Loop-guard trap:** each refused attempt increments the `same_tool_failure_warning` loop guard. After **3 failures on the same file**, the harness BLOCKS all further `patch` calls on that file for the rest of the turn — so you cannot recover by trying a third variant. The only escape is to abandon `patch` and switch to the `terminal python3` script path (write the script to `/tmp/...py` via `write_file`, then `terminal python3 /tmp/...py`) — the script path is exempt from the loop guard.
- **Applied lesson (this run):** after 2 refused attempts on the `last_finch_review` value, anchor on the `"id":` line of the specific task instead. Worked immediately.

**General rule for any repeated-value JSON edit:** never patch on the repeating value; anchor on a unique sibling key (the `id:`), or just do the whole mutation in one `terminal python3` script.
