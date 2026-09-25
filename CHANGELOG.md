# Changelog

## [3.2.1] - 2026-09-24

### Changed
- **SKILL.md progressive-disclosure pass** — the inline Scanning Gotchas list is now a curated top-traps set with pointers into `references/scanning-gotchas.md` / `references/finch-scan-pitfalls.md` (mixed recovery, table of contents, and path traps moved there); manual-run / 401 / cron-rebase detail moved to `references/manual-run-verification.md`; OKR rows moved into `references/okrs.md`.
- **Portability fix** — `scripts/finch_hooks_plugin.py` guards the POSIX-only `fcntl` import so `--help` and non-POSIX hosts degrade to an unlocked append instead of failing at import.
- **Test fix** — the HERMES_PROFILE path-doubling regression now asserts on the path relative to HERMES_HOME, so a TMPDIR that itself contains `profiles/` no longer produces a false failure.

## [3.2.0] - 2026-09-16

### Changed
- **Staged patch routing** — proposed skill patches mined from session corrections are staged under `{agent_root}/commons/data/ocas-forge/staged/{skill}/` for `ocas-fellow` evaluation before committing to production (staged-write-approval gate). MEMORY.md behavioral rules still apply immediately (priority 0); skill rebuilds go through staging.