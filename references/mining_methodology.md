# Session Mining Methodology

This document captures the methodology for mining session JSONL files
for learning signals, as developed for ocas-finch.

## Why JSONL files, not state.db

- `~/.hermes/state.db` is 14GB+ and slow to query (minutes for simple counts)
- SQLite queries timeout on large date ranges
- JSONL files are immediately accessible — one file per session
- Each file is self-contained with full conversation context
- No database locking or concurrency issues

## File format

Each session file is JSONL (one JSON object per line):

```json
{"role": "session_meta", "tools": [...], "model": "...", "platform": "telegram", "timestamp": "..."}
{"role": "user", "content": "...", "timestamp": "..."}
{"role": "assistant", "content": "...", "timestamp": "..."}
{"role": "tool", "content": "...", "timestamp": "..."}
```

Key fields:
- `role`: "session_meta", "user", "assistant", "tool"
- `content`: message text (may be empty for tool calls)
- `platform`: "telegram", "cli", "cron" (only in session_meta)
- `timestamp`: ISO 8601

## Filtering rules

### Always exclude:
1. **Cron sessions** — platform = "cron" in session_meta
2. **System messages** — content starts with:
   - "[System note:"
   - "[IMPORTANT:"
   - "[CONTEXT COMPACTION"
   - "Your previous turn"
   - "Your active task list"
   - "[CRON"
3. **Empty messages** — content is null, empty, or < 3 chars
4. **Tool results** — role = "tool"

### Include:
- Messages from "telegram" and "cli" sessions
- Sessions without session_meta but with real user content (check content patterns)

## Signal detection approach

Use regex patterns on user message content. Each signal type has:
- A regex pattern
- A confidence score (0.0–1.0)
- A routing target

### Pattern design principles:
1. **Start with high-confidence patterns** — explicit phrases like "Never do X"
2. **Use word boundaries** — `\bnever\b` not `never` (avoids matching "whenever")
3. **Anchor when possible** — `^no[,.]` matches start of message
4. **Context matters** — capture surrounding messages for breakthroughs/stops

### Confidence calibration:
- 0.95: Unambiguous ("Never do X", "That's exactly right")
- 0.85: Strong ("Don't do that", "Stop")
- 0.70: Moderate ("Actually...", "Instead...")
- 0.50: Weak (single word matches without context)

## Context windows

For breakthroughs and stop signals, capture the preceding assistant message
to understand what triggered the signal. A 3-message window (1 before, 1 after)
is usually sufficient.

## OCAS compliance notes

Per `spec-ocas-journal.md`, every mining run emits an Action Journal entry
to `{agent_root}/commons/journals/ocas-finch/YYYY-MM-DD/{run_id}.json`.

Per `spec-ocas-shared-schemas.md`, routing decisions are recorded as
DecisionRecord entries in `{agent_root}/commons/data/ocas-finch/decisions.jsonl`.

## Lessons learned

1. **Context compaction messages leak through** — Many sessions contain
   "[CONTEXT COMPACTION — REFERENCE ONLY]" blocks that mention "always" and
   "never" as part of the compaction summary. These must be filtered out.

2. **Session meta is not always present** — Some real sessions (especially
   older ones) don't have a session_meta message. Don't reject these — check
   content patterns instead.

3. **Cron sessions without meta** — Some cron sessions don't have session_meta.
   Filter by content patterns (cron messages tend to be short, imperative).

4. **False positive rate** — Without filtering, ~80% of "correction" matches
   are false positives (compaction summaries, system messages). With proper
   filtering, the false positive rate drops to ~10%.

5. **Deduplication matters** — The same correction may appear in multiple
   sessions. Deduplicate by content similarity before routing.
