# Ledger, clocks, and the restore path — the dated reasoning

The three rules in SKILL.md that govern *when* a pass may write have a
rationale longer than a bullet. Each one below is a rule that was violated in
production before it was written, so the failure is recorded here with the
measurement that motivated it. Read this when a rule looks like it is being
arbitrary, or before changing any of them.

## 1. A restored occurrence re-fires the job (before step 1)

Added 2026-09-28, after the pipeline was re-fired 5 minutes after completing
and had to be made idempotent to avoid doing the work twice.

The scheduler's restore path re-dispatches an occurrence that was "taken off
the schedule but never claimed": `next_run_at` advances, the process dies
before claiming, and on restart the un-claimed occurrence is restored as the
due instant. Measured: **309 restore events in one day across 20+ jobs**,
silent per-job (`last_status` stays `ok`).

The `already running — skipping` guard cannot see it, because the first run has
already **completed** when the restore fires.

**The check:** read the most recent `daily-*.json` / `scan-*.json` for this job
and compare its `completed_at`/`as_of` against the current clock. If it falls
inside this job's own period (daily → the last ~24h, scan → the last ~2h),
this is a duplicate fire.

**Then:** record it as such in the journal, and **CONVERGE** — re-verify the
prior run's claims from disk, mine only the delta after its `completed_at`, and
decline every write that would redo completed work. A second compaction pass
over a near-cap MEMORY.md evicts a live directive for nothing; a second ledger
write duplicates tasks.

**Why catch-up does not cover it:** a duplicate window reads as a ~0h gap, so
every catch-up clause passes while completed work is redone. The two are
different defects that look alike in the arithmetic.

Run-id signature and the full detection recipe:
`references/pitfalls.md` § "A restored occurrence re-fires the job".

## 1a. A journal stamp must be in the field the NEXT gate reads (2026-10-01)

The writer (`finch_journal_write.py`) stamps `timestamp` from its own clock. It does
**not** create `completed_at`/`as_of` — supply them in `--doc` and the writer
preserves/clamps them to its real clock (verified 2026-10-01: supplying
`2026-10-02T09:00:00Z` was clamped to now, 2 stamps, 0 forward remaining).

Measured 2026-10-01 across 14 recent dailies, the stamp field name is
**inconsistent**: `timestamp` (most), `started_at` (09-30, 10-01), or
`completed_at`+`as_of` (09-27, 09-28). The duplicate-fire gate in SKILL.md step 3
reads `completed_at`/`as_of`. So an entry written only with `timestamp` is
**invisible to its own successor's gate**, and the successor cannot tell a duplicate
fire from a missed window — the exact confusion the gate exists to prevent.

- **(a) verify a stamp by the field the reader uses, not the field the writer
  emits.** A file that parses and validates clean can still be unreadable to the
  control that consumes it. `WRITTEN CLEAN` is the writer talking about clamping;
  it is not a claim that the gate can see the entry.
- **(b) the two probes that mattered here are cheap and general:** read the file
  back and check the field the *next* run will read, and supply a **forward**
  stamp in a throwaway probe to prove the writer clamps rather than trusts. A
  probe using only a past stamp cannot distinguish "preserved" from "clamped" —
  that fixture cannot fail.
- **(c)** a gap in the series caused by an unreadable field looks exactly like a
  quiet period. Both read as "nothing new"; only one is a defect.

### 1b. A PROBE THAT SEARCHES A PREFIX reports its own window as an absent field

