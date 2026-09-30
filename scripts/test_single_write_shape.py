#!/usr/bin/env python3
"""Test the writer's work_log shape handling, in both directions.

The defect this covers: `[new] + "old"` raises TypeError, so a task whose
work_log is a bare string is UNWRITABLE by the only sanctioned writer. The
pass that picks it does all the work, passes the pre-write ledger guard, and
then dies at the last step with the finding unrecorded.

Runs against a temp copy of a synthetic ledger, never the real one. Both
directions matter:
  * a string work_log must be REPAIRED, not rejected -- the record is
    preserved verbatim and the write succeeds;
  * a shape genuinely unknown (dict, int) must ABORT LOUDLY rather than be
    guessed into a plausible-looking list.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

WRITER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "finch_tasklist_single_write.py")

BASE_PAYLOAD = {
    "id": "t",
    "signal": "SIG",
    "notes": "NOTES",
    "work_log": "NEW ENTRY",
    "last_finch_review": "REV",
    "updated_at": "2026-09-30T00:00:00Z",
}


def run_writer(tasklist, payload_obj):
    d = tempfile.mkdtemp()
    try:
        ppath = os.path.join(d, "payload.json")
        with open(ppath, "w") as fh:
            json.dump(payload_obj, fh)
        # The writer hardcodes TASKLIST, so exercise the real merge logic by
        # importing it is not possible (it runs on import). Instead run it
        # against a temp ledger by pointing the module-level constant.
        env = dict(os.environ)
        with open(WRITER) as src_fh:
            src = src_fh.read()
        patched = src.replace(
            'TASKLIST = "%s"' % "/root/.hermes/commons/data/ocas-finch/task-list.json",
            'TASKLIST = "%s"' % tasklist,
        )
        wpath = os.path.join(d, "w.py")
        with open(wpath, "w") as fh:
            fh.write(patched)
        proc = subprocess.run([sys.executable, wpath, ppath],
                              capture_output=True, text=True, timeout=60, env=env)
        with open(tasklist) as fh:
            return proc, json.load(fh)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def make_ledger(work_log_value, include_key=True):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "ledger.json")
    t = {"id": "t", "status": "open", "work_log": work_log_value} if include_key \
        else {"id": "t", "status": "open"}
    with open(p, "w") as fh:
        json.dump({"tasks": [t]}, fh)
    return p, d


class TestWorkLogShape(unittest.TestCase):
    def test_string_prior_is_repaired_not_rejected(self):
        p, d = make_ledger("OLD ENTRY AS A STRING")
        try:
            proc, data = run_writer(p, dict(BASE_PAYLOAD))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("VERIFIED CLEAN", proc.stdout)
            self.assertIn("normalised", proc.stdout)
            wl = data["tasks"][0]["work_log"]
            self.assertIsInstance(wl, list)
            self.assertEqual(wl[0], "NEW ENTRY", "new entry must be first")
            self.assertEqual(wl[1], "OLD ENTRY AS A STRING",
                             "prior content must survive verbatim")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_unknown_shape_aborts_loudly(self):
        p, d = make_ledger({"entry": "a dict is not a work_log"})
        try:
            proc, _ = run_writer(p, dict(BASE_PAYLOAD))
            self.assertNotEqual(proc.returncode, 0, "an unknown shape must not succeed")
            self.assertIn("ABORT", proc.stdout + proc.stderr)
            with open(p) as fh:
                after = json.load(fh)
            self.assertEqual(after["tasks"][0]["work_log"],
                             {"entry": "a dict is not a work_log"},
                             "a refused write must leave the ledger untouched")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_normal_list_unchanged(self):
        p, d = make_ledger(["OLD1", "OLD2"])
        try:
            proc, data = run_writer(p, dict(BASE_PAYLOAD))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotIn("normalised", proc.stdout)
            self.assertEqual(data["tasks"][0]["work_log"],
                             ["NEW ENTRY", "OLD1", "OLD2"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_missing_key_still_works(self):
        p, d = make_ledger(None, include_key=False)
        try:
            proc, data = run_writer(p, dict(BASE_PAYLOAD))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(data["tasks"][0]["work_log"], ["NEW ENTRY"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
