# Finch Interactive Menu

When invoked interactively (via `/` command), present a two-level menu using the `clarify` tool so the user can pick which function to run.

## Level 1 — Category selection (max 4 choices)

```python
result = clarify(
    question="What would you like to do?",
    choices=[
        "Scan & Mine — scan session data, mine for signals",
        "Route & Compact — route findings to skills, compact summaries",
        "Pipeline & Dry-Run — run full pipeline, run without applying",
        "Status — show system status",
    ]
)
```

## Level 2 — Action selection based on Level 1 choice

- **Scan & Mine** → clarify with choices: "scan — Scan for improvement opportunities", "mine — Mine session data for signals"
- **Route & Compact** → clarify with choices: "compact — Compact and summarize findings", "route — Route findings to skills"
- **Pipeline & Dry-Run** → clarify with choices: "run — Run the self-improvement pipeline", "dry-run — Run pipeline without applying", "work — Execute one task from list"
- **Status** → run "status — Show system status" directly (single action — no sub-menu needed)

After the user selects an action, execute it following the relevant procedure in this skill. Loop back to the menu after each action completes, until the user chooses to exit or sends `/stop`.

**Clarify timeout**: When `clarify` times out ("The user did not provide a response within the time limit"), default to `run` (full daily pipeline). It is the safest superset. Log the default in evidence.jsonl. Do NOT re-prompt — the user already declined to interact once.

## Response parsing

Match the user's response against the full choice string. Extract the action key by splitting on `" — "` and taking the first segment. If the response doesn't match any known choice (user typed free-form via "Other"), match key prefixes case-insensitively. Re-present the current menu level on no match.

## Platform adaptation

On CLI, choices are navigable with arrow keys. On messaging platforms, choices render as a numbered list. The two-level hierarchy ensures no more than 4 options appear at any level on any platform.
