#!/usr/bin/env python3
"""Regression tests for finch_step_attribution.py.

Run before and after ANY change to that script:

    python3 scripts/test_finch_step_attribution.py

WHY THIS SUITE EXISTS (measured 2026-10-03, finch:work #1129).

Four consecutive passes reported the same ~1.8 GB disk-watch step as
"unattributable", each searching for files modified inside the window. Two
defects in that method, both silent, both reproduced here:

  1. A DELETION LEAVES NO FILE. The deletion half of the step had been
     recorded -- as a 150 KB reap manifest -- and a 150 MB search floor
     could never see it.
  2. `find -newermt "<naive string>"` parses the string in LOCAL TIME, so a
     UTC window is compared as PDT and returns a confident zero.

These tests pin both: the deletion side is found, the timezone cannot be
lost, and a failed control turns an absence into an ERROR rather than a
clean zero.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finch_step_attribution as attr  # noqa: E402


class TestEpochParsing(unittest.TestCase):
    """A window boundary must never be guessed at the wrong zone."""

    def test_z_suffix_is_utc(self):
        a = attr._epoch("2026-10-03T00:44:24Z")
        b = attr._epoch("2026-10-03T00:44:24+00:00")
        self.assertEqual(a, b)
        self.assertEqual(attr._fmt(a), "2026-10-03T00:44:24Z")

    def test_offset_is_honoured_not_ignored(self):
        # The same instant expressed in PDT. If offsets were dropped this
        # would be 7h off -- which is exactly the find -newermt bug.
        utc = attr._epoch("2026-10-03T00:44:24Z")
        pdt = attr._epoch("2026-10-02T17:44:24-07:00")
        self.assertEqual(utc, pdt)

    def test_naive_string_is_read_as_utc(self):
        # Documented convention, pinned so it cannot drift silently.
        self.assertEqual(attr._epoch("2026-10-03T00:44:24"),
                         attr._epoch("2026-10-03T00:44:24Z"))

    def test_garbage_is_refused_not_guessed(self):
        with self.assertRaises(SystemExit):
            attr._epoch("not-a-timestamp")


class TestArrivalScan(unittest.TestCase):
    """The arrival scan must find a file whose mtime is inside the window."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="finch_attr_test_")

    def _write(self, name, mtime, size=4096):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as fh:
            fh.write(b"x" * size)
        os.utime(path, (mtime, mtime))
        return path

    def test_finds_file_inside_window(self):
        target = self._write("in.bin", 1_000_000.0)
        hits = attr.scan_arrivals([self.dir], 900_000.0, 1_100_000.0)
        self.assertIn(target, [h[2] for h in hits])

    def test_excludes_file_outside_window(self):
        # One second too early. The boundary is the whole point.
        self._write("early.bin", 899_999.0)
        hits = attr.scan_arrivals([self.dir], 900_000.0, 1_100_000.0)
        self.assertEqual([h[2] for h in hits if "early" in h[2]], [])

    def test_includes_file_exactly_at_the_upper_bound(self):
        """The upper boundary is INCLUSIVE.

        A sample whose mtime is exactly t_hi arrived inside the window, so
        an exclusive upper bound silently drops it. This is the same class
        of off-by-one as the lower bound: a step's bracketing samples are
        often exactly on a boundary, because the ring writes at a whole
        second.
        """
        edge = self._write("edge.bin", 1_100_000.0)
        hits = attr.scan_arrivals([self.dir], 900_000.0, 1_100_000.0)
        self.assertIn(edge, [h[2] for h in hits])

    def test_includes_file_exactly_at_the_lower_bound(self):
        edge = self._write("edge_lo.bin", 900_000.0)
        hits = attr.scan_arrivals([self.dir], 900_000.0, 1_100_000.0)
        self.assertIn(edge, [h[2] for h in hits])

    def test_size_floor_applies(self):
        self._write("small.bin", 1_000_000.0, size=1024)
        hits = attr.scan_arrivals([self.dir], 900_000.0, 1_100_000.0,
                                  min_mb=1.0)
        self.assertEqual([h[2] for h in hits if "small" in h[2]], [])

    def test_window_math_is_immune_to_local_timezone(self):
        """The bug this suite exists for, as a direct assertion.

        A file at 2026-10-03T00:44:24Z must be found by a window given in
        UTC, regardless of what TZ the process is running under. If any
        code path handed a naive string to a shell date parser, this fails
        under TZ=America/Los_Angeles and passes under UTC.
        """
        epoch = attr._epoch("2026-10-03T00:44:24Z")
        self._write("tz.bin", epoch)
        import time as _t
        os.environ["TZ"] = "America/Los_Angeles"
        try:
            _t.tzset()
            hits = attr.scan_arrivals([self.dir], epoch - 60, epoch + 60)
        finally:
            os.environ["TZ"] = "UTC"
            _t.tzset()
        self.assertIn(os.path.join(self.dir, "tz.bin"), [h[2] for h in hits])


