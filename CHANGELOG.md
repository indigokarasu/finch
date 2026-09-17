# Changelog

## [3.2.0] - 2026-09-16

### Changed
- **Staged patch routing** — proposed skill patches mined from session corrections are staged under `{agent_root}/commons/data/ocas-forge/staged/{skill}/` for `ocas-fellow` evaluation before committing to production (staged-write-approval gate). MEMORY.md behavioral rules still apply immediately (priority 0); skill rebuilds go through staging.