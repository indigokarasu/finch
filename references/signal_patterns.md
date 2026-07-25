# Finch — Signal Pattern Reference

This document defines the signal patterns used by the session miner to detect
learning signals from user messages in session JSONL files.

## Signal Types

### Correction
User explicitly rejects the agent's action and provides alternate direction.

**Patterns:**
- `^no[,.]` — "No, do X instead"
- `^wrong` — "Wrong, try Y"
- `^stop` — "Stop doing that"
- `^don't` — "Don't do that"
- `^never` — "Never do that"
- `\bI meant\b` — "I meant X, not Y"
- `\bnot what I\b` — "That's not what I asked"
- `\bthat's not\b` — "That's not right"
- `\byou (should|shouldn't|need to)\b` — "You should/shouldn't..."
- `\bplease (don't|stop|fix)\b` — "Please don't/stop/fix"
- `\bactually[,.\\s]` — "Actually, X"
- `\binstead[,.\\s]` — "Instead, do X"
- `\bwhat I'm (saying|trying) is\b` — Course correction
- `\bthat's not what I (asked|want|need|meant)\b` — Explicit rejection
- `\byou (misunderstood|misread|got that wrong)\b` — Misunderstanding flag
- `\bI didn't (ask|say|mean)\b` — Intent clarification

**Confidence:** 0.7–0.95

**Routing:** MEMORY.md → User Corrections section

### Directive (Always/Never)
User provides an explicit behavioral rule.

**Patterns:**
- `\balways\b` — "Always do X"
- `\bnever\b` — "Never do X"
- `\bmust (always|never)\b` — Strong directive
- `\bdon't ever\b` — Emphatic never
- `\b(make sure|ensure) (to|you)\b` — "Make sure to X"
- `\bremember to\b` — "Remember to X"
- `\bfrom now on\b` — Behavioral rule change
- `\bgoing forward\b` — Future behavior directive

**Confidence:** 0.7–0.9

**Routing:** MEMORY.md → Always Rules / Never Rules sections (priority 0)

### Course Change
User reinterprets what the agent said and redirects.

**Patterns:**
- `\bwhat I'm (saying|trying) is\b`
- `\bthat's not what I (asked|want|need|meant)\b`
- `\byou (misunderstood|misread|got that wrong)\b`
- `\bI didn't (ask|say|mean)\b`

**Confidence:** 0.9–0.95

**Routing:** MEMORY.md → Course Changes section

### Breakthrough
User confirms something works or expresses satisfaction.

**Patterns:**
- `\bthat's (exactly|perfect|right|correct|it)\b`
- `\bthat works\b`
- `\bgreat (job|work|idea)\b`
- `\bexactly what I (wanted|needed|was looking for)\b`
- `\byou (nailed|got) it\b`
- `\bthis is (great|perfect|exactly right)\b`
- `\blove (it|this|that)\b`
- `\bwell done\b`

**Confidence:** 0.8–0.95

**Routing:** MEMORY.md → What Works section

### Methodology
User describes a reproducible process.

**Patterns:**
- `\bthe (way|method|process|approach|trick) (is|that works)\b`
- `\bwhat works (is|for me|best)\b`
- `\bthe (key|secret|trick|hack) is\b`
- `\bthis is how (you|we|I) (should|do|can)\b`
- `\bthe pattern (is|here)\b`
- Step-by-step patterns (numbered steps)

**Confidence:** 0.7–0.9

**Routing:** Skill patch (if related skill exists) or MEMORY.md → Methodologies

### Stop
User stops or cancels a task.

**Patterns:**
- `^stop$` — Bare stop
- `^stop\b` — Stop with context
- `^cancel\b` — Cancel
- `^abort\b` — Abort
- `^never mind\b` — Never mind
- `^forget (it|that|this)\b` — Forget it
- `^not worth (it|the effort)\b` — Not worth continuing

**Confidence:** 0.85–0.95

**Routing:** MEMORY.md → Stop Signals section

## Failure-Phase Patterns

Corrections should be tagged with their failure phase to enable targeted skill patches. After detecting any correction signal above, classify the phase:

### Planning failure patterns
Agent chose wrong approach, had incorrect assumptions, or missed prerequisites.

**Patterns:**
- `\bshould have (checked|verified|confirmed|read|looked)\b`
- `\bbefore (you|doing|starting)\b.*\b(should|need to|have to)\b`
- `\bwrong (approach|method|way|direction|tool)\b`
- `\bthat's not the right (way|approach|method)\b`
- `\bthis won't work (because|since)\b`
- `\bdidn't (consider|account for|think about)\b`
- `\bmissing (prerequisite|dependency|step|requirement)\b`

**Tag:** `[PHASE:planning]`

### Execution failure patterns
Right plan but wrong tool call, wrong parameters, API failure, or timeout.

**Patterns:**
- `\bfailed (to|because|with)\b`
- `\b(error|timeout|exception|reject)\b`
- `\bwrong (parameter|argument|value|option|flag)\b`
- `\b(doesn't|does not) (exist|work|support)\b`
- `\bpointing to (wrong|old|incorrect)\b`
- `\b(invalid|bad|malformed) (input|format|syntax)\b`

**Tag:** `[PHASE:execution]`

### Response failure patterns
Correct result but wrong output format, verbosity, tone, or framing.

**Patterns:**
- `\b(too|way too|far too) (verbose|long|wordy|brief|short)\b`
- `\b(format|structure|layout|style)\b.*\b(wrong|bad|doesn't fit)\b`
- `\bjust (give|tell|show) (me )?(the|it)\b`
- `\bdon't (explain|narrate|elaborate|summarize)\b`
- `\b(ignore|skip|remove) (the|this) (summary|explanation|context)\b`
- `\b(make it|keep it) (concise|short|brief|simple)\b`

**Tag:** `[PHASE:response]`

When routing, include the phase tag so the skill patch targets the right section of the skill.

## Filtering Rules

The miner automatically excludes:
- Messages from cron sessions (platform = "cron")
- System-generated messages (starting with "[System note:", "[IMPORTANT:", etc.)
- Context compaction summaries (starting with "[CONTEXT COMPACTION")
- Messages shorter than 3 characters
- Tool result messages (role != "user")

## Confidence Scores

| Score | Meaning |
|-------|---------|
| 0.95 | Explicit, unambiguous signal ("Never do X", "That's exactly right") |
| 0.85 | Strong signal with clear intent ("Don't do that", "Stop") |
| 0.70 | Moderate signal, may need context ("Actually...", "Instead...") |
| 0.50 | Weak signal, likely needs manual review |

Use `--min-confidence 0.7` to focus on high-confidence findings.
