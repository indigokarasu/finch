# Finch — Skill Library Maintenance

After every session, review the conversation for signals and update the skill library. This is not optional — a pass that does nothing is a missed learning opportunity.

## Signals that warrant action (any one triggers an update)

1. **User corrected style, tone, format, legibility, or verbosity.** Frustration signals like "stop doing X", "this is too verbose", "don't format like this", "why are you explaining", "just give me the answer", "you always do Y and I hate it", or an explicit "remember this" are **first-class skill signals**, not just memory signals. Update the relevant skill(s) to embed the preference so the next session starts already knowing.

2. **User corrected workflow, approach, or sequence of steps.** Encode the correction as a pitfall or explicit step in the skill that governs that class of task.

3. **Non-trivial technique, fix, workaround, debugging path, or tool-usage pattern emerged** that a future session would benefit from. Capture it.

4. **A skill that got loaded or consulted turned out to be wrong, missing a step, or outdated.** Patch it immediately.

## Preference order for where to put the update

1. **Update a currently-loaded skill** — If the session loaded a skill via `/skill-name` or `skill_view`, and that skill covers the territory of the new learning, patch it first.

2. **Update an existing umbrella skill** — If no loaded skill fits but an existing class-level skill does, patch it.

3. **Add a support file under an existing umbrella** — Use the right directory:
   - `references/<topic>.md` — session-specific detail, error transcripts, reproduction recipes, provider quirks, condensed knowledge banks, quoted research, API docs, external authoritative excerpts, or domain notes.
   - `templates/<name>.<ext>` — starter files meant to be copied and modified.
   - `scripts/<name>.<ext>` — statically re-runnable actions (verification scripts, fixture generators, deterministic probes).

4. **Create a new class-level umbrella skill** — Only when no existing skill covers the class. The name MUST be at the class level.

## User-preference embedding

When the user expressed a style/format/workflow preference, the update belongs in the SKILL.md body, not just in memory. Skills capture "how to do this class of task for this user."

## What NOT to capture (these become persistent self-imposed constraints)

- **Environment-dependent failures**: missing binaries, fresh-install errors, post-migration path mismatches, "command not found", unconfigured credentials, uninstalled packages.
- **Negative claims about tools or features** ("browser tools do not work", "X tool is broken"). These harden into refusals the agent cites against itself for months after the actual problem was fixed.
- **Session-specific transient errors** that resolved before the conversation ended.
- **One-off task narratives.** A user asking "summarize today's market" or "analyze this PR" is not a class of work that warrants a skill.

## Protected skills (DO NOT edit)

- Bundled skills (shipped with Hermes, e.g. `hermes-agent`).
- Hub-installed skills (installed via `hermes skills install`).

Pinned skills CAN be improved — pin only blocks deletion/archive/consolidation by the curator, not content updates.

## Overlap detection

If you notice two existing skills that overlap, note it in your reply — the background curator handles consolidation at scale.

## "Nothing to save" is a real option

If the session ran smoothly with no corrections and produced no new technique, say "Nothing to save." and stop. But do NOT make it the default — most sessions produce at least one signal.
