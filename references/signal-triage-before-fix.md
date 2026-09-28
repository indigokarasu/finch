# Signal Triage Before Fix (finch:work)

When a finch:work task lists N affected jobs, do NOT assume one root cause. Task titles are scan heuristics, not diagnoses.

## The Pattern

Cron tasks like "cron 429 errors" or "script timeouts" aggregate failures from multiple distinct root causes under one label. Example from 2026-05-28: a task labeled "cron 429 errors" (44 affected jobs) actually contained:
- Transient HTTP 429s from OpenRouter (20 jobs) — self-resolving, no intervention needed
- HTTP 429s from manifest.build (1 job) — different provider, still active
- Script timeouts at 120s (14 jobs) — a config/resource problem, not rate limiting
- Script path security blocks (2 jobs) — needs path fix
- Other errors (git missing, idle timeout, runtime errors) — each a separate issue

Applying a single fix to all 44 jobs would have been wrong for at least 3 of the 5 groups.

## Procedure

1. **Query the actual error state** — Read errors.log and jobs.json to get distinct error signatures, not just the task description.
2. **Group by root cause** — Cluster jobs by error fingerprint, not by the task label.
3. **Classify each group**:
   - **Transient**: Provider errors where the provider is currently reachable. Action: "monitoring", no config change.
   - **Persistent**: Script errors, path errors, config errors that won't self-resolve. Action: fix.
   - **Already-fixed**: The Tier 1 fix is already in place (e.g., schedule staggering is applied but the task still references it). Action: note it, move on.
4. **Inspect wrapper scripts** — When a task says "script path blocked errors", the cron job's `script` field may already point to the correct path. The actual problem is often *inside* the wrapper script (e.g., `update_rally.sh` calling `~/.hermes/scripts/update_skill.sh` instead of `~/.hermes/profiles/<profile>/scripts/update_skill.sh`). Always `cat` the wrapper script to verify internal path references before concluding the fix.
5. **Journal the decomposition** — Record counts per group so finch:scan can track recovery per group.

## jobs.json Structure (cron health inspection)

When inspecting `~/.hermes/cron/jobs.json` directly (because the `cronjob` tool is unavailable in cron context):

- **`state` is a string, NOT a dict** — Values: `"scheduled"`, `"error"`, etc. Do not try `state.get('status')`.
- **Error details live in flat fields**:
  - `last_error` — string error message (e.g., `"RuntimeError: HTTP 429: Rate limited by upstream provider"`) or `None`
  - `consecutive_failures` — integer count, may be nonzero even when `last_error` is `None`
  - `last_delivery_error` — delivery-side issue string or `None`
- **`consecutive_failures > 0` with `last_error=None`** — This pattern means the job's *script* ran fine but delivery failed, or the counter is stale from a previously-resolved issue. Do not treat this as an active job error. Verify with `last_status` (may be `"ok"`).
- **To find truly errored jobs**: filter for `last_error is not None`. Consecutive failures alone are a weak signal.

## A "batch of N findings" is a set of CAUSES until you can name them

The decomposition above groups by error fingerprint. The same rule applies to a
count, not just to a list of errors: **a reported count of N identical-looking
findings is not one finding repeated N times.** Before acting, ask what makes
each member forward the same way, and split the set if the members do not share
a cause.

Measured 2026-09-28 (finch:work #232). The ledger guard reported "27 journal
self-stamps forward" as one flat number, which reads as 27 instances of one
defect. It was two causes:

- **24 clock-forward** — the stamp really is ahead of the file. Genuine.
- **3 offset-tag-mislabelled** — the DIGITS are UTC and the local offset tag
  (`-07:00`) lies, so reading the stamp as written moves it a whole timezone
  forward. The writer is fine; the label is wrong, and every consumer of that
  stamp reads the wrong instant.

The evidence that split them was a second reading of the same string: read the
digits as UTC and compare against the file's own mtime. When that lands
*behind* the commit by a plausible amount, the tag is the error; when it lands
incoherently in both directions, the tag cannot be the explanation.

**Discriminate toward the bucket a reviewer reads as benign.** "Mislabelled" is
the comfortable label, so require positive evidence for it (coherent digits,
within a window) rather than treating "has an offset tag" as sufficient.
Absorbing a real forward stamp into a benign bucket hides a live violation, and
the direction of that error is the one nobody looks for.

**When a single file's timestamps are the only evidence, go get a second clock.**
A file cannot tell you whether its own digits are UTC or local — both readings
are internally consistent, and one just happens to place a run's start after its
own commit, which is impossible. Resolve it against a source that did not
generate the number: in this case the guard's own append-only receipt log,
written by a different process, bracketed the commit and showed the run started
8.6 min before it committed. Without that, the "obvious" reading — a clock 7h
forward — is a defect that does not exist.

**An attribution is not a suppression.** The mislabelled stamps stayed in the
count. Adding a `cause` field changes what a reader is told; it must never
change how many findings there are, or the new field becomes a place to hide
violations.

## Key Decision Rule

If the only findings are transient provider errors AND the provider is reachable (HTTP 200), the correct outcome is "monitoring" — NOT escalation, NOT config changes, NOT job re-registration. The stuck scheduler will self-heal once the provider recovers. This follows <other-ocas-skill>'s transient-error decision rules.

## Cross-Reference: Custodian's Recurrence Pattern Taxonomy

When triaging errors that have recurred across multiple scans, Custodian's RCA framework classifies recurrence into five patterns (A-E) with schedule-adjusted stickiness metrics. If finch:work encounters a task where the same error fingerprint has appeared in multiple previous tasks, the decomposition should check:

- **Pattern B** (fix applied but didn't hold): The previous task applied a fix that didn't survive one full schedule cycle per recurrence. Don't re-apply — the task should escalate with occurrence chain evidence.
- **Pattern C** (different root cause, same symptom): The aggregated task contains multiple distinct causes behind one fingerprint. Decompose into sub-fingerprints before fixing.
- **Pattern E** (cascade trigger): The error only occurs when another specific job/error fires first. Fix the upstream trigger, not the downstream symptom.

See `<other-ocas-skill>/references/root-cause-analysis.md` for the full taxonomy and drilldown procedure.
