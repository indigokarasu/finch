# Forgetting-Aware Compaction Algorithm

Based on the Ebbinghaus forgetting curve: memories decay exponentially without
reinforcement, but each review extends the retention half-life.

## Compaction Algorithm

Run during `finch:daily` or `finch:weekly`:

### Step 1: Reinforcement scan
For each MEMORY.md entry, check if it was referenced, re-encountered, or
re-applied in any session since last compaction. Evidence sources:
- Session transcripts mentioning the same topic/context
- Skill patches that reference the same principle
- User corrections that reinforce the same directive

### Step 2: Age classification
Classify each entry by reinforcement status:

| Status | Criteria | Action |
|--------|----------|--------|
| **Reinforced** | Referenced in last compaction interval | Keep. Increment reinforcement count. |
| **Stable** | Not reinforced but < 3 intervals old | Keep. Flag for priority reinforcement next cycle. |
| **Decaying** | Not reinforced for 3+ intervals | Candidate for eviction. |
| **Critical** | Directive (Always/Never) — never auto-evict | Keep regardless. Flag for manual review if stale. |

### Step 3: Consolidation
Merge entries that share the same underlying principle:
- If 2+ corrections share the same "why", merge into a single entry with
  multiple "when" contexts.
- Example: "Don't use curl for GitHub API calls" + "Use gh api instead of curl"
  → "Use gh api for GitHub interactions (not curl) — applies to release fetching,
  API queries, and issue management."

### Step 4: Eviction
Remove Decaying entries that are:
- Not directives (Always/Never)
- Not referenced by any skill
- Not user-critical operating constraints

### Step 5: Re-ranking
After consolidation, re-rank remaining entries:
1. Directives (Always/Never) — always first
2. Corrections with causal grounding (Why + What + When)
3. Bare corrections (What only)
4. Breakthroughs / What Works
5. Methodologies

## Reinforcement Schedule

Mirrors spaced repetition intervals:

| Review # | Interval |
|----------|----------|
| 1st | 1 day |
| 2nd | 3 days |
| 3rd | 7 days |
| 4th | 14 days |
| 5th | 30 days |

After 5 reinforcements, an entry is considered "consolidated" — it can be
compacted into a terse one-liner since the principle is well-established.

## Format for Grounded Corrections

```
[CORRECTION] What: <what was wrong>. Why: <underlying principle>. When: <contexts where this applies>
```

Grounded corrections survive longer in compaction because they generalize.
Bare corrections ("don't do X") are single-instance and get pruned first.
