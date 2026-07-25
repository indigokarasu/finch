# Windowed Miner Silent-Data-Drop Trap

**Confirmed:** 2026-07-23, the `daily_ft_miner.py` self-improvement cron.

## Symptom
A data-mining / analysis cron that filters events by a `now - N hours` cutoff reported
`"0 events — nothing to analyze"` and was about to emit `[SILENT]`. Independent
re-verification showed **7 real events in the window**. The job would have self-excused
while genuine signal sat unexamined — the exact "status ≠ action" false-completion the
agent is built to avoid.

## Root cause
The event log (`skill_usage_log.csv`) stored **timezone-naive** timestamps
(e.g. `2026-07-23T04:32:31` — no trailing `Z`). The cutoff was built **aware** (UTC):
`cutoff = datetime.now(timezone.utc) - timedelta(hours=24)`.

```python
ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
# ^ for naive input, ts.tzinfo is None
if ts >= cutoff:   # naive >= aware  → raises TypeError
    recent_events.append(row)
```

Comparing a naive datetime to an aware datetime raises `TypeError`. The surrounding
`except:` was **bare**, so the exception was swallowed and **the row was dropped** —
not just the comparison, the entire `append` path. Every interactive row in the window
suffered the same fate, so the loop collected zero events and reported "nothing to do."

This is a **subtype of the cron "0 = false-negative" trap**: a run that looks healthy and
self-excuses, when in fact it processed nothing because of a silent internal error.

## Fix (applied to the miner)
Normalize naive timestamps to UTC before the comparison:

```python
ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
if ts.tzinfo is None:
    ts = ts.replace(tzinfo=timezone.utc)
if ts >= cutoff:
    recent_events.append(row)
```

## Standing mitigations (apply to ANY windowed mining/analysis cron)
1. **Never compare mixed naive/aware datetimes.** Normalize naive → UTC
   (`ts.replace(tzinfo=timezone.utc)`) at parse time. A naive-vs-aware compare raises
   `TypeError`, it does not evaluate to a boolean.
2. **Never wrap a data-inclusion gate in a bare `except:`.** At minimum
   `except Exception as e: print("WARN:", e, row_id)` so a swallowed error can't
   masquerade as "no data." An exception inside the filter means "I couldn't decide,"
   NOT "exclude this row."
3. **Re-verify before trusting "0 events."** When a windowed miner reports nothing,
   independently re-query the same data with corrected timezone handling (a separate
   code path, not a re-read of the miner's own output). A healthy-looking muted run is
   the precise failure mode to suspect — treat "0" as a claim to verify, not a fact.
4. **Filter by the data's own `source` COLUMN, not by assumption.** The miner correctly
   skipped `cron`-sourced rows via `row["source"] == "cron"`. Keep row-source filtering
   explicit; don't assume all rows in the log are interactive.
5. **The bare-except anti-pattern generalizes.** Any `try/except` around a loop that
   decides inclusion/selection is a silent-drop hazard. Make the exception path visible
   (log it, or re-raise after recording) so a parsing/type error can't erase data.

## How to detect this class in the wild
- A cron that emits `[SILENT]` or "no events / nothing to do" over a period that should
  have produced data (e.g. a skill-usage miner when skills ARE being used).
- A miner whose output count is suspiciously round (0) after a quiet-but-nonzero stretch.
- Any `except:` with no logging inside a row-filtering loop in the mining script.

Cross-ref: `references/cron-health-false-negative.md` (the broader "0 = false-negative"
family, including truncated greps and stale `jobs.json` snapshots).

## Secondary trap: co-loaded skills get identical action summaries (misclassify risk)
The same miner built its `action_summaries` by taking the assistant tool-calls in the
messages AFTER a `skill_view`. When two skills are loaded in the SAME turn (a common
pattern — e.g. "what data sources does RALLY have, including through sift and reach?"
loads all three), the post-load messages belong to BOTH skill-load events, so both
received an **identical** summary of only `search_files` / `read_file` calls. Judged
blindly, that looks like "loaded the skill but only did local file reads, not the
skill's actual functions" — a would-be FALSE trigger.

**Why it's a trap:** the summary misses the `skill_view` RETURN content and the
reference-file reads in the same turn. The load was correct; the summary just doesn't
show it.

**Mitigation:** when a mined skill shows only generic post-load tool calls and the
classification would be FALSE, pull the actual session transcript for that `session_id`
and inspect the `skill_view` returns + same-turn reference reads before flagging a false
trigger. Verify against the real session, not the summarized tool list.

