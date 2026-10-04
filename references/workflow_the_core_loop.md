## Workflow — the core loop

Finch owns its core domain operations; it does NOT own trigger detection,
session management, or cross-skill orchestration (the calling agent does).
Interactive invocation presents a two-level menu
(`references/interactive-menu.md`).

1. **Scan** (`finch:scan`, 2h) — read the 7 sources, update `task-list.json`. Cron health MUST come from the LIVE `jobs.json` (`references/cron-health-validation.md`), never `cronjob list` alone — it hides paused/disabled errors. Re-validate prior tasks both directions: re-open on relapse, resolve on recovery.
2. **Work** (`finch:work`, 30m) — pick the top pending task, load the governing skill, execute ONE. De-duplicate task IDs first (`references/duplicate-task-detection.md`), then append `[Work log: <timestamp> <summary>]` and set `status: "done"`, `done_at`, `updated_at`.
3. **Route** — classify scope first. A finding about this user's interaction preferences or their relationship with the agent goes to Chronicle/User Dreaming and MUST NOT become a global MEMORY.md rule or a skill patch. Agent/system-general findings route to MEMORY.md, skill patches, or references; proposed patches stage under `{agent_root}/commons/data/ocas-forge/staged/{skill}/` for `ocas-fellow` before production. Only genuinely system-general rules (priority 0) apply immediately.
4. **Journal** — every run emits an entry under `{agent_root}/commons/journals/ocas-finch/`. **Do not let the model stamp the journal time**: derive it inside the write path from the real clock and clamp it with the ledger writer's due-date exclusion. Omit `completed_at`/`as_of` from any hand-built journal doc too; supply them and the writer clamps them to its own clock, so the file contradicts your prose.

### Three gates before any write

Rules only — the measurements and the failure behind each are in
**`references/ledger-and-clock-protocol.md`**, which is also what to read
before changing any of them.

- **Restored occurrence, or new one?** Compare the newest
  `daily-*.json`/`scan-*.json` `completed_at` to the clock; inside this job's own
  period (daily ~24h, scan ~2h) ⇒ **record the duplicate fire and CONVERGE** —
  re-verify prior claims from disk, mine only the delta, decline every write
  that would redo completed work. *(A restore re-dispatches an unclaimed
  occurrence, `last_status` stays `ok`, and the `already running` guard cannot
  see it: 309 restores in a day across 20+ jobs.)*
- **Catch-up is a MISSED window only** — newest `daily-*.json` >24h old ⇒ expand
  the window and note it in the journal. *(It does not cover a restore: a
  duplicate window reads as a ~0h gap, so every clause passes while the work is
  redone.)*
