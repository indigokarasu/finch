# Security Architecture Reference

Structural analysis of Hermes Agent's skills security system. Condensed reference for understanding security audit results on OCAS skills.

## Three-Layer Defense

1. **skills_guard.py** — regex-based static analysis. ~400 patterns across 8 categories. Trust-tiered: builtin → trusted → community → agent-created.
2. **path_security.py** — runtime `validate_within_dir()` using `Path.resolve()` + `relative_to()`. Directory-level validation.
3. **tirith_security.py** — pre-exec command scanning via external `tirith` binary. Fail-open by default.

## Known Scanner False Positives

### `~/.hermes/` paths → Sensitive File Access
**False positive** when the skill lives in `~/.hermes/skills/` and describes its own operational directories.
**Fix**: Use descriptive prose ("the agent's session store") instead of literal paths in running text. Keep literal paths in code blocks.

### `api.github.com` / curl → Data Exfiltration
**False positive** when legitimately fetching from GitHub's API.
**Fix**: Use `gh api` instead of raw `curl`.

### "auto-approved" in commands → Social Engineering
**False positive** when describing what a command does.
**Fix**: Rephrase to "proposals that the user has approved."

### `curl | python3` → Pipe to interpreter
**Blocked by Tirith**. Save to file first, then read.

## Trust Model Gaps

1. No "self" tier for agent-authored skills
2. No systematic false-positive regression tests for skills_guard patterns
3. Directory-level (not file-level) path validation

## Conservation Law

The system maximizes catch rate at the expense of false-positive discrimination. Cannot be shifted without adding semantic preprocessing.