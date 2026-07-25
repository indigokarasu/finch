# Post-Session Skill Update Methodology

This document captures the framework for deciding what to save after each session and where it belongs.

## Core Principle

**Most sessions produce at least one skill update.** A pass that does nothing is a missed learning opportunity, not a neutral outcome. "Nothing to save" is a real option but should NOT be the default.

## Signal Types That Warrant Action

1. **Style/tone/format corrections** — User corrected verbosity, formatting, legibility, tone, or communication style. Frustration signals like "stop doing X", "this is too verbose", "don't format like this", "why are you explaining", "just give me the answer", "you always do Y and I hate it", or "remember this" are **FIRST-CLASS skill signals**, not just memory signals.

2. **Workflow/approach corrections** — User corrected the sequence of steps, the approach, or the method. Encode as a pitfall or explicit step in the governing skill.

3. **New technique/fix/workaround** — Non-trivial debugging path, tool-usage pattern, or workaround emerged that a future session would benefit from.

4. **Skill was wrong/missing/outdated** — A skill that got loaded turned out to have wrong instructions, missing steps, or stale content. Patch it NOW.

## Preference Order (pick the earliest that fits)

1. **Update a currently-loaded skill** — If a skill was loaded via /skill-name or skill_view during this session and it covers the territory of the new learning, PATCH that one first. It was in play, so it's the right one to extend.

2. **Update an existing umbrella skill** — If no loaded skill fits but an existing class-level skill does, patch it. Add a subsection, pitfall, or broaden a trigger.

3. **Add a support file under an existing umbrella** — Use the right directory:
   - `references/<topic>.md` — session-specific detail, error transcripts, reproduction recipes, provider quirks, condensed knowledge banks
   - `templates/<name>.<ext>` — starter files meant to be copied and modified
   - `scripts/<name>.<ext>` — statically re-runnable actions (verification scripts, probes)
   The umbrella's SKILL.md should gain a one-line pointer to any new support file.

4. **Create a new class-level umbrella skill** — Only when no existing skill covers the class. Name MUST be at the class level, NOT a specific PR number, error string, feature codename, or session artifact.

## Memory vs Skill: Where Lessons Land

- **Memory** = "Who the user is and what the current situation and state of your operations are" — preferences, habits, current project state, operational facts.
- **Skill** = "How to do this class of task for this user" — procedures, workflows, pitfalls, quality standards.

When the user complains about how you handled a task, the skill that governs that task needs to carry the lesson. Don't just put it in memory.

## What NOT to Capture

- **Environment-dependent failures** — missing binaries, fresh-install errors, post-migration path mismatches, "command not found", unconfigured credentials. The user can fix these.
- **Negative claims about tools** — "browser tools do not work", "X tool is broken", "cannot use Y". These harden into refusals that persist after the actual problem is fixed.
- **Transient errors that resolved** — If retrying worked, the lesson is the retry pattern, not the original failure.
- **One-off task narratives** — "summarize today's market" or "analyze this PR" is not a class of work.

If a tool failed because of setup state, capture the FIX (install command, config step) under an existing setup/troubleshooting skill — never "this tool does not work" as a standalone constraint.

## Overlap Detection

If two existing skills overlap, note it in the session reply. The background curator handles consolidation at scale.
