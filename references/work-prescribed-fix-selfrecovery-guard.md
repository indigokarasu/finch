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
