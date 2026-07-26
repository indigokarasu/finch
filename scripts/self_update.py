#!/usr/bin/env python3
"""Update the local ocas-finch skill checkout from its Git remote.

Non-destructive by design: local modifications are NEVER discarded. If the
working tree is dirty, the update either stops (default) or stashes the
changes, pulls, and restores them (--stash).

Previously this ran `git reset --hard` + `git clean -fd` unconditionally,
which silently destroyed uncommitted local edits and untracked files. That
is unrecoverable data loss on a host where the skill is edited in place.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def emit(proc: subprocess.CompletedProcess) -> None:
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)


def dirty_files(skill_dir: Path) -> list[str]:
    """Tracked modifications + untracked files (what a hard reset would eat)."""
    proc = run(["git", "status", "--porcelain"], skill_dir)
    if proc.returncode != 0:
        return []
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Update the ocas-finch skill checkout from its Git remote (non-destructive).")
    ap.add_argument("--stash", action="store_true",
                    help="Stash local changes, pull, then restore them "
                         "(default: refuse to run on a dirty tree).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would happen; change nothing.")
    args = ap.parse_args()

    skill_dir = Path(__file__).resolve().parents[1]
    if not (skill_dir / ".git").is_dir():
        print(f"Not a git checkout: {skill_dir}", file=sys.stderr)
        return 1

    dirty = dirty_files(skill_dir)
    if dirty:
        print(f"Local changes present in {skill_dir}:")
        for line in dirty:
            print(f"  {line}")
        if not args.stash:
            print("\nRefusing to update: local changes would be at risk.", file=sys.stderr)
            print("Commit them, or re-run with --stash to auto-preserve them.", file=sys.stderr)
            return 2

    if args.dry_run:
        print(f"\n[dry-run] would run: git pull --ff-only"
              + (" (with stash/restore around it)" if dirty else ""))
        return 0

    stashed = False
    if dirty and args.stash:
        proc = run(["git", "stash", "push", "--include-untracked",
                    "-m", "ocas-finch self_update autostash"], skill_dir)
        emit(proc)
        if proc.returncode != 0:
            print("Stash failed — aborting before pull.", file=sys.stderr)
            return proc.returncode
        stashed = True

    proc = run(["git", "pull", "--ff-only"], skill_dir)
    emit(proc)
    pull_rc = proc.returncode

    if stashed:
        restore = run(["git", "stash", "pop"], skill_dir)
        emit(restore)
        if restore.returncode != 0:
            print("\nWARNING: could not auto-restore your changes. They are safe in "
                  "the stash — recover with:  git stash list && git stash pop",
                  file=sys.stderr)
            return restore.returncode

    return pull_rc


if __name__ == "__main__":
    raise SystemExit(main())
