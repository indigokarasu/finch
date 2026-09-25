# Manual run & verification (when the user says "run finch")

Operating finch means verifying the deployed cron jobs are healthy and, when
asked, forcing a run. Job names drift — always enumerate the live registry
(`jobs.json`) before assuming a job exists.

## Deployed job set

Treat the live registry as ground truth; the design doc lists a separate
`finch:work` cron that is not always deployed. Before 2026-07 the deployed set
was five jobs:

- **`finch`** — profile-root MEMORY.md compaction. Runs `memory_guard.py` on the
  DEFAULT profile's MEMORY.md, NOT the finch profile's — guard the `--file`
  override or it compacts the wrong memory.
- **`finch:floor`** — `no_agent` script safety floor (memory guard). Normally
  `enabled: false` but self-triggers; a disabled state here is NOT broken.
- **`finch:scan`** — every 2h, pure LLM. Its cron-health step must enumerate
  `jobs.json` via `references/cron-health-validation.md` (not `cronjob(action='list')`
  / `hermes cron list`, which undercount).
- **`ocas-finch:daily`** — daily 6am PT, pure LLM.
- **`ocas-finch:weekly`** — Sunday 8am PT, pure LLM.

Work execution is covered by the interactive `finch.work` command /
`finch:scan`-driven task list when no separate cron exists.

## Forcing an immediate run

`cronjob action='run'` does NOT force a scheduled **LLM** job to execute — it
only bumps `next_run_at` to the next natural tick. To force execution now:
**pause the job first (`action='pause'`), then `run`** — the paused state
triggers forced execution. `no_agent`/script jobs (e.g. `finch`, `finch:floor`)
run on a plain `run` without pausing. After a forced run succeeds the job
returns to `state: scheduled` automatically.

## Verification gate

A queued immediate run is not a completed run. After every manual trigger,
re-read `jobs.json`/`cronjob list` and verify `last_run_at` advanced to the
current run window and `last_status` is current. If `next_run_at` is in the
past but `last_run_at` did not advance after a tick, report the job as
**queued/not yet executed**, not completed. Where a deterministic sub-function
exists (`memory_guard.py`, task-list inspection, journal write), run it directly
and distinguish those completed direct actions from still-queued LLM jobs.

## Mass 401 across finch (and other) jobs

Classify WHICH 401 it is before acting:

- **MCP-auth 401** (dead `[mcp_servers]` token): a stale `[mcp_servers]` block
  in the profile `.env` (`~/.hermes/profiles/<p>/.env`) ships an invalid/expired
  token that breaks ALL MCP calls. Fix: remove the `[mcp_servers]` section; the
  client falls back to valid config.
- **Provider-auth 401** (LLM provider token): run output shows
  `RuntimeError: Error code: 401` with `token_expired` or
  `"Your API key is invalid, blocked or out of funds"` from the provider portal.
  This is NOT the `[mcp_servers]` block. Fix: **restart the gateway** (kill the
  `--profile <p> gateway run` process and let it respawn) so it reloads the
  current valid provider token. Post-restart runs should return `ok`.

Diagnostic steps: (1) read the actual run output / `jobs.json` `last_error` —
`cronjob list` may display `last_error: None` even when `jobs.json` holds the
401. (2) `grep -n "mcp_servers" ~/.hermes/profiles/<p>/.env` — if absent, it is
provider-auth, not MCP-auth. (3) If interactive sessions on the same
provider/model work but cron 401s, the scheduler holds a stale token → restart
the gateway. See the `cron-job-repair` skill for the model-routing-401 vs
MCP-auth-401 distinction.

## Cron rebase breakage pattern

Multiple `ocas-*:update` jobs can fail simultaneously with the same `git rebase`
conflict signature — upstream sync publication introduced incompatible changes
across related repos. Job output typically shows `Removing references/...`,
`Removing data/`, and `Dropped refs/stash@{0}`. Treat as ONE systemic sync
breakage, not N independent failures.

## Autonomy — take the action without being prompted

When a finch job (or any cron job) is failing and the fix is clear, do NOT ask
"continue?" or wait for the user to "say the word." Apply the fix, run the
affected jobs, then report results in one message. The user explicitly requires
the agent to take the needed action without prompting: "I shouldn't have to
'say the word' you should just take action that needs to be taken."
