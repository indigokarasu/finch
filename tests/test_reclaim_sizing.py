"""The reclaim section must separate two reasons a weight is not reclaimable.

A hardlinked file is a real `du` artifact: du counts every name, deleting one
reclaims zero. An in-use file is a liveness gap: it is simply alive, and du
counts it exactly once, correctly. The old code summed both into one field
named for the du artifact, so that field moved when a service merely began
reading a weight -- which is what made #1050's recorded 1,657.9 MB read
3,402.4 MB five passes later with no disk change at all.

The load-bearing assertion is the NEGATIVE: a file that is hardlink-unique but
in use must contribute 0 to the du field. A test that only checked the positive
would pass under a "count everything not reclaimable as over-report"
implementation, which is the bug.

Every fixture is a temp tree under a patched HOME_DIR, so nothing here reads
the real /opt weights and no pass can quote a number off this host.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import finch_disk_watch as w  # noqa: E402

MB = 1024 * 1024
BIG = 250 * MB  # over the 200 MB floor the walker applies


class ReclaimSizingTest(unittest.TestCase):
    def _rows(self, spec, in_use=()):
        """spec: list of (subdir, size_mb, hardlink_count). Returns reclaim rows."""
        with tempfile.TemporaryDirectory() as tmp:
            built = []
            for subdir, size_mb, links in spec:
                d = os.path.join(tmp, subdir)
                os.makedirs(d, exist_ok=True)
                p = os.path.join(d, "a.gguf")
                with open(p, "wb") as fh:
                    fh.truncate(size_mb * MB)
                if links > 1:
                    os.link(p, os.path.join(d, "b.gguf"))
                built.append(p)
            with mock.patch.object(w, "RECLAIM_ROOTS", (tmp,)):
                return w._reclaim_candidates({p for p in built if p in set(in_use)})

    def test_hardlinked_file_counts_only_the_du_overreport(self):
        """A 2-link pair: du double-counts it, so the du field is one size."""
        rows = self._rows([("pair", 250, 2)])
        self.assertEqual(len(rows), 1, "hardlinked names collapse to one inode")
        r = rows[0]
        self.assertEqual(r["nlink"], 2)
        self.assertEqual(r["hardlink_overreport_mb"], 250.0)
        self.assertEqual(r["truly_reclaimable_mb"], 0.0)
        # du would report both names, so its over-report is exactly one size.
        self.assertAlmostEqual(
            r["hardlink_overreport_mb"], r["size_mb"], places=3
        )

    def test_in_use_unique_file_is_NOT_du_overreport(self):
        """THE NEGATIVE. Unique inode, but a process holds it: du is right.

        Counting this as over-report is the bug -- it makes a du-artifact field
        track service liveness, and no test that only checks the hardlink case
        would catch it.
        """
        p = None
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "solo")
            os.makedirs(d)
            p = os.path.join(d, "a.gguf")
            with open(p, "wb") as fh:
                fh.truncate(BIG)
            with mock.patch.object(w, "RECLAIM_ROOTS", (tmp,)):
                rows = w._reclaim_candidates({p})
        r = rows[0]
        self.assertTrue(r["in_use_by_running_process"])
        self.assertEqual(r["nlink"], 1)
        self.assertEqual(
            r["hardlink_overreport_mb"], 0.0,
            "an in-use unique file is a liveness gap, not a du artifact",
        )
        self.assertEqual(r["truly_reclaimable_mb"], 0.0)
        # It still shows up in the not-reclaimable bucket, so the bytes remain
        # visible -- separability, not erasure.
        self.assertAlmostEqual(r["size_mb"], 250.0, places=3)

    def test_totals_partition_and_du_overreport_is_a_separate_crosscut(self):
        """Reclaimable + not-reclaimable partitions the set; du over-report cuts
        ACROSS it, so it is deliberately allowed to overlap.

        An earlier draft of this test asserted a single disjoint partition and
        failed: a hardlinked weight is simultaneously a du artifact AND
        unreclaimable, so counting it in both buckets is correct, not a
        double-count. What must hold is that the partition is exact and that
        the du term stays independently meaningful.
        """
        rows = self._rows([("pair", 250, 2), ("uniq_a", 250, 1), ("uniq_b", 260, 1)])
        du_total = round(sum(r["hardlink_overreport_mb"] for r in rows), 1)
        not_reclaimable = round(
            sum(r["size_mb"] for r in rows if not r["truly_reclaimable_mb"]),
            1,
        )
        reclaimable = round(sum(r["truly_reclaimable_mb"] for r in rows), 1)
        # The partition is exact: every candidate is reclaimable or not, once.
        self.assertEqual(
            round(not_reclaimable + reclaimable, 1),
            round(sum(r["size_mb"] for r in rows), 1),
            "reclaimable + not-reclaimable covers every candidate exactly once",
        )
        self.assertAlmostEqual(reclaimable, 510.0, places=1)
        self.assertAlmostEqual(not_reclaimable, 250.0, places=1)
        # The du term counts ONLY hardlinked candidates -- the 250 MB pair,
        # never the 510 MB of unique in-use-or-free weights.
        self.assertAlmostEqual(du_total, 250.0, places=1)

    def test_du_field_is_invariant_to_liveness(self):
        """THE REGRESSION PIN, quoted from the live incident.

        Same tree, two different liveness sets. The du field must not move: if
        it does, the field is tracking services, not counting hardlinks.
        """
        with tempfile.TemporaryDirectory() as tmp:
            pair = os.path.join(tmp, "pair")
            solo = os.path.join(tmp, "solo")
            os.makedirs(pair)
            os.makedirs(solo)
            pp = os.path.join(pair, "a.gguf")
            sp = os.path.join(solo, "a.gguf")
            with open(pp, "wb") as fh:
                fh.truncate(250 * MB)
            os.link(pp, os.path.join(pair, "b.gguf"))
            with open(sp, "wb") as fh:
                fh.truncate(300 * MB)

            with mock.patch.object(w, "RECLAIM_ROOTS", (tmp,)):
                idle = w._reclaim_candidates(set())
                busy = w._reclaim_candidates({sp})

            du_idle = round(sum(r["hardlink_overreport_mb"] for r in idle), 1)
            du_busy = round(sum(r["hardlink_overreport_mb"] for r in busy), 1)
            self.assertEqual(
                du_idle, du_busy,
                "du over-report changed when a service began reading a weight",
            )
            self.assertAlmostEqual(du_idle, 250.0, places=1)
            # ...while the reclaim estimate DID fall, which is the whole point.
            self.assertGreater(
                sum(r["truly_reclaimable_mb"] for r in idle),
                sum(r["truly_reclaimable_mb"] for r in busy),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
