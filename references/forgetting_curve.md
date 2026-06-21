# Forgetting-Aware Compaction Algorithm

Based on the Ebbinghaus forgetting curve: memories decay exponentially without
reinforcement, but each review extends the retention half-life.

## Storage Tier Model

MEMORY.md is the most expensive context real estate — injected into every session.
Not everything belongs there. Finch classifies all knowledge into **four storage tiers**
and routes entries to the right tier during compaction:

| Tier | Storage target | What belongs there | When loaded |
|------|---------------|-------------------|-------------|
| **Tier 1** | MEMORY.md | Behavioral directives (Always/Never), cross-cutting corrections, critical operating constraints | Every session (system prompt) |
| **Tier 2** | Skill SKILL.md / references/ | Tool-usage facts, service-specific gotchas, howtos for a specific tool or API | When that skill is loaded |
| **Tier 3** | Reference files (references/) | Detailed guides, config references, URLs, paths, canonical patterns | On demand (read when needed) |
| **Tier 4** | Chronicle / Elephas KG | Entity facts, relationships, durable world knowledge | Queried via elephas.query |

### Concept classification guide

Use this to determine which tier an entry belongs to:

- **"Always/Never do X"** → Tier 1 (MEMORY.md) — behavioral directive
- **"X causes Y" / "When Z happens, do W"** → Tier 1 (MEMORY.md) — cross-cutting correction with causal grounding
- **"Use tool A for purpose B"** → Tier 2 (skill) — tool-usage fact, belongs in the skill that uses tool A
- **"Service X has gotcha Y"** → Tier 2 (skill) — service-specific, belongs in the skill that interacts with service X
- **"How to do X with Y" (multi-step)** → Tier 3 (reference) — procedural guide, belongs in references/
- **"URL/path/config for X"** → Tier 3 (reference) — look-up-able detail, belongs in references/ or a skill's references/
- **"Entity X has property Y"** → Tier 4 (Chronicle) — factual knowledge, belongs in the knowledge graph

### Known directive-to-skill routes

When the following directives appear in MEMORY.md, route them to the specified skill during compaction:

| Directive pattern | Target skill | Reason |
|-------------------|-------------|--------|
| Weave/Google Contacts sync rules | `ocas-weave` | Contact management is Weave's domain |
| "Never create workflow docs for API endpoints" | `api-integration` | API documentation governance |
| "Never skip tests during dev" | `test-driven-development` or `software-development` | Testing practice belongs in dev skills |
| "Never assume MCP broken without testing" | Consolidate into "verify before diagnosing" in MEMORY.md | Cross-cutting, but merge with existing correction |
| "Check tool defs before concluding" | Consolidate into "read actual code before diagnosing" in MEMORY.md | Cross-cutting, but merge with existing principle |

### Tier routing during compaction

When an entry is classified as Decaying or Stable, **do not default to eviction**.
Instead, route it to the correct tier:

1. If it's Tier 1 (behavioral/cross-cutting) → keep in MEMORY.md
2. If it's Tier 2 (tool/service-specific) → move to the governing skill's SKILL.md or references/ directory
3. If it's Tier 3 (reference/detail) → move to the cross-session reference directory
4. If it's Tier 4 (entity fact) → ingest into Chronicle via Elephas
5. If it's truly stale (service decommissioned, tool removed, fact outdated) → evict

**After routing:** Update MEMORY.md to remove moved entries. Do NOT add pointers to the routed content — if a session needs Tier 2/3/4 knowledge, it loads the skill or reads the reference directly. MEMORY.md is for cross-cutting behavioral knowledge only, not a directory of everything the agent knows.

## Compaction Algorithm

Run during `finch:daily` or `finch:weekly`:

### Step 1: Reinforcement scan
For each MEMORY.md entry, check if it was referenced, re-encountered, or
re-applied in any session since last compaction. Evidence sources:
- Session transcripts mentioning the same topic/context
- Skill patches that reference the same principle
- User corrections that reinforce the same directive

### Step 2: Concept classification + age classification
For each entry, first classify by storage tier (see Tier Model above), then by
reinforcement status:

