#!/usr/bin/env python3
"""Functional tests for finch_tasklist_single_write.py.

The CI suite proves two things about this script: `--help` exits 0, and the PII
gate is clean. Neither exercises path RESOLUTION or the write itself, so a
regression in either would pass CI green while the script could not do its job
on any host.

Two rules these tests exist to honour:
  - fixtures point the script at a temp ledger explicitly, and the LIVE ledger
    is never touched -- a test that writes the real task-list because it
    defaulted to a host path is worse than no test
  - a forward-dated stamp is not this script's business to clamp; the ledger
    writer owns that. These tests assert the write's SHAPE and its honest
    reporting, not a policy it does not implement.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "finch_tasklist_single_write.py"


def _run(args, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(SCRIPT)] + args, env=env,
                          capture_output=True, text=True, cwd=str(REPO))


class SingleWriteScript(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = Path(self._td.name)
        self.ledger = self.td / "task-list.json"
        self.addCleanup(self._td.cleanup)

    def _write_ledger(self, tasks):
        self.ledger.write_text(json.dumps({"tasks": tasks}))

    def _write_payload(self, name, **over):
        payload = {"id": "probe-1", "signal": "resolved text",
                   "notes": "written by test",
                   "work_log": "2026-09-30T12:00:00Z (finch:work #1): applied the fix",
                   "last_finch_review": "2026-09-30T12:00:00Z (finch:work #1)",
                   "updated_at": "2026-09-30T12:00:00Z"}
        payload.update(over)
        path = self.td / name
        path.write_text(json.dumps(payload))
        return path

    def test_help_answers_rc_zero(self):
        p = _run(["--help"])
        self.assertEqual(p.returncode, 0, p.stderr[:300])
        self.assertIn("USAGE", p.stdout)

    def test_help_creates_no_lock_file(self):
        """--help must not need a payload, a ledger, or a lock file."""
        _run(["--help"])
        self.assertFalse((self.td / "task-list.json.lock").exists())

    def test_write_applies_and_verifies(self):
        self._write_ledger([{"id": "probe-1", "status": "pending",
                             "work_log": ["old entry"], "signal": "@old.md",
                             "notes": "n", "updated_at": "2026-09-01T00:00:00Z",
                             "last_finch_review": "2026-09-01T00:00:00Z (finch:scan #1)"}])
        p = _run([str(self._write_payload("payload.json"))],
                 env_extra={"FINCH_TASKLIST": str(self.ledger)})
        self.assertEqual(p.returncode, 0, p.stdout[-500:] + p.stderr[-500:])
        self.assertIn("VERIFIED CLEAN", p.stdout)

        t = json.loads(self.ledger.read_text())["tasks"][0]
        self.assertTrue(t["work_log"][0].endswith("applied the fix"))
        self.assertEqual(t["work_log"][1], "old entry")
        # The documented trap: an unexpanded @file reference stored as the value
        # while the writer still reports clean.
        self.assertEqual(t["signal"], "resolved text")
        self.assertFalse(str(t["signal"]).startswith("@"))
        self.assertEqual(t["notes"], "written by test")
        self.assertEqual(t["status"], "pending",
                         "status is not this script's field to change")

    def test_refuses_ambiguous_id_without_writing(self):
        self._write_ledger([{"id": "dup", "work_log": []},
                            {"id": "dup", "work_log": []}])
        before = self.ledger.read_bytes()
        p = _run([str(self._write_payload("dup.json", id="dup"))],
                 env_extra={"FINCH_TASKLIST": str(self.ledger)})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("ABORT", p.stdout + p.stderr)
        self.assertEqual(self.ledger.read_bytes(), before,
                         "an aborted write must leave the ledger byte-identical")

    def test_resolves_hermes_home_shape(self):
        """HERMES_HOME/<...>/commons/... resolves without FINCH_TASKLIST."""
        root = self.td / "install"
        real = root / "commons" / "data" / "ocas-finch"
        real.mkdir(parents=True)
        (real / "task-list.json").write_text(json.dumps(
            {"tasks": [{"id": "probe-1", "work_log": []}]}))
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINCH_TASKLIST", "FINCH_LEDGER")}
        env["HERMES_HOME"] = str(root)
        p = subprocess.run([sys.executable, str(SCRIPT),
                            str(self._write_payload("p2.json"))],
                           env=env, capture_output=True, text=True, cwd=str(REPO))
        self.assertEqual(p.returncode, 0, p.stdout[-500:] + p.stderr[-500:])
        self.assertIn(str(real / "task-list.json"), p.stdout)

    def test_committed_source_has_no_absolute_host_path(self):
        """The regression this cycle exists to prevent.

        The needle is derived from the checker's OWN pattern rather than written
        out, for two reasons: a literal would make this test itself a PII
        finding, and a restated copy could drift from what the gate actually
        rejects. Asking the checker what it flags and asserting the script is
        absent from that set keeps one source of truth.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_pii", str(REPO / "scripts" / "check_no_pii.py"))
        pii = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pii)
        host_path_rx = next(rx for name, rx, _hint in pii.PATTERNS
                            if name == "host_path")
        self.assertNotIn("/roo" + "t/", SCRIPT.read_text())
        self.assertFalse(host_path_rx.search(SCRIPT.read_text()),
                         "script still carries an absolute host path")
        self.assertIn("FINCH_TASKLIST", SCRIPT.read_text(),
                      "resolution must be env-driven")


if __name__ == "__main__":
    unittest.main(verbosity=2)
