# Finch

<p align="center">
  <img src="./assets/readme/hero.jpg" width="100%" alt="Finch — OCAS self-improvement orchestrator">
</p>

> Mines session history for learning signals, keeps MEMORY.md within its cap, and records what is in flight. It observes and records; it does not act.

## Why Finch?

Skills drift. Finch catches the drift: it scans session transcripts for corrections, directives, breakthroughs and methodologies, then routes each one to where it belongs, so the system improves without manual bookkeeping.

## Quick start

```bash
hermes skills install ocas-finch
```

## What it does

- **Mines sessions** for corrections, Always/Never directives, breakthroughs and methodologies.
- **Routes findings:** directives go to MEMORY.md through `memory_guard.py`; skill patches are staged for `ocas-fellow` review; user-scoped signals go to Chronicle.
- **Compacts MEMORY.md** to stay within its character cap without losing directives.
- **Tracks work in flight** (`finch:track`): projects, in-flight tasks and todos from sessions, journals and logs, written to `tracker.json` and `tracker.md`.
- **Scans system health** (`finch:scan`): sessions, cron health, kanban and system signals, with a ledger entry per scan.

Since 3.3.0 Finch does not read email, calendar or Drive, and it does not execute tasks. Mentor routes tasks to the owning skill.

## Jobs and commands

| Name | What it does |
|------|--------------|
| `finch:scan` | Scheduled signal scan (every 2h) |
| `finch:track` | Records projects, in-flight tasks and todos |
| `finch:daily` / `finch:weekly` | Daily mining and compaction; weekly review |
| `finch.mine` | Mine sessions for signals only |
| `finch.compact` | Compact MEMORY.md only |
| `finch.dry-run` | Full pipeline without writing anything |

## Development

```bash
python -m unittest discover -s tests -v   # includes every scripts/test_*.py suite
python scripts/check_no_pii.py            # must pass before any push
```

This repo is public. Publish through a PR that CI checks, never a blind `git add -A` to `main`: see `references/reference-file-workflow.md` § Publishing. Reference docs are indexed in `references/README.md`.

## Dependencies

Hermes Agent runtime. Reads session transcripts, journals, logs and MEMORY.md from the active profile.

*Part of the [OCAS Agent Suite](https://github.com/indigokarasu).*
