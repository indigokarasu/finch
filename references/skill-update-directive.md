# Skill Update Directive — End-of-Session Review Methodology

## When to run

At the end of every session, before finishing. This is not optional — it's part of the session lifecycle.

## What to scan for

Review the conversation for any of these signals:

1. **Style/tone/format corrections** — User said "stop doing X", "this is too verbose", "don't format like this", "why are you explaining", "just give me the answer", "you always do Y and I hate it", or "remember this". These are FIRST-CLASS skill signals.

2. **Workflow/approach corrections** — User corrected your sequence of steps, told you to do something differently, or redirected your approach.

3. **New techniques or patterns** — A non-trivial fix, workaround, debugging path, or tool-usage pattern emerged that a future session would benefit from.

4. **Wrong/missing/outdated skill content** — A skill you loaded or consulted turned out to be incorrect, missing a step, or outdated.

## Routing preference (earliest fit wins)

1. **Update the loaded skill** — If a skill was loaded via /skill-name or skill_view and it covers the territory of the new learning, patch it first.

2. **Update an existing umbrella** — If no loaded skill fits but an existing class-level skill does, patch it.

3. **Add a support file** — Under an existing umbrella: references/ for detail/knowledge, templates/ for boilerplate, scripts/ for runnable actions. Add a one-line pointer in SKILL.md.

4. **Create a new class-level umbrella** — Only when no existing skill covers the class. Name MUST be at class level, not session-specific.

## Style corrections belong in SKILL.md body

When the user expressed a style/format/workflow preference, the update belongs in the SKILL.md body, not just in memory.

## What NOT to capture

- Environment-dependent failures, negative tool claims, transient errors, one-off narratives.
- If a tool failed because of setup state, capture the FIX, not the failure.

## Reference index pattern

When creating reference files that accumulate across sessions, use the centralized pattern:
1. Store files in `~/.hermes/references/` (not inside individual skill directories)
2. Maintain `~/.hermes/references/INDEX.md` with a table: `| File | When to use |`
3. Add a one-liner in MEMORY.md: `Reference index: /root/.hermes/references/INDEX.md`

This ensures any session can discover and use accumulated knowledge regardless of which skill triggered its creation.

## Skill discovery pattern

When searching for skills matching a pattern, use `find` not glob:
- **Wrong**: `ls ~/.hermes/skills/ocas-*/` — misses subdirectory skills
- **Right**: `find ~/.hermes/skills -name "SKILL.md" -path "*/ocas*"` — catches all locations including `infrastructure/` and nested dirs

## Protected skills: DO NOT edit bundled, hub-installed, or pinned skills.

"Nothing to save" is valid but not default.