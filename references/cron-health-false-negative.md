# Cron-health "0 errors" false-negative — repro + prevention

## Incident (2026-07-18, finch:scan 09:06Z)
- 07:05Z scan `cycle_note` asserted: "all 150 indigo-profile jobs last_status=ok (0 error / 0 delivery-error / 0 consecutive_failures)."
- FALSE. Job `<cron-job-id>` ("Engineering Manager — <other-ocas-skill> Escalation Handler", every 10m) had been erroring `KeyError: 'HERMES_KANBAN_BOARD'` since `2026-07-18T01:52:22-07:00`.
- 09:06Z scan caught it: 1 job in `grep` error set. Sibling handler `b1ae8917c3a2` (BOOK) ran ok — failure specific to <other-ocas-skill> board lookup (missing env var / config key).
- This was a retrospective false-negative: 2 prior cycles reported clean while an every-10m job failed.

## Likely mechanism
The surface grep was run against a TRUNCATED `hermes cron list` view (e.g. `... | tail -80`). `hermes cron list` lists jobs oldest-first; the erroring job fell outside the visible tail window, so it was never grepped and the "0 errors" claim was emitted from the truncated/recollected view rather than the full output.

## Correct procedure (canonical)
```bash
# FULL output, no truncation, then grep for non-ok last runs:
hermes cron list --profile indigo 2>&1 | grep -iE "Last run:" | grep -viE " ok$" | head -40
# count jobs:
hermes cron list --profile indigo 2>&1 | grep -cE "^  [a-f0-9]{12} \[active\]"
```
- NEVER pipe `hermes cron list` through `tail`/`head` before the error grep. If you must page, page AFTER the grep, or grep the whole stream.
- The error count asserted in `cycle_note` MUST be the grep's actual stdout count — not a templated "all clean" or a recollection of a prior scan.

## Retrospective-correction discipline
If the current scan finds errors a prior scan's `cycle_note` claimed absent:
1. State it as a CORRECTION in the new `cycle_note` (e.g. "CORRECTION vs <time>: the 'all 150 ok' claim was INACCURATE — job X was erroring and missed").
2. Re-state the prior claim verbatim in the note (so the drift is visible in context).
3. Add a `cron-health` task (P2 by default for an actively-recurring error) with `source_ref` = the job ID, the exact error string, and `last_finch_review` timestamp.
4. Do NOT edit the prior scan's journal/task-list to "fix" history — correct forward only.

## Cadence-nuance correction (added 2026-07-18)
The original "had been erroring every 10m ... since 01:52Z" wording was **itself imprecise** — the per-run artifacts show the <other-ocas-skill> job errored ONCE at 01:52:22, then ran OK at 02:14:58 and 02:26:28. It was a *single* transient error (an inherited-env gap after a gateway restart), not a sustained every-10m failure. The scan's `cycle_note` over-claimed a cadence the artifacts contradicted.
**Lesson:** when a scan asserts a sustained/recurring cadence ("erroring every Nm since T"), cross-check it against the job's per-run output files (`cron/output/<jobid>/`) and `jobs.json` `last_error` before trusting the cadence. A single error sandwiched between two OKs is a transient gap, not a persistent loop. Source of truth = the artifacts, not the scan summary. (The env-propagation root cause + the durable `.env` fix + a re-runnable verification script live in `skills/<other-ocas-skill>/references/kanban-board-env-keyerror-2026-07-18.md` and `scripts/verify_kanban_env.py`.)

 ## Incident (2026-07-22, finch:scan ~23:05Z) — scope-miss variant

 - 22:34Z scan `cycle_note` asserted "NO new genuine cron faults" / "all active jobs ok."
 - FALSE. Job `3ddbc4948ee8` (rally:daily-performance) had `last_status=error`,
 `last_run 2026-07-22T14:17:28 PDT` (= 21:17Z) — an error PREDATING the 22:34Z scan by ~1h17m.
 - The 23:05Z scan re-enumerated `jobs.json` fully and caught it: `'tuple' object has no attribute 'get'`
 (a genuine code defect, not transient — recurs every run until fixed).
 - Mechanism here was NOT truncated output (jobs.json WAS read). It was a **scope/assertion miss**: the
 prior scan failed to verify that every currently-flagged job's error was either already on the task
 list, a known transient, or newly captured — and emitted a "clean" claim that the next full
 enumeration contradicted.

 Lesson (additive to the canonical procedure above):
 - The "0 errors" / "no new faults" claim MUST be derived from a FULL re-enumeration of `jobs.json`
 `last_status=error` (and `last_error` non-null) on THIS scan — NOT carried forward from a prior
 scan's `cycle_note`. A prior "clean" claim is not evidence; re-prove it every cycle.
 - For each flagged job, classify the error as (a) already on the task list, (b) a known transient
 (consecutive_failures=0, recurring benign pattern), or (c) genuinely new. Only (c) is a "new fault."
 But a prior scan that reported 0 new while a (c) sat in jobs.json is a RETROSPECTIVE FALSE-NEGATIVE —
 correct it forward per the discipline above (state the correction, add the task, never edit history).
 - Source of truth = the live `jobs.json` file, re-read every cycle. Never trust a prior scan's summary
 as the current health state, even one written ~90 minutes earlier.
