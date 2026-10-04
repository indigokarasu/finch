## Manual run, commands, recovery

"Run finch" = verify ALL deployed jobs are healthy and force runs where needed. Force an LLM job by **pausing, then running**; `no_agent` jobs run directly. A queued run is not a completed run — confirm `last_run_at` advanced. Job set, verification gate, 401 triage, cron-rebase breakage: `references/manual-run-verification.md`.

**The scan allocator's floor has a HOLE, and its own counter field hides it.**
`finch_scan_counter.py` floors on header + journals + journal prose + sidecar, and
it prints `ledger_scan_number` from the **HEADER only**. A ledger whose `work_log`
carries `#1167 (finch:work)` has live scan numbers that exist in no header and in
no journal filename, so the counter prints a stale header and mints them again —
three times in one pass (1167, 1168, 1169) before returning the first free one.
**When a pass has worked the ledger within the hour, compare the allocated number
against the ledger's own task prose before using it**, and take the LAST
allocation when several are burned. The number is still allocated, never computed;
the defect is in the floor's corpus, not in the allocation.

**df's Use% is `used/(used+avail)`, and the naive `used/total` form can print
~100% where df prints 85%** — on ext4 the reserved-for-root pool makes `f_bfree`
small relative to `f_bavail`'s sibling, and dividing by block count ignores it
entirely. A disk probe that reports a level df has never reported is a probe
defect until proven otherwise: **resolve it against a CONTROL (does the formula
reproduce df's own column?) and an INTERVAL (census in, census out, count the
swing over seconds, record the min and max), never two point-in-time counts.**
Measured 2026-10-04 (#1170): the first probe printed ~100% with `f_bfree` near
zero; two live reads four minutes apart then disagreed by 14.8 GiB while df
agreed with the later one; 8 samples over 35.0s settled it at a 0.125 GiB swing.

**Two coverage joins are both called "correct" and they answer different
questions.** For lost-fire occurrences, the **span join** (does some body in
flight overlap the refusal train in wall-clock terms?) asks whether the WORK ran;
the **exact join** (all rows sharing `job_id` AND `scheduled_instant`) asks whether
the OCCURRENCE produced a row of its own. #1167 covered a 6-row cohort by span
against a body stamped to a different instant; the same cohort is uncovered on the
exact join on #1169 and #1170. Neither refutes the other and neither is a bug —
but a coverage number quoted without naming its join is unreadable. **Name the
join in the sentence, every time.**

Commands: `finch.run` (full pipeline) · `finch.mine` (signals only) · `finch.compact` (MEMORY.md) · `finch.route` · `finch.dry-run` (no changes) · `finch.status` · `finch.scan` · `finch.work`.

**Recovery**: every run writes `evidence.jsonl` (no-ops included); a gap beyond cadence logs `gap_detected` and triggers a remedial pass. Missing Chronicle signals → continue; missing session store → log `degraded: session_store`, skip mining. Log compaction: no-op >30d, error/gap >90d; last 7 days retained.

**Review**: OKRs at `finch:weekly` → `references/okrs.md`; 10 anti-patterns → `references/anti-patterns.md`. Active-review principle → `references/active-review.md`: no signal found is a missed learning — patch the skill in play, don't create a narrow new one.