- **A gate run BEFORE the write is not evidence the write was clean.** A pass
  must re-measure AFTER writing, from disk, and report *that*. Measured
  2026-10-02 (finch:work #1095): the prior pass listed "pre-write ledger guard
  EXIT 0 / LEDGER CLEAN" in its own pick rationale and the write it
  immediately followed left THREE forward stamps (+1947s) on the ledger. The
  receipts file is the proof, not the prose: `forward_count=0` before the write,
  `forward_count=3` after it. A guard cited as evidence FOR a pass is a claim
  about the world made from an instrument; only the post-write re-measure
  separates "the gate passed" from "the write was clean."
- **Claim a cohort rate with the COHORT'S JOB COUNT, or not at all.** A per-cadence
bucket is 2-5 jobs, so one job can wear 20+ rows and make a bucket look like a
scheduling effect. Measured 2026-10-04 (#1168): a prior pass reported `*/5 0/88`,
`*/10 23/161 (14.29%)` and read that as "the class separates cleanly on cadence"
— while its own mechanism (a 600s p50 lag defeats a 5-minute slot) predicted `*/5`
was the *worst* cohort. Re-deriving the buckets from `jobs.json` `schedule.expr`
reproduced the table exactly, so the numbers were right and the conclusion was
wrong: `email:draft` wore 21 of the 42 lost rows. **A bucket rate with no job
count is not a finding.** Pair every cohort rate with its distinct-job count and
its top-2 contributing jobs before naming a cause, and check the mechanism
predicts the ordering you measured — a mechanism that predicts the opposite of
your own table has just refuted itself. Corollary: re-deriving the same table next
pass is not new information; put the standing measure where the variation actually
is (per-job service time, not the bucket).

**`claimed_at` is a DISPATCH stamp; the fire claim starts at ADOPTION.** In
`cron/executions.py` the dispatching gateway writes the row via `create_execution`
and stamps `claimed_at` for EVERY due job at once (`scheduler.py:4350`), while the
fire claim and the body begin at adoption inside `_process_due_job`
(`scheduler.py:4283`), minutes later. So `claimed_at → started_at` is *queue
residence*, and a large value is a throughput property of the dispatch path, not
claim expiry — do not read it as the reaper TTL firing. Separate the two by
measuring queue depth (rows created but not yet running) and confirming with
Little's Law: `mean_lag ≈ depth × mean_duration` should land within ~2x on a
healthy path, and its ratio is a first read on whether a slow consumer or an
overfull queue dominates. Expect **50%+ of completed rows to start >600s after
dispatch on a saturated host** — that is normal, not a finding.

**`max_parallel_jobs` is per-FLEET-of-jobs, and one thread per job is not the
whole concurrency.** The tick resolves the pool via `_resolve_max_parallel_workers()`,
submits every due job to it, and each `run_one_job` opens a SECOND
`ThreadPoolExecutor(max_workers=1)` for the agent conversation
(`scheduler.py:2023`) while the gateway spawns an **external worker process** per
job (`scheduler.py:3965`). So: expect observed body concurrency to exceed the pool
size (size 1 → observed max 2 is correct, not a violation); expect one distinct
`pid` per execution row; and resolve the effective bound by *calling*
`_resolve_max_parallel_workers()` in a subprocess under the gateway's live
`/proc/<pid>/environ`, never by reading config files — a declared
`HERMES_CRON_MAX_PARALLEL` absent from the gateway environ is normal (the resolver
falls through to config) and is not proof the bound is inert. A bound that resolves
to 1 with a queue at p50 66 is *already in effect and is the reason for the queue*,
which makes "bound admission by free worker slots" a **config value Jared already
owns**, not a source patch.

**A refusal can be CORRECT and still block the truth from being written.**
  `finch_tasklist_single_write.py` scans a whole field for the ISO pattern and
  compares every match to `now()`, so a narrative that QUOTES a forward stamp
  is indistinguishable from one that ASSERTS one — the pass that diagnosed the
  defect could not record the diagnosis (#1095 aborted, exit 1, ledger
  untouched). Prefer a non-ISO rendering of a quoted instant ("02:05:00 UTC",
  "the same 02:05:00 reading") and say so in the entry: that is a workaround on
  your own content, not a repair of the tool. The durable fix is positional —
  only a stamp in a claim-bearing field, or at the LEAD of a narrative, is a
  pass-time claim, exactly the distinction `clamp_narrative_leads()` already
  draws in `finch_ledger_write.py`.
- **A writer that REFORMATS the ledger changes the file size without changing
  the data** — and a shrinking byte count is the #1058 record-loss signature.
  Measured #1095: the sanctioned single-shot writer emitted `indent=1` while
  the file on disk was `indent=2`, for −1,363 bytes on a write that ADDED a
  work_log entry. Do not adjudicate a delta by size. Verify record IDENTITY
  against a pre-write backup: task-id and scan_note-id sets and ORDER, plus
  per-task `work_log` lengths. Zero lost records plus a reindent is a clean
  write; a byte delta alone proves nothing either way.
- **Close the ledger's clock before AND after writing:**
  `python3 scripts/finch_ledger_guard.py` (`--repair`; `--json` for the
  `*_measured` flags) — no timestamp in `task-list.json` may be later than the
  file's own mtime. Exit 0 clean / 1 forward / 2 unreadable, and **2 is never
  clean**; read the VERDICT line, not the exit. *(A forward stamp is a P1
  finding, not a scan note.)*

**Allocate the scan NUMBER, don't compute it.** Call
`python3 scripts/finch_scan_counter.py` FIRST and use what it prints; it
flocks, floors on header/journals/prose/sidecar, and **burns** the number before
you write. Never write `scan_number = header + 1` — a hand-edited number with no
lock, so two overlapping passes mint the same one (observed: two files both 174
with the header at 173). Hand-adjudicated collisions get `scan_number_suffix`,
which the guard excludes from the series.

**Scanning traps**: 43 dated traps grouped by the step they bite at, in `references/scanning-traps.md` — read the one group matching what you are about to do, not the file. The gates above and the cron-health rule in step 1 are the ones that bite most often. Per-source mechanics: `references/scanning-gotchas.md`, `references/finch-scan-pitfalls.md`.

**Task selection priority:** `action_required: true` first; then high > medium > low; then earliest due; `pending` before `in_progress`. Skip `action_required: false` + `in_progress` (events in flight). Nothing actionable → validate and close the top pending item.

**Work-execution rules** (details in `references/work-execution-procedures.md`): triage signal (real / stale / transient); actionability filter (unattended cron); pipeline resumption from the ledger; break repeated check-and-close loops; prescribed fixes may be wrong — verify self-recovery / fail-loud guards first (`references/work-prescribed-fix-selfrecovery-guard.md`).

**Mining frameworks** (`references/mining_methodology.md`): scope before transfer. User-scoped relationship corrections route to Chronicle/User Dreaming; only agent/system-general signals continue through Finch. For those, tag failures by phase — **Planning** → patch preconditions; **Execution** → patch gotchas; **Response** → patch output sections. Record corrections as `[CORRECTION] What / Why / When` so lessons transfer.

