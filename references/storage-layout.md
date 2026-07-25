# Finch — Storage Layout

```
{agent_root}/commons/
  data/ocas-finch/
    decisions.jsonl          — DecisionRecord log
    memory_archive.md        — evicted MEMORY.md entries from compaction
    intents.jsonl            — Durable intent queue (DIQ)
    evidence.jsonl           — Execution evidence log (EEL)
    task-list.json           — Scan/work handoff
  journals/ocas-finch/
    YYYY-MM-DD/{run_id}.json — Action Journal entries
```

Skill package:

```
<skill-directory>/
  SKILL.md
  scripts/
    self_update.sh           — OCAS self-update via gh CLI (only active script)
  archive/                   — Deprecated scripts (miner.py, router.py, compact.py, anticipate.py, task_list_builder.py)
  references/
    signal_patterns.md       — Signal pattern reference for session mining
    mining_methodology.md    — Session mining methodology and lessons learned
    scan-work-architecture.md — Scan/work architecture, signal sources, governance
    skill-update-methodology.md — Post-session skill update framework
    skill-update-directive.md — Meta-rules for skill library updates
    cleanup-and-health.md    — System health checks, cleanup patterns, lock files
    external-skill-overlap-map.md — Overlap map: OCAS vs external skills
    git-skill-push-pattern.md — Git push workflow for skill repos
    pitfalls.md              — Consolidated pitfalls and anti-patterns
```
