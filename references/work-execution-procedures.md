# finch:work Execution Procedures

Step-by-step procedures moved out of `SKILL.md` so they load on demand
rather than on every invocation. Content is unchanged.

| procedure | read it when |
|---|---|
| Signal triage before execution (WORK step) | before acting on any finch:work signal |
| Repeated check-and-close anti-pattern (work execution) | when a task keeps reappearing across runs |
| Task actionability filter (cron context) | when finch:work runs without a user present |
| Pipeline task resumption (ledger/state-based) | when a task was interrupted mid-pipeline |

### Repeated check-and-close anti-pattern (work execution)

When a task was completed and marked `done`, then re-opened by a subsequent scan for the same unresolved issue, **do NOT run another check-and-close cycle.** After the first re-open, the correct action is decisive resolution or escalation — not re-verifying the same fact.

**Symptoms:**
- Task description says "still NXDOMAIN" / "still unresolved" / "re-opened from prior done status"
- Task was previously marked done with a "checked, found X" work log but the underlying issue persists
- The work log shows N consecutive identical checks with no fix attempted

**Procedure when you encounter a re-opened task:**
1. **Classify the task** — Is this a verification-only task (monitor, check, validate) or an action task (fix, create, configure, deploy)?
   - Verification tasks that are repeatedly re-opened for the same stable condition should be downgraded to `watching` with a note: "Stable state — not actionable." Do not mark `done`; that triggers re-open.
   - Action tasks that were marked `done` without the action being taken should be escalated: the prior closure was premature. Execute the actual fix.
2. **Identify the decisive action** — What single action would close this task permanently? For DNS: create the record. For config: apply the fix. For monitoring: leave as `watching` (not `done`).
3. **Pick decisive execution over verification** — If the task title or description implies an action (e.g., "DNS... unresolved"), invest the first tool call in actually resolving it, not re-verifying. Verification was already done by the prior finch:run or finch:scan.
4. **If genuinely stuck** — Mark the task `watching` with a `blocked_reason` field explaining what's needed to unblock it (e.g., "needs <operator> to choose IP", "requires panel access to provision"). Do NOT mark `done`.

**Rationale:** Three cycles of check-and-close for one unmet DNS record cost ~9 tool calls over 12 hours. One decisive action costs 2 tool calls. The system learns nothing from re-verification; it only learns from resolution.

#### Monitor re-evaluation discipline (work execution)

When a `monitor`/actionable task carries an explicit re-evaluation instruction ("re-evaluate after time T", "apply fix if condition X", "escalate if retry also errors"), the finch:work pass MUST execute the gate against LIVE signal, not the task note:

1. **Read the authoritative live source** (pinned `jobs.json` for cron; direct API for email/calendar) — NEVER decide from the task note's prose, which may be a prior-scan false-positive (see Scanning Gotchas: false-recovery claim).
2. **Compute the gate against current wall-clock.** For a "re-evaluate after 12:50PDT" task, confirm current time is PAST 12:50 before concluding the retry fired. If `next_run_at` is still in the future, the retry has NOT executed — the recurrence condition is UNMET. Record this explicitly; do not infer from the note.
3. **Do NOT apply a preemptive fix.** If the gate is unmet (condition not yet observable), take NO code change — applying a guard "just in case" exceeds the written task and is the same error class as acting on a false note. The correct output is "condition unmet, re-eval next cycle."
4. **Root-cause the error class before deciding.** For interpreter-shutdown, check gateway-restart timing (see Scanning Gotchas) — a pre-restart error is a teardown race, and the next tick is the real test.
5. **Close only on live recovery.** Flip monitor→done only when live signal shows the error cleared (last_status=ok on the post-T tick); never on the note's assertion alone.

**Confirmed 2026-07-24 finch:work (`dispatch-summary-interpreter-shutdown-0724`):** eval ran at 12:33PDT, 17 min before the 12:50 retry; live jobs.json showed `next_run_at` still 12:50 + `last_status` error; the task note's "12:50 retry fired and self-recovered" claim was a false-positive. Gate unmet → no guard applied; monitor retained; discrepancy flagged in the note. This is the model behavior for re-eval-gated monitor tasks.

#### Constructive progress while blocked (work execution)

