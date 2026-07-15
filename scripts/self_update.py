#!/usr/bin/env python3
"""Update the local ocas-finch skill checkout from its Git remote."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_HELP_ARGS = {"--help", "-h"}
if set(sys.argv[1:]) & _HELP_ARGS:
    print((__doc__ or "").strip() or "Usage: python3 self_update.py [no flags]")
    sys.exit(0)


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    if not (skill_dir / ".git").is_dir():
        print(f"Not a git checkout: {skill_dir}", file=sys.stderr)
        return 1

    for cmd in (["git", "reset", "--hard", "HEAD"], ["git", "clean", "-fd"], ["git", "pull", "--ff-only"]):
        proc = run(list(cmd), skill_dir)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        if proc.returncode != 0:
            return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
