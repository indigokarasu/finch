# Changelog

## [3.4.0] - 2026-11-15

### Fixed
- **SKILL.md matches the 3.3.0 scope.** `finch:scan` reads 4 sources (sessions, cron health, kanban, system). The claims that Finch reads email, calendar and Drive are gone, the retired `finch:work` checklist is replaced by a `finch:track` section, and the author field reads "Indigo Karasu" again.
- **All script test suites run in CI.** `tests/test_script_suites.py` runs every `scripts/test_*.py` (20 suites that CI never ran). Suites that need host-only state exit 77 and are reported as named skips, never as passes. Three suites that failed on a clean machine now use fixtures.
- **PII gate protects the public identity.** `check_no_pii.py` has a `PUBLIC_IDENTITY` allowlist and a `scrubbed_identity` check that fails when a scrub damages the author name.

### Changed
- **Publishing is gated.** `data/` is gitignored and the empty `data/activity_model.jsonl` is untracked. Docs replace the blind `git add -A` push to `main` with named staging, the PII gate and a CI-checked PR (`references/reference-file-workflow.md` § Publishing).
- **References reorganised.** `references/README.md` indexes every file by job. Retired executor and Gmail-scan docs moved to `references/retired/`; four empty stubs removed.
- **README** describes current behavior. **Evals:** one file, `evals/evals.json`, at 3.4.0, with cases for the tracker and the retired scope.

### Removed
- Six one-off edit scripts at the repo root (`improve_d5d6.sh`, `apply_pointers.sh`, `extract_and_point.py`, `extract_sections.sh`, `backup.sh`, `backup_skill.sh`) and the duplicate root `evals.json`.

## [3.3.0] - 2026-10-23

### Changed
- **Scope reset** — Finch observes and records only. The inbox/calendar/Drive scan and the task executor are retired. New `finch:track` keeps projects, in-flight tasks and todos from sessions, journals and logs (`data/ocas-finch/tracker.json` + `tracker.md`); project status is Mentor's call. See `references/inflight-tracker.md`.

## [3.2.1] - 2026-09-24

### Changed
- **SKILL.md progressive-disclosure pass** — the inline Scanning Gotchas list is now a curated top-traps set with pointers into `references/scanning-gotchas.md` / `references/finch-scan-pitfalls.md` (mixed recovery, table of contents, and path traps moved there); manual-run / 401 / cron-rebase detail moved to `references/manual-run-verification.md`; OKR rows moved into `references/okrs.md`.
- **Portability fix** — `scripts/finch_hooks_plugin.py` guards the POSIX-only `fcntl` import so `--help` and non-POSIX hosts degrade to an unlocked append instead of failing at import.
- **Test fix** — the HERMES_PROFILE path-doubling regression now asserts on the path relative to HERMES_HOME, so a TMPDIR that itself contains `profiles/` no longer produces a false failure.

## [3.2.0] - 2026-09-16

### Changed
- **Staged patch routing** — proposed skill patches mined from session corrections are staged under `{agent_root}/commons/data/ocas-forge/staged/{skill}/` for `ocas-fellow` evaluation before committing to production (staged-write-approval gate). MEMORY.md behavioral rules still apply immediately (priority 0); skill rebuilds go through staging.