# Hermes Security Architecture — System Self-Knowledge

Finch's understanding of the security system it operates within. Updated May 2026 from first-principles analysis of `skills_guard.py`, `path_security.py`, `skills_hub.py`, and the agentskill.sh scanner.

## The Three-Layer Defense Model

```
Layer 1: skills_guard.py     — regex static analysis (~400 patterns, 8 categories)
Layer 2: path_security.py    — runtime path validation (resolve + relative_to)
Layer 3: tirith_security.py  — pre-exec command scanning (external binary)
```

Plus opt-in: `skills_ast_audit.py` for Python dynamic import/eval detection.

## Structural Invariant 1: Regex Scanning Cannot Distinguish Intent From Description

`skills_guard.py` operates on raw text matching with zero semantic understanding. This means:

- **Any path reference is flagged regardless of context.** A sentence saying "never read `~/.hermes/.env`" still matches the `~/.hermes/.env` pattern. The scanner doesn't parse negation or section headers.
- **Operational descriptions look like attacks.** "Reads session JSONL from `~/.hermes/sessions/`" triggers "Sensitive File Access" even though this is the skill reading its own platform's data.
- **Command documentation looks like instructions.** Describing what `bower.apply` does ("executes approved proposals") triggers "Social Engineering" because the pattern matcher sees urgency language.

**Implication for Finch:** When reviewing security audit results on OCAS skills, discount findings that are purely descriptive. Focus on: inline credentials, access to paths outside `~/.hermes/`, destructive operations without confirmation gates.

## Structural Invariant 2: No "Self" Trust Tier

The trust model has four levels: `builtin` → `trusted` → `community` → `agent-created`. There is no tier for "the agent's own skills running on its own platform."

- OCAS skills authored by Indigo receive the same scrutiny as untrusted community code when scanned externally
- There is no signing or provenance mechanism marking agent-authored skills as first-party
- The `TRUSTED_REPOS` set only contains 3 GitHub orgs (`openai/skills`, `anthropics/skills`, `huggingface/skills`)

**Implication for Finch:** Don't treat external scanner scores on OCAS skills as actionable security findings without manual review. The scanner doesn't know these are our own skills.

## Structural Invariant 3: Directory-Level Sandboxing

`path_security.py:validate_within_dir()` checks that resolved paths stay within allowed roots. But:

- It operates at directory level, not file level
- It doesn't track provenance — a compromised skill writing to `~/.hermes/skills/` is within bounds
- Symlinks are followed by `resolve()`, so a symlink within the allowed directory can point outside

**Implication for Finch:** When creating files, always use explicit paths. Never construct paths from user input or session content without validation.

## Structural Invariant 4: Pattern Library Grows Monotonically

New patterns are added when new threats are discovered. Old patterns are never removed or refined for false positives. This means:

- The false-positive rate can only increase over time
- Each new pattern adds catch capability but also adds potential false positives
- There is no systematic false-positive regression test suite for the 400+ patterns

**Implication for Finch:** When a new security finding appears on an OCAS skill that previously passed, check whether a new pattern was added rather than assuming the skill changed.

## The Conservation Law

This system **maximizes catch rate at the expense of false-positive discrimination**. This trade-off is inherent to regex-based scanning without semantic preprocessing. It cannot be shifted within the current architecture — only a semantic pre-processor (understanding SKILL.md structure, section headers, negation) would improve discrimination without reducing catch.

## Known False Positive Patterns (agentskill.sh)

| Pattern | Trigger | Reality |
|---------|---------|---------|
| `~/.hermes/` paths | Any reference to `~/.hermes/sessions/`, `~/.hermes/skills/`, etc. | Expected for Hermes skills operating on their own platform |
| `curl` to `api.github.com` | Flagged as "non-GitHub URL" | GitHub's own API endpoint |
| "auto-approved" in descriptions | Flagged as "Social Engineering / urgency" | Operational description of command behavior |
| `~/.hermes/references/*.md` | Flagged as "home directory dotfiles" | Hermes's own cross-session knowledge store |

## What To Do When OCAS Skills Get Flagged

1. **Classify the finding:** Is it (a) scanner limitation, (b) false positive on trusted code, or (c) real gap?
2. **For (a):** Document in pitfalls.md. Don't restructure the skill.
3. **For (b):** If the fix is trivial (rephrase, swap `curl` for `gh api`), apply it. Don't compromise skill clarity for scanner scores.
4. **For (c):** Fix the actual issue. File a DecisionRecord. Update the relevant skill.
5. **Never:** Remove operational descriptions, add unnecessary confirmation gates, or degrade skill usability to improve scanner scores.

## Scanner Categories Tested

The agentskill.sh scanner tests 10 categories. Only "Sensitive File Access" and "Data Exfiltration" are relevant to OCAS skills:

| Category | Relevant to OCAS? | Notes |
|----------|-------------------|-------|
| Prompt Injection | No | OCAS skills don't process untrusted user content |
| Command Injection | No | No shell interpolation of user input |
| Data Exfiltration | Yes | False positive on `curl` to GitHub API |
| Credential Harvesting | No | OCAS skills don't handle credentials |
| Obfuscation | No | No encoding/eval patterns |
| Sensitive File Access | Yes | False positive on `~/.hermes/` paths |
| External Calls | No | Expected for update checks |
| Persistence | No | Cron jobs are declared, not injected |
| Social Engineering | Yes | False positive on "auto-approved" descriptions |
| ClickFix Attack | No | No user-facing instructions |
| Staged Malware | No | No multi-stage payloads |
| Second-Order Injection | No | No stored content executed later |
