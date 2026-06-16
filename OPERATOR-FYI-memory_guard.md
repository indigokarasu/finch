# FYI — operator added a deterministic memory-cleanup safety guard (2026-06-16)

**What changed (by the operator, not by you):**
- New script: `skills/ocas-finch/scripts/memory_guard.py`
- Wired into `references/forgetting_curve.md` Step 7 (the Write step) as the **mandatory final step** of `finch.compact`:
  `python3 ~/.hermes/profiles/indigo/skills/ocas-finch/scripts/memory_guard.py --apply --emit-decision`

**Why:** MEMORY.md compaction had been drifting *over* the cap — the `memory` tool was repeatedly
rejecting writes (`Replacement would put memory at 2,226/2,200 chars`, also 2,445 / 2,520 …), and the
old approach had no atomic/locked write, so an OOM mid-write could corrupt MEMORY.md. The LLM procedure
decides *what* to keep/route/consolidate; this guard provides the *guarantees* it can't.

**What the guard does (deterministic, line-preserving — it never rewrites or reorders your entries,
so it can't erode them):**
- Enforces the hard char cap by evicting only the lowest-priority **non-directive** lines (Always/Never/Must are protected and never auto-evicted).
- Strips `see references/…` pointer lines (the documented "grows back over 2,200" anti-pattern).
- Writes atomically (temp + fsync + rename) under a PID lock, with a timestamped backup in `.backups/` — OOM-safe and race-safe vs the live `memory` tool.
- Archives anything it removes to `commons/data/ocas-finch/memory_archive.md`; logs a DecisionRecord.
- Is a **no-op** when MEMORY.md is already compliant (prevents churn). Verified: 13/13 isolation tests pass.
- If it warns `STILL OVER CAP` (directives alone exceed the cap), that needs your consolidation or human review — it deliberately will not evict directives to fit.

**Please take ownership of it:**
1. **Commit it to the skill's git repo** — it's currently untracked; your `self_update` could otherwise clobber it.
2. **Confirm the canonical MEMORY.md path.** Two exist (`~/.hermes/MEMORY.md` and `~/.hermes/profiles/indigo/MEMORY.md`); the guard defaults to `$HERMES_HOME/MEMORY.md`. Point Step 7 at whichever your `memory` tool actually writes (pass `--file` if needed).
3. **Add the test cases to `evals.json`** (cap held, directive never lost, atomic under kill, idempotent, transactional — the isolation tests cover these).
4. **Make the guarantee independent of you remembering to call it** — schedule it as a small deterministic floor (a finch cron post-step or systemd timer running `memory_guard.py --apply`), so the cap is enforced even if a compaction run is skipped or crashes.
5. **Surface failures** — wire the guard's `STILL OVER CAP` warning / failed runs into the custodian cron-health monitor (see the operator's separate custodian FYI) so compaction problems alert instead of failing silently.
6. **Future extension (the deeper spec):** add a persisted reinforcement-state store (`commons/data/ocas-finch/memory_state.json`: entry → {reinforcement_count, last_reinforced_at, half_life}) so the Ebbinghaus schedule is actually computed across runs instead of re-guessed each cycle, and make tier-routing transactional (verify the entry landed in the target tier before removing it from MEMORY.md).

The guard is the safety floor; your forgetting-curve algorithm remains the brain. Backup of the edited
reference doc is at `references/forgetting_curve.md.bak.preguard`.
