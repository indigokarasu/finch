"""Is clause (c) of cron-wedged-claim-115692-silent-error-class satisfiable?

Clause (c) reads: "the resolved stale bound being found to be BELOW its declared
7200s floor".  _live_owner_stale_after_seconds() returns
``max(inactivity * HEADROOM, script_timeout, FLOOR)`` -- the floor is one of the
max() ARGUMENTS, so the result is >= FLOOR for every input.  The clause therefore
has an empty solution set: it can never fire, whatever the host config does.

That is the same empty-solution-set defect already recorded for
cron-paused-boolean-inert-gate-ignores clause (a) (measured 0 of 32 field
combinations) and for the pre-2026-09-29 watcher.  This suite pins the fact
against the REAL function rather than against a restatement of it, so a future
refactor that drops the floor from the max() -- the only way the clause could
ever fire -- fails here instead of silently changing this task's trigger.

Run: python3 test_wedged_bound_clause.py
"""

import os
import sys
import unittest
from unittest import mock

# The agent source tree is resolved from the environment, not baked in as a
# literal: a concrete host path in shipped prose is a PII finding, and this file
# has to import cleanly on a host that lays the tree out elsewhere.
AGENT_SRC = os.environ.get("FINCH_AGENT_SRC") or os.path.join(
    os.path.expanduser("~/.hermes"), "hermes-agent")

# The cron package is imported INSIDE the tests, not at module scope. A
# module-scope import of a third-party package exits before argparse on any host
# that does not have it -- so `--help` died with a ModuleNotFoundError instead of
# printing usage, and the failure looked like a broken script rather than a
# missing optional dependency. The suite legitimately needs the real package:
# it pins an unsatisfiable clause against the PRODUCTION resolver, not against a
# restatement of it, so faking the dependency would defeat the point.
_MODULES = None


def _load():
    """Import the agent's cron package on demand; return (executions, sched, script)."""
    global _MODULES
    if _MODULES is None:
        if AGENT_SRC not in sys.path:
            sys.path.insert(0, AGENT_SRC)
        from cron import executions as _exec
        import cron.scheduler as _sched
        import cron.scheduler_script as _script
        _MODULES = (_exec, _sched, _script)
    return _MODULES


def floor():
    """The declared stale-claim floor, read from the production constant."""
    return _load()[0].LIVE_OWNER_STALE_CLAIM_FLOOR_SECONDS


def resolved_under(inactivity, script_timeout):
    """Call the REAL resolver with both config readers forced, so the knob
    values are the only variable and the assertion cannot pass by accident."""
    executions, sched, script = _load()
    with mock.patch.object(sched, "_cron_inactivity_seconds",
                           return_value=inactivity), \
         mock.patch.object(script, "_get_script_timeout",
                           return_value=script_timeout):
        return executions._live_owner_stale_after_seconds()


def _print_help():
    sys.stdout.write(__doc__ or "")
    sys.stdout.write(
        "\nUSAGE\n  python3 test_wedged_bound_clause.py        # run the suite\n"
        "  python3 test_wedged_bound_clause.py --help  # this text, no import\n\n"
        "ENV\n  FINCH_AGENT_SRC  agent source tree (default ~/.hermes/hermes-agent)\n")
    return 0


class WedgedBoundClauseC(unittest.TestCase):
    def test_live_config_resolves_at_or_above_the_floor(self):
        """The production reading: resolved == 7200.0, i.e. exactly AT the floor,
        not below it.  Clause (c) asks for strictly below."""
        FLOOR = floor()
        b = resolved_under(1800.0, 3600.0)
        self.assertIsNotNone(b)
        assert b is not None
        self.assertGreaterEqual(b, FLOOR)
        self.assertEqual(b, FLOOR)

    def test_clause_c_unsatisfiable_across_the_knob_space(self):
        """Sweep both config knobs across three orders of magnitude BELOW the
        floor.  If any combination resolved under FLOOR, clause (c) would be
        satisfiable and this task's trigger would be re-pickable on it.  Zero is
        the measured answer; it is asserted, not argued."""
        FLOOR = floor()
        under = []
        for inactivity in (1.0, 30.0, 300.0, 1800.0, 2000.0, 2399.9):
            for timeout in (1.0, 60.0, 600.0, 3600.0, 4000.0, 7199.9):
                b = resolved_under(inactivity, timeout)
                if b is None or b < FLOOR:
                    under.append((inactivity, timeout, b))
        self.assertEqual(under, [], f"clause (c) is satisfiable at {under[:3]}")

    def test_fail_closed_when_no_bound_is_derivable(self):
        """inactivity 0 / non-finite means 'never reclaim a live owner'
        (returns None).  Recorded so a reader does not mistake None for a
        measured bound, and so the None branch is covered by a direction that
        asserts something rather than just running the code."""
        self.assertIsNone(resolved_under(0.0, 3600.0))
        self.assertIsNone(resolved_under(float("inf"), 3600.0))

    def test_the_floor_is_an_argument_of_the_max_not_a_comparison(self):
        """The reason clause (c) is empty: the guard is structural.  Read the
        real source and assert the floor appears inside the returned max(...).
        If someone rewrites it as a clamp-then-comparison the clause becomes
        satisfiable and this test fails, which is the intended alarm."""
        import inspect
        src = inspect.getsource(_load()[0]._live_owner_stale_after_seconds)
        self.assertIn("LIVE_OWNER_STALE_CLAIM_FLOOR_SECONDS", src)
        self.assertIn("max(", src)
        body = src.split("return", 1)[1]
        self.assertIn("LIVE_OWNER_STALE_CLAIM_FLOOR_SECONDS", body,
                      "floor is no longer an argument of the returned max()")


if __name__ == "__main__":
    # Answer --help BEFORE importing the agent package: the flag must not depend
    # on an optional dependency being installed.
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        raise SystemExit(_print_help())
    unittest.main(verbosity=2)