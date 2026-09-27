# Finch — Anti-Patterns

- Don't modify SOUL.md, USER.md, IDENTITY_RULES.md, credential files
- Don't apply without review (weekly runs show plan first)
- Don't duplicate entries in MEMORY.md
- Don't mine cron sessions
- Don't create skills autonomously — ask for approval
- Don't skip skill updates — most sessions produce at least one
- Don't invoke deprecated scripts from `archive/`
- Don't use `delegate_task` from cron jobs
- **Don't declare victory prematurely** — Score honestly. "Almost complete" based on structural checks is not the same as "50/50 per the rubric". Show concrete verifiable evidence, not prose summaries.
- **Code fence pairing** — After any edit that moves content in/out of code blocks, verify even number of ``` markers. Odd count = broken fence pairing. Use Python line-by-line parsing to count accurately.
- **A coverage flag must be computed from what was measured** — a guard reporting `measured: true` while its glob and its field requirement disagree is asserting coverage, not measuring it. `finch_ledger_guard.py` shipped `journals.measured: true` while globbing only `scan-*.json` AND requiring an int `scan_number` — 49 of 275 journals examined, 24 of them carrying a forward self-stamp. If the denominator is not the real population, the number is decorative. Compute the flag from the loop, never set it beside the loop.
- **Don't widen a glob without re-scoping its consumers** — broadening the journal glob to all namespaces tripled an unrelated filename-vs-mtime finding from 32 files to 157, because that check had only been calibrated against the 49-file subset. A check's calibration does not travel with a change to its input set; re-measure and re-label, or it reads as a finding when it is noise. That skew proved bidirectional (98 late / 59 early, median +2 min), so the check was relabelled `[LOW SIGNAL]` with the measurement inline.
- **Don't ship a new non-zero exit code for findings nobody can clear** — a first attempt gave unfixable historical journal findings their own exit 3, which makes a genuinely clean ledger return non-zero forever, so callers learn to ignore the code and the guard stops guarding. The test suite caught it before it shipped. The exit code answers only "must a writer act on the artifact it writes?"; everything else is reported in the text and `--json` but never coded. Run the false-positive cases before shipping any exit-code change.
- **A field name is a namespace, and namespaces mean different things** — `scan_number` in `work-*.json` names the scan that pass ran AGAINST, not its own number, so sorting it into a monotonicity series manufactures false breaks. Journal field names also drift between runs (`scan_number`, `run`, `as_of`, `timestamp`), so reading one of them measures a fraction of the archive and the fraction changes silently: 32 journals hold their number in prose only (`run: "finch:scan #165"`), indistinguishable from a lost scan unless checked.
- **Don't let MEMORY.md entries go stale without review** — Entries not reinforced in 3+ compaction cycles should be candidates for eviction. The forgetting curve applies to agent memory too: unreinforced entries decay. During each compaction pass, check reinforcement status before keeping entries.
- **Don't record corrections without causal grounding** — A correction without "why" is a single-instance fix that won't transfer. Always extract the underlying principle (the "why") alongside the "what". Bare corrections ("don't do X") decay faster than grounded corrections ("don't do X because Y fails when Z").
