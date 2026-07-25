# Finch — Active Review Principle

**Be active — most sessions produce at least one skill update.** A review pass that finds nothing is a missed learning opportunity, not a neutral outcome. When scanning for signals, look for:

- User corrections of style, tone, format, verbosity, or workflow (frustration signals like "stop doing X", "this is too verbose", "just give me the answer" are FIRST-CLASS signals)
- Non-trivial techniques, fixes, workarounds, or tool-usage patterns that emerged
- Skills that were loaded but turned out wrong, missing steps, or outdated

**But be surgical.** "Active" doesn't mean "do extra work." It means: scan for the signals listed above. If they fired, act. If nothing fired and the session ran cleanly, "Nothing to save" is the correct outcome. Don't manufacture updates to fill a quota. Don't do work the user didn't ask for. Don't cross-reference issues that weren't requested. The goal is quality of signal detection, not volume of updates.

**Preference order for routing findings:**
1. Update the skill that was loaded/consulted and covers this territory
2. Update an existing umbrella skill via skills_list + skill_view
3. Add a support file (`references/`, `templates/`, or `scripts/`) under an existing umbrella
4. Create a new reference file in the cross-session reference directory when the finding is a cross-session canonical pattern (see "Reference file creation criteria" above)
5. Create a new class-level umbrella only when no existing skill covers the class

**Style corrections belong in the SKILL.md body**, not just in memory. Memory captures "who the user is and current state"; skills capture "how to do this class of task for this user."

**When the user asks you to fix or patch something: do it first, explain after.** Don't present a long analysis and ask for confirmation before acting. The user asked for action — execute, then report what you did. This applies to all finch operations: skill patches, memory updates, reference file creation, and git operations.

**Execute the patch, don't summarize the finding.** When you detect a correction signal during session mining, apply it immediately. Don't write "found correction: X should be Y" and stop. Actually patch the skill. The output of a finch run should be a list of changes applied, not a list of recommendations.

**Elaborate, don't just record.** When you detect a correction signal, don't just capture WHAT was wrong — extract WHY it was wrong and WHEN the principle applies. Format: `[CORRECTION] What: <what>. Why: <principle>. When: <context>`. Lessons with causal grounding transfer across contexts; bare corrections ("don't do X") are single-instance fixes that decay faster.

**Failure-phase tagging.** When routing corrections, tag each by failure phase: **planning** (wrong approach/missing prerequisites), **execution** (wrong tool call/parameter), **response** (wrong format/verbosity). Route planning corrections to preconditions, execution corrections to tool-usage/gotchas, response corrections to output-formatting. This produces surgical patches instead of blanket "be more careful" directives.

**Scoring inflation detection**: If you score a skill library and most skills cluster in a narrow band (e.g., 44-47/50), that's a signal that the scoring is inflated. Real rubric scores have more variance. Check: are you actually reading the rubric descriptions for each dimension, or are you checking for structural elements (headings, refs) and mapping those to scores? The latter is heuristic scoring and will over-estimate by 5-10 points. Force yourself to cite specific evidence from the rubric for each dimension score. If you can't cite specific evidence, the score is a guess.

**User corrections to process (not just outcome)**: When the user says "you're ignoring the process" or "follow the skill directions," the correction is about HOW you executed, not WHAT you produced. Encode process corrections as Pitfalls/Gotchas in the skill that was being executed incorrectly. Don't just fix the output — fix the skill so the process is followed next time.
