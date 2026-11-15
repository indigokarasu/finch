#!/usr/bin/env python3
"""Run every scripts/test_*.py suite from the unittest entry point CI uses.

20 suites live beside the scripts they test, and CI only discovered tests/,
so none of them ran on a push. Each suite is a standalone program (most print
their own PASS/FAIL lines and exit non-zero on failure), so this wrapper runs
each one as a subprocess and asserts on its exit code:

  0   pass
  77  SKIPPED: the suite needs host-only state (a live ledger, the agent
      source tree, a gitignored host watcher). Reported as a named skip with
      the suite's own reason, never counted as a pass.
  any other code: failure, with the tail of the suite's output.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
SKIP_EXIT = 77
TIMEOUT_S = 600


def _suites():
    return sorted(SCRIPTS.glob("test_*.py"))


class ScriptSuites(unittest.TestCase):
    def test_suites_exist(self):
        self.assertTrue(_suites(), "no scripts/test_*.py found: the glob is wrong")

    def test_every_script_suite(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        for suite in _suites():
            with self.subTest(suite=suite.name):
                proc = subprocess.run([sys.executable, str(suite)], cwd=str(SCRIPTS),
                                      env=env, capture_output=True, text=True,
                                      timeout=TIMEOUT_S)
                out = (proc.stdout + proc.stderr).strip()
                if proc.returncode == SKIP_EXIT:
                    reason = next((l for l in out.splitlines() if "SKIP" in l), "host-only")
                    self.skipTest(f"{suite.name}: {reason.strip()}")
                self.assertEqual(proc.returncode, 0,
                                 f"{suite.name} exited {proc.returncode}:\n"
                                 + "\n".join(out.splitlines()[-40:]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
