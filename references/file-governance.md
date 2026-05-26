# Finch — File Governance

## File governance

### Write targets

| File | What | How |
|------|------|-----|
| **MEMORY.md** | Corrections, directives, breakthroughs, stop signals. Concise 1-liners. Pointers to deeper reference files. | `memory` tool |
| **Skill SKILL.md files** | Methodologies, workflows, edge cases, pitfalls (skill-specific) | `skill_manage` tool |
| **Reference files** (cross-session reference directory) | Cross-session canonical patterns, guides, references. Created when a finding doesn't fit cleanly in MEMORY.md or a single skill. | `write_file` tool |
| **Reference INDEX** (cross-session reference directory) | One-line "when to use" entry for each reference file. Updated whenever a new reference file is created. | `patch` or `write_file` tool |
| **decisions.jsonl** | DecisionRecord per routing decision | Direct write |
| **intents.jsonl** | Durable intent queue | Direct write |
| **evidence.jsonl** | Execution evidence log | Direct write |
| **Action Journals** | Per-run journal entries | Direct write |

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

**File naming:** `{topic}-guide.md` or `{topic}-reference.md` — descriptive, hyphenated, lowercase.

**After creating a reference file:**
1. Add a one-line "when to use" entry to `INDEX.md`
2. Add a one-line pointer in MEMORY.md under the relevant section (e.g., "Reference index: INDEX.md in the cross-session reference directory")
3. Log the decision in `decisions.jsonl` with `decision_type: "reference_file_created"`
