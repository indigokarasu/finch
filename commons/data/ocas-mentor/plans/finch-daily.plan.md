---
plan_id: finch-daily
name: Finch Daily Self-Improvement Run
version: "2.0.0"
description: >
  Daily session mining run. Mines the last 24 hours of sessions, compacts
  MEMORY.md, routes findings, auto-applies low-risk corrections, and flags
  directives/contradictions for review. Runs at 6am PT.
parameters:
  min_confidence:
    type: number
    required: false
    default: 0.7
    description: Minimum confidence threshold for auto-apply.
  days:
    type: number
    required: false
    default: 1
    description: Number of days to mine.
steps:
  - id: compact
    name: Compact MEMORY.md
    skill: ocas-finch
    command: finch.compact
    on_failure: abort
  - id: mine
    name: Mine Sessions
    skill: ocas-finch
    command: finch.mine
    on_failure: abort
  - id: route
    name: Route Findings
    skill: ocas-finch
    command: finch.route
    on_failure: abort
  - id: apply
    name: Auto-Apply Low-Risk
    skill: ocas-finch
    command: finch.apply
    on_failure: skip
---

# Finch Daily Self-Improvement Run

Mines the last 24 hours of sessions, compacts MEMORY.md, routes findings,
auto-applies low-risk corrections, and flags directives/contradictions for
review.

## Step 1: compact

**Skill:** ocas-finch
**Command:** finch.compact

**Inputs:**
- `apply`: true

**Outputs:**
- `compaction_report`: dedup count, evictions, contradictions found, final MEMORY.md size

**On failure:** abort
**Notes:** Must run first to free space in MEMORY.md before new findings are applied.

## Step 2: mine

**Skill:** ocas-finch
**Command:** finch.mine

**Inputs:**
- `days`: `{{params.days}}`
- `min_confidence`: `{{params.min_confidence}}`
- `json`: true

**Outputs:**
- `miner_output`: raw JSON with findings array and metadata
- `total_findings`: count of all signals found
- `by_type`: breakdown by signal type

**On failure:** abort
**Notes:** Mines session JSONL files directly. Emits Action Journal and DecisionRecords automatically.

## Step 3: route

**Skill:** ocas-finch
**Command:** finch.route

**Inputs:**
- `input`: `{{steps.mine.miner_output}}`
- `json`: true

**Outputs:**
- `action_plan`: structured plan with memory_additions, skill_patches, manual_review, overflow
- `summary`: counts by target type

**On failure:** abort
**Notes:** Size-aware routing. MEMORY.md overflow goes to skill files or manual review queue.

## Step 4: apply

**Skill:** ocas-finch
**Command:** finch.apply

**Inputs:**
- `plan`: `{{steps.route.action_plan}}`
- `auto_apply_threshold`: 0.8
- `skip_directives`: true

**Outputs:**
- `applied_count`: number of findings auto-applied
- `flagged_for_review`: directives and contradictions requiring human review

**On failure:** skip
**Notes:** Only auto-applies corrections with confidence >= 0.8. Directives (Always/Never)
are always flagged for review — never auto-applied. Contradictions are flagged, not resolved.
