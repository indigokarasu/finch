# ⚙️ Finch

  <img src="./assets/readme/hero.jpg" width="100%" alt="Finch">

OCAS self-improvement orchestrator (Darwin''s finch — adaptive evolution).

**Skill name:** `ocas-finch`
**Version:** 2.15.3
**Type:** 
**Layer:** software-development
**Author:** Indigo Karasu

---

## 📖 Overview

OCAS self-improvement orchestrator (Darwin''s finch — adaptive evolution).

---

## 🔧 Capabilities

- `tool_search` ≠ `tool_call` availability — probe a suspect MCP tool alone before batching; MCP load state is intermittent between runs
- `read_file` view of a JSON file is NOT validation — it can display trailing-comma corruption as valid and misreport size; only `json.load()` catches it. Validate-after-edit with `terminal python3 -c "import json; json.load(open(...))"` (execute_code is blocked in indigo cron).
- `jobs.json` for cron health when `cronjob` tool unavailable; `hermes cron list` hides disabled jobs. **NEVER report "cron health clean" without enumerating ALL jobs from `jobs.json` and surfacing every `last_status=error` job — including paused/disabled ones a summary view hides.** Classification procedure (see `references/cron-health-validation.md` for the reusable parse script): (a) TRANSIENT/recovered if `consecutive_failures=0` AND a later run produced success output (check `cron/output/<jobid>/` for a subsequent ok file) — not a task; (b) PAUSED-BY-DESIGN if `state=paused` and `last_error` names a missing credential/OAuth the agent can't complete interactively (e.g. `taste:sync-spotify` needs Jared's interactive Spotify OAuth) — note as standing limitation, not a task; (c) REAL if `consecutive_failures>0` or the error recurs across ticks — create/escalate a task. **Anti-pattern (2026-07-17):** a prior scan reported "cron health clean" and missed `monitor:journals` (transient, recovered next tick) and `taste:sync-spotify` (paused) because it relied on a summary-style view instead of full `jobs.json` error enumeration. Re-verify against `jobs.json` directly every scan.
- **`finch`** — profile-root MEMORY.md compaction (runs `memory_guard.py` on the DEFAULT profile's MEMORY.md — NOT the indigo profile's; guard the `--file` override or it compacts the wrong memory).
- **`finch:floor`** — `no_agent` script safety floor (memory guard). Normally `enabled: false` but self-triggers; do NOT treat its disabled state as broken.
- **`finch:scan`** — every 2h, pure LLM.
- **`ocas-finch:daily`** — daily 6am PT, pure LLM.
- **`ocas-finch:weekly`** — Sunday 8am PT, pure LLM.
- `finch.run` — Full daily pipeline
- `finch.mine` — Mine sessions for signals only
- `finch.compact` — Compact MEMORY.md only
- `finch.route` — Route mined findings
- `finch.dry-run` — Full pipeline without applying changes
- `finch.status` — Show recent stats
- `finch.scan` — Run scan manually
- `finch.work` — Run work manually
- `memory` tool may be unavailable in cron — fall back to direct file edit at the canonical profile memory path; re-read before write on sibling-warning
- `memory_guard.py` — deterministic MEMORY.md safety floor; mandatory post-guard Step 7.5 verification (Methodologies must outrank Course Changes in eviction)
- `self_update.py` / `self_update.sh` — real Python wrapper resolving skill dir from `Path(__file__).resolve().parents[1]`; `self_update.sh` is the GitHub fetch/install path
- `memory_state.py` — persisted reinforcement-state store (Ebbinghaus forgetting curve); `reinforce` / `check` / `route` / `decay-report` subcommands

---

## 📊 Outputs

See `SKILL.md` for outputs, journals, and persistence rules.

---

## 📄 Files

| File | Purpose |
|---|---|
| `SKILL.md` | Skill definition |
| `references/` | Supporting documentation |
| `scripts/` | Helper scripts |


## 📚 Documentation

Read `SKILL.md` for operational details, schemas, and validation rules.

Read `references/` for detailed specifications and examples.


---

## 📄 License

MIT License — see `LICENSE` for details.