class TestDeletionScan(unittest.TestCase):
    """The deletion half of a net step must be findable."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="finch_attr_manifest_")
        stamp = "2026-10-03T00:10:12Z"
        body = {
            "target": "/root/.hermes/cache/scratch/swifttool",
            "file_count": 1110,
            "total_bytes": 5828052817,
            "manifested_at_utc": "2026-10-03T00:10:12.098630+00:00",
        }
        self.path = os.path.join(self.dir, "reap-manifest-swifttool-x.json")
        with open(self.path, "w") as fh:
            json.dump(body, fh)

    def test_finds_manifest_inside_window(self):
        lo = attr._epoch("2026-10-02T23:49:33Z")
        hi = attr._epoch("2026-10-03T00:44:24Z")
        found = attr.scan_deletions([self.dir], lo, hi)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["mb"], round(5828052817 / 1048576, 1))
        self.assertEqual(found[0]["target"],
                         "/root/.hermes/cache/scratch/swifttool")
        self.assertEqual(found[0]["file_count"], 1110)

    def test_excludes_manifest_outside_window(self):
        # The tarball reap at 01:10Z is AFTER the step's window and must
        # not be counted against it.
        lo = attr._epoch("2026-10-02T23:49:33Z")
        hi = attr._epoch("2026-10-03T00:44:24Z")
        self.assertEqual(attr.scan_deletions([self.dir], lo, hi, min_mb=0.0)
                         and [m for m in attr.scan_deletions([self.dir], lo, hi)
                              if "tarball" in m["manifest"]], [])

    def test_small_manifest_below_floor_is_skipped(self):
        lo = attr._epoch("2026-10-02T23:49:33Z")
        hi = attr._epoch("2026-10-03T00:44:24Z")
        self.assertEqual(attr.scan_deletions([self.dir], lo, hi, min_mb=99999.0),
                         [])

    def test_malformed_manifest_is_skipped_not_fatal(self):
        bad = os.path.join(self.dir, "reap-manifest-broken.json")
        with open(bad, "w") as fh:
            fh.write("{not json")
        lo = attr._epoch("2026-10-02T23:49:33Z")
        hi = attr._epoch("2026-10-03T00:44:24Z")
        found = attr.scan_deletions([self.dir], lo, hi)
        self.assertEqual(len(found), 1)  # only the good one


class TestControl(unittest.TestCase):
    """A control that only passes for recent windows is a broken control."""

    def test_control_passes_against_an_old_window(self):
        """The window-independent property, asserted directly.

        The window is from 2026-10-02; the probe file's mtime is whatever it
        is now. An earlier draft scoped the control to the window itself and
        failed here, manufacturing a false alarm on a healthy scan.
        """
        result = attr.run_control(
            attr._epoch("2026-10-02T23:49:33Z"),
            attr._epoch("2026-10-03T00:44:24Z"))
        self.assertTrue(result["ok"], msg=result.get("reason"))
        self.assertIsNotNone(result["newest"])


class TestControlFailureIsLoud(unittest.TestCase):
    """A broken control must be an ERROR, never a clean zero.

    This is the property that makes an absence trustworthy. When the scan
    proved nothing, the script has to say so and exit non-zero, because the
    failure mode being defended against is a confident "nothing found" from a
    search that never ran correctly -- which is exactly what four passes of
    `find -newermt` produced on this host.
    """

    def test_broken_control_exits_nonzero(self):
        import io
        import contextlib
        pristine = attr.run_control
        try:
            # Force the control to fail while the rest of the scan works.
            attr.run_control = lambda a, b: {"probe_root": "x", "ok": False,
                                             "files_seen_in_window": 0,
                                             "reason": "forced",
                                             "newest": None}
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = attr.main(["--from", "2026-10-02T23:49:33Z",
                                "--to", "2026-10-03T00:44:24Z",
                                "--json", "--root", "/nonexistent-root-t"])
        finally:
            attr.run_control = pristine
        self.assertNotEqual(rc, 0, "a failed control must not exit 0")
        self.assertIn("CONTROL FAILED", err.getvalue())

    def test_good_control_exits_zero(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = attr.main(["--from", "2026-10-02T23:49:33Z",
                            "--to", "2026-10-03T00:44:24Z",
                            "--json", "--root", "/nonexistent-root-t"])
        self.assertEqual(rc, 0)


class TestReportShape(unittest.TestCase):
    def test_help_exits_zero(self):
        with self.assertRaises(SystemExit) as cm:
            attr.main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_inverted_window_is_refused(self):
        with self.assertRaises(SystemExit):
            attr.main(["--from", "2026-10-03T01:00:00Z",
                       "--to", "2026-10-03T00:00:00Z"])

    def test_json_report_has_both_sides(self):
        lo, hi = "2026-10-02T23:49:33Z", "2026-10-03T00:44:24Z"
        with tempfile.TemporaryDirectory() as mdir:
            body = {"target": "/x", "total_bytes": 5828052817,
                    "manifested_at_utc": "2026-10-03T00:10:12+00:00"}
            with open(os.path.join(mdir, "reap-manifest-a.json"), "w") as fh:
                json.dump(body, fh)
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = attr.main(["--from", lo, "--to", hi, "--json",
                                "--manifest-dir", mdir,
                                "--root", "/nonexistent-root-for-test"])
            self.assertEqual(rc, 0)
            rep = json.loads(buf.getvalue())
        for key in ("window", "control", "arrivals", "deletions", "net_mb",
                    "caveat"):
            self.assertIn(key, rep)
        self.assertEqual(rep["deletions"]["count"], 1)
        self.assertIn("LOWER bound", rep["caveat"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
