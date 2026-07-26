# Finch

<p align="center">
  <img src="./assets/readme/hero.jpg" width="100%" alt="Finch — OCAS self-improvement orchestrator">
</p>

> Mines session history for learning signals, compacts memory, and routes findings back into skills.

## Why Finch?

Skills drift. Finch catches the drift: it scans session transcripts for corrections, breakthroughs, and behavioral patterns, then turns them into memory updates and skill patches so the system improves without manual bookkeeping.

## Quick Start

```bash
# Install as a Hermes skill
hermes skills install ocas-finch
```

## What It Does

- Mines session JSONL for learning signals (corrections, breakthroughs, patterns)
- Compacts MEMORY.md to stay within the char limit (dedup, re-rank, evict, compress)
- Routes each finding to the right target (MEMORY.md for rules, skill patches for methods)
- Emits OCAS Action Journals and DecisionRecords
- Applies low-risk findings automatically (daily) or queues for review (weekly)

## Commands

| Command | Description |
|---------|-------------|
| `finch.scan` | Run the learning-signal scan manually |
| `finch.work` | Apply mined findings |
| `finch.compact` | Compact MEMORY.md only |
| `finch.mine` | Mine sessions for signals only |
| `finch.dry-run` | Full pipeline without applying changes |

## Dependencies

Hermes Agent runtime. Reads session transcripts and MEMORY.md from the active profile.

*Part of the [OCAS Agent Suite](https://github.com/indigokarasu).*
