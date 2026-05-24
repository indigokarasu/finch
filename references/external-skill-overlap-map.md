# External Skill Overlap Map

This file documents overlaps between OCAS skills and externally-sourced skills installed
from other repositories. The curator uses this to decide consolidation candidates.

## finch ↔ reflexion-memorize

- **ocas-finch**: Automated session mining → MEMORY.md / skill patches. Runs on cron.
- **reflexion-memorize**: Manual reflection → AGENTS.md / skill files. Triggered by user or after reflexion-reflect.

**Relationship**: finch is the automated pipeline; reflexion-memorize is the manual trigger.
They write to the same targets (MEMORY.md, skill files). finch should take precedence
for automated compaction; reflexion-memorize is for explicit "save this insight" moments.
No consolidation needed — different triggers, same destination is fine.

## mentor ↔ cek-judge ↔ reflexion-critique

- **ocas-mentor**: Full orchestration + evaluation engine. Reads journals, scores OKRs, proposes variants.
- **cek-judge**: Two-phase meta-judge → judge pipeline for evaluating completed work.
- **reflexion-critique**: Adversarial single-pass critique with structured scoring.

**Relationship**: mentor is the umbrella. cek-judge and reflexion-critique are specialized
evaluation tools. mentor's "Constraint Transparency" section references prism-reflect.

## subagent-driven-dev ↔ delegate_task

- **cek-subagent-driven-dev**: Structured subagent-per-task workflow with review gates.
- **delegate_task** (built-in tool): The actual mechanism for dispatching subagents.

**Relationship**: cek-subagent-driven-dev is a workflow pattern; delegate_task is the tool.
No conflict — the skill describes HOW to use delegate_task for plan execution.

## prism-* ↔ ocas-fellow

- **prism-* skills**: Analytical lenses for code/artifact review.
- **ocas-fellow**: Empirical experimentation engine for skill evaluation.

**Relationship**: prism skills are for human-requested analysis; fellow is for automated
skill variant evaluation. Complementary, not overlapping.
