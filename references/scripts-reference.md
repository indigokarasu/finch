# finch scripts — full reference

Every `.py` in `scripts/`, with the flags and exit codes that matter. The
ones an operator runs are also in SKILL.md's short list; read here when you
need the exact flag, the exit-code contract, or the tests that must pass
before you change something.

All scripts answer `-h`/`--help` and exit 0 **before doing any work**. That is
load-bearing rather than cosmetic: an audit that probes `--help` must not run
a watcher, sweep a mailbox, or create a fixture tree. Two suites
(`test_restore_doublefire_watch.py`, and previously three more) failed this
exact check, and in the restore suite's case an unguarded `--help` created
real directories in `/root` on every probe.

Exit-code convention across the instruments: **0 = clean / no new / all
directions pass · 1 = a finding or a failed direction · 2 = NOT MEASURED or
unreadable**. Never read a 2 as clean, and never gate a claim on the exit
alone — read the VERDICT line.

| `memory_guard.py` | MEMORY.md safety floor (cap, atomic write) | `--apply --file <path>`, `--emit-decision`, `--json` |
| `memory_state.py` | Reinforcement-state store (forgetting curve) | `reinforce`, `check`, `route`, `decay-report` |
| `gws_direct_puller.py` | Workspace pull when MCP absent (googleapiclient; `<hermes-venv>/bin/python`) | `--full-text` |
| `verify_sepagree_signature.py` | Docusign EMAIL-SEPAGREE "unsigned" re-verifier; prints VERDICT | `--since <RFC3339>` probe |
| `finch_hooks_plugin.py` | Hooks: signal capture, memory guard, subagent tracking | `--extract-signals`, `--check-tool` |
| `finch_scan_tasklist_rerank.py` | Safe re-rank + validation for task-list.json | (positional path) |
| `finch_scan_counter.py` | flock-atomic scan-number allocator; max-floor over header/journals/prose/sidecar | `--peek`, `--floor`, `--json`; EXIT 0 / 1 unreadable / 2 lock held |
| `pause_gate_watch.py` | Claim-vs-enforcement check for the `paused` boolean (inert vs real markers) | `--json`, `--quiet`, `--tolerance N`; EXIT 0 ok / 1 unreadable / 2 drift |
| `finch_ledger_guard.py` | Ledger forward-stamp / laundering / journal-coherence gate. Exit 0 clean / 1 forward or laundered / 2 unreadable. **Read the VERDICT line, not the exit alone.** Offset-aware; covers flat AND nested header stamps. Fix a forward stamp with `--repair` |
| `finch_ledger_write.py` | Sanctioned ledger write choke point; clamps at write time so a forward stamp is unreachable. `--set` / `--task --set` / `--doc` / `--clamp-only` / `--dry-run`; exit 3 = written but a re-read still shows a stamp |
| `ledger_forward_sweep.py` | rvt-clause-3 instrument: offset-aware sweep of the WHOLE ledger for forward stamps, independent of the guard's field list. Exits 1 on any hit outside `due_date`; prose-field examples are listed, not counted |
| `finch_forward_event_watch.py` | rvt-clause-(a) instrument: **distinct** forward events in the guard receipts, de-duplicated and watermarked. The guard answers "forward NOW"; an event a later pass OVERWRITES is invisible to it forever, so the receipts are the only durable witness. Exit 0 no new / 1 new event / 2 NOT MEASURED. `--ack` advances the watermark (and then returns 0, so an acking caller does not re-fire). Reports STILL-IN-LEDGER vs OVERWRITTEN — repaired vs merely overwritten. Test: `test_finch_forward_event_watch.py` (9 directions) |
| `test_finch_ledger_guard_parse.py` | 9 directions: offset form + nested form caught, clean ledger stays clean, no-parse regressions. **Run before and after any guard change** |
| `test_ledger_guard_repair.py` | 6 directions: everything `check()` can see, `repair()` can clear — nested, offset, both, task stamps; clean ledger is a no-op; a future `due_date` is untouched |
| `check_no_pii.py` | PII gate CI runs before publish | `--quiet`, `--path <file-or-dir>`; EXIT 0 clean / 1 findings. NOTE (2026-09-27): run on the whole skill it reports 79 findings, and that count is PRE-EXISTING and unchanged by edits -- measure a single file with `--path <file>` to attribute a finding, and diff the whole-skill count against HEAD (`git stash`) before claiming your change introduced one. |
| `finch_count_population_guard.py` | Enforces "a count names its population" (finch:work 1067). Reads `cron/executions.db` only -- the `cron/output/` listing is measured and printed as a **REJECTED** proxy, never used as a count. Two independently-worded constructions of the SAME predicate must agree. `--json`, `--quiet`; EXIT 0 MEASURED / 1 CORRECTION (constructions disagree) / 2 NOT MEASURED (missing db, schema drift). Test: `test_count_population_guard.py` (7 directions). Mutation harness: `test_count_population_guard_mutation.py` (3 mutants; **exits 2 if a mutant fails to apply**, so a stale mutant is never counted as killed) |
| `finch_resume_boolean_sweep.py` | Sweeps the FULL mitigation-era population for the `paused=True` defect `resume_job()` leaves behind, proving the pause-gate watcher's printed remedy actually clears the boolean. **Read-only on live jobs**: the probe subprocess runs against a temp `HERMES_HOME` holding a COPY of `jobs.json` and only calls `resume_job()` there. EXIT 0 all cleared / 1 at least one still `paused=True` (**a refutation, not a tool failure**) / 2 NOT MEASURED. Writes `cron/finch_resume_boolean_sweep.json`. Resolves its population from `FINCH_PROFILE`/`HERMES_HOME`, and passes the agent source tree to the probe via `FINCH_AGENT_SRC`. `--help` returns before any measurement or file write -- load-bearing, not cosmetic: without it every `--help` probe ran the whole 46-id sweep and rewrote the result file |