Measured 2026-10-03 (finch:work #1134). A verification probe checked the four
stamp fields of a fresh journal entry with a regex over `read()[:2000]` and
printed `completed_at ABSENT, as_of ABSENT, timestamp ABSENT, started_at
ABSENT` — every field "missing", which reads as a clean and alarming finding.
`json.loads` on the whole file shows 10 top-level keys and a valid `timestamp`
at `05:37:46`, written **last**. The byte window, not the document, decided the
answer.

- **(a) a probe must PARSE the document it claims to inspect.** Coverage should be
  the document's own structure, never a byte offset chosen before the document's
  length is known. Write `json.loads(open(p).read())` and then look up keys.
- **(b) "absent" and "not reached" must print differently.** When a search can
  fail to reach its target, the output says so; a probe that reports its own
  incompleteness as a property of the world is the same failure as the stale
  `find` window in section 2 below, at a different layer.
- **(c) a control is what separates the two.** The one-line check that did it here
  was printing the file's byte length and its key count: 9,240 bytes and 10 keys
  cannot be an empty document. Cheap, and it fails if the probe is wrong.

Three probe defects landed in that one pass, and all three produced output that
read as a finding about the host: a `%`-format verb inside a `%`-formatted string
(the trap section 3a already records, hit again), a misplaced paren binding
`.mtime` to a string literal, and this prefix search. None were host defects. A
probe is an instrument, and its output is a claim about the world made from an
instrument — so a probe's own limits get the same treatment as a guard's
coverage: enumerate the sibling shape it cannot see before quoting its zero.

## 2. Close the ledger's own clock before and after writing

`python3 scripts/finch_ledger_guard.py` (`--repair` to fix, `--json` for the
`*_measured` flags) is mandatory at both ends of steps 1 and 2. No timestamp in
`task-list.json` may be later than the file's own mtime.

**The confirmed cause of violations** is a pass stamping from the scheduler's
`next_run_at` instead of `datetime.now()` at write. The slot is published in
`jobs.json` and looks like a legitimate "this cycle" clock, which is exactly
why it survived review. A stamp ahead of the write is a false-completion
variant that corrupts scan ordering and every "last reviewed" claim built on
it, so it is a **P1 finding, not a scan note**.

Exit 0 = clean, 1 = forward stamps present, 2 = ledger unreadable — **never
treat 2 as clean**. Read the VERDICT line, not the exit alone.

Full rationale and the journal-coherence findings:
`references/finch-scan-pitfalls.md` §11.

### The parser trap that hid a forward stamp for a day

The guard's `_parse()` was `fromisoformat(v[:19]).replace(tzinfo=UTC)`: it
dropped the 19th character onward, so a `-07:00` stamp read 7h *early*. A
stamp 43 minutes past the file mtime measured −22631s and exited 0 — a
safe-direction false negative produced by the instrument meant to catch it.

Two things let it survive review: the correct implementation was already in
the same file 40 lines below serving the journal path, so the diff read as an
improvement; and a fixture whose stamp is forward **under either reading**
passes before and after the fix and proves nothing — the case has to be
constructed so truncation and the true instant fall on **opposite sides** of
the mtime.

Two lessons from the repair, both caught by running the suite rather than
reading the diff: delegating to the stricter parser naively **broke** the
`' (finch:scan #N)'` suffix on `last_finch_review` (the old truncation had
tolerated it; `fromisoformat` on the whole string raises, so every suffixed
forward stamp became silently *missed*), and the first repair isolated the
timestamp with a 19-character regex — **reproducing the original bug inside the
fix**. Generalise: when a fix delegates to a stricter parser, re-run every
existing suite *and confirm the failure is yours* (`git stash`, compare against
HEAD) before assuming it is pre-existing; and a "test" whose fixture cannot
fail is decoration.

**Coverage is the union of shapes, not a flat key list.** The ledger header
records the same instant twice, as flat `last_scan_at` and nested
`last_scan.at`. The guard walked `HEADER_FIELDS` with `if k not in doc`, so the
nested copy was skipped **in silence** and its absence reported as a pass. When
you widen coverage, route the **repair** path through the same resolver too —
otherwise the guard can see a stamp `--repair` cannot clear, which is the same
false negative one layer down.

**Hand-typed prose times are invisible to the guard.** It inspects stamp
*fields*; a `01:55Z` written into a prose string when the write stamped
`01:46:59Z` is a forward stamp the guard cannot see. Derive prose times from
the same `datetime.now()` that produced the write — never re-type a clock
reading from memory or an earlier tool result.

**A fixture that asserts on a clock-measured window must not pin the clock
(added 2026-09-29, finch:work #1018).** `test_finch_ledger_guard_selfstamp.py`
pinned `COMMIT = datetime(2026, 9, 28, 3, 28, 58)` as an absolute instant while
the guard computes its "recent (≤24h)" window against the **wall clock**. The
suite therefore went red *by itself* at 2026-09-29T03:28Z — a day after it was
written — and would have stayed red forever, reading as an unrelated
regression. It was disabling a genuine repair: the failing direction *is* the
#232 fix that a 1.2h-old journal member must not be swept into a flat
"(historical)" clause.

Fix: derive `COMMIT` from `now()` and express every stamp as an **offset** from
it (`_at(offset_s, tag)`), so each direction keeps exactly the delta it was
written to test and only the epoch moves.

The trap it belongs to is already recorded from 2026-09-28 — "a tally over a
time window must print the number of files it actually iterated", where a
`sorted()` window silently contained **nothing**. This is the same defect at the
test-design layer: a window silently **emptied itself** as the calendar moved.
Both read as PASS or as an unrelated failure rather than as the bug they are.
The tell is identical in both cases: a fixed instant in a file that also
measures against `now()`.

**Prove a time-bomb fix under a moved clock, not once.** A fixture rebased to
`now()` and then only ever run in the current hour is the same time bomb
wearing a new hat. The check that distinguishes them is to run the suite with
the clock faked forward (+2d, +400d): 12/12 at all three offsets here. And
check that the fake-clock harness itself can fail — mine read `sys.argv[0]` as
the day offset and produced three *identical* failures, which is the tell that
it was broken rather than a result.

**A lead-stamp is a pass-identity claim, and a repair that only walks dicts
will leave it behind (added 2026-09-29, finch:work #1018).** A `work_log`
entry opening with a clock is claiming *when this pass ran*, so it obeys the
same rule as the `updated_at` beside it. finch:scan #1016 stamped 13 fields
and 6 narrative entries forward by 130s, caught itself within 55s, and
repaired the 13 — because its `fix()` had a `dict` branch and a `list` branch
but **no `str` branch**, and a `work_log` entry is a bare string *inside* a
list. The 6 survivors were **a permanent false record**: 21:55 when the pass
ran at 21:51, i.e. in the *past*, so no clock-based instrument can ever see it
— the guard reads fields, `ledger_forward_sweep.py` excludes prose by design,
and the watcher only reads receipts.

Three rules that came out of it:

- **A repair must report what it did NOT change, not just what it did.** That
  script printed the count of replacements and nothing about coverage, so a
  silently-partial repair read as a successful one. A count is not a
  completeness claim.
- **Clamp prose, but only a LEADING stamp.** `finch_ledger_write.py clamp()`
  now sweeps narrative keys document-wide. The pattern is anchored to the start
  of the string and `due_date` is excluded by key: a deadline is legitimately
  future, and a timestamp quoted mid-sentence is quoted *history*. Rewriting
  history would be a worse defect than the one prevented — measure which is
  which before widening a clamp's reach.
- **A clamp cannot repair a stale-but-false claim.** It pulls a stamp back to
  `now`; it cannot reconstruct the instant a past claim *should* have carried.
  The 6 survivors had to be corrected once by hand, and that limit is worth
  stating in the same breath as the fix rather than after it.

The general shape, now hit twice: **the guard's coverage and the writer's
coverage are separate claims, and a third tool (the sweep) covers a third set
of fields.** "All three report clean" was true and meant nothing — none of the
three read a `work_log` entry. When a new control lands, enumerate the
*sibling shapes* it still cannot see rather than trusting the count of tools
that agree.

- **A MISSING claim is not a wrong claim, and no clamp can supply one.**
  `find_unexpanded_lead_formats()` / exit 4 in `finch_ledger_write.py`, added
  2026-09-29. A pass that builds `"%s (finch:work #N): ..." % now` and stores
  the *template* writes a lead that asserts **no instant at all** — measured
  live, 2 such entries in 169 tasks, 23.9h and 2 days old, one of them this
  task's own `work_log[6]`. The guard reads stamps, the sweep reads
  timestamp-shaped strings, the watcher reads receipts: all three are silent,
  because there is nothing to compare. So the writer **refuses** (exit 4) rather
  than inventing a timestamp, and the same failure repeated inside the fix
  itself: the first version of the refusal message carried a literal
  `%-format` inside a `%`-formatted string and raised `TypeError` on the very
  write it was protecting. *Never put a `%`-format verb in prose that is itself
  `%`-formatted* — `%%`, or compose with `.format()`/f-strings.
- **Pre-existing debt must not brick the choke point.** A refusal that fires on
  damage the tool cannot repair stops the ledger moving and buries the debt
  under a failure nobody can act on. The control therefore refuses only
  damage **new to this write** and reports carried-through debt on stdout
  (`debt : N PRE-EXISTING ...`). Key that comparison on **(trail, full text)**,
  not trail alone: keying on the trail lets a *different* damaged entry written
  to the same list index pose as known debt and be waved through, which test 17
  caught in the first implementation.


### 3a. A DOCUMENTED repair path that was never wired up (finch:scan #1126, 2026-10-02)

Section 2 already said the rule — *"route the **repair** path through the same
resolver too, otherwise the guard can see a stamp `--repair` cannot clear"* —
and `finch_ledger_guard.py` implemented it: `NESTED_HEADER_FIELDS =
('last_scan.at',)` exists precisely because the header records one instant twice.
`finch_ledger_write.py clamp()` was never widened to match. It walked
`guard.HEADER_FIELDS` and `guard.TASK_FIELDS`, so:

- `--doc` clamped 7 flat stamps and silently left the nested one;
- `--clamp-only` then printed **`clamped 0 (every stamp is at or before now)`**
  on a ledger the guard was *simultaneously* flagging `VERDICT 1 FORWARD`.

That is a documented lesson that had been recorded and not built, and the
signature to recognise it is a repair tool reporting **zero changes** while a
verdict it exists to clear is live. Zero is what a passing clamp looks like.
Fixed by walking the dotted paths explicitly, leaving a missing/non-dict
intermediate alone; `test_finch_ledger_write.py` 32/32 after.

**A prose lesson in this file is not a code path in the script.** Two files in
one skill can disagree for months, and the document is the one that gets
re-read, so it accrues authority the code never earned.

### Never hand-write an instant in an apply script — take the clock AT WRITE TIME

Scan #1126 spent this rule's cost in the same pass: its apply script set
`NOW = '2026-10-02T23:30:00Z'` by hand against a real clock reading 23:28:57Z,
which manufactured a forward stamp the guard caught three times at +62.6s then
+34.9s. It resolved on its own when wall time passed the invented instant — and
the guard called the result **LAUNDERED**, which is precisely the failure mode
that records itself as a pass. The only cure is to derive the clock where the
write happens, so there is no instant in the model's output to be wrong.

The next paragraph's rule has a second identity worth keeping separate: the
scan counter guards against two passes minting one *number*, not against a bad
*clock*.

### 3. Allocate the scan NUMBER, don't compute it

The counter had the same class of bug as the guard and stayed unfixed until
2026-09-27. Never write `scan_number = header + 1`: that field is a plain
number each pass edits by hand, with no lock, so two passes overlapping in
wall-clock read the same header and mint the same number. Observed live:
`scan-174.json` and `scan-2000.json` both carried 174 while the header sat at
173 — neither run advanced it, which is the tell.

Call `python3 scripts/finch_scan_counter.py` FIRST and use the number it
prints. It flocks, floors on the max of (header, journals, journal prose,
sidecar) so a drifted header cannot re-mint a used number, and **burns** the
number durably before you write.

**BURNING rather than reserving is deliberate** — a pass that dies after
allocating loses a number, which is safe; a reused number corrupts the series.

### A harvest that samples fields is a coverage claim, not a measurement

The allocator floored on `run`/`source`/`summary` only, while the guard scanned
whole documents, so **26 of 33 prose-carried numbers — up to #157 — were
invisible to the floor** while the guard saw every one. The guard's own
`[COVERAGE]` count then used `re.search` (FIRST prose number only) and a
`(\d{2,3})` bound, so #91 was called lost while the series had already passed
176. Both now harvest the whole serialized document with `findall` and a loose
bound, and the two patterns are asserted byte-identical by
`test_finch_scan_counter.py`.

The general rule: **a floor may over-approximate safely** (it only ever burns
an unused number) and must never under-approximate; and when two tools read one
corpus, assert their SETS AGREE on the real data instead of trusting each to be
complete. The tests could not catch this because the fixture used `run`, the
one field the old code did read — a test pinned to the fields that happen to
work proves nothing about the ones that don't.

### Adjudicate a duplicate as a COLLISION, never by merging or deleting

A duplicate means two runs minted one number. The evidence that decides which
is which is (a) mtime order — earlier keeps the bare number — and (b) payload
identity: non-identical payloads mean two distinct runs, identical means one
run written twice and nothing to adjudicate. `scan_number_suffix` in the
journal body is what the guard keys on (`_adjudicated()`); **renaming the FILE
is a separate, riskier act**.

Worked cases: #132 — `scan-0608.json` vs `scan-1000.json`, non-identical, 3h57m
apart, so suffixed `132a` with the filename left alone because 6 files reference
it by name; unlike `scan-174.json`, which was renamed to `scan-174a.json`
because nothing did. Renaming a file that ingestion logs reference by name
dangles every reference, and editing an append-only log to match falsifies a
historical record.

## 4. A choke point on one write path is not a fix for the sibling

The ledger got `finch_ledger_write.py` after #179 showed detection losing; the
journal path kept emitting self-stamped entries with no equivalent, so the same
lie moved somewhere quieter. Measured: **38 of 168** journal files in 7 days
carry a stamp >60s past their own mtime, 2 under 24h, the newest being the
scheduler slot.

Three rules:
- **(a)** when you harden a write path, enumerate its siblings and ask which
  carry the same untrusted input — here the model typing a clock reading, and
  it types it in BOTH paths;
- **(b)** a guard's exit code is evidence about the guard's **coverage**, never
  about the world; attribution that improves never becomes prevention;
- **(c)** fix the ORDER when a tool both transforms and stamps — the first
  writer set `timestamp` before clamping, so a forward stamp in the caller's
  own `timestamp` was *erased* rather than clamped, passing every downstream
  check by deleting the evidence. **Clamp first, stamp second.**

Companion defect, same pass: a `sorted()` over a directory of files AND
subdirectories interleaves them, so a loop assuming `[-N:]` are all days
silently scans nothing. Counting "self-stamps in the last 6 days" returned
**0** while an independent whole-tree sweep returned 63. It read as clean
because zero forward stamps is what a passing check looks like. **Any tally
over a time window must print the number of files it actually iterated.**

## 4a. A MERGED SERIES hides a rename as a disappearance (2026-10-02, #1111)

`email-wealthfront-routing-number-cutover-oct1` carried, unverified for two days,
"the cash-account statement class stopped after 2026-09-17." It did not stop. Two
subject templates of ONE monthly event had been counted as a single series:

| era | subject | span | rows | median gap |
|---|---|---|---|---|
| old | `Your monthly Cash Account statement from Green Dot Bank is available` | 2020-10-17..2025-06-17 | 57 | 30.99d |
| new | `Your monthly Green Dot statement is available for your Individual Cash Account` | 2025-08-17..2026-09-17 | 14 | 31.04d |

Merged (71 rows) the gap distribution is **bimodal** and its median (15.04d)
belongs to neither era. Split, both medians are ~31d, the newest hit is the new
era's own latest, and the cadence was never broken. The "last" 2026-09-17 row
that made the series look finished was the new template arriving on time.

- **(a) before reporting an event class as stopped, split it by any
  discriminator that is not the one you are measuring by** — here, the subject
  template. A merged series manufactures a gap distribution that describes
  neither population, and a cadence rule over it fires on a healthy signal.
- **(b) a vendor's subject text is not an identity.** Match such a class by a
  STABLE STEM, exclude adjacent classes by an explicit NEGATIVE match (the
  brokerage statement interleaves around the 3rd-7th and 17th), and REPORT
  `templates_seen` so the next rename appears as a third template rather than as
  an absence. A keyword watcher scoped to one era is silent on the other era and
  reports it as a cessation — the blind spot is invisible precisely because the
  matcher still returns matches.
- **(c) "stopped" and "renamed" are indistinguishable from inside a single
  keyword.** Leaving the question UNVERIFIED was correct; leaving it at "the
  count dropped" was not. A finding parked as unresolved must carry the specific
  measurement that would resolve it.

### The 500-row ceiling is a measurement cap, not a sample

The first statement probe queried `from:wealthfront.com` and got exactly 500
rows with `at_max_results_ceiling: true`. Paging to exhaustion gave **780**. The
280 hidden rows included the entire older template era's tail, so the capped
query could not have seen the rename at all. **Always page a corpus you intend
to characterise, and print the page count next to the row count.**

### A count is not a series, and the diff must be inside the shape

The two probes used to corroborate ("subject without sender", "no sender") were
independently worded and **disagreed by 15 months** — a warning that the corpus
was being partitioned, not a measurement. The settled numbers (780 / 71 / 57 / 14)
come from one paged pull with a template discriminator, reported as counts *and*
spans together.

## 4b. A MUTANT THAT CHANGES NOTHING kills nothing (2026-10-02, #1111)

The drift guard was mutation-tested and the first mutant **SURVIVED**. It was not
a green result: it narrowed `STATEMENT_RE` only, but the predicate is an `or` of
two regexes and `STATEMENT_ACCOUNT_RE` still matched the new template on its own,
so the mutant never changed the behaviour under test.

- **(a) assert that a mutation APPLIED something before reading its verdict.**
  `mutant != source` is one line and catches the whole class. "The mutant
  survived" and "the mutation was a no-op" look identical from the exit code.
- **(b) reproduce the defect, not a neighbour of it.** The real #1107 error was
  scoping to the old template in BOTH regexes; the second mutant did that and
  turned the suite red at `test_both_template_eras_match`.
- **(c) run the mutation in a COPY and compare inode/device, not path.** A
  harness that mutates the live object to test a guard on that object destroys
  the thing it is measuring; `st_ino`/`st_dev` equality proves the original was
  not the thing that got tested.

## 5. A suite that asserts on MAGNITUDE only is blind to the SIGN

`find_stale_review_claims` refuses a write whose `last_finch_review` is older
than a `work_log` entry naming the same event (exit 5). Its tolerance is read
off a measured bimodal gap, and the recording of that measurement was wrong
twice: the firing population's **sign was inverted** (called negative; it is
positive — `lag > 0` fires), and "nothing sits near zero" was false (−80s
exists). The count 8 matched by coincidence, which is the worst way for a
measurement to be wrong — a reader checking only the count confirms it.

Twenty-five green directions did not catch either. Every one of them asserted
on a **magnitude** (2/4/6 min fires, equal/2min/4min does not). Reverting the
comparison to the sign-blind `abs(lag) > tolerance` leaves all five green,
because a larger firing population still refuses honestly-stamped writes.

- **(a)** measure the **shape** of a population — both sides of the threshold,
  with the nearest record on each — not just the threshold and the count.
  A tolerance justified by an overstated gap is one edit from being wrong.
- **(b)** when a comparison has a direction, **one direction must assert the
  sign at matched magnitude**. A side with no test is not an untested
  edge case; it is an unmeasured population.
- **(c)** a corrected measurement must **name the correction in place**.
  Quietly replacing a wrong number leaves the next reader to re-derive it,
  and "the number matched" is not evidence when the sign was inverted.
- **(d)** a control's own stated evidence is re-measured, not trusted, when
  the control ships as **uncommitted work with no recorded claim** — the one
  thing none of the instruments can see is a change nobody wrote down.

Note the negative side needs **no tolerance at all**: firing is `lag >
tolerance`, so a negative lag is excluded by the sign whatever the tolerance
is. State that structurally rather than leaving a reader to assume a
mirrored threshold exists on both sides.

## 6. A gate's own scan path can make it structurally incapable of firing

`check_no_pii.py` classified each finding as shipping or host-local with
`ships = rel_repo in tracked`, where `tracked` is `git ls-files`. Two things
follow, and the second is the one that bit.

**An untracked-but-unignored file is invisible.** `git ls-files` lists the
index, so a new file that is not ignored is not in it — and a file that
`git add -A` is about to stage is exactly that. Measured 2026-09-30:
`references/gmail-content-batch-call-shape.md` carried three real Gmail
thread ids, the gate printed them each with `(gitignored, does not ship)`, and
`git check-ignore` confirmed **no rule matches it** — it would have shipped.

**A `--path` scan made the pre-commit hook inert.** `REPO` is derived from
`Path(__file__).resolve().parents[1]`, but the hook scans a temp tree of the
staged snapshot under `/tmp`. Every file therefore fails
`relative_to(REPO)`, took the `ValueError` branch, and was labelled
non-shipping — so the hook exited 0 against a staged, confirmed leak. The
gate that exists to stop the publish was incapable of reporting it, and CI,
which runs the same gate, only runs **after** the push to a **public** repo.
That is the 2026-09-26/27 leak the hook was written to prevent, with the hook
present and green. Fixed: a file whose location cannot be placed in the repo
is treated as shipping.

- **(a)** a classification predicate must be tested on its own boundary: what
  does it return for a file it cannot place? "Unknown" is not "clean".
- **(b)** a gate that runs **before** a publish and a gate that runs after it
  are not the same control. Only the first one prevents; the second only
  reports, and by then the data is public.
- **(c)** a control wired into a path it never scans is decoration. Exercising
  it against the real staged state is what turned "exit 0" into "exit 1".

### 6a. The half of a two-part fix that stops at the first half (2026-09-30)

The fix above repaired **one** of the two defects and reported the pair as
closed. The `ValueError` branch was fixed; `ships = rel in tracked` was left
exactly as it was, and that is the half the *root* scan uses on every ordinary
invocation. Measured on the live tree the same day: 5 untracked, unignored
files were each tagged `(gitignored, does not ship)` while the scan exited 0.

**The tag is the tell, and it is checkable without trusting anything else.**
A gate that prints a *reason* it skipped a finding must be able to prove the
reason. "(gitignored)" is a claim about `.gitignore`, and it is answerable in
one `git check-ignore` call. The old code never made that call — it inferred
the reason from index membership, a different question, and printed a
conclusion about a file it had not examined. This is the same shape as the
`#181` empty section and the `0 adapters connected` counter: a report of a
condition it did not measure.

**Why the "already fixed" reading was so available.** The 09-30 pass verified
its fix on a *copy* of the tree, on the `--path` branch only, and its own
signal said "FIXED BOTH". The copy could not surface the unfixed half, because
the unfixed half is reached through a *different invocation* of the same
script. Verifying a fix on a copy tests the copy.

- **(a)** a fix with N parts must be checked against N *invocations*, not one
  script's existence. Enumerate the entry points and ask which of them reach
  the changed branch.
- **(b)** when a repair is recorded as complete, re-run it **on the live
  object** it will govern. A copy proves the copy.
- **(c)** an intermediate state between "before" and "after" is a real state.
  The 09-30 pass read its own successful `--path` result as evidence about
  the root scan, which it had never run. A fix is not done when its *first*
  symptom clears.
- **(d)** a printed skip-reason must be derived from a measurement of the
  condition it names, not from a proxy that happens to correlate.
- **(e) a repo gate's own literal test fixtures are shipping content.** The
  new direction needed an address-shaped string; written literally it tripped
  the very gate being tested, and the fix was to build the literal at runtime —
  the convention the adjacent token test already used. A test for a leak
  detector that leaks is a self-inflicted false green.

## 7. An EMPTY schema is not an empty store, and a journalled result is not a file

Both measured in the same 2026-10-01 pass, and both are the same shape: a
zero that reads like a clean result.

**The empty schema.** `state_fresh.db` has the full `sessions`/`messages`
schema and **0 rows**. A query against it returns an empty set, which is
byte-for-byte what "no interactive sessions in the window" looks like. The real
store is `state.db` (measured: 2129 sessions / 96015 messages). Had the window
been read from the first file, this pass would have reported **zero signals
across zero sessions** — a complete, confident, wrong mining result.

- **(a) a count must name the population it iterated.** Print the table's total
  row count alongside the windowed query, and treat rows-in-schema-but-0-rows
  as a store that was never written to.
- **(b)** a "no signal" verdict is the finding that most needs a positive
  control: re-run it against a store known to hold data.

**The unwritten result.** The 13:26Z daily recorded
`chars_before 2130 -> chars_after 1510` with an `applied` count, while
MEMORY.md's mtime was ~30h older than the claim and the file measured 2130
before *and* after. `memory_guard.py --json` returned `idempotent_noop: true`,
`evicted: []` — so the claimed result was **not achievable by the sanctioned
writer** at all; the record described an outcome the only permitted path cannot
produce.

- **(c) verify a reported result against the artifact in the same pass that
  reports it.** The journal read clean and would have stayed clean.
- **(d)** where a workflow has a sanctioned writer, a hand-typed result field is
  an assertion the system cannot check. Make the writer the only path that can
  set it, or the field will eventually record an outcome nothing performed.
- **(e) a claim describing an impossible outcome is stronger evidence of a
  reporting defect than of a transient error** — it rules out "the write ran and
  was later reverted." The write never ran.
