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
- **Don't let MEMORY.md entries go stale without review** — Entries not reinforced in 3+ compaction cycles should be candidates for eviction. The forgetting curve applies to agent memory too: unreinforced entries decay. During each compaction pass, check reinforcement status before keeping entries.
- **Don't record corrections without causal grounding** — A correction without "why" is a single-instance fix that won't transfer. Always extract the underlying principle (the "why") alongside the "what". Bare corrections ("don't do X") decay faster than grounded corrections ("don't do X because Y fails when Z").
