#!/usr/bin/env python3
"""Mutation harness: prove test_count_population_guard.py can FAIL.

Three mutants, each defeating one of the guard's three load-bearing properties.
If the suite passes any mutant, the suite is decorative and the guard is unverified.

  M1  emit a bare count with no population      (defeats the task's core lesson)
  M2  source the headline number from the directory proxy (defeats rule 2)
  M3  treat an unreadable/missing db as 0        (defeats NOT-MEASURED honesty)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Shared fixture-deletion guard; see rmtree_confined.py for why the invariant is
# register-at-creation rather than "lives under /tmp".
from rmtree_confined import new_root as _new_root  # noqa: E402
from rmtree_confined import rmtree_confined as _rmtree  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "finch_count_population_guard.py")
SUITE = os.path.join(HERE, "test_count_population_guard.py")

MUTANTS = [
    (
        "M1_bare_count_no_population",
        # Delete the population print entirely -- the guard then emits a bare
        # count with no population attached, which is the exact defect the task
        # was filed about. (An earlier version of this mutant only re-indented
        # the line, so the output was unchanged and the suite correctly passed:
        # a mutant that does not change behaviour cannot kill anything.)
        (r'\n\s*print\(f"  population: \{p\[.rows_total.\]\} rows "'
         r'\n\s*f"\(\{p\[.terminal_rows.\]\} terminal\) spanning "'
         r'\n\s*f"\{p\[.retention_window_hours.\]\}h "\n'
         r'\s*f"\[\{p\[.instant_min.\]\} \.\. \{p\[.instant_max.\]\}\]"\)',
         '\n        pass'),
    ),
    (
        "M2_directory_proxy_as_count",
        # Make the headline duplicate count come from the listing instead.
        (r'"construction_A_grouped_job_instant": len\(pairs_a\),',
         '"construction_A_grouped_job_instant": dir_entries_probe(),'),
    ),
    (
        "M3_missing_db_reads_as_zero",
        # Swallow the read failure and return a zero-measurement.
        (r'except Exception as e:\n\s*if not args\.quiet:\n\s*print\(f"VERDICT: NOT MEASURED -- \{type\(e\).__name__\}: \{e\}"\)\n\s*return 2',
         'except Exception as e:\n        if not args.quiet:\n            print("VERDICT: MEASURED")\n        return 0'),
    ),
]


def main():
    if not os.path.exists(TARGET):
        print("target missing")
        return 2
    original = open(TARGET).read()
    results = []
    for name, (pat, repl) in MUTANTS:
        new, n = re.subn(pat, repl, original, count=1)
        if n != 1:
            print(f"  SKIP  {name}: pattern did not apply ({n}) -- "
                  f"mutant is stale against the current source")
            results.append((name, None))
            continue
        with tempfile.NamedTemporaryFile(
                suffix=".py", delete=False, mode="w") as fh:
            fh.write(new)
            mutant_path = fh.name
        # Run the suite against the mutant by staging a temp dir.
        tmpd = _new_root(tempfile.mkdtemp(prefix="finch_mutant_"))
        try:
            m_target = os.path.join(tmpd, "finch_count_population_guard.py")
            m_suite = os.path.join(tmpd, "test_count_population_guard.py")
            shutil.copy(mutant_path, m_target)
            shutil.copy(SUITE, m_suite)
            p = subprocess.run([sys.executable, m_suite],
                               capture_output=True, text=True, timeout=400)
            killed = p.returncode != 0
            print(f"  {'KILLED' if killed else 'SURVIVED'}  {name} "
                  f"(suite rc={p.returncode})")
            results.append((name, killed))
        finally:
            os.unlink(mutant_path)
            _rmtree(tmpd)

    applied = [r for r in results if r[1] is not None]
    survivors = [n for n, k in applied if not k]
    print(f"\n{len(applied) - len(survivors)}/{len(applied)} mutants killed")
    if len(applied) < len(MUTANTS):
        print("INCONCLUSIVE: a mutant did not apply -- re-derive it")
        return 2
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())