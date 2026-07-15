# ocas-finch Operational Gotchas & Script Detail

Extracted from `SKILL.md` to keep it under the 449-line D3 cap. Full bodies here; `SKILL.md` carries pointers.

## Gotchas (verbose bodies)

### `memory` tool may be unavailable in cron
If the `memory` tool returns unavailable during finch daily/compact runs, do not stop after reporting failure. Use the canonical profile memory path (`/root/.hermes/profiles/indigo/memories/MEMORY.md`) and perform the same operation by direct file edit, preserving the compaction cap and directive priority ordering. Treat direct writes as a fallback for cron execution only; re-read before writing if any sibling-write warning appears.

### MEMORY.md must not contain pointers to routed content
After tier routing, MEMORY.md should contain **only Tier 1 knowledge** — behavioral directives, cross-cutting corrections, and critical operating constraints. Do NOT add pointers like "see skill/references/X.md" for routed entries. Pointers add noise without value. If a session needs Tier 2/3/4 knowledge, it loads the skill or reads the reference directly. MEMORY.md is not a directory of everything the agent knows.

**Symptom of violation:** MEMORY.md grows back to 2,000+ chars after compaction because pointers were added for every routed entry.
**Fix:** Remove all pointers. MEMORY.md should be under 500 chars for a well-compacted library.

### Directive consolidation pattern
When two directives share the same underlying principle, merge them into one entry with combined provenance. This reduces MEMORY.md bloat and strengthens the surviving entry by showing it was reinforced across multiple sessions.

**Example from 2026-06-21:**
- "NEVER assume MCP broken without testing — verify first" (Jun 12)
- "NEVER state a wrong diagnosis with certainty — test simplest hypothesis first" (Jun 20)
- → Merged: "NEVER state a wrong diagnosis with certainty — test simplest hypothesis first. Verify before concluding." (Jun 12, Jun 20)

**Rule:** When merging, keep the more specific/vivid phrasing and list both dates. The merged entry is stronger because it was reinforced across sessions.

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
1. First call: `session_search(limit=20, sort='newest')` — identify which sessions are interactive (source=telegram/web/cli) vs cron.
2. Pull actual user messages with direct SQL, not `session_search` scroll. Use `sqlite3 /root/.hermes/profiles/indigo/state.db` and join `sessions` to `messages`, filtering `s.source!='cron'`, `m.role='user'`, and the desired `started_at` window. Scroll mode is unreliable because message IDs are global, not session-local.
3. Filter out context compaction, system notes, tool results, and messages shorter than 3 chars before signal extraction.
4. Only mine cron sessions for system-health signals (job failures, errors), never for behavioral signals.
5. **Query-based fallback when browse shows zero interactive sessions:** Browse mode returns at most 20 sessions, which can all be cron if the window is busy even when interactive sessions exist. If step 1 shows no interactive sessions, run targeted queries before concluding: `query="That's wrong"`, `query="No,"`, `query="Don't"`, `query="Actually"`, `query=YYYY-MM-DD` for each day in the mining window. Interactive sessions have user messages containing natural-language corrections that don't appear in cron prompts. Only report "no interactive sessions" after all keyword queries return zero non-cron results.
6. If no interactive sessions exist in the mining window, report "no interactive sessions — nothing to mine" rather than mining cron noise

**Confirmed pattern:** As of June 2026, a typical 24h window contains 50+ cron sessions and 0-3 interactive sessions. Mining without source filtering wastes the entire pass on cron noise.

### Skill usage analytics — state.db mining
For mining skill usage data from state.db (not behavioral signals), the opposite is true — cron sessions ARE the signal. See `util-skill-analytics` skill for the full procedure. Key differences:
- Use `JOIN sessions s ON m.session_id = s.id` (not `session_id`)
- `PRAGMA busy_timeout=30000` (gateway locks the DB)
- Parse `tool_calls` JSON in Python (LIKE is a full table scan)
- Filter by `source != 'cron'` for interactive-only analysis

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

**Gotcha**: The old two-branch logic (`name != "profiles"`) fails when `HERMES_HOME` is already the profile directory (name is e.g. `"indigo"`, not `"profiles"`), causing double-nesting to `profiles/indigo/profiles/indigo/MEMORY.md`. Fixed in `scripts/memory_guard.py` as of 2026-06-21 — the script now uses three-branch logic: (1) detect if HERMES_HOME already IS the profile dir by checking `name == _HERMES_PROFILE && MEMORY.md.exists()`, (2) standard `profiles/` subdir layout, (3) fallback to HERMES_HOME directly.

### Two evals.json files must be kept in sync
There are two `evals.json` files: `evals.json` (root) and `evals/evals.json` (subdirectory). Both must be updated when adding/removing test cases. The root one is the canonical reference.

## Scripts (verbose detail)

### memory_guard.py eviction priority — Methodologies outrank Course Changes
The memory guard's `LOW_PRIORITY_REFILE` regex and eviction sort order can evict Methodologies entries while keeping bare Course Changes entries. This is wrong — Methodologies (actionable techniques) are higher value than Course Changes (historical pivots).

**Symptom:** After guard runs, Methodologies section is empty but Course Changes still has entries.
**Confirmed:** 2026-06-21 — guard evicted "Root-cause-first debugging" (Methodologies) while keeping "Seamless task-switching" and "Budget exhaustion" (Course Changes).

**Mandatory post-guard verification (Step 7.5):**
After every guard run, BEFORE writing the final MEMORY.md:
1. Check if any Methodologies entries were evicted
2. If yes: restore the highest-value Methodologies entries by consolidating or removing Course Changes entries to make room
3. Never leave MEMORY.md with Course Changes intact but Methodologies empty — this inverts the priority ordering

**Fix needed in guard:** The guard's eviction sort should rank: Directives > Corrections > Methodologies > Course Changes > Pointers. Currently Methodologies and Course Changes are both in the "non-directive" bucket with no differentiation. Until the guard is fixed, the manual Step 7.5 workaround is MANDATORY.

```bash
# Dry-run report
python3 scripts/memory_guard.py

# Enforce + safe-write
python3 scripts/memory_guard.py --apply --emit-decision

# JSON output
python3 scripts/memory_guard.py --json
```

Run as Step 7 of `finch.compact` or independently via `finch:memory-guard-floor` cron (every 6h).

### self_update.py / self_update.sh
`self_update.py` must be a real Python wrapper (not a bash script with a `.py` extension) and must resolve the skill directory from `Path(__file__).resolve().parents[1]`, never from a hardcoded default-profile path like `/root/.hermes/skills/ocas-finch`. Manual Finch runs should execute `python3 scripts/self_update.py` and require exit 0 before reporting update health. `self_update.sh` is the GitHub-version fetch/install path; if it exits 1 with no output, inspect the `gh api`/remote-version step rather than treating Finch as generally broken.

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
