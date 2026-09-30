---
run: finch:work
scan_number: 1055
ts: 2026-09-30T22:34:48Z
task: ledger-scan167-future-timestamps
status: open
---

# finch:work #1055 — the writer made the defect a policy, and it is now refused

## Pick rationale (the substantive judgement)

#35 system-disk-rising is the top-of-list P1 and I did **not** pick it. Its own
last pass (#1053) recorded both gates unmet, level flat-to-falling, growth
measured and under trigger — a re-run would restate a measured state.

I picked #116 because the standing command I must run at the start of *every*
finch:scan and finch:work **is this task's own re_verify_trigger**, and it
returned a state never seen before: `laundered_count 0 -> 2`. A fired trigger
with a new state outranks a P1 whose gate is merely unmet.

The awkward part, recorded because it is the point: **#35 created the defect I
then fixed.** Its #1053 pass is the source of both laundered stamps.

## Pre-write guard (run FIRST, redirected to a file — never a pipe)

```
EXIT 1
VERDICT: 2 LAUNDERED LEDGER STAMP(S) PRESENT
  system-disk-rising  updated_at         2026-09-30T22:04:00Z   +265.1s vs receipt mtime 21:59:34.944315Z
  system-disk-rising  last_finch_review  2026-09-30T22:04:00Z   +265.1s
header stamps 5 checked, 0 forward | task stamps 0 forward
458 receipts, 0 unparseable
```

Prior pass (#1054, 22:20Z) recorded `laundered_count=0`. **State change, not a
restatement.**

## Root cause — from the receipts, not from prose

The two values were authored by finch:work #1053 and are fields
`finch_tasklist_single_write.py` copied verbatim from a hand-written payload.
The writer compared neither against the moment of the write.

`22:04:00Z` is a **round number**, and the receipt puts it +265s past the file's
own mtime. That is not clock skew. That is a pass summarising instead of
reading a clock. The detector was sound; the **write** created the offence, and
nothing stood between them.

The writer's own test suite made the gap a **policy** — `test_single_write_script.py`:

> "a forward-dated stamp is not this script's business to clamp; the ledger
> writer owns that."

That was true when written and false on this ledger, because *the ledger writer
IS this script*. The disclaimer is why the defect reached the file. I corrected
the docstring in the same commit rather than leaving a stale rationale behind a
new behaviour.

## The fix — prevention, not detection

`finch_tasklist_single_write.py` now **refuses** a payload whose stamps lie in
the future, before the lock and before any read-modify-write, so a rejected
payload leaves the ledger byte-identical.

**Refusing, not clamping** is load-bearing. A clamp substitutes a time the pass
never witnessed and then reports the write clean — the optimistic misreport this
task exists to kill, the same defect as #190's coverage-claim-as-measurement one
layer down. A refusal is loud, leaves no trace, costs one retry.

Scope is **five fields**, not one: `updated_at`, `last_finch_review`, `signal`,
`notes`, `work_log`. The guard reports per-field and the next pass quotes
whichever field it reads, so a stamp smuggled into `work_log` launders exactly
as well as one in `updated_at`. A test exercising only `updated_at` would pass
against a narrower fix — so there is a test for the other path.

Offsets compared as **instants, not strings**. A lexicographic compare reads
`16:00:00-07:00` as past when it is 23:00Z. That test is the negative case,
because a guard that only ever refuses is indistinguishable from one that
refuses everything.

## Validation — the part that matters

Both refusal cases **verified to FAIL against the pre-fix script**:

```
git stash -- scripts/finch_tasklist_single_write.py   # only the script
python3 tests/test_single_write_script.py             # FAILED (failures=2)
                                                         returncode 0 == it wrote the future stamp
```

Suite **10/10** after. The two negative cases pass both ways, so the fix
discriminates rather than blanket-refusing.

Green: `test_finch`, `test_single_write_script`, `test_single_write_shape`,
`test_reclaim_sizing`, `test_profile_resolution`, `test_finch_ledger_guard`
(20/20), `test_finch_scan_counter` (32/32). PII gate exit 0, 0 findings.

Two of my own errors, both wrong-path FAILs (`tests/test_…` vs `scripts/test_…`)
that I re-ran correctly rather than reporting. Committed `8ee8cfe` on a clean
`main` with **no rebase in flight** — unlike #204, which stopped short for
exactly that reason.

## Proven live, on the real file's shape

Replayed #1053's exact +265s stamps through the new writer against a **byte-copy**
of the live ledger:

```
EXIT 1 — updated_at, last_finch_review, work_log all named
ledger sha before = 772fd7fe…  after = 772fd7fe…   UNTOUCHED
```

## Post-write guard

`EXIT 1`, 0 forward, 2 laundered — **the same two, unchanged**. My write added
no stamp of its own. 459 receipts.

## Not repaired, deliberately

`--repair` exists, but rewriting third-party rows to a clock this pass did not
witness is the manual-workaround class this ledger exists to prevent. The prior
pass reached the same conclusion independently.

Counting precisely, and separating two things that were previously conflated:

- stamps **produced**: 4 → 2 (#956 → #1054), now **0 going forward**
- stamps **invisible**: 2 → 0 (only since #204's receipts existed)

## Status

Stays **open, P1**. The prevention gap in `blocked_reason` is now closed *at the
writer* — but registering `finch_hooks_plugin.py` remains an approval-class
change for Jared under the 2026-09-25 approvals rule, and one unwired
enforcement point is not a wired one.
