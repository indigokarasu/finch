# finch:work — prescribed-fix can be wrong: verify self-recovery + fail-loud guard first

When a task-list entry prescribes a specific "fix" (e.g. "seed the missing file",
"relink the path", "create X"), do NOT apply it on sight. Two conditions make the
prescribed fix wrong — both occurred on a real `items.jsonl` FileNotFoundError case:

## 1. The job already self-recovered (stale task)
The error is from an OLD `last_run_at`. By the time you investigate, an upstream
pipeline may have reseeded the missing artifact and the next scheduled run already
succeeded (`last_status: ok`, `last_error: null`).
- **Verify before acting:** read the job's run-history dir (`cron/output/<job-id>/`),
  not just `jobs.json`. Confirm a post-error run succeeded and rewrote/reseeded
  the artifact (match file mtime to the successful run timestamp). If so, the task's
  prescribed fix is stale — mark the task completed/self-recovered, do NOT re-apply.

## 2. The crash is a fail-loud guard over a destructive path
A `FileNotFoundError` at an early open() may be the ONLY thing preventing a later
step from rewriting the whole file. In the real case, line ~109 opened the item
file to read "other" non-target records; if that open were wrapped in
`except FileNotFoundError: others=[]` to silence the crash, a future wipe would let
line ~125 (which `open(..., "w")` and rewrites the ENTIRE file) proceed and
**destroy every sibling record** in that file, not just the target.
- **Rule:** a missing-file crash that guards a full-file rewrite is CORRECT behavior.
  It must fail loud so the upstream reseed (the real recovery) can run. Do NOT
  patch the open() to swallow the error. Fix the absence (reseed), not the guard.

## 3. The fix's RATIONALE is a config comparison, not a measurement

Two conditions make a prescribed fix wrong when the job is NOT self-recovered. The first two sections
cover "the error is stale". This one covers "the diagnosis is right and the remedy is still wrong".

**Symptom:** the task argues from a *setting mismatch* — "8 workers against a 2-thread server", "6
retries against a 30s budget", "N parallel calls against a timeout of T" — and lands on a knob to
turn. A mismatch is a hypothesis. It is not evidence that turning the knob changes the outcome.

**Procedure:**
1. Identify the quantity the fix is supposed to move, and its actual budget. For a network client that
   is the per-request timeout, not the concurrency.
2. Measure the real path, not a reconstruction of it. Import the production class and call it. A
   hand-rolled HTTP probe **bypasses the production code's own guards** — the `max_input_tokens` clamp
   (2048 tokens -> 6144 chars) in the Chronicle embedder is the concrete case: a probe that POSTs
   arbitrary text will happily reproduce timeouts that the real worker can never emit, which makes an
   unrelated hypothesis look confirmed.
3. Measure the CURRENT config and the PROPOSED config in the same pass, same process, so the numbers
   are comparable. Report success rate AND throughput; a fix that raises the success rate while
   halving throughput is a trade, and the trade belongs to the operator.
4. Test at least one alternative the task did not consider. The cheapest dimension is often the one
   nobody measured.
5. If the prescription is refuted, say so in the record and do NOT carry it forward for approval as
   if it were sound. Sending a wrong fix to the operator for a yes/no is worse than sending none: it
   spends their attention and gets a change that will not work.

**Confirmed 2026-09-26 finch:work (#180, `cron-chronicle-embedding-script-error`):** the task
prescribed `ENRICH_WORKERS 8->2` because the script's default fan-out exceeded the embedder's
`-t 2` thread count. Measured through the real `OpenAICompatEmbedder` at a typical 1806-char blob:
n=2 costs 4.27-4.86s of the 10.0s default timeout (2x margin, not comfortable) and roughly halves
throughput, while n=8 at a *raised* client timeout of 30-45s completes 8/8 at 0.44 emb/s - both safer
and faster than the prescription. The fix direction was the client timeout, not the worker count.

## 4. The loss is an amplifier, not N independent failures

Before characterising a failure by its count, find the ratio between the *real* errors and the
*reported* ones. A circuit breaker, retry budget, or fail-fast guard turns one error into thousands
of reported ones: the same run held 1 real timeout and 4,230 `is presumed down` lines (a ~1:4230
amplification, with cooldown escalating 30->60->120->240->480->600s so recovery inside a 540s budget
is impossible).

`count("failed")` in a log is not `count("broken")`. Report both, and let the ratio name the
mechanism. The shape also inverts the fix: making the first error less likely barely moves the total,
whereas preventing the first error from *propagating* (widen the budget, stop the cascade) moves it
all at once. When a task's own watcher conflates the two, fix the watcher - that conflation is what
kept the wrong diagnosis alive across passes.

## Decision procedure for any finch:work "fix the missing artifact" task
1. Read the job's run history; identify the failing run AND any later run.
2. If a later run = ok AND the artifact now exists with a matching mtime →
   self-recovered. Resolve the task, cite evidence, take NO code action.
3. If the artifact is still missing:
   a. Trace the script: is the crash open() guarding a later full-file `open("w")`?
   b. If YES → the guard is intentional; the fix is to restore the artifact via
      its normal producer, NOT to edit the script. Do not suppress the guard.
   c. If NO (genuine dead path, no destructive sibling) → the prescribed fix
      (seed/relink) is reasonable; apply and verify.
4. Never "create the file" by hand when the file's real producer will reseed it
   correctly — hand-seeding risks a partial/duplicated artifact.

## Anti-pattern this prevents
"Task said seed it, so I seeded it." → wasted action at best; at worst, you
silence a guard and the next wipe corrupts unrelated data. The task-list is a
signal, not an instruction to execute literally. finch:work judges; the task
describes.