When a task is blocked on an external party (<operator> login, third-party OAuth, a human decision) but has an the agent-owned executable sub-component, **build that component now** rather than re-verifying the block. This converts a no-op check into durable, reusable tooling.

**Confirmed 2026-07-17 (finch:work, `relay-shutdown`):** The task was blocked on <operator>'s Relay login (actual export needed his credentials). Instead of another "still blocked" check, finch:work authored `verify.py` — a self-contained stdlib verifier that checks every `workflows/*.json` parses as JSON and every `tables/*.csv` has ≥1 data row, exiting non-zero on any failure. It was validated against fixtures (broken JSON / empty CSV / header-only CSV all FAIL; valid data PASSes) and wired into the runbook's step 8. The verifier is reusable the moment <operator> exports — no re-derivation needed.

**Procedure when a task is blocked but has an executable sub-component:**
1. Decompose the task into the blocked part (needs external actor) vs. the autonomous part (the agent can build now).
2. Build the autonomous part as a real, re-runnable artifact (script, fixture, template) — not a status note.
3. Validate it actually works (run it against fixtures / a dry target) before reporting done. A "created script" claim with no execution is the naming-without-fixing anti-pattern.
4. Wire it into the task's runbook/steps so the eventual unblock is one command, not re-analysis.
5. Report the block honestly — the verifier existing does NOT mean the underlying task is complete.

This is the inverse of the check-and-close anti-pattern: instead of burning tool calls re-confirming a stable block, invest them in tooling that makes the eventual execution one-shot.

### Task actionability filter (cron context)

When running as a cron job with no user present, **filter for autonomous actionability** before applying the priority selection. A task is autonomously actionable if it passes ALL of:

- [ ] **No external response required** — doesn't depend on someone else replying (e.g., "track response from X" is NOT actionable; "check if X responded" IS actionable as a monitoring check)
- [ ] **No business decision required** — doesn't require accepting/declining engagements, making commitments, or choosing between options with capital implications (e.g., "respond to consulting inquiry — accept or decline" is NOT actionable)
- [ ] **No authentication required** — doesn't need app login, OAuth, or credentials the agent doesn't have (e.g., "check One Medical app" is NOT actionable)
- [ ] **No user input required** — doesn't need the user to clarify, confirm, or choose

**When all pending tasks fail the actionability filter:** Pick the highest-priority task that CAN be executed (even if low-priority), execute it as a monitoring/validation check, and mark it done with a resolution note. Report that higher-priority tasks are blocked pending user input. This is preferable to returning "no tasks" — at minimum, validate system health signals.

**When a task becomes actionable later** (e.g., <contact-name> replies, <operator> provides input), finch:scan will create a new task or re-activate the existing one. The blocked status is not permanent — it's a reflection of current actionability, not importance.

#### Cascading dependency awareness (confirmed 2026-06-29)

When a critical infrastructure dependency fails, it blocks MANY tasks simultaneously — not just the task that names the failure. Before iterating through each pending task individually, check for cascading blockers:

1. **Identify infrastructure-level blockers first** — If any `critical` task names an infrastructure failure (OAuth revoked, disk full, gateway down, provider outage), assume ALL tasks depending on that infrastructure are blocked until it's resolved.
2. **Map the dependency graph mentally** — OAuth revocation blocks: email tasks, calendar tasks, Drive tasks, Takeout tasks, any task requiring Gmail API. Provider outages block: all LLM-dependent tasks. Disk full blocks: all write operations.
3. **Skip the blocked bulk** — Don't waste time evaluating each email task individually when OAuth is known-dead. Skip the entire dependency cluster in one decision.
4. **Find the first non-dependent task** — Look for tasks that don't depend on the broken infrastructure: cron health monitoring (uses `hermes cron list`, not Gmail), disk checks (`df -h`), system stats, web lookups, non-Google API calls.
5. **Execute the first actionable task** — Even if it's low-priority, a monitoring check that produces a useful signal (e.g., "provider errors recovered") is better than returning "no tasks."

**Confirmed 2026-06-29 (this session):** OAuth revoked (task_019) blocked 6+ email/Gmail tasks simultaneously (task_004, task_005, task_006, task_021, task_012, plus the OAuth task itself). Rather than evaluating each one, the correct move was to recognize the cascade, skip the entire cluster, and pick task_014 (cron provider error monitoring) which only needed `hermes cron list` — no Gmail dependency. **Total impact**: 8/140 cron jobs failed from one OAuth revocation event.

