# Finch — File Governance

## Storage Tier Model

Finch routes knowledge to four storage tiers. See `references/forgetting_curve.md`
for the full tier model and concept classification guide.

| Tier | Storage target | What belongs there |
|------|---------------|-------------------|
| **Tier 1** | MEMORY.md | Behavioral directives, cross-cutting corrections, critical operating constraints |
| **Tier 2** | Skill SKILL.md / references/ | Tool-usage facts, service-specific gotchas, howtos for a specific tool or API |
| **Tier 3** | Reference files (references/) | Detailed guides, config references, URLs, paths, canonical patterns |
| **Tier 4** | Chronicle / Elephas KG | Entity facts, relationships, durable world knowledge |

**Routing rule:** During compaction, if an entry is in the wrong tier, move it to the
correct tier — don't just evict. Only evict when the knowledge is truly stale
(service decommissioned, tool removed, fact outdated).

## File governance

### Write targets

| File | Tier | What | How |
|------|------|------|-----|
| **MEMORY.md** | 1 | Corrections, directives, breakthroughs, stop signals. Concise 1-liners. Pointers to deeper reference files. | `memory` tool |
| **Skill SKILL.md files** | 2 | Methodologies, workflows, edge cases, pitfalls (skill-specific). Tool-usage facts and service gotchas routed from MEMORY.md. | `skill_manage` tool |
| **Skill references/** | 2 | Detailed howtos, API references, service-specific guides for a skill. | `write_file` tool |
| **Reference files** (cross-session reference directory) | 3 | Cross-session canonical patterns, guides, references. Created when a finding doesn't fit cleanly in MEMORY.md or a single skill. | `write_file` tool |
| **Reference INDEX** (cross-session reference directory) | 3 | One-line "when to use" entry for each reference file. Updated whenever a new reference file is created. | `patch` or `write_file` tool |
| **Chronicle / Elephas KG** | 4 | Entity facts, relationships, durable world knowledge. | Elephas bridge or `elephas.ingest` |
| **decisions.jsonl** | — | DecisionRecord per routing decision | Direct write |
| **intents.jsonl** | — | Durable intent queue | Direct write |
| **evidence.jsonl** | — | Execution evidence log | Direct write |
| **Action Journals** | — | Per-run journal entries | Direct write |

### Read-only

Session transcripts, BehavioralSignal files, state.db.

### Off-limits

**USER.md**, **SOUL.md**, **IDENTITY_RULES.md**, **AGENTS.md**, credential files. Finch can *suggest* changes to USER.md/SOUL.md via weekly pipeline but never auto-apply.

### Reference file creation criteria

Create a new reference file rather than appending to MEMORY.md when:
- The finding is a **canonical pattern** applicable across multiple skills/sessions (not just "current state")
- The content is **procedural** (how to do X) rather than factual (what is true right now)
- The finding is **longer than 3 lines** and would bloat MEMORY.md
- A new skill is being created and needs supporting reference material
- The entry was routed from MEMORY.md during tier routing (decaying tool-usage fact or service gotcha)

**File naming:** `{topic}-guide.md` or `{topic}-reference.md` — descriptive, hyphenated, lowercase.

**After creating a reference file:**
1. Add a one-line "when to use" entry to `INDEX.md`
2. Add a one-line pointer in MEMORY.md under the relevant section
3. Log the decision in `decisions.jsonl` with `decision_type: "reference_file_created"`

### Tier routing log format

Every tier routing decision is logged in `decisions.jsonl`:

```json
{
  "timestamp": "2026-06-03T21:35:00Z",
  "decision_type": "tier_routing",
  "entry": "FAL: key in config/web. Use ocas-imagine.",
  "from_tier": 1,
  "to_tier": 2,
  "target": "skills/ocas-imagine/references/fal-usage.md",
  "reason": "Tool-usage fact, not cross-cutting behavioral knowledge. Belongs in the skill that uses FAL."
}
```
