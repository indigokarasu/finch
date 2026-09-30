# Gmail content-batch call shape — do not nest the ID list

**Recurrence class:** `oc_tool_call_shape_validation_recurring` · **Measured 2026-09-29:** 26 ERROR/WARNING
events today across 8 jobs, most recent 09:06:31 PDT. Rising, not flat (09-28: 2, 09-29: 13 on the
pinned 4-file set; 26 across all logs).

This class was closed on 2026-09-28 as "known model behavior — the fix is call-shape guidance to the
model, not a Tier 1 code patch." **That closure was wrong: with no durable reference to load, the
shape error kept firing.** This file is that reference.

## The two sub-classes

### 1. `local_batch` — passing a list to a local tool

```
tool_call takes exactly one entry for local tools; you sent N
```

`N` observed: 2 (×7), 3 (×4), 4 (×1), 5 (×1). A **local** tool is invoked with a single argument
object, not a batch array. `tool_search` returns a local tool; its `tool_call` takes one dict.

```
WRONG   tool_call([{...}, {...}])
RIGHT   tool_call({...})
```

### 2. `message_ids[0]` — nesting a list inside `message_ids`

This is the one that bites hardest, and the shape is subtle because the docs are *right*:

```
get_gmail_messages_content_batch(message_ids=["a", "b"], format="metadata")
```

is correct. What actually fails is a list nested **inside** the list — the model reaches for the
`by_id` / page-collect pattern from other scripts and wraps the ID list one level too deep:

```
{'item': ['<thread-id-a>', '<thread-id-b>']}   is not of type 'string'
{'item': {'item': ['<thread-id-c>', ...]}}     is not of type 'string'
```

`message_ids[0]` must be a **bare string**. If your variable holds
`{"item": [...]}` — the shape returned by a prior metadata fetch — unwrap it first:

```python
ids = [m["id"] if isinstance(m, dict) else m for m in page["messages"]]
ids = [i["item"] if isinstance(i, dict) and "item" in i else i for i in ids]  # <- the fix
ids = [i for i in ids if isinstance(i, str)]                                  # <- verify
assert all(isinstance(i, str) for i in ids)
```

## Every `gws_*` call needs `user_google_email`

Independent, separate, and easy to lose when rewriting the call:
`get_gmail_messages_content_batch` returns a pydantic error ("user_google_email Missing required
argument") without it, even though `search_gmail_messages` may appear to work without one. See
`finch-scan-pitfalls.md` §4.

## Batch size

Up to **25** Message IDs per call. Over-size gets rejected at the schema, which looks like a
shape error but is a different failure — check the count before blaming the shape.

## Measurement note (carried forward)

Count this class on **log LEVEL** first. A first pass counting any line containing
`get_gmail_messages_content_batch` returned 92 hits — 90 were INFO-level tool mentions, not errors.
The real error-class count is a small fraction of the substring count. The same trap is documented
for a different class in `ocas-custodian`'s `references/execution-loops.md` (Step 3, the
timestamp+millisecond-prefix rule) — **filter before counting, or the number is fiction.**
