# session-2026-05-31-disk-recovery.md

## Disk-100% Crisis During finch:scan (May 31, 2026)

### What Happened
- `/dev/sda1` at 100% (96G/96G) when finch:scan started
- **All Google MCP calls failed with `[Errno 28] No space left on device`** — NOT auth errors
- Root cause: accumulated state-snapshots (24G) + /root/backups (18G)
- Cleaned up: deleted both, freed 42G, disk now at 57%
- **After cleanup**: MCP immediately returned re-auth consent URL — tokens were corrupted by ENOSPC, not just expired

### Key Diagnostic Pattern
When ALL Google MCP services (Gmail, Calendar, Drive) fail simultaneously:
1. **RUN `df -h /` FIRST** — if at 100%, it's ENOSPC, not auth
2. Do NOT attempt OAuth re-auth until disk has free space — token writes need bytes
3. The MCP error message changes once disk is freed: ENOSPC → auth-required or consent URL

### Cleanup Targets (in order of safety during emergency)
1. `/root/.hermes/state-snapshots/` — pre-update rollback points, zero risk if no pending update
2. `/root/backups/` — stale copies of state.db, session DBs, mempalace
3. `/root/.hermes/sessions/` — large session files (fallback only, requires state.db intact)
4. `/root/indigo-repo/` — git clone copies (refetchable)

### Parallel Tool Batch Poisoning
Calling `cronjob(action='list')` in a batch of 6 tools failed because `cronjob` doesn't exist in this session's toolset. The error "Skipped: another tool call in this take used an invalid name" caused ALL 6 parallel calls to be skipped. 

**Lesson**: Never call tools in parallel when one tool name is unverified. Either:
- Call tools individually, OR
- Verify tool availability first via skills_list, OR
- Use execute_code which doesn't have this poisoning behavior
