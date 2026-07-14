# GitHub CI-stale-run verification (finch:work, 2026-07-13)

## Problem
A finch task referenced a failing CI run on `jaredzimmerman/BOOK` PR #871 (run `29200772746`) — `test: Failed to resolve import "./test-utils/dom-matchers"`. Investigation showed the task signal was STALE: the branch had been force-pushed; a LATER run on the SAME SHA (`29201113722`, 16:58 UTC) had PASSED. The PR was already green; no fix was needed.

**Key insight:** a failing run does NOT mean the branch is broken — CI runs are point-in-time. A superseding green run on the same head SHA is the authoritative verdict. Never open a fix task on a repo-CI failure until you've checked whether a later run already passed.

## Verification recipe (Bun/Vitest repos)
1. **List all runs for the PR/branch** — find the green superset:
   ```
   gh run list --repo <owner>/<repo> --branch <branch> --limit 10
   ```
   Look for a `completed`/`success` run AFTER the failing one (compare timestamps / run IDs).
2. **Confirm the green run tested the SAME head SHA as the current branch:**
   ```
   gh api repos/<owner>/<repo>/actions/runs/<GREEN_ID> --jq '.head_sha'
   git -C <repo> rev-parse HEAD          # local checkout of the branch
   ```
   If they match, the branch is fixed at its current head — the failing run was a prior revision. (For TASK-034 both equaled `a366bde4…`.)
3. **Fetch the PR head ref locally** (the remote branch may not be advertised by name):
   ```
   git fetch origin refs/pull/<PR>/head:fix/pr-head
   git checkout fix/pr-head
   ```
   If HTTPS fetch asks for a password, set a `gh` credential helper first:
   ```
   git config credential.helper '!gh auth git-credential'
   ```
4. **Reproduce locally** to be certain — install deps and run the originally-failing test file:
   ```
   bun install
   ./node_modules/.bin/vitest run tests/path/to/failing.test.tsx
   ```
   The failing run ID, its job ID, and the originally-failing file come from `gh run view <FAIL_ID>` and its job annotations (`gh api repos/<owner>/<repo>/actions/jobs/<JOB_ID>/logs`).
5. **Raw job-log fetch gotcha:** `gh api .../jobs/<ID>/logs` returns a LONG single text blob (UTF-8, no gzip despite content-type). Save it raw, then `grep -n -iE "FAIL|Error|404|✗"`. Do NOT pipe through `python3 -c json` — the payload is plain text, not JSON (the `--jq '.log'` form errors with a stray-character decode failure).

## Resolution
If green-run `head_sha` == local HEAD AND the originally-failing test passes locally → mark the task `completed` with a note: "stale signal — superseded by force-push; PR green on head <SHA>, ready for merge." Do NOT push/merge unless explicitly authorized (PRs with consulting/personal content need Jared's review; the task said "Agent MAY fix if authorized; otherwise flag").

## Caveat — unrelated runtime crashes
A full-suite local run may hit a Bun 1.3.12 **segfault** in tests that spawn Node child probes (e.g. `google-sync-reconciliation.test.ts`). That is a Bun-runtime crash, not test-logic failure, and may not reproduce in CI. If the originally-failing file passes and a green CI run on the same SHA exists, do not chase the segfault in this run unless explicitly scoped.
