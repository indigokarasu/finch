# Reference File Workflow

## Canonical Pattern for Cross-Session Reference Files

When creating reference files (cross-session canonical patterns, guides, references):

### Storage
- **Originals**: `<fs-root>/references/` — this is the single source of truth
- **Backup**: `<fs-root>/<profile>-repo/identity/references/` — copy only, never the original
- **NEVER** put originals in skill directories (`~/.hermes/skills/*/references/`)
- **NEVER** put originals in the backup directory

### Index
- Maintain `<fs-root>/references/INDEX.md` with one-line "when to use" entries
- Update INDEX.md whenever a new reference file is created
- Format: `| filename | when to use (one line) |`

### Workflow
1. Create the file in `<fs-root>/references/`
2. Add an entry to `<fs-root>/references/INDEX.md`
3. Copy to `<fs-root>/<profile>-repo/identity/references/` for backup
4. Add a one-liner pointer in MEMORY.md if the finding is also a memory-level fact

### Naming
- `{topic}-guide.md` or `{topic}-reference.md`
- Descriptive, hyphenated, lowercase

### "Identity" Means Root
- "Identity" in MEMORY.md context refers to `~` (the agent's root directory)
- NOT a literal directory called "identity"
- The <profile>-repo/identity/ path is a *backup* of root-level artifacts, not the original location

---

## MANDATORY: Genericise Before You Write

**This skill is published in a PUBLIC repository.** Reference files are distilled
from real operational runs, so anything you paste from a live scan — an address,
a name, a thread id, a path — becomes public the moment it is pushed. This has
already happened once: a counterparty's work email, their name, an employer, and
live Gmail thread ids were published and had to be scrubbed.

A reference must describe **the pattern, not the incident**. Write it so a
stranger on a different machine, a different mailbox and a different employer can
follow it. If a detail only makes sense on this host, it does not belong in the
reference.

### Never write a real value. Substitute:

| Real thing | Write instead |
|---|---|
| a person's name | `<counterparty>`, `<contact-name>`, `<colleague>` |
| an email address | `counterparty@example.com`, `contact@example.com` |
| an employer / client / vendor | `<employer>`, `<vendor>`, `<client>` |
| a Gmail/message/thread id | `<thread-id>`, `<message-id>` |
| a task id from a live board | `<task-id>` (or `task-<id>`) |
| a phone number | `<phone>` |
| an API key, token, password | an env var name, e.g. `$OCAS_OPERATOR_EMAIL` |
| an absolute home path | `~/…` or `<fs-root>/…` |
| a profile name | `<profile>` |
| a document/matter that is private | describe the *category* ("a signature envelope"), never the matter |

### Keep the useful part

Genericising is not redaction — the reference must still teach the pattern.

- **Bad (leaks, and teaches nothing reusable):**
  `search_gmail_messages(query="from:jane.doe@realcorp.com")` → 1 result, so the <!-- pii-allow -->
  envelope from Jane at RealCorp is unsigned.
- **Bad (over-redacted, now useless):**
  Search for the email and check the result.
- **Good (generic *and* actionable):**
  `search_gmail_messages(query="from:<counterparty-domain>")` — a single result
  means the envelope is still open. Match the sender by domain rather than a
  full address so the query survives a change of contact.

Dates, error strings, tool names, API shapes, exit codes and command syntax are
**not** PII — keep them. They are what makes the reference worth having.

### Enforcement (do not rely on memory)

`scripts/check_no_pii.py` fails the build on structural PII — real-looking
emails, thread ids, phone numbers, keys and tokens, and home paths containing a
username. CI runs it on every push and pull request.

Run it yourself before committing:

```
python3 scripts/check_no_pii.py
```

Names and employers cannot be detected structurally, and a committed denylist
would republish the very strings it protects. Keep those in `.pii-denylist` at
the repo root — one term per line. That file is gitignored, so it stays on your
machine while the scanner still catches the terms locally.

A line containing `pii-allow` is skipped, for deliberate bad-examples like the
one above and for test fixtures. Use it sparingly — it shows up in review.

If the scanner flags something that is genuinely a placeholder, widen the
allowlist in `check_no_pii.py` rather than deleting the finding — a suppression
that lives in the scanner is reviewable; one that lives in your head is not.

---

## ROUTING: does this reference belong to finch at all?

Finch's job is to **route** findings to the tier and the skill that owns them.
It is not a filing cabinet. Historically it became one: 57 reference files
accumulated in this directory, 32 of which documented *other* systems (Gmail,
MCP, cron, the `patch` tool, OAuth, git, disk, state.db). Those were finch's
**output**, not finch's content — and because they lived inside a published
skill, every operational detail in them was published too. That is exactly how
the 2026-07-26 PII incident happened.

**Before writing a reference here, ask one question:**

> Does this document how **finch** behaves, or how **something else** behaves?

| The finding is about… | Where it goes |
|---|---|
| finch's own principles, architecture, algorithms, scan/work procedure | `references/` **here** — it ships with the skill |
| another skill's behaviour | that skill's own `SKILL.md` / its reference set |
| a tool, API, or platform quirk (cron, MCP, Gmail, `patch`, OAuth, git) | `<fs-root>/references/` — **local, never published** |
| a one-off incident with no reusable pattern | the task/journal record, not a reference at all |
| a memory-level fact about the operator | MEMORY.md (or its routed tier) |

**Default to "not here."** A reference in this directory ships to a public
repo and must be useful to a stranger running finch on their own machine. If
it is only meaningful on this host, it belongs in `<fs-root>/references/`.

`<fs-root>/references/` is the local, unpublished library. Create it if absent
(`mkdir -p ~/references`) and keep `INDEX.md` there current. Nothing in it is
tracked by this repo.

### Why this matters more than the PII scanner

`scripts/check_no_pii.py` catches *structural* leaks — addresses, thread ids,
tokens. It cannot catch a sentence like "the January invoice from the vendor
was double-charged": no email, no id, nothing to match, but still a private
detail about the operator. Routing is the real protection; the scanner is the
backstop. Keep host-specific findings out of this directory and the scanner
rarely has to fire.