**Key insight:** The actionability filter's 4 conditions are per-task checks. Cascading dependency awareness is a pre-filter that eliminates entire clusters before per-task evaluation. It saves 5-10 tool calls per blocked cluster.

### Pipeline task resumption (ledger/state-based)

When an `in_progress` task involves a data pipeline that uses an idempotency ledger or state file (e.g., Chronicle ingest ledger, corpus processing), the original background process may have died while the pipeline was partially complete. Do NOT re-run from scratch — the ledger tracks completed windows.

**Resumption pattern:**
1. **Verify the process is dead** — `ps -p <PID>` or `ps aux | grep <script_name>`. Confirm the process is actually terminated, not still running silently.
2. **Check the ledger/state** — Read the pipeline's idempotency ledger (SQLite, JSONL, or similar) to determine which work units are already complete.
3. **Compare ledger to source data** — Identify which work units (months, files, batches) from the source data are NOT yet in the ledger.
4. **Run without limits** — The pipeline's ledger-based dedup will skip already-complete units automatically. Running `run_ingest.py --source X --file Y --apply` without `--limit` is safe — it processes only what's missing.
5. **Update task to done** — Once the ledger shows all units processed, mark the task `done` with a resolution noting the final completion timestamp.

**Confirmed 2026-06-29 (task_023):** Background PID 1663225 (Timeline ingest) was dead. Ledger showed 8/10 months complete (through 2026-04). Source data had 10 months (2025-09 through 2026-06). Ran `run_ingest.py --source timeline --file location-history.json --apply` without `--limit` — ledger correctly skipped the 8 completed months, processed 2026-05 and 2026-06 (2 documents written at 07:33Z). Task marked done.

**Key insight:** Pipeline tasks with idempotency ledgers are ALWAYS resumable. The `--limit N` parameter is only needed for initial testing. Once confirmed working, subsequent runs should omit `--limit` so the ledger handles dedup.

2. **Work** (`finch:work`, every 30 min) — Pick top pending task. Load governing skill via `skill_view`. Execute ONE task per run. Before selecting, check for duplicate task IDs and clean up if found (see `references/duplicate-task-detection.md`). Route findings to MEMORY.md, skill patches, or reference files.
2a. **Sessions scan — correct pattern**: When scanning recent sessions in finch:scan, call `session_search(limit=10, sort='newest')` WITHOUT `query` (FTS5 treats query as literal text, not a time filter — `query="last 24h"` matches sessions containing those words, not recent sessions). Manually check result timestamps. For finch:daily/weekly mining, follow the cron-skew filtering procedure in SKILL.md § "Session source filtering".
3. **Mine** (`finch:daily` / `finch:weekly`) — Process session JSONL files for signals: corrections, directives (Always/Never), course changes, breakthroughs, methodologies, stop signals. See `references/mining_methodology.md` for the full methodology.
4. **Route** — Direct each finding to the optimal storage tier: MEMORY.md (Tier 1: corrections, directives), skill SKILL.md/references/ (Tier 2: tool-usage, service gotchas), reference files (Tier 3: guides, paths, URLs), or Chronicle KG (Tier 4: entity facts). See `references/file-governance.md` for routing criteria and the tier model.
5. **Journal** — Every run emits Action Journal + DecisionRecord to `decisions.jsonl`.

### Signal triage before execution (WORK step)

A task on the list may aggregate multiple distinct failure modes under one title (e.g., "cron 429 errors" that actually mix transient rate limits, script timeouts, and path blocks). Before committing to a fix:

1. **Decompose the task** — List the distinct error signatures from logs/jobs.json. Group by root cause, not by symptom label.
2. **Classify each group** — Transient (will self-resolve), persistent (needs intervention), or already-fixed (mitigation in place).
3. **Handle each group appropriately** — Transient groups get "monitoring" with a 24h recheck. Persistent groups get fixes. Already-fixed groups get a note that the Tier 1 was already applied.
4. **Journal the decomposition** — Record the group counts so the next finch:scan can check recovery per group, not just per task.

Do NOT assume a task with N affected jobs has one root cause. The task title is a scan heuristic, not a diagnosis.

#### Already-fixed verification (resumed investigations)

