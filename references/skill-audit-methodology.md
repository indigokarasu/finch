# Skill Audit Methodology

## Rubric (agentskill.sh quality dimensions)

1. **Be Concise** — Code ratio in SKILL.md body must be <20%. Move large code blocks to `references/`.
2. **Feedback Loops** — Every skill must have validation/verification steps (read-back, spot-check, confirm).
3. **Progressive Disclosure** — SKILL.md body stays lean; detail lives in `references/`, `templates/`, `scripts/`.
4. **Support File Maps** — Every support file gets a "When to read" signal in the SKILL.md map. Signals must be conditional ("when X" not just "this file exists").
5. **Gotchas/Pitfalls** — Every skill needs a `## Gotchas` or `## Pitfalls` section with hard-won lessons.
6. **License** — Every SKILL.md needs `license: MIT` (or appropriate) in frontmatter.
7. **Naming** — Skill names are class-level (what kind of task), not session-specific (what happened today).
8. **Checklists** — Complex skills need task progress tracking with checkable steps.

## Audit Process

1. `skills_list` to enumerate all skills
2. `skill_view(name)` on each to load full content
3. Measure code ratio: `lines_in_code_blocks / total_lines * 100`
4. Check for feedback loops (grep for validate/verify/confirm/read-back/spot-check)
5. Check for conditional support file maps ("When to read")
6. Check for Gotchas/Pitfalls sections
7. Check for license in frontmatter
8. Patch failures via `skill_manage(action='patch')`

## Common Fixes

- Code ratio >20%: Move code blocks to `references/<topic>.md`, replace with one-line pointer
- No feedback loop: Add validation step to core workflow (e.g., "verify output is valid JSON" or "re-query to confirm")
- Passive support map: Rewrite as conditional ("When X, read Y")
- No gotchas: Add section with 3-5 pitfalls from actual usage patterns
- Missing license: Add `license: MIT` to frontmatter

## Overlap Detection

When two skills share >50% of their signal patterns or workflows, flag for consolidation. The umbrella principle: one class-level skill with support files per sub-domain, not N flat skills per sub-domain.
