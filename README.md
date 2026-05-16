# ocas-finch

**OCAS Self-Improvement Orchestrator** — Darwin's finch: adaptive evolution for AI agents.

Finch mines session JSONL files to detect learning signals from real user interactions — corrections, breakthroughs, methodologies, course-changes, and behavioral directives (Always/Never). Each finding is routed to the modification target that will have the most behavioral impact: MEMORY.md or skill patches.

Part of the [OCAS](https://github.com/indigokarasu/ocas-architecture) (OpenClaw Agent System) ecosystem.

## What it does

1. **Mines** session JSONL files for learning signals using regex pattern matching
2. **Compacts** MEMORY.md to stay within the 2,200 char limit (dedup, re-rank, evict, compress)
3. **Routes** each finding to the optimal target (MEMORY.md for behavioral rules, skill patches for methodologies)
4. **Emits** OCAS Action Journals and DecisionRecords per the OCAS spec
5. **Applies** changes with user review (weekly) or auto-applies low-risk findings (daily)

## Signal types

| Signal | What it means | Where it goes |
|--------|--------------|---------------|
| **Correction** | User said "no/wrong/don't/stop" | MEMORY.md |
| **Directive (Always)** | User said "always do X" | MEMORY.md — Always Rules |
| **Directive (Never)** | User said "never do X" | MEMORY.md — Never Rules |
| **Course change** | User reinterpreted and redirected | MEMORY.md |
| **Breakthrough** | User confirmed something works | MEMORY.md — What Works |
| **Methodology** | User described a reproducible process | Skill patch or MEMORY.md |
| **Stop** | User stopped/cancelled a task | MEMORY.md — Stop Signals |

## Architecture

```
~/.hermes/
  skills/ocas-finch/
    SKILL.md                    # Skill definition (this package)
    scripts/
      miner.py                  # Session mining engine
      router.py                 # Recommendation router
      compact.py                # MEMORY.md compaction engine
    references/
      signal_patterns.md        # Complete regex pattern reference
      mining_methodology.md     # Mining methodology and lessons learned
  commons/
    data/ocas-finch/
      decisions.jsonl           # DecisionRecord log (append-only)
      memory_archive.md         # Evicted MEMORY.md entries
    journals/ocas-finch/
      YYYY-MM-DD/
        {run_id}.json           # Action Journal entries
```

## OCAS compliance

- **Storage**: Per `spec-ocas-storage-conventions.md` — all data under `commons/`
- **Journals**: Action Journal entries per `spec-ocas-journal.md`
- **DecisionRecords**: Per `spec-ocas-shared-schemas.md`
- **Naming**: `ocas-` prefix per OCAS naming convention
- **Workflow plans**: `finch-daily.plan.md` and `finch-weekly.plan.md` per `spec-ocas-workflow-plans.md`

## Usage

### Mine sessions
```bash
python3 ~/.hermes/skills/ocas-finch/scripts/miner.py --days 7 --json --min-confidence 0.7
```

### Compact MEMORY.md
```bash
python3 ~/.hermes/skills/ocas-finch/scripts/compact.py --apply
```

### Route findings
```bash
python3 ~/.hermes/skills/ocas-finch/scripts/router.py --input /tmp/finch_mined.json --dry-run
```

### Full pipeline (daily)
```bash
python3 ~/.hermes/skills/ocas-finch/scripts/miner.py --days 1 --json --min-confidence 0.7 > /tmp/finch_mined.json
python3 ~/.hermes/skills/ocas-finch/scripts/compact.py --apply
python3 ~/.hermes/skills/ocas-finch/scripts/router.py --input /tmp/finch_mined.json
```

## Scheduled tasks

| Job | Frequency | Behavior |
|-----|-----------|----------|
| **ocas-finch:daily** | Daily 6am PT | Mine 24h → Compact → Route → Auto-apply low-risk. Flag directives. |
| **ocas-finch:weekly** | Sunday 8am PT | Mine 7d → Compact → Route → Show full plan for approval. |

## Integration with Hermes Agent

This skill is designed for [Hermes Agent](https://github.com/indigokarasu/hermes-agent) and uses:
- `memory` tool for MEMORY.md modifications
- `skill_manage` tool for skill patches
- `cronjob` tool for scheduled runs
- Session JSONL files from `~/.hermes/sessions/`

## Related

- [OCAS Architecture Spec](https://github.com/indigokarasu/ocas-architecture) — System architecture, schemas, and design documents
- [Mentor](https://github.com/indigokarasu/mentor) — Self-improving orchestration and evaluation engine
- [Forge](https://github.com/indigokarasu/forge) — Skill architect and builder
- [Fellow](https://github.com/indigokarasu/fellow) — Empirical experimentation engine
- [Corvus](https://github.com/indigokarasu/corvus) — Exploratory pattern analysis engine

## License

Part of the OCAS ecosystem. See [indigo](https://github.com/indigokarasu/indigo) for licensing.