| Status | Criteria | Action |
|--------|----------|--------|
| **Reinforced** | Referenced in last compaction interval | Keep in current tier. Increment reinforcement count. |
| **Stable** | Not reinforced but < 3 intervals old | Keep in current tier. Flag for priority reinforcement next cycle. |
| **Decaying** | Not reinforced for 3+ intervals | Candidate for tier routing or eviction. |
| **Critical** | Directive (Always/Never) — never auto-evict | Keep in Tier 1 regardless. Flag for manual review if stale. |

### Step 3: Tier routing
For each Decaying or Stable entry, apply the tier routing rules above:
- Classify the entry's concept type
- If it's in the wrong tier (e.g., a tool-usage fact sitting in MEMORY.md), move it to the correct tier
- If it's in the right tier but decaying, keep it there (it may reinforce next cycle)
- Log every routing decision in decisions.jsonl

### Step 4: Consolidation
Merge entries that share the same underlying principle:
- If 2+ corrections share the same "why", merge into a single entry with
  multiple "when" contexts.
- Example: "Don't use curl for GitHub API calls" + "Use gh api instead of curl"
  → "Use gh api for GitHub interactions (not curl) — applies to release fetching,
  API queries, and issue management."
- Consolidation applies within a tier — don't merge Tier 1 and Tier 3 entries.

### Step 5: Eviction
Remove Decaying entries that are:
- Not directives (Always/Never)
- Not referenced by any skill
- Not user-critical operating constraints
- Not reroutable to another tier (already in the lowest appropriate tier)

### Step 6: Dependency and ordering analysis

After consolidation, analyze read-order dependencies between remaining entries.
MEMORY.md is read top-to-bottom by every session. Order matters.

**Dependency scan:** For each pair of entries (A, B), check if A is a prerequisite
for understanding B:

- **Conceptual dependency:** A defines a concept that B references (e.g., "two Google accounts exist" → "use calendar_id=jared.zimmerman@gmail.com")
- **Safety dependency:** A is a guardrail that prevents misuse described in B (e.g., "never run gcloud auth revoke" → "GCloud auth flow...")
- **Context dependency:** A establishes context that makes B's constraint meaningful (e.g., "ticker dies on restart" → "check .tick.lock mtime before diagnosing")

**Ordering rules (apply in order):**

1. **Guardrails first:** Safety directives (Never/Always) before operational details they guard
2. **General before specific:** Broad constraints before narrow applications
3. **Context before action:** Setup/prerequisite knowledge before instructions that depend on it
4. **Criticality within same level:** Higher blast-radius entries first (affects more sessions/skills)
5. **Independent entries:** Alphabetical by topic (deterministic, easy to scan)

**Forward references:** If entry B depends on entry A, add a brief forward reference
in A: "See also: [topic]" so the agent's attention is primed. These are *within-MEMORY.md*
cross-references — not pointers to external content.

**Anti-patterns to avoid:**
- Don't order by recency (newest first) — this puts the least-tested knowledge in the most-read position
- Don't order by length — short entries aren't inherently more important
- Don't leave ordering to insertion order — this drifts toward chaos over time

### Step 7: Write

Write the final MEMORY.md. Format:
- One entry per §-delimited line
- No markdown headers, bullets, or sections
- Ordered per Step 6 analysis
- Total length ≤ 2,200 chars

**Deterministic enforcement (MANDATORY final step).** Do not trust the char count above -
after writing your proposed MEMORY.md, run the safety guard to GUARANTEE the cap and a safe write:

    python3 ~/.hermes/profiles/indigo/skills/ocas-finch/scripts/memory_guard.py --apply --emit-decision

It enforces the hard cap (deterministically evicting lowest-priority NON-directive lines; Always/Never
directives are never auto-evicted), strips 'see references/...' pointer anti-patterns, writes atomically
with a timestamped backup under a PID lock (OOM/race-safe vs the live `memory` tool), archives anything
removed to `commons/data/ocas-finch/memory_archive.md`, logs a DecisionRecord, and is a no-op when
MEMORY.md is already compliant. If it warns `STILL OVER CAP` (directives alone exceed the cap),
consolidate via the LLM steps above or flag for human review - never force past it.


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
