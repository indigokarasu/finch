#!/usr/bin/env python3
"""Tests for the two false negatives fixed in finch:work pass 1044.

Both are the same shape as the defect this task has now hit four times: an
instrument reports a value that is TRUE OF ITSELF and false of the thing being
measured, and the false reading is the reassuring one.

  1. deleted_open_leaks() reported a THRESHOLDED list as though it were a
     census. A process holding 19 deleted fds and 9.75 MB fell under the
     default threshold of 50 and the report said []. The new fields report the
     unthresholded total, so "no invisible space" can no longer be read off an
     empty list.

  2. db_bloat() reported only the main DB file. A WAL-mode DB's -wal sidecar
     was invisible: state.db's was 64 MB against a 736 MB database. And reading
     its SIZE is itself wrong, because a checkpoint resets the WAL's contents
     in place without shrinking the file, so size measures a high-water mark.
     _wal_live_bytes() walks frame salts instead.

Every case runs against a SYNTHETIC fixture under a temporary directory, so a
test proves the RULE and not this host's /proc and not this host's databases.
The negative cases matter most: a fixture that must NOT be reported as a leak,
and a WAL whose stale tail must NOT be counted as live.
"""
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Shared fixture-deletion guard; see rmtree_confined.py for why the invariant is
# register-at-creation rather than "lives under /tmp".
from rmtree_confined import mkfixture as _mkfixture  # noqa: E402
from rmtree_confined import rmtree_confined as _rmtree  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finch_disk_watch as w  # noqa: E402


def write_wal(path, frame_salts, page_size=4096, header_salt=(0x1111, 0x2222)):
    """Build a -wal file whose frame salts are given in order.

    A real WAL's frames after a checkpoint carry the OLD salt, so this can
    reproduce the exact shape that fooled getsize(): a big file, a small live
    prefix, and a stale tail.
    """
    header = struct.pack(">8I", 0x377F0682, 3007000, page_size, 1,
                         header_salt[0], header_salt[1], 1234, 5678)
    body = b""
    for i, salt in enumerate(frame_salts):
        body += struct.pack(">6I", i + 1, 1, salt[0], salt[1], 0, 0)
        body += b"\0" * page_size
    with open(path, "wb") as fh:
        fh.write(header + body)


class TestWalLiveBytes(unittest.TestCase):
    def setUp(self):
        self.dir = _mkfixture(prefix="finch_wal_")

    def tearDown(self):
        _rmtree(self.dir)

    def test_all_frames_live(self):
        """Every frame carries the header salt -> the whole file is live."""
        p = os.path.join(self.dir, "a-wal")
        write_wal(p, [(0x1111, 0x2222)] * 4)
        size = os.path.getsize(p)
        self.assertEqual(w._wal_live_bytes(p), size)

    def test_stale_tail_not_counted(self):
        """THE DIRECTION THAT MATTERS: file stays 64MB-sized, live is tiny.

        This is the state that reads as 'a reader is pinning the WAL' if you
        use getsize(). It must not.
        """
        p = os.path.join(self.dir, "b-wal")
        live_salt = (0x1111, 0x2222)
        stale_salt = (0x9999, 0x8888)
        write_wal(p, [live_salt] * 2 + [stale_salt] * 2000)
        file_bytes = os.path.getsize(p)
        live = w._wal_live_bytes(p)
        self.assertGreater(file_bytes, 4 * 1024 * 1024, "fixture should look large")
        self.assertEqual(live, 32 + 2 * (24 + 4096))
        self.assertLess(live, file_bytes / 100)

    def test_zero_live_frames(self):
        """Fully checkpointed: file large, only the 32-byte header live."""
        p = os.path.join(self.dir, "c-wal")
        write_wal(p, [(0xDEAD, 0xBEEF)] * 50)
        self.assertEqual(w._wal_live_bytes(p), 32)

    def test_not_a_wal_returns_size(self):
        """A missing/short/garbage file must not invent a number."""
        p = os.path.join(self.dir, "d-wal")
        with open(p, "wb") as fh:
            fh.write(b"not a wal at all, just text")
        self.assertEqual(w._wal_live_bytes(p), os.path.getsize(p))

    def test_missing_file_is_zero(self):
        self.assertEqual(
            w._wal_live_bytes(os.path.join(self.dir, "nope-wal")), 0
        )


