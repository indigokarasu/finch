# finch:work Cron-Error Diagnostic (before patching)

When finch:work picks a cron-error task, do NOT assume a patchable per-cron
defect. Run this diagnostic first. It prevents the most expensive misdiagnosis
in the class: inventing a "broken orchestrator script" to patch when the job
has no code at all, or patching a job that already self-recovered.

## Diagnostic sequence (in order)

1. **Read the job from `jobs.json`** — find the entry by `id` (or `rid`) in
   `~/.hermes/profiles/<profile>/cron/jobs.json` (and the system file
   `~/.hermes/cron/jobs.json` if the job lives there). Capture:
   - `script` — **the decisive field** (see below)
   - `last_status`, `last_error`, `consecutive_failures`, `last_run_at`
   - `state` (`scheduled` / `paused`)

2. **Check `script` field to classify job type:**
   - `script = null` → **pure-LLM prompt cron.** The cron runs an LLM prompt
     directly; there is NO orchestrator/shell/Python file for finch:work to
     patch. Any error is framework-level (Hermes execution runtime), not a
     job-side code defect. Do NOT write a patch; resolve as a diagnostic
     (corrected root cause) task if recovered.
   - `script = "/path/to/file.py"` or `.sh` → **script-backed cron.** A real
     file exists; inspect it, reproduce, and patch as normal.

3. **Check recovery state** (same gate as scan side):
   - `consecutive_failures = 0` AND `last_status = "ok"` → **self-recovered.**
     The error was transient. Verify by reading the output journals (step 4),
     then resolve the task as diagnostic-only — no patch.
   - `consecutive_failures > 0` → real, active error. Proceed to root-cause.

4. **Read the output journals** under
   `~/.hermes/profiles/<profile>/cron/output/<id>/`. The error run's `.md`
   shows the actual traceback (`## Error` block). A *later* run's `.md` with a
   real `## Response` or clean output proves recovery. Sandwich pattern
   (clean run → error run → clean run) = transient by definition.

5. **Correlate sibling failures in the same window.** If multiple unrelated
   crons errored within minutes of each other, suspect a SHARED framework/
   lifecycle cause (gateway restart, DB contention, executor shutdown) rather
   than N independent job bugs. Confirm via system state (e.g. a hot
   `chronicle.db` + WAL at the same timestamp). One shared cause → one
   diagnostic conclusion; do not over-decompose.

## interpreter-shutdown / "cannot schedule new futures" specifics

- Fingerprint: `RuntimeError: cannot schedule new futures after interpreter
  shutdown`. This is the Hermes framework-level `DaemonThreadPoolExecutor`
  interpreter-shutdown race (event-log fingerprint `oc_cron_interpreter_
  shutdown_futures`), NOT a per-cron ThreadPoolExecutor bug.
- It recurs across many crons under gateway/DB-contention load. On a pure-LLM
  prompt cron it is **never** a patchable defect — there is no executor code in
  the job to race.
- Classification (scan side): LOW, always transient, self-resolves next tick.
  Only escalate if 3+ CONSECUTIVE failures persist after the job has re-run.
- finch:work action: if `consecutive_failures = 0` and a later run is clean,
  mark the task `resolved` and record the *corrected* root cause (framework
  race, not a job defect). Do not leave a misleading "ThreadPoolExecutor in
  orchestrator" hypothesis in the notes.

## Concrete example (2026-07-19)

Task `cron-finchscan-shutdown` (job `c04eff488df8`, `finch:scan`):
- Task hypothesis (wrong): "ThreadPoolExecutor/async submit racing interpreter
  teardown in scan orchestrator — patch it."
- Actual: `jobs.json` shows `script = null` → pure-LLM prompt cron, no code to
  patch. `last_status = ok`, `last_error = null`, `consecutive_failures = 0`,
  `last_run_at = 2026-07-19T06:13:06` (clean full rescan). The 04:02Z error
  was sandwiched between clean 02:19Z and 06:13Z runs.
- Sibling `chronicle:daily-embed` failed at 03:40Z in the same hot-chronicle.db
  window → shared framework/lifecycle cause confirmed.
- Resolution: task marked `resolved`, notes corrected to "framework-level
  DaemonThreadPoolExecutor race, no patch applicable, job healthy." No <operator>
  action.

## Related

- `references/stale-cron-task-detection.md` — verify the job still *exists*
  before fixing. This doc covers verifying the job *type* (`script` field)
  before assuming a patchable defect. Both are pre-patch gates.
- `references/scan-error-classification.md` — scan-side fingerprint table
  (interpreter-shutdown = LOW/transient).