When a task asks to "resume" or "complete" an interrupted investigation (e.g., "Session identified systemic issues but did not complete fixes"), do NOT assume the fixes are missing. The prior session may have produced findings that were already implemented, or the features may have existed under different names.

**Procedure:** Read the actual code at the relevant file:line locations. Map each claimed-missing feature to a function/class. Check for detection → classification → response → guard completeness. Run existing tests for those features. If all checks pass, mark the task `done` with specific file:line references and test counts as evidence. See `references/already-fixed-verification.md` for the full procedure and an example. For CI-failure tasks on a repo PR/branch, remember a failing run is point-in-time and may already be superseded by a green run on the same head SHA — check the latest run for that SHA before treating it as broken.

#### Cron code-crash fix: the repair may already be uncommitted
When finch:scan flags a cron `last_status=error` with a Python traceback message (e.g. `'tuple' object has no attribute 'get'`), it's a genuine code defect, not transient. The committed (HEAD) version is what failed, BUT a working-tree modification may already repair it (`git status` shows ` M <file>`) — common when an interactive/sibling run patched the file but didn't commit, while the prior cron tick still ran broken HEAD. Procedure:
1. `git status --short` + `git diff HEAD -- <file>` — confirm whether the fix is already present uncommitted before assuming the crash is live.
2. Reproduce against the CURRENT working-tree code with a traceback harness (import `main()`, call inside `try/except: traceback.print_exc()`). OCAS scripts catch `Exception` at the top level and print only `FAIL: ...: <msg>` with NO line number, so `jobs.json` stderr alone won't name the broken line — the harness will.
3. If verified, COMMIT the fix (the fix file only; leave unrelated working-tree modifications uncommitted — they belong to other tasks). An uncommitted patch is fragile under cron: these repos carry many local commits ahead of upstream and get rebased/pulled, which discards or conflicts uncommitted changes, so the next scheduled tick would crash again. Committing makes it durable.
4. Clean verification side-effects: running `main()` appends a row to any append-only log it writes — dedupe to one deterministic row per key (e.g. per date; for mixed-type logs key on `(decision_type, date)`) so the data stays honest.

#### All-transient resolution (no fix needed)

When investigation reveals that ALL errors in a task are transient (provider errors with `consecutive_failures: 0`, missing-module errors where the package is actually installed, interpreter-shutdown errors), the correct action is:

1. **Verify** — Read `jobs.json`, check `last_status`, `last_error`, `consecutive_failures` for each affected job. Do NOT trust the task description alone.
2. **Mark task done** — Set `status: "done"`, add `resolved` timestamp, write `outcome` explaining what was checked and why no fix is needed.
3. **Downgrade priority if misclassified** — If a task was marked HIGH for interpreter-shutdown or provider errors, downgrade to LOW per the error taxonomy.
4. **Journal** — Record the resolution so finch:scan doesn't re-create the task on next scan.

**Confirmed 2026-06-28:** task_019 (provider errors + missing-module) — all jobs showed `consecutive_failures: 0` and `last_status: ok`. googleapiclient was already installed. No intervention required. task_014 (interpreter-shutdown) — also transient, downgraded HIGH→LOW.

MEMORY.md entries decay without reinforcement. During compaction:

1. **Reinforcement check**: For each existing entry, check if it was reinforced (re-encountered or re-applied) since last compaction. Entries reinforced within their expected half-life get a `§` durability marker.
2. **Concept classification**: Classify each entry by storage tier (see `references/forgetting_curve.md` § Storage Tier Model). Is this entry in the right tier?
3. **Tier routing**: Entries in the wrong tier get moved — tool-usage facts to skills (Tier 2), reference details to reference files (Tier 3), entity facts to Chronicle (Tier 4). Only evict if truly stale.
4. **Decay candidates**: Entries not reinforced in 3+ compaction cycles that cannot be routed to another tier are candidates for eviction.
5. **Priority for retention** (Tier 1 only): Directives (Always/Never) > Corrections with causal grounding > Bare corrections > Breakthroughs > Methodologies > Pointers to Tier 2/3 knowledge
6. **Consolidation**: Merge entries that share the same underlying principle into a single entry with multiple contexts. Within-tier only.

See `references/forgetting_curve.md` for the full compaction algorithm including the tier routing procedure.

See `references/scan-work-architecture.md` for signal source details and governance rules.