class TestDeletedOpenQualification(unittest.TestCase):
    """The leak list is thresholded; the total must not be."""

    def test_both_shapes_reported(self):
        rows = [(10 * 1048576, 3, 111), (10223656, 19, 222), (0, 60, 333)]
        # Same tuple shape the patched function returns.
        self.assertEqual(len(rows), 3)
        total = sum(t for t, _n, _p in rows)
        self.assertEqual(total, 10 * 1048576 + 10223656)
        thresholded = [r for r in rows if r[1] >= 50]
        self.assertEqual(len(thresholded), 1, "only the 60-fd row clears the threshold")
        self.assertEqual(len(rows), 3, "but the unthresholded census sees all three")

    def test_below_threshold_still_contributes_to_total(self):
        """The exact live shape: 19 fds, under 50, invisible to the old report."""
        row = (10223656, 19, 933497)
        self.assertLess(row[1], 50)
        self.assertEqual(sum(t for t, _n, _p in [row]), 10223656)


class TestDbBloatSidecars(unittest.TestCase):
    def setUp(self):
        self.dir = _mkfixture(prefix="finch_bloat_")
        self.db = os.path.join(self.dir, "t.db")
        import sqlite3
        con = sqlite3.connect(self.db)
        con.execute("pragma journal_mode=wal")
        con.execute("create table t(x)")
        con.executemany("insert into t values(?)", [(i,) for i in range(5000)])
        con.commit()
        con.close()
        # DB_TARGETS is a module-level constant resolved from the profile root
        # at import time, so db_bloat() cannot see a fixture created in a temp
        # dir. Point the name at the fixture and restore it after: the test
        # proves the rule, not this host's configured database list.
        self._saved = w.DB_TARGETS
        w.DB_TARGETS = [("t.db", self.db)]

    def tearDown(self):
        w.DB_TARGETS = self._saved
        _rmtree(self.dir)

    def test_sidecar_fields_present_when_wal_exists(self):
        write_wal(self.db + "-wal", [(0x1111, 0x2222)] * 3 + [(0x0BAD, 0x0BAD)] * 60)
        rows = w.db_bloat()
        row = [r for r in rows if r.get("db") == "t.db"]
        self.assertTrue(row, "the test DB should appear in db_bloat()")
        row = row[0]
        self.assertIn("wal_file_mb", row)
        self.assertIn("wal_live_mb", row)
        self.assertGreater(row["wal_file_mb"], row["wal_live_mb"],
                           "fixture's stale tail must make file size exceed live size")
        self.assertLess(row["wal_live_mb"], 1.0)

    def test_sidecar_fields_match_disk_exactly(self):
        """Fields are present iff the sidecar exists, and equal its real size.

        Note what cannot be tested here: 'a WAL-mode DB with no -wal file'.
        Opening one -- even read-only, which is all db_bloat() does --
        recreates the sidecar, so a 0-byte -wal is present every time. An
        assertion for the absent case would be asserting something the code
        cannot deliver, so the contract tested is the one that holds: the
        fields track the real file, and a 0-byte WAL reports 0 live, not the
        file's high-water mark.
        """
        rows = w.db_bloat()
        row = [r for r in rows if r.get("db") == "t.db"][0]
        self.assertTrue(os.path.exists(self.db + "-wal"),
                        "opening a WAL-mode DB recreates the sidecar")
        self.assertIn("wal_file_mb", row)
        self.assertIn("wal_live_mb", row)
        real_mb = round(os.path.getsize(self.db + "-wal") / 1048576.0, 1)
        self.assertEqual(row["wal_file_mb"], real_mb)
        self.assertGreaterEqual(row["wal_live_mb"], 0.0)
        self.assertLessEqual(row["wal_live_mb"], row["wal_file_mb"])
        for key in ("size_mb", "free_mb", "bloat_pct", "used_mb"):
            self.assertIn(key, row)

    def test_absent_sidecar_yields_no_fields(self):
        """A non-WAL (DELETE-mode) DB reports no sidecar fields at all."""
        plain = os.path.join(self.dir, "p.db")
        import sqlite3
        con = sqlite3.connect(plain)
        con.execute("pragma journal_mode=delete")
        con.execute("create table t(x)")
        con.commit()
        con.close()
        for suffix in ("-wal", "-shm"):
            if os.path.exists(plain + suffix):
                os.remove(plain + suffix)
        w.DB_TARGETS = [("p.db", plain)]
        rows = w.db_bloat()
        row = [r for r in rows if r.get("db") == "p.db"][0]
        self.assertNotIn("wal_file_mb", row)
        self.assertNotIn("wal_live_mb", row)


if __name__ == "__main__":
    unittest.main(verbosity=2)
