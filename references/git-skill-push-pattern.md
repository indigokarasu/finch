# Git Skill Push Pattern

## Pushing Local Skill Changes to GitHub

When pushing skill changes, always check for detached HEAD first:

```bash
cd ~/.hermes/skills/<skill-name>
git branch          # Check current state
```

If detached (shows `(HEAD detached from vX.Y.Z)`):
```bash
git checkout main
git merge HEAD@{1} --no-edit   # Merge the detached commit(s) onto main
git push origin main
```

If on `main` normally:
```bash
git add -A
git commit -m "Description of changes"
git push origin main
```

## Common Issue: Detached HEAD After Version Tag Checkout

Skills with version tags (e.g., `ocas-rally` at `v3.0.1`) may be left in detached HEAD after the update script checks out a tag. The `git commit` succeeds but `git push origin main` fails with `src refspec main does not match any` because there's no local `main` branch.

**Fix:** `git checkout main` creates the local branch tracking `origin/main`, then fast-forwards to include the detached commit.

## All OCAS Skill Remotes

All skill repos are under `https://github.com/indigokarasu/` with repo names matching the skill directory name minus the `ocas-` prefix:
- `ocas-bones` → `bones`
- `ocas-spot` → `ocas-spot` (exception — full name preserved)
- All others: `ocas-<name>` → `<name>`

## Unrelated Histories (Most Common Scenario)

Local skill directories and their GitHub remotes are often initialized separately. When pushing, you'll hit:

```
fatal: refusing to merge unrelated histories
```

**Fix:** Force push. The local directory is the authoritative source:

```bash
git push origin main --force
```

Do NOT `git pull --allow-unrelated-histories` — it creates messy merge commits.

## Auth: Use gh Credential Helper, Not Embedded Tokens

Remote URLs should be clean:
```
https://github.com/indigokarasu/repo.git
```

If a remote URL contains an embedded/corrupted token (e.g., `ghp_rB...y5G7`), fix it:
```bash
git remote set-url origin https://github.com/indigokarasu/repo.git
```

Authentication is handled by `gh auth git-credential` — never embed tokens in URLs.
