# Incremental Email Classification via Message-ID Watermark

## Why
A `finch:scan` cycle runs every 2h and queries `newer_than:2d`. That window overlaps the previous cycle by ~46h, so each run returns ~30 messages — but only a handful are actually NEW since the last scan. If you classify the whole batch every cycle you (a) waste tool calls re-parsing ~28 stale messages and (b) risk creating duplicate tasks for the same email.

## The watermark technique (confirmed 2026-07-24 finch:scan)
1. **Record the boundary each cycle.** The task-list `cycle_note` / `filtered_noise` already captures the prior boundary as `boundary <old> -> <new>`. The `<new>` value (the highest message-ID seen that cycle) is your watermark.
   - In this run the prior watermark was `<thread-id>`; the 20 new messages were `<thread-id>` … `<thread-id>` — all lexically greater than the watermark.
2. **Fetch the full 2d batch** (paginate to completion — see the pagination gotcha) to get all current IDs.
3. **Filter to new IDs only:**
   ```python
   prior_watermark = "<thread-id>"   # read from previous cycle_note/filtered_noise
   new_ids = [mid for mid in all_ids if mid > prior_watermark]  # LEXICAL compare
   ```
   Gmail message IDs are assigned in increasing order per mailbox and sort correctly under **lexical** (string) comparison — `19f96…` > `19f95…`. Do NOT cast to int (they contain hex letters `a-f` and will raise `ValueError`).
4. **Classify only `new_ids`** through the actionable classifier (`references/finch-scan-email-actionable-classifier.md`). Stale IDs already have task-list entries from prior cycles.
5. **Persist the new watermark** for next cycle by writing `boundary <prior_watermark> -> <highest_new_id>` into this cycle's `filtered_noise` + `cycle_note`.

## Pitfall
- If the MCP namespace is ABSENT this cycle and you fall back to `gws_direct_puller.py`, the same watermark logic applies — the puller returns `id` fields; filter identically before classification.
- A bulk send (e.g. 18× RapidAPI "Subscribe Confirmation" in one minute) all share a tight ID cluster above the watermark — that's expected and correct; classify them as one noise cluster, don't create 18 tasks.
- Never assume `newer_than:2d` is id-ordered across pages; always compare every returned ID against the watermark rather than trusting position.
