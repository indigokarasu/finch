---
name: ocas-finch
description: >
  OCAS self-improvement orchestrator (Darwin's finch — adaptive evolution).
  Mines session JSONL files to detect corrections, breakthroughs, methodologies,
  course-changes, and behavioral directives (Always/Never). Routes each finding
  to the optimal modification target: MEMORY.md or skill patches. Emits Action
  Journals and DecisionRecords per OCAS spec. Part of the OCAS System Evolution
  Layer alongside Mentor, Fellow, and Forge.
metadata:
  author: Indigo Karasu
  version: "2.0.0"
  hermes:
    tags: [self-improvement, orchestration, session-mining, evolution, ocas]
    category: ocas
    requires_toolsets: [terminal]
---

# ocas-finch

Finch is the OCAS System Evolution Layer's session mining engine. It mines
session JSONL files directly — no dependency on Hermes Dojo or state.db — to
detect learning signals from real user interactions. Each finding is routed to
the modification target that will have the most behavioral impact.

## OCAS Architecture

**Layer:** System Evolution Layer (alongside Mentor, Fellow, Forge)

**Role:** Session mining engine. Detects behavioral signals from conversation
transcripts and routes them to durable modification targets (MEMORY.md, skill
patches). Complements Mentor's journal-based evaluation by mining the raw
session JSONL files that Mentor's journal feed also derives from.

**Journal type:** Action Journal (per `spec-ocas-journal.md`). Every finch run
emits an Action Journal entry to `{agent_root}/commons/journals/ocas-finch/`.

**Cooperation:**
- Receives: Session JSONL files (read-only, from `~/.hermes/sessions/`)
- Emits: DecisionRecords (to `commons/data/ocas-finch/decisions.jsonl`)
- Emits: Action Journals (to `commons/journals/ocas-finch/YYYY-MM-DD/`)
- Writes: MEMORY.md (via memory tool), skill SKILL.md files (via skill_manage)

**Independence:** Finch operates independently. It does not depend on Mentor,
Fellow, Forge, or any other OCAS skill being present.

## Storage

Per `spec-ocas-storage-conventions.md`, all persistent data lives under
`{agent_root}/commons/`:

```
{agent_root}/commons/
  data/ocas-finch/
    decisions.jsonl          — DecisionRecord log (append-only)
    memory_archive.md        — evicted MEMORY.md entries from compaction
  journals/ocas-finch/
    YYYY-MM-DD/
      {run_id}.json          — Action Journal entries
```

Finch skill package (scripts, references, SKILL.md):
```
~/.hermes/skills/ocas-finch/
  SKILL.md
  scripts/
    miner.py
    router.py
    compact.py
  references/
    mining_methodology.md
    signal_patterns.md
```

## File governance

### Write targets (finch maintains these)

| File | What goes there | How |
|---|---|---|
| **MEMORY.md** | Corrections, directives, tool quirks, conventions, stop signals, breakthroughs | `memory` tool |
| **Skill SKILL.md files** | Methodologies, workflows, edge cases, pitfalls | `skill_manage` tool (`action=patch`) |
| **decisions.jsonl** | DecisionRecord per routing decision | Direct write to `commons/data/ocas-finch/` |
| **Action Journals** | Per-run journal entries | Direct write to `commons/journals/ocas-finch/` |

### Read-only (finch mines these, never writes)

| File | Why read-only |
|---|---|
| **Session JSONL** (`~/.hermes/sessions/`) | Source of truth. Never modify transcripts. |
| **state.db** | Historical reference only. Too slow for active use. |

### Off-limits (finch never touches these)

| File | Why off-limits |
|---|---|
| **USER.md** | Jared's profile. Only Jared edits. Finch can *suggest* changes but never auto-apply. |
| **SOUL.md** | Operational rules set at bootstrap. Finch can *recommend* rule changes but never self-edit. |
| **IDENTITY_RULES.md** | Identity constraints. Off-limits. |
| **HEARTBEAT.md** | Heartbeat instructions. Not a learning target. |
| **AGENTS.md** | Hermes dev guide. Not finch's file. |
| **Credential files** | Auth tokens. Completely out of scope. |

## Ontology

Per `spec-ocas-ontology.md`, finch extracts and references the following entity
types:

**Entity types extracted:** None. Finch does not extract entities into
Chronicle. It operates on session transcripts, not world knowledge.

**Signal types produced:** Behavioral signals (corrections, directives, course
changes, breakthroughs, methodologies, stop signals). These are routed to
MEMORY.md and skill files, not emitted to Elephas as Chronicle signals.

**Journal type:** Action Journal (external side effects: writes to MEMORY.md,
skill files, decision logs).

## Data source

**Primary:** Session JSONL files in `~/.hermes/sessions/`

Each file is a conversation transcript with messages containing:
- `role`: "user", "assistant", "tool", or "session_meta"
- `content`: the message text
- `timestamp`: ISO timestamp
- `platform`: "telegram", "cli", "cron", etc.

**Why JSONL files, not state.db:**
- The 14GB state.db is slow to query and requires SQLite
- JSONL files are immediately accessible, grep-able, and portable
- Each file is a complete, self-contained conversation
- No cron/system noise — real sessions are clearly identifiable

## Behavioral directives (priority 0)

When the user says "Always" or "Never", this is an explicit behavioral rule.
These are **priority 0** — the highest priority. Apply immediately and prominently.

- Route to MEMORY.md under `## Always Rules` or `## Never Rules`
- Never batch with lower-priority findings
- Never skip the review step for these — but apply as soon as the user confirms

## Signal types

| Signal | What it means | Where it goes |
|--------|--------------|---------------|
| **Correction** | User said "no/wrong/don't/stop" and gave alternate direction | MEMORY.md |
| **Directive (Always)** | User said "always do X" | MEMORY.md — Always Rules |
| **Directive (Never)** | User said "never do X" | MEMORY.md — Never Rules |
| **Course change** | User reinterpreted what you said and redirected | MEMORY.md |
| **Breakthrough** | User confirmed something works ("exactly right", "perfect") | MEMORY.md — What Works |
| **Methodology** | User described a reproducible process | Skill patch or MEMORY.md |
| **Stop** | User stopped/cancelled a task mid-execution | MEMORY.md — Stop Signals |

## Modification targets (ranked by impact)

### 1. MEMORY.md (highest impact)

`~/.hermes/MEMORY.md` is injected into every session's system prompt. Changes here
affect **all future sessions immediately**. This is where corrections, directives,
and behavioral rules go.

Structure additions by section:
```markdown
## Always Rules
- [Extracted directive]

## Never Rules
- [Extracted directive]

## User Corrections
- [Extracted correction]

## Course Changes
- [Extracted course change]

## What Works
- [Extracted breakthrough]

## Stop Signals
- [Extracted stop trigger]

## Methodologies
- [Extracted methodology]
```

### 2. Skill patches (high impact)

Existing skill SKILL.md files in `~/.hermes/skills/`. Changes here affect behavior
when the skill is loaded. Only patch **user skills** — never bundled skills.

### 3. Config changes (medium impact)

`~/.hermes/config.yaml` for agent-wide configuration changes. Suggest first,
don't auto-apply.

## Workflow

### Step 1: Mine

```bash
python3 ~/.hermes/skills/ocas-finch/scripts/miner.py --days 7 --json > /tmp/finch_mined.json
```

Options:
- `--days N` — only scan last N days
- `--min-confidence 0.7` — filter by confidence threshold
- `--sessions-dir /path` — custom sessions directory

### Step 2: Compact

```bash
python3 ~/.hermes/skills/ocas-finch/scripts/compact.py --apply
```

Runs deduplication, contradiction check, re-ranking, and eviction on existing
MEMORY.md content. Compression only triggers when MEMORY.md exceeds 80% (1,760
chars). This step frees up space before new findings are applied.

Operations (in order):
1. **Deduplicate** — merge entries that say the same thing
2. **Contradiction check** — flag conflicting entries for review
3. **Re-rank** — reorder sections and entries by priority
4. **Evict** — remove lowest-priority entries if over limit
5. **Compress** — rewrite entries compactly (only if >80%)

Evicted entries are archived to `commons/data/ocas-finch/memory_archive.md`.

### Step 3: Route

```bash
python3 ~/.hermes/skills/ocas-finch/scripts/router.py --input /tmp/finch_mined.json
```

Produces an action plan: which findings go to MEMORY.md, which need skill
patches, which need manual review. Size-aware: won't overfill MEMORY.md.

### Step 4: Review

**Always show the plan before applying (weekly run).** For each finding:
- What signal was detected
- What it means
- Where it's being routed
- The exact text that will be written

The user may:
- Skip a finding
- Redirect it (e.g., to a different section)
- Edit the suggested entry
- Approve all

Daily runs auto-apply low-risk findings (corrections >=0.8 confidence) and flag
directives/contradictions/evictions for review.

### Step 5: Apply

**Memory additions:**
Use the `memory` tool to add entries. Add entries under the appropriate
section headers.

**Skill patches:**
1. Read the current skill's SKILL.md
2. Use `skill_manage` with `action="patch"` to add the finding
3. Add to pitfalls section if it's a new edge case

### Step 6: Journal

Every finch run emits:
1. **Action Journal** to `commons/journals/ocas-finch/YYYY-MM-DD/{run_id}.json`
2. **DecisionRecord** to `commons/data/ocas-finch/decisions.jsonl`

Journal schema per `spec-ocas-journal.md`. DecisionRecord schema per
`spec-ocas-shared-schemas.md`.

## Commands

- `finch.run` — Full pipeline: mine → compact → route → review → apply
- `finch.mine` — Only mine, output raw findings
- `finch.compact` — Only compact MEMORY.md
- `finch.route` — Only route existing mined output
- `finch.dry-run` — Full pipeline without applying changes
- `finch.status` — Show recent routing history and MEMORY.md stats

## Scheduled tasks

| Job | Frequency | Behavior |
|---|---|---|
| **finch-daily** | Daily 6am PT | Mine 24h → Compact → Route → Auto-apply low-risk. Flag directives. |
| **finch-weekly** | Sunday 8am PT | Mine 7d → Compact → Route → Show full plan for approval. |

## Filtering

The miner automatically filters out:
- Cron sessions (platform = "cron")
- System-generated messages (starting with "[System note:", "[IMPORTANT:", etc.)
- Empty or too-short messages
- Tool result messages

## Confidence scoring

Each signal has a confidence score (0.0–1.0):
- **0.9–1.0**: Explicit directive or correction ("Never do X", "No, do Y instead")
- **0.7–0.8**: Strong signal ("Always make sure to...", "That's not what I asked")
- **0.5–0.6**: Weak signal, may need review

Use `--min-confidence 0.7` to focus on high-confidence findings.

## Anti-patterns

- **Don't modify SOUL.md, USER.md, IDENTITY_RULES.md, HEARTBEAT.md, or AGENTS.md** — these are off-limits
- **Don't modify credential files** — auth.json, credentials.json, .env are completely out of scope
- **Don't apply without review** — always show the plan first (weekly runs)
- **Don't duplicate entries** — check if a similar entry already exists in MEMORY.md
- **Don't mine cron sessions** — they're filtered out automatically
- **Don't create skills autonomously** — always ask for approval
- **Don't auto-apply config changes** — suggest to Jared first

## Pitfalls

- **MEMORY.md has a 2,200 char limit** — when approaching it, prioritize directives > corrections > breakthroughs. Overflow goes to skill files.
- **MEMORY.md is the highest-impact target** — a correction in MEMORY.md affects every future session. A skill patch only affects sessions where that skill loads. When in doubt, put it in MEMORY.md.
- **Directives (Always/Never) are priority 0** — these are explicit behavioral rules from the user. Apply immediately and prominently.
- **Breakthroughs need context** — a "that's perfect" is only useful if you know what preceded it. The miner captures context windows for this reason.
- **Stop signals are negative knowledge** — they tell you what NOT to do. Record what the agent was doing when the user stopped it.
- **Session files are append-only** — never modify session JSONL files. They are the source of truth. Write to MEMORY.md and skills instead.
- **USER.md is Jared's file** — if finch detects a user preference change, suggest it to Jared. Don't auto-edit USER.md.
- **SOUL.md is operational rules** — if finch discovers a gap, recommend the change. Don't self-edit SOUL.md.

## Support files

- `references/signal_patterns.md` — Complete regex pattern reference for all signal types
- `references/mining_methodology.md` — Session mining methodology and lessons learned
