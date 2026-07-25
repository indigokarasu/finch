# TODO: Finch — Praxis Interface + Corvus Signal Output

## Priority: MEDIUM

### Issue: No Interface with Praxis or Corvus
Finch mines sessions for corrections, breakthroughs, and methodologies, but the findings go only to MEMORY.md and skill patches. Two other skills could benefit:

1. **Praxis** could consume Finch findings as behavioral events (e.g., "user corrected X" → lesson)
2. **Corvus** could consume Finch signals for pattern detection across sessions

### Proposed Changes

#### Finch → Praxis Interface
- Finch emits `CorrectionSignal` files to a shared directory
- Praxis reads these as event inputs for lesson extraction
- Schema: `{type: correction|breakthrough|methodology|directive, content, source_session, timestamp}`

#### Finch → Corvus Interface
- Finch emits structured findings to `commons/data/ocas-finch/signals/`
- Corvus ingests these during analysis cycles (similar to how it reads Thread journals)

### Steps
1. Add signal emission to Finch's session mining pipeline
2. Add signal ingestion to Praxis's event recording
3. Add Finch to Corvus's data source list
4. Define shared signal schema in both skills

### Dependencies
- Praxis and Corvus must be available
- No changes to Finch's existing MEMORY.md/skill patch output

### Risk
Low — additive interfaces only
