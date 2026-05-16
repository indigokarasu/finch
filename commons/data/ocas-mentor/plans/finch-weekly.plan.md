---
plan_id: finch-weekly
name: Finch Weekly Self-Improvement Review
version: "2.0.0"
description: >
  Weekly deep session mining run. Mines the last 7 days of sessions, compacts
  MEMORY.md, routes findings, and presents the full action plan to the user for
  approval before applying. Runs Sunday 8am PT.
parameters:
  min_confidence:
    type: number
    required: false
    default: 0.7
    description: Minimum confidence threshold for findings.
  days:
    type: number
    required: false
    default: 7
    description: Number of days to mine.
  auto_apply:
    type: boolean
    required: false
    default: false
    description: If true, auto-apply without user review (for testing).
steps:
  - id: compact
    name: Compact MEMORY.md
    skill: ocas-finch
    command: finch.compact
    on_failure: abort
  - id: mine
    name: Mine Sessions (7 days)
    skill: ocas-finch
    command: finch.mine
    on_failure: abort
  - id: route
    name: Route Findings
    skill: ocas-finch
    command: finch.route
    on_failure: abort
  - id: review
    name: Present Plan for Review
    skill: ocas-finch
    command: finch.dry-run
    on_failure: abort
  - id: apply
    name: Apply Approved Findings
    skill: ocas-finch
    command: finch.apply
    on_failure: skip
---

# Finch Weekly Self-Improvement Review

Weekly deep session mining run. Mines the last 7 days, compacts MEMORY.md,
routes findings, and presents the full action plan to the user for approval
before applying.

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

## Step 4: review

**Skill:** ocas-finch
**Command:** finch.dry-run

**Inputs:**
- `plan`: `{{steps.route.action_plan}}`

**Outputs:**
- `review_summary`: formatted plan showing each finding, its signal type, confidence, routing target, and suggested entry text

**On failure:** abort
**Notes:** Presents the full plan to the user. For each finding: what signal was
detected, what it means, where it's being routed, and the exact text that will
be written. User may skip, redirect, edit, or approve each finding.

## Step 5: apply

**Skill:** ocas-finch
**Command:** finch.apply

**Inputs:**
- `plan`: `{{steps.route.action_plan}}`
- `approved_only`: true

**Outputs:**
- `applied_count`: number of findings applied
- `skipped_count`: number of findings skipped by user

**On failure:** skip
**Notes:** Only applies findings the user approved. Directives (Always/Never) require
explicit approval — never auto-applied in weekly mode.
