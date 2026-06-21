---
name: ocas-finch
description: 'OCAS self-improvement orchestrator (Darwin''s finch — adaptive evolution). Mines session JSONL files to detect corrections, breakthroughs, methodologies, course-changes, and behavioral directives (Always/Never). Routes each finding to the optimal storage tier: MEMORY.md, skill files, reference files, or Chronicle KG. Compacts MEMORY.md by routing entries to the correct tier. Part of the OCAS System Evolution Layer alongside Mentor, Fellow, and Forge. NOT for real-time behavioral adaptation, skill evaluation, or skill creation.'
license: MIT
source: https://github.com/indigokarasu/finch
includes:
- references/**
metadata:
  author: Indigo Karasu (indigokarasu)
  version: 2.15.0
tags:
- self-improvement
- session-mining
- behavioral-adaptation
- OCAS-core
triggers:
- self-improvement
- session mining
- behavioral adaptation
- skill evolution
- correction detection
---

# ocas-finch

Finch is the OCAS System Evolution Layer's self-improvement orchestrator. It operates as four pure-LLM cron jobs:

- **finch:scan** (every 2h) — Scans 6 signal sources, validates existing tasks, maintains prioritized task list
- **finch:work** (every 30 min) — Picks top pending task, loads governing skill, executes one task per run
- **finch:daily** (daily 6am PT) — Mines 24h of sessions, compacts MEMORY.md, auto-applies low-risk findings
- **finch:weekly** (Sunday 8am PT) — Mines 7d, full pipeline with SOUL.md/USER.md recommendations

All four jobs are pure LLM cron prompts. No Python scripts at runtime. Deprecated scripts are in `archive/`.


## Interactive Menu

When invoked interactively, present a two-level menu. See `references/interactive-menu.md` for the full two-level menu layout, Clarify timeout behavior, response parsing, and platform adaptation.

## Responsibility Boundary

ocas-finch owns its core domain operations.

ocas-finch does not own: trigger detection, session management, or cross-skill orchestration (those belong to the calling agent).

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

## Scanning Gotchas

- **Verify tool availability before parallel batches**: When finch:scan calls multiple tools in parallel, one invalid tool name poisons the entire batch — ALL calls return "Skipped" with no partial results. Always verify tool names exist before batching. The `cronjob` tool does NOT exist in all session profiles. Use `search_files` or `terminal` to inspect cron state when unavailable.
- **Stale errors from `hermes cron list`**: The text output of `hermes cron list` shows the full history of each job. A job that failed at 14:00 but recovered at 15:00 will still show the error line. **`grep -B1 "error:"` matches these stale errors, inflating the error count.** Always verify the `Last run:` timestamp is from the latest run before counting an error as active. If the last run shows `ok`, the error is stale and should not be counted or reported. Observed 2026-06-13: 9 grep hits but only 3 were actual transient errors; the rest had already recovered. Create tasks only for persistent issues that won't self-resolve.
- **Only report actual fixes, never stale/transient issues**: User explicitly stated: do NOT report transient errors, already-recovered jobs, or stale errors. If nothing was actually fixed or changed, say "Nothing new" and stop. Reporting noise wastes the user's time.
- **Never force model overrides on cron jobs**: Only `openrouter/owl-alpha` is available. If a job's output is too large and truncated, fix the prompt to be more concise — never pin a different model in the cron job config.
- **Maintain a skill index**: Build and maintain `~/.hermes/profiles/indigo/references/skill-index.md` listing all skills and their GitHub repos. Refer to it instead of re-deriving from scratch every time. After any skill file modifications, commit and push to the source repo immediately.
- **Push local changes to GitHub (MANDATORY — user directive)**: After modifying any skill file (SKILL.md, references/, scripts/), **always** commit and push to the source repo immediately after testing and code verification. `git add -A && git commit -m "sync" && git push origin main` (or `--force` if remote diverged). **Do not wait for the user to ask.** This is an explicit user directive ("ALWAYS... automatically push and merge... Do not wait for the user to ask"). Never leave local changes uncommitted.
- **Disk-before-auth diagnostic**: When ALL Google MCP services fail simultaneously, first check `df -h /`. ENOSPC produces errors that look like auth failures. Do not generate auth URLs or ask user to re-auth while disk is full. See `references/session-2026-05-31-disk-recovery.md`.
- **`execute_code` is BLOCKED in cron jobs**: This tool is denied during cron execution. Use `terminal()` directly for all operations in cron context. For task-list.json updates specifically: use `terminal(command='python3 << PYEOF ...')` to read the file with `json.load()`, modify the dict in memory, and write back with `json.dump()`. Do NOT use `read_file` for structured files — it wraps content in a JSON structure with line-number prefixes (`1|`, `2|`, ...) that corrupt the data if passed through. See `references/pitfalls.md` for the full pattern.
- **`jobs.json` for cron health**: When the `cronjob` tool is unavailable in cron context, read `~/.hermes/cron/jobs.json` directly. Parse with `json.load()` and filter on `last_error=None` vs set — `consecutive_failures > 0` alone is not evidence of active errors.

## Architecture

- **All finch jobs are pure LLM**

**Role:** Session mining engine. Detects behavioral signals from conversation transcripts and routes them to durable modification targets (MEMORY.md, skill patches).

**Journal type:** Action Journal. Every finch run emits an Action Journal entry to `{agent_root}/commons/journals/ocas-finch/`.

**Cooperation:**
- Receives: Session transcripts (read-only, from the agent's session store)
- Reads: BehavioralSignal files from the Corvus signal directory
- Emits: DecisionRecords to the Finch decision log
- Writes: MEMORY.md (via memory tool), skill SKILL.md files (via skill_manage)

## File governance

See `references/file-governance.md` for write targets, read-only files, off-limits files, and creation criteria.

## Signal types

See `references/signal-types-table.md` for the full signal type table.

## Behavioral directives (priority 0)

When the user says "Always" or "Never", this is an explicit behavioral rule. **Priority 0** — highest priority. Apply immediately and prominently. Route to MEMORY.md under `## Always Rules` or `## Never Rules`. Never batch with lower-priority findings.

## Core loop

Finch operates as a continuous improvement cycle:

1. **Scan** (`finch:scan`, every 2h) — Read 6 signal sources (cron health, email, calendar, sessions, Drive, system). Validate existing tasks. Maintain prioritized task list at `task-list.json`.
2. **Work** (`finch:work`, every 30 min) — Pick top pending task. Load governing skill via `skill_view`. Execute ONE task per run. Route findings to MEMORY.md, skill patches, or reference files.
3. **Mine** (`finch:daily` / `finch:weekly`) — Process session JSONL files for signals: corrections, directives (Always/Never), course changes, breakthroughs, methodologies, stop signals. See `references/mining_methodology.md` for the full methodology.
4. **Route** — Direct each finding to the optimal storage tier: MEMORY.md (Tier 1: corrections, directives), skill SKILL.md/references/ (Tier 2: tool-usage, service gotchas), reference files (Tier 3: guides, paths, URLs), or Chronicle KG (Tier 4: entity facts). See `references/file-governance.md` for routing criteria and the tier model.
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

### Signal triage before execution (WORK step)

A task on the list may aggregate multiple distinct failure modes under one title (e.g., "cron 429 errors" that actually mix transient rate limits, script timeouts, and path blocks). Before committing to a fix:

1. **Decompose the task** — List the distinct error signatures from logs/jobs.json. Group by root cause, not by symptom label.
2. **Classify each group** — Transient (will self-resolve), persistent (needs intervention), or already-fixed (mitigation in place).
3. **Handle each group appropriately** — Transient groups get "monitoring" with a 24h recheck. Persistent groups get fixes. Already-fixed groups get a note that the Tier 1 was already applied.
4. **Journal the decomposition** — Record the group counts so the next finch:scan can check recovery per group, not just per task.

Do NOT assume a task with N affected jobs has one root cause. The task title is a scan heuristic, not a diagnosis.

MEMORY.md entries decay without reinforcement. During compaction:

1. **Reinforcement check**: For each existing entry, check if it was reinforced (re-encountered or re-applied) since last compaction. Entries reinforced within their expected half-life get a `§` durability marker.
2. **Concept classification**: Classify each entry by storage tier (see `references/forgetting_curve.md` § Storage Tier Model). Is this entry in the right tier?
3. **Tier routing**: Entries in the wrong tier get moved — tool-usage facts to skills (Tier 2), reference details to reference files (Tier 3), entity facts to Chronicle (Tier 4). Only evict if truly stale.
4. **Decay candidates**: Entries not reinforced in 3+ compaction cycles that cannot be routed to another tier are candidates for eviction.
5. **Priority for retention** (Tier 1 only): Directives (Always/Never) > Corrections with causal grounding > Bare corrections > Breakthroughs > Methodologies > Pointers to Tier 2/3 knowledge
6. **Consolidation**: Merge entries that share the same underlying principle into a single entry with multiple contexts. Within-tier only.

See `references/forgetting_curve.md` for the full compaction algorithm including the tier routing procedure.

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

## Skill Library Maintenance

After every session, review the conversation for signals and update the skill library. See `references/skill-library-maintenance.md` for the full procedure including signals that warrant action, preference order for updates, and what NOT to capture.

## Gotchas

See `references/pitfalls.md` for the full consolidated pitfalls list.

### MEMORY.md must not contain pointers to routed content

After tier routing, MEMORY.md should contain **only Tier 1 knowledge** — behavioral directives, cross-cutting corrections, and critical operating constraints. Do NOT add pointers like "see skill/references/X.md" for routed entries. Pointers add noise without value. If a session needs Tier 2/3/4 knowledge, it loads the skill or reads the reference directly. MEMORY.md is not a directory of everything the agent knows.

**Symptom of violation:** MEMORY.md grows back to 2,000+ chars after compaction because pointers were added for every routed entry.
**Fix:** Remove all pointers. MEMORY.md should be under 500 chars for a well-compacted library.

### FTS5 minimum token length

When mining sessions via `session_search` with `query=`, FTS5 silently drops tokens shorter than its minimum length (typically 3-4 characters). This means short-form correction signals are **invisible** to FTS5 queries:

- `"No"` (2 chars) → **dropped entirely**
- `"Don't"` → tokenized as `"don"` + `"t"`, both **dropped**
- `"Stop"` (4 chars) — borderline, may or may not match depending on tokenizer

**What to do:** When mining for corrections, always use `session_search` WITHOUT `query` (browse mode, no FTS5 filter) and read user messages directly. Use `role_filter=user` to narrow to user messages and scan for short-form corrections visually. Only use `query=` for multi-word terms (≥3 chars each) like `"actually wrong"` or `"don't do that"` where at least one token survives.

This applies to all finch jobs that mine sessions: finch:daily, finch:weekly, and manual finch.mine runs.

### Session source filtering — cron-skew problem

When `session_search` is called without a source filter, the results are overwhelmingly cron sessions (health monitors, heartbeats, dispatcher runs). These contain **zero** user-facing behavioral signals. Interactive sessions (where corrections, directives, and preferences live) are a small fraction of total sessions.

**Mining procedure — ALWAYS do this:**
1. First call: `session_search(limit=20, sort='newest')` — identify which sessions are interactive (source=telegram/web) vs cron
2. Second calls: `session_search(session_id='<interactive_session_id>', role_filter='user', window=20)` — read actual user messages from interactive sessions only
3. Only mine cron sessions for system-health signals (job failures, errors), never for behavioral signals
4. If no interactive sessions exist in the mining window, report "no interactive sessions — nothing to mine" rather than mining cron noise

**Confirmed pattern:** As of June 2026, a typical 24h window contains 50+ cron sessions and 0-3 interactive sessions. Mining without source filtering wastes the entire pass on cron noise.

### HERMES_HOME path resolution in scripts

When writing Python scripts that reference MEMORY.md or commons directories, never hardcode `~/.hermes/MEMORY.md`. The `HERMES_HOME` env var may point to either `~/.hermes` or `~/.hermes/profiles/<name>`. Use this pattern:

```python
HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
_HERMES_PROFILE = os.getenv("HERMES_PROFILE", "indigo")
# Handle three cases: (1) HERMES_HOME already IS the profile dir, (2) standard layout with profiles/ subdir, (3) fallback
if HERMES_HOME.name == _HERMES_PROFILE and (HERMES_HOME / "MEMORY.md").exists():
    PROFILE_HOME = HERMES_HOME
elif HERMES_HOME.name != "profiles" and (HERMES_HOME / "profiles" / _HERMES_PROFILE).is_dir():
    PROFILE_HOME = HERMES_HOME / "profiles" / _HERMES_PROFILE
else:
    PROFILE_HOME = HERMES_HOME
MEMORY_FILE = PROFILE_HOME / "MEMORY.md"
```

**Gotcha**: The old two-branch logic (`name != "profiles"`) fails when `HERMES_HOME` is already the profile directory (name is e.g. `"indigo"`, not `"profiles"`), causing double-nesting to `profiles/indigo/profiles/indigo/MEMORY.md`. Fixed in `scripts/memory_guard.py` as of 2026-06-21.

### Two evals.json files must be kept in sync

There are two `evals.json` files: `evals.json` (root) and `evals/evals.json` (subdirectory). Both must be updated when adding/removing test cases. The root one is the canonical reference.

## Support File Map

| File | When to read |
|------|-------------|
| `references/active-review.md` | Before scanning for signals |
| `references/signal_patterns.md` | Before mining sessions |
| `references/mining_methodology.md` | Before first mining run |
| `references/scan-work-architecture.md` | Before configuring scan/work jobs |
| `references/skill-library-maintenance.md` | After any session that produces a learning |
| `references/skill-update-directive.md` | During end-of-session skill review |
| `references/cleanup-and-health.md` | During system health audits |
| `references/session-2026-05-31-disk-recovery.md` | When investigating disk-full → MCP auth cascades, parallel tool batch poisoning, or emergency cleanup patterns |
| `references/external-skill-overlap-map.md` | Before creating evaluation skills |
| `references/git-skill-push-pattern.md` | When pushing skill changes to GitHub |
| `references/pitfalls.md` | Before any finch operation |
| `references/anti-patterns.md` | Before any finch operation — 10 anti-patterns including declaration of victory and code fence pitfalls |
| `references/okrs.md` | During OKR evaluation |
| `references/storage-layout.md` | When inspecting data directories or skill package structure |
|| `references/forgetting_curve.md` | During MEMORY.md compaction — reinforcement scan, tier routing, consolidation, eviction ||
|| `references/file-governance.md` | Before routing findings — write targets, tier model, off-limits files, creation criteria ||
|| `references/signal-triage-before-fix.md` | Before executing any finch:work task — decompose multi-failure tasks into distinct root causes ||
|| `references/custodian-error-investigation.md` | When a finch:work task involves a custodian error (e.g., custodian:deep Broken pipe) — investigation pattern for journal files and issues.jsonl ||
|| `references/signal-types-table.md` | Before mining — signal type definitions and routing ||
|| `references/interactive-menu.md` | When invoked interactively via `/` command — two-level menu layout, Clarify timeout, response parsing, platform adaptation ||
|| `scripts/memory_guard.py` | Deterministic safety floor for MEMORY.md — hard cap enforcement, directive protection, pointer stripping, atomic locked write. Run as final step of finch.compact or via finch:memory-guard-floor cron. ||
|| `scripts/memory_state.py` | Persisted reinforcement-state store — entry-key -> {reinforcement_count, last_reinforced_at, half_life, tier}. Use `reinforce`, `check`, `route`, `decay-report` subcommands. ||

## Scripts

### memory_guard.py eviction priority — Methodologies outrank Course Changes

The memory guard's `LOW_PRIORITY_REFILE` regex and eviction sort order can evict Methodologies entries while keeping bare Course Changes entries. This is wrong — Methodologies (actionable techniques) are higher value than Course Changes (historical pivots).

**Symptom:** After guard runs, Methodologies section is empty but Course Changes still has entries.
**Workaround:** After guard runs, check if Methodologies were evicted. If so, restore the highest-value ones by consolidating Course Changes entries to make room.
**Fix needed:** The guard's eviction sort should rank: Directives > Corrections > Methodologies > Course Changes > Pointers. Currently Methodologies and Course Changes are both in the "non-directive" bucket with no differentiation. Enforces hard cap, protects Always/Never directives, strips pointer anti-patterns, writes atomically under PID lock.

```bash
# Dry-run report
python3 scripts/memory_guard.py

# Enforce + safe-write
python3 scripts/memory_guard.py --apply --emit-decision

# JSON output
python3 scripts/memory_guard.py --json
```

Run as Step 7 of `finch.compact` or independently via `finch:memory-guard-floor` cron (every 6h).

### memory_state.py

Persisted reinforcement-state store. Computes Ebbinghaus forgetting curve across runs.

```bash
# Record a reinforcement
python3 scripts/memory_state.py reinforce "entry text" --tier 1

# Check decay status
python3 scripts/memory_state.py check "entry text"

# Transactional tier-routing (verify dest before removing from MEMORY.md)
python3 scripts/memory_state.py route "entry text" --to-tier 2 --dest-path path/to/skill/references/foo.md

# Full decay report (decaying entries first)
python3 scripts/memory_state.py decay-report
```

State stored at `commons/data/ocas-finch/memory_state.json`.

## Self-update

`finch.update` pulls the latest from GitHub. Runs silently unless version changed or error.

## Platform notes

Finch is designed for Hermes but degrades gracefully on other harnesses. Minimum viable platform: any harness with `write_file`, `read_file`, and `terminal` tools.