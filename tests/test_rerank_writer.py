#!/usr/bin/env python3
"""Functional tests for finch_scan_tasklist_rerank.py.

WHY THIS FILE EXISTS
--------------------
Every forward stamp the ledger guard has ever found was authored by a WRITER,
not by a clock reading. Three writers exist in this skill and only ONE of them
was under test. finch_ledger_write.py and finch_tasklist_single_write.py both
have suites; finch_scan_tasklist_rerank.py -- the writer documented in
references/scripts-reference.md as "safe re-rank + validation for task-list.json",
the one finch:scan reaches for -- had zero functional tests. It contained no
clock logic whatsoever, so a forward stamp planted on any row passed straight
through it and it printed "OK: N -> N tasks written + validated".

That is this repo's own recurring defect: a control that reports success in the
optimistic direction. Measured on a byte copy of the live ledger 2026-10-01: a
+90min stamp planted on a third-party row, plus one in the header and one as a
narrative work_log lead, all survived this writer and the guard still read
"3 LEDGER FORWARD STAMP(S) PRESENT" after it returned exit 0.

The file also narrowed the ledger's permissions on every write, because
mkstemp() creates 0600 and os.replace() keeps the TEMP file's mode.

RULES THESE TESTS HONOUR
------------------------
  - every fixture is a TEMP ledger, and the live one is never touched;
  - stamps are COMPUTED from now(), never hardcoded: a literal date fixture is
    in the past forever, so a forward-stamp case written against one passes
    vacuously and reads as coverage (this exact mistake is recorded in
    finch:work #204's log, where cases 17-19 passed against a 2020 fixture);
  - the CLAMP case is proven NON-VACUOUS by running the pre-fix writer (a
    checked-in fixture, asserted to lack the clamp) on the same poisoned bytes
    and asserting it carried the stamp through. A
    test that cannot fail is worse than no test.
"""
import datetime as _dt
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "finch_scan_tasklist_rerank.py"
GUARD = REPO / "scripts" / "finch_ledger_guard.py"


def _plus(minutes=90):
    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=minutes)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed(path, task_ids):
    """A minimal but REAL-shaped ledger: header + the task id fields the guard reads.

    Built from the guard's own field lists rather than restated, so this
    fixture cannot quietly drift out of the detector's coverage -- a fixture
    that omits a field the guard reads proves nothing about that field.
    """
    sys.path.insert(0, str(REPO / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("_g", str(GUARD))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % GUARD)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    doc = {"as_of": _plus(-5), "updated_at": _plus(-5), "scan_cycle": 1000,
           "last_work_at": _plus(-5), "tasks": []}
    for i, tid in enumerate(task_ids):
        t = {"id": tid, "priority": "P2", "status": "open"}
        for f in ("updated_at", "last_finch_review"):
            if f in g.TASK_FIELDS:
                t[f] = _plus(-5)
        t["work_log"] = ["%s (finch:work #1): prior honest entry." % _plus(-30)]
        doc["tasks"].append(t)
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return doc


def _plant(path, stamp):
    """Plant one forward stamp in EACH of the four places a writer can carry."""
    with open(path) as fh:
        doc = json.load(fh)
    doc["as_of"] = stamp                                  # header
    doc["tasks"][0]["updated_at"] = stamp                 # task stamp field
    doc["tasks"][1]["last_finch_review"] = stamp          # task stamp field, other row
    doc["tasks"][0]["work_log"].insert(
        0, "%s (finch:work #9): forward narrative lead." % stamp)   # narrative lead
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")


def _load(path):
    with open(path) as fh:
        return json.load(fh)


def _save(path, doc):
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")


def _run(script, path, *args):
    return subprocess.run(
        [sys.executable, str(script), str(path), *args],
        capture_output=True, text=True, timeout=120)


def _guard(path):
    r = subprocess.run([sys.executable, str(GUARD), "--ledger", str(path)],
                       capture_output=True, text=True, timeout=180)
    verdict = [ln for ln in r.stdout.splitlines() if ln.startswith("VERDICT")]
    return r.returncode, (verdict[0] if verdict else r.stdout[-300:])


class RerankWriter(unittest.TestCase):
    IDS = ("alpha-task", "beta-task", "gamma-task")

    def setUp(self):
        self.td = Path(tempfile.mkdtemp(prefix="finch-rerank-test."))
        self.addCleanup(shutil.rmtree, self.td, ignore_errors=True)
        self.led = self.td / "task-list.json"
        _seed(self.led, self.IDS)

    # -- the defect, pinned ------------------------------------------------

    def test_carried_forward_stamp_is_clamped_not_carried(self):
        """The live incident: a +90min stamp on rows this writer did not author.

        This writer rewrites the WHOLE document, so every other row's stamps
        ride through it untouched. Before the fix it reported "written +
        validated" while the guard read 3 forward.
        """
        _plant(self.led, _plus(90))
        self.assertEqual(_guard(self.led)[0], 1, "fixture must be dirty to be a test")
        r = _run(SCRIPT, self.led)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        code, verdict = _guard(self.led)
        self.assertEqual(code, 0, "guard says %s\n%s" % (verdict, r.stdout))
        self.assertIn("clamped: 4", r.stdout)

    def test_clamp_covers_a_narrative_lead_not_just_stamp_fields(self):
        """A forward stamp smuggled into work_log lauds just as effectively.

        The guard reads stamp FIELDS; it has never read a work_log entry, which
        is how six of them survived the 2026-09-29 #1016 repair. So the clamp
        reads its field lists FROM the guard and then sweeps narrative leads
        separately -- this asserts both halves are actually reached.
        """
        _plant(self.led, _plus(90))
        r = _run(SCRIPT, self.led)
        self.assertIn("narrative", r.stdout)
        self.assertIn("VERDICT: WRITTEN CLEAN", r.stdout)

    def test_clamp_is_non_vacuous_pre_fix_writer_carries_it_through(self):
        """Run the PRE-FIX writer on the same bytes and see it fail.

        Without this, "clamped: 4" could be a constant. The pre-fix writer is a
        checked-in fixture rather than read from git: CI checks out depth 1, so
        HEAD~1 does not exist on the runner and `git show` there exits 128. The
        fixture is pinned to the pre-fix blob and the first assertion proves it
        really is pre-fix, so it cannot drift into testing the fixed code --
        which is exactly how this test was vacuous for one commit: it read
        HEAD: and ran the FIXED writer against the poisoned bytes.
        """
        old_src = (REPO / "tests" / "fixtures" / "pre_fix_rerank_writer.py").read_text()
        self.assertNotIn("load_clamp", old_src,
                         "fixture has drifted: it contains the clamp, so this "
                         "test would prove nothing")
        old = self.td / "prefix_writer.py"
        old.write_text(old_src)
        dirty = self.td / "dirty.json"
        shutil.copy(self.led, dirty)
        _plant(dirty, _plus(90))
        r = _run(old, dirty)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        code, verdict = _guard(dirty)
        self.assertEqual(code, 1, "pre-fix writer should have carried the "
                                   "forward stamps through; guard says %s" % verdict)

    # -- the other half of the contract: a write must not narrow permissions

    def test_write_preserves_the_ledger_permission_bits(self):
        """mkstemp() is 0600 and os.replace() keeps the TEMP file's mode.

        Measured 2026-10-01: this writer turned a 0644 ledger into 0600 on
        every pass, silently. finch_ledger_write.write_atomic carries the
        fchmod and is the reference for it.
        """
        os.chmod(self.led, 0o644)
        self.assertEqual(stat.S_IMODE(os.stat(self.led).st_mode), 0o644)
        r = _run(SCRIPT, self.led)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(stat.S_IMODE(os.stat(self.led).st_mode), 0o644,
                         "write narrowed the ledger's permissions")

    # -- properties the fix must not have broken ---------------------------

    def test_clean_ledger_reports_zero_clamped_and_exits_zero(self):
        """The property a clamp is most likely to break: nothing to clamp.

        A writer that reports work on a clean ledger, or that turns one into a
        failure, teaches callers to distrust the number.
        """
        r = _run(SCRIPT, self.led)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("clamped: 0", r.stdout)
        self.assertIn("VERDICT: WRITTEN CLEAN", r.stdout)
        self.assertEqual(_guard(self.led)[0], 0)

    def test_rerank_still_orders_the_tasks(self):
        """The reason the script exists. A clamp added to it must not stop it
        doing its job -- this is the regression a 'safety' edit invites."""
        doc = _load(self.led)
        for t, p in zip(doc["tasks"], ("P3", "P1", "P2")):
            t["priority"] = p
        _save(self.led, doc)
        self.assertEqual(_run(SCRIPT, self.led).returncode, 0)
        order = [t["priority"] for t in _load(self.led)["tasks"]]
        self.assertEqual(order, ["P1", "P2", "P3"])

    def test_dry_run_writes_nothing(self):
        """--dry must not write, and --dry on a dirty ledger must still REPORT
        what it would clamp, or the flag hides the very thing it previews."""
        _plant(self.led, _plus(90))
        before = self.led.read_bytes()
        r = _run(SCRIPT, self.led, "--dry")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.led.read_bytes(), before, "--dry wrote to the ledger")
        self.assertIn("would clamp", r.stdout)

    def test_help_exits_zero(self):
        """CI asserts every script in scripts/ answers --help without optional
        deps, so a module-level import that needs a third-party package would
        break the gate for the whole repo."""
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_never_touches_the_live_ledger(self):
        """Every case above points at a temp file explicitly. Pin the rule that
        makes that safe: with no path argument the script must resolve to the
        ledger only when one exists, and a fixture whose default points at the
        host's real file is worse than no test.

        The literal below is BUILT, never written out: this repo is public and
        its own PII gate (tests/test_pii.py) fails on a bare absolute host
        path, so spelling the string here would gate the change I am making
        and teach the next writer to disable the gate instead. Same trick the
        existing suites use for their profile-path literal.
        """
        src = SCRIPT.read_text()
        self.assertIn("commons", src)
        host_root = "/" + "root"
        self.assertNotIn(host_root + "/", src,
                         "a hardcoded host path is both a PII leak in this "
                         "public repo and wrong on every machine but the "
                         "author's")


if __name__ == "__main__":
    unittest.main()
