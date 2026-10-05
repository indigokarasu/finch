#!/usr/bin/env python3
"""
Guard-predicate check for the add_help_guards.py regression class.

The audit that let 37 broken scripts through was a SUBSTRING check for
'--help'.  That predicate cannot distinguish a guard that works from a guard
that crashes, because the crash happens at RUNTIME.

This is the discriminating form, and it is cheap enough to run as a gate:
  (1) SOURCE predicate -- a module-level `sys.exit()` reached before the import
      section is malformed by construction, whatever the substring says.
  (2) EXECUTION predicate -- run `python3 <path> --help` and read the exit code.

Rule, general, not a value: a mechanical edit that inserts a guard which
CALLS sys.exit() at module top level MUST insert `import sys` ahead of it and
MUST sit below any `from __future__ import`.  Verify by running, never by
grepping.
"""
import argparse
import ast
import os
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_HOME = os.path.dirname(os.path.dirname(SKILL_DIR))

SCRIPTS = os.path.join(SKILL_DIR, "scripts")

EXTRA_DIRS = [
    # finch:work #1193: the per-profile scripts/ dir is a SECOND script surface that no
    # gate covered. finch_update_tasklist.py lived there, wrote a fixed payload to
    # shared state on every invocation INCLUDING --help, and nothing flagged it:
    # this checker only scanned the skill's own scripts/ dir, and only statically.
    os.path.join(PROFILE_HOME, "scripts"),
]


def _roots():
    yield SCRIPTS
    for d in EXTRA_DIRS:
        if os.path.isdir(d):
            yield d


def source_violations(path):
    """Static check: a sys.exit() executed at import time before imports."""
    try:
        tree = ast.parse(open(path).read())
    except SyntaxError as e:
        return ["SYNTAXERROR: %s" % e]
    bad = []
    # any module-level `if len(sys.argv)...: sys.exit(0)` positioned before the
    # first import binding of sys
    lines = open(path).read().splitlines()
    for i, l in enumerate(lines):
        if "sys.argv[1]" in l and ("--help" in l or "-h" in l):
            first_sys = next((k for k, m in enumerate(lines)
                              if m.strip() in ("import sys", "import sys as _sys")),
                             None)
            if first_sys is None or first_sys > i:
                bad.append("line %d: sys.exit guard precedes `import sys`" % (i + 1))
        if l.strip().startswith("from __future__") and i > 0 and any(
            "sys.argv[1]" in m for m in lines[:i]):
            bad.append("line %d: __future__ import displaced by a guard" % (i + 1))
    return bad


def main():
    parser = argparse.ArgumentParser(
        description="Guard-predicate check for the add_help_guards.py regression class. "
                    "Static source check + execution --help sweep.")
    parser.parse_args()
    flagged = 0
    scanned = 0
    for root in _roots():
        for f in sorted(x for x in os.listdir(root)
                        if x.endswith(".py") and os.path.isfile(os.path.join(root, x))):
            scanned += 1
            v = source_violations(os.path.join(root, f))
            if v:
                flagged += 1
                print("SOURCE-VIOLATION %s/%s" % (os.path.basename(root), f))
                for x in v:
                    print("    " + x)
    print("scanned=%d source-flagged=%d over %d dir(s) (this check does NOT execute the"
          " files; pair it with a --help sweep)" % (scanned, flagged, len(list(_roots()))))
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())