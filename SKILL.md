---
name: ocas-finch
description: >
  OCAS self-improvement orchestrator (Darwin's finch — adaptive evolution).
  Mines session JSONL files to detect corrections, breakthroughs, methodologies,
  course-changes, and behavioral directives (Always/Never). Routes each finding
  to the optimal modification target: MEMORY.md or skill patches. Emits Action
  Journals and DecisionRecords per OCAS spec. Part of the OCAS System Evolution
  Layer alongside Mentor, Fellow, and Forge.
  NOT for real-time behavioral adaptation (use Corvus), skill evaluation (use Mentor), or skill creation (use Forge).
license: MIT
source: https://github.com/indigokarasu/finch
includes:
  - references/**
metadata:
  author: Indigo Karasu
  version: "2.12.0"
---

# ocas-finch

Finch is the OCAS System Evolution Layer's self-improvement orchestrator. It operates as four pure-LLM cron jobs:

- **finch:scan** (every 2h) — Scans 6 signal sources, validates existing tasks, maintains prioritized task list
- **finch:work** (every 30 min) — Picks top pending task, loads governing skill, executes one task per run
- **finch:daily** (daily 6am PT) — Mines 24h of sessions, compacts MEMORY.md, auto-applies low-risk findings
- **finch:weekly** (Sunday 8am PT) — Mines 7d, full pipeline with SOUL.md/USER.md recommendations

All four jobs are pure LLM cron prompts. No Python scripts at runtime. Deprecated scripts are in `archive/`.

## When to Use

- Scheduled self-improvement: finch:scan (every 2h), finch:work (every 30 min), finch:daily (6am PT), finch:weekly (Sunday 8am PT)
- Manual session mining via `finch.mine` or `finch.run`
- After major sessions: auto-detect corrections, directives, breakthroughs, methodologies
- MEMORY.md compaction: dedup, re-rank, evict stale entries
- Skill library maintenance: route findings to SKILL.md patches

## When NOT to Use

- Real-time behavioral adaptation (Corvus handles pattern detection)
- Skill evaluation scoring (Mentor handles OKR evaluation)
- Skill creation/architecting (Forge handles skill building)
- Entity identity resolution (Elephas handles Chronicle writes)

## Storage

See `references/storage-layout.md` for the full directory tree and skill package structure.

## OCAS Architecture

**Layer:** System Evolution Layer (alongside Mentor, Fellow, Forge)

**Role:** Session mining engine. Detects behavioral signals from conversation transcripts and routes them to durable modification targets (MEMORY.md, skill patches).

**Journal type:** Action Journal. Every finch run emits an Action Journal entry to `{agent_root}/commons/journals/ocas-finch/`.

**Cooperation:**
- Receives: Session transcripts (read-only, from the agent's session store)
- Reads: BehavioralSignal files from the Corvus signal directory
- Emits: DecisionRecords to the Finch decision log
- Writes: MEMORY.md (via memory tool), skill SKILL.md files (via skill_manage)

## File governance

See `references/file-governance.md` for write targets, read-only files, off-limits files, and reference file creation criteria.

## Signal types

See `references/signal-types-table.md` for the full signal type table.

## Behavioral directives (priority 0)

When the user says "Always" or "Never", this is an explicit behavioral rule. **Priority 0** — highest priority. Apply immediately and prominently. Route to MEMORY.md under `## Always Rules` or `## Never Rules`. Never batch with lower-priority findings.

## Core loop

Finch operates as a continuous improvement cycle:

1. **Scan** (`finch:scan`, every 2h) — Read 6 signal sources (cron health, email, calendar, sessions, Drive, system). Validate existing tasks. Maintain prioritized task list at `task-list.json`.
2. **Work** (`finch:work`, every 30 min) — Pick top pending task. Load governing skill via `skill_view`. Execute ONE task per run. Route findings to MEMORY.md, skill patches, or reference files.
3. **Mine** (`finch:daily` / `finch:weekly`) — Process session JSONL files for signals: corrections, directives (Always/Never), course changes, breakthroughs, methodologies, stop signals. See `references/mining_methodology.md` for the full methodology.
4. **Route** — Direct each finding to the optimal target: MEMORY.md (corrections, directives), skill patches (methodologies, edge cases), or reference files (cross-session patterns). See `references/file-governance.md` for routing criteria.
5. **Journal** — Every run emits Action Journal + DecisionRecord to `decisions.jsonl`.

### Failure-phase taxonomy (from arxiv:2508.13143)

When mining corrections and failures, categorize each by the task phase where the failure occurred. This taxonomy enables targeted skill patches instead of vague "be more careful" updates:

| Phase | Description | Example signal |
|-------|-------------|----------------|
| **Planning** | Wrong approach chosen, incorrect assumptions, missing prerequisites | "You should have checked X first" |
| **Execution** | Right plan but tool call/API/step failed, wrong parameters, timeout | "The command failed because..." |
| **Response** | Correct result but wrong format, verbosity, tone, or framing | "Too verbose" / "Wrong format" |

Route planning-phase corrections to skill preconditions/setup sections. Route execution-phase corrections to tool-usage/gotchas sections. Route response-phase corrections to output-formatting sections. This produces surgical patches instead of blanket directives.

### Elaborative interrogation (from Dunlosky et al. 2013)

When recording a correction or lesson, don't just capture WHAT was wrong — extract the underlying principle by asking "why" and "when":

- **Why was this wrong?** — What assumption was violated? What constraint was unknown?
- **When does this apply?** — What contexts trigger this pattern? What's the boundary condition?
- **What's the causal mechanism?** — Why does the correct approach work?

Format: `[CORRECTION] What: <what was wrong>. Why: <underlying principle>. When: <applicable context>`

This produces lessons that transfer across contexts, not just single-instance fixes.

### Forgetting-aware compaction (from Ebbinghaus curve)

MEMORY.md entries decay without reinforcement. During compaction:

1. **Reinforcement check**: For each existing entry, check if it was reinforced (re-encountered or re-applied) since last compaction. Entries reinforced within their expected half-life get a `§` durability marker.
2. **Decay candidates**: Entries not reinforced in 3+ compaction cycles are candidates for eviction — they've passed through the forgetting curve without strengthening.
3. **Priority for retention**: Directives (Always/Never) > Corrections with causal grounding > Bare corrections > Breakthroughs > Methodologies
4. **Consolidation**: Merge entries that share the same underlying principle into a single entry with multiple contexts. This mirrors memory consolidation in sleep — related traces merge into general principles.

See `references/forgetting_curve.md` for the compaction algorithm.

See `references/scan-work-architecture.md` for signal source details and governance rules.

## Commands

- `finch.run` — Full daily pipeline
- `finch.mine` — Mine sessions for signals only
- `finch.compact` — Compact MEMORY.md only
- `finch.route` — Route mined findings
- `finch.dry-run` — Full pipeline without applying changes
- `finch.status` — Show recent stats
- `finch.scan` — Run scan manually
- `finch.work` — Run work manually

## Scheduled tasks

| Job | Frequency | Behavior |
|-----|-----------|----------|
| **finch:scan** | Every 2h | Scan 6 sources → maintain task list |
| **finch:work** | Every 30 min | Pick top item → execute. ONE task per run. |
| **finch:daily** | Daily 6am PT | Mine 24h → Compact → Route → Auto-apply low-risk |
| **finch:weekly** | Sunday 8am PT | Mine 7d → Compact → Route → Full plan |

## Recovery Behavior

- **Evidence**: Every run writes to `evidence.jsonl` (including no-op runs with `not_activity_reason`).
- **Gap detection**: On every wake, checks evidence log. If gap exceeds expected cadence (2h for scan, 30min for work), logs `gap_detected` and runs compact remedial pass.
- **Degraded mode**: When Corvus signals unavailable, continues with available inputs. When session store unavailable, logs `degraded: session_store` and skips mining.
- **Log compaction**: Evidence/decision logs older than 30 days (no-op) or 90 days (error/gap) compacted. Last 7 days retained.

## OKRs

See `references/okrs.md` for targets (schedule adherence, data integrity).

|-----|--------|--------|
| `schedule_adherence` | ≥ 0.98 | 30 runs |
| `data_integrity` | 1.00 | 30 runs |

## Anti-patterns

See `references/anti-patterns.md` for the full list of 10 anti-patterns including declaration of victory and code fence pitfalls.

## Active review principle

See `references/active-review.md` for the full principle.

## Gotchas

See `references/pitfalls.md` for the full consolidated pitfalls list.

## Support File Map

| File | When to read |
|------|-------------|
| `references/active-review.md` | Before scanning for signals |
| `references/signal_patterns.md` | Before mining sessions |
| `references/mining_methodology.md` | Before first mining run |
| `references/scan-work-architecture.md` | Before configuring scan/work jobs |
| `references/skill-update-methodology.md` | After any session that produces a learning |
| `references/skill-update-directive.md` | During end-of-session skill review |
| `references/cleanup-and-health.md` | During system health audits |
| `references/external-skill-overlap-map.md` | Before creating evaluation skills |
| `references/git-skill-push-pattern.md` | When pushing skill changes to GitHub |
| `references/pitfalls.md` | Before any finch operation |
| `references/anti-patterns.md` | Before any finch operation — 10 anti-patterns including declaration of victory and code fence pitfalls |
| `references/okrs.md` | During OKR evaluation |
| `references/storage-layout.md` | When inspecting data directories or skill package structure |
| `references/forgetting_curve.md` | During MEMORY.md compaction — reinforcement scan, consolidation, eviction |
| `references/file-governance.md` | Before routing findings — write targets, off-limits files, creation criteria |
| `references/signal-types-table.md` | Before mining — signal type definitions and routing |

## Self-update

`finch.update` pulls the latest from GitHub. Runs silently unless version changed or error.

## Platform notes

Finch is designed for Hermes but degrades gracefully on other harnesses. Minimum viable platform: any harness with `write_file`, `read_file`, and `terminal` tools.