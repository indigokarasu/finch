# Reference File Workflow

## Canonical Pattern for Cross-Session Reference Files

When creating reference files (cross-session canonical patterns, guides, references):

### Storage
- **Originals**: `<fs-root>/references/` — this is the single source of truth
- **Backup**: `<fs-root>/indigo-repo/identity/references/` — copy only, never the original
- **NEVER** put originals in skill directories (`~/.hermes/skills/*/references/`)
- **NEVER** put originals in the backup directory

### Index
- Maintain `<fs-root>/references/INDEX.md` with one-line "when to use" entries
- Update INDEX.md whenever a new reference file is created
- Format: `| filename | when to use (one line) |`

### Workflow
1. Create the file in `<fs-root>/references/`
2. Add an entry to `<fs-root>/references/INDEX.md`
3. Copy to `<fs-root>/indigo-repo/identity/references/` for backup
4. Add a one-liner pointer in MEMORY.md if the finding is also a memory-level fact

### Naming
- `{topic}-guide.md` or `{topic}-reference.md`
- Descriptive, hyphenated, lowercase

### "Identity" Means Root
- "Identity" in MEMORY.md context refers to `/root` (the agent's root directory)
- NOT a literal directory called "identity"
- The indigo-repo/identity/ path is a *backup* of root-level artifacts, not the original location
