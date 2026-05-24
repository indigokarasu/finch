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

All skill repos are under `https://github.com/indigokarasu/` with repo names matching the skill directory name (except `ocas-bones` → `odds`, `ocas-spot` → `ocas-spot`).
