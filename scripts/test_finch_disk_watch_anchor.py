#!/usr/bin/env python3
"""finch_disk_watch anchor-selection regression tests.

Run before and after ANY change to _pick_anchor() / the growth leg:
    python3 scripts/test_finch_disk_watch_anchor.py

Why this suite exists (measured 2026-10-01, finch:work #1082): the growth leg
reported -7,596 MB/24h on a disk that had risen +1,063 MB monotonically over
3.8h. The cause was anchor SELECTION, not the disk -- the rule took the oldest
retained sample, which sat on the far side of a 2,316 MB step, so the sign of
the published rate was a property of the anchor's position. `growth_measured`
was true throughout, because it only asserts that an anchor existed.

The fixture below is that night's real ring, so the regression is pinned to real
numbers rather than to ones chosen to suit the assertion.
"""
import os
import sys
import time
import json
import re
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finch_disk_watch as dw  # noqa: E402

# The real 2026-10-01 ring, read from state/disk_watch_baseline.json at
# 20:42:47Z. Times are expressed as hours-before-now so the test is not pinned
# to a wall clock, and the two pre-transient samples (16:22:06Z 80,678.3 and
# 16:22:27Z 78,362.3) have already aged out of the 4h retention window -- which
# is the point: the anchor that produced the bad rate is not on disk any more.
RING_2026_10_01 = [
    (-3.83, 78243.7),   # 16:53:08Z
    (-3.45, 78361.9),   # 17:15:33Z
    (-3.44, 78361.9),   # 17:15:52Z
    (-2.36, 78580.0),   # 18:21:21Z
    (-2.33, 78592.7),   # 18:23:15Z
    (-2.15, 78650.5),   # 18:34:04Z
    (-1.27, 78879.8),   # 19:26:59Z
    (-1.10, 78948.8),   # 19:36:51Z
    (-1.09, 78952.8),   # 19:37:07Z
    (-0.57, 79127.3),   # 20:08:31Z
    (-0.40, 79171.4),   # 20:18:35Z
    (-0.00, 79306.9),   # 20:42:47Z
]

# The pre-transient pair, retained here only to prove the OLD rule's failure.
# 2,316.0 MB of level was lost in 21 seconds, then the disk climbed.
RING_WITH_TRANSIENT = [
    (-5.0, 80678.3),
    (-4.99, 78362.3),   # 2,316 MB drop in 21 seconds
    (-3.83, 78243.7),
    (-2.36, 78580.0),
    (-0.57, 79127.3),
    (-0.00, 79306.9),
]

# Measured 2026-10-01 (finch:work #1086). The ring as it stood at 22:26Z, and
# the reading taken 23m34s after the last saved sample. The tail between the
# last ring sample and `now` carried -158.0 MB -- the only decrease in the
# window -- and was the segment the old dominance test never saw.
RING_WITH_UNMEASURED_TAIL = [
    (-3.878, 78650.5),  # 18:34:04Z
    (-2.984, 78879.8),
    (-2.163, 78948.8),
    (-2.131, 78952.8),
    (-1.304, 79127.3),
    (-0.868, 79171.4),
    (-0.399, 79306.9),
    (-0.004, 79348.0),
    (-0.002, 79356.3),
    (-0.048, 79448.4),
    (-0.043, 79456.6),
    (-0.023, 79460.6),
    (-0.021, 79460.6),
]
TAIL_READING_MB = 79302.6   # 22:26:39Z, -158.0 MB below the newest ring sample


def as_samples(rows, now):
    return [
        {"ts": now + age_h * 3600.0, "used_mb": mb, "pct": mb / 98147.9 * 100.0}
        for age_h, mb in rows
    ]


class TestPickAnchor(unittest.TestCase):

    def setUp(self):
        self.now = 1790887367.93  # 2026-10-01T20:42:47Z

    def test_real_ring_measures_a_rate(self):
        anchor, note, step, spans = dw._pick_anchor(
            as_samples(RING_2026_10_01, self.now), self.now)
        self.assertIsNotNone(anchor, "a monotonic window must still produce a rate")
        self.assertFalse(spans_step_is_true(spans), "no step in a monotonic window")
        self.assertIn("endpoints", note)

    def test_sign_matches_the_disk_not_the_anchor(self):
        """The regression: this window has RISEN. The rate must be positive."""
        anchor, _note, _step, _spans = dw._pick_anchor(
            as_samples(RING_2026_10_01, self.now), self.now)
        newest = max(as_samples(RING_2026_10_01, self.now), key=lambda s: s["ts"])
        dt_h = (newest["ts"] - anchor["ts"]) / 3600.0
        rate = (newest["used_mb"] - anchor["used_mb"]) * (24.0 / dt_h)
        self.assertGreater(rate, 0.0, "a rising disk must not report negative growth")
        # And the measured magnitude: +1063.2 MB over 3.83h -> ~+6.7k MB/24h,
        # which is ABOVE the +5,120 runaway trigger.
        self.assertGreater(rate, 5120.0)

    def test_interior_transient_is_flagged_and_cannot_bias(self):
        anchor, note, step, spans = dw._pick_anchor(
            as_samples(RING_WITH_TRANSIENT, self.now), self.now)
        self.assertTrue(spans, "a dominant step must be reported")
        self.assertAlmostEqual(step, 2316.0, delta=1.0)
        self.assertIn("SIGN", note)

    def test_anchor_is_the_oldest_endpoint_not_a_step_neighbour(self):
        """With a transient present, anchoring on an endpoint still yields the
        post-transient trend, which is what the disk actually did."""
        anchor, _n, _s, _sp = dw._pick_anchor(
            as_samples(RING_WITH_TRANSIENT, self.now), self.now)
        self.assertEqual(anchor["used_mb"], 80678.3,
                         "endpoints must be oldest-retained and newest")

    def test_young_window_reports_unknown_not_a_guess(self):
        rows = [(-0.4, 100.0), (-0.2, 110.0), (-0.0, 120.0)]
        anchor, note, _s, _sp = dw._pick_anchor(as_samples(rows, self.now), self.now)
        self.assertIsNone(anchor, "under MIN_BASELINE_AGE_H there is no rate")
        self.assertIn("not measured", note)

    def test_no_samples(self):
        anchor, note, step, spans = dw._pick_anchor([], self.now)
        self.assertIsNone(anchor)
        self.assertIn("no samples", note)
        self.assertEqual(step, 0.0)
        self.assertFalse(spans)

    def test_zero_duration_window_does_not_divide_by_zero(self):
        rows = [(-2.0, 100.0), (-2.0, 130.0)]
        anchor, note, _s, _sp = dw._pick_anchor(as_samples(rows, self.now), self.now)
        self.assertIsNone(anchor)
        self.assertIn("zero duration", note)

    def test_flat_window_is_not_a_step(self):
        rows = [(-3.0, 500.0), (-2.0, 500.0), (-1.0, 500.0), (-0.0, 500.0)]
        anchor, _n, step, spans = dw._pick_anchor(as_samples(rows, self.now), self.now)
        self.assertIsNotNone(anchor)
        self.assertFalse(spans, "zero movement is not a step")
        self.assertEqual(step, 0.0)

    def test_minor_churn_is_not_a_step(self):
        """Many small moves must not trip the dominance test -- otherwise every
        busy window would cry wolf and the flag would stop being read."""
        rows = [(float(-i), 1000.0 + i * 12.0) for i in range(60, 0, -1)]
        _a, _n, step, spans = dw._pick_anchor(as_samples(rows, self.now), self.now)
        self.assertFalse(spans)
        self.assertAlmostEqual(step, 12.0, delta=0.01)

    def test_endpoint_anchoring_is_immune_to_interior_step(self):
        """The general property the fix exists for: adding one huge interior
        jump must not change the endpoint rate."""
        clean = as_samples(RING_2026_10_01, self.now)
        spiked = list(clean)
        mid = dict(clean[len(clean) // 2])
        mid["used_mb"] = float(mid["used_mb"]) + 5000.0
        spiked.insert(len(spiked) // 2, mid)
        a1, _n1, _s1, _p1 = dw._pick_anchor(clean, self.now)
        a2, _n2, _s2, _p2 = dw._pick_anchor(spiked, self.now)
        self.assertEqual(a1["used_mb"], a2["used_mb"],
                         "an interior spike must not move the anchor")
        self.assertEqual(a1["ts"], a2["ts"])


class TestAnalysisWindowCoversPublishedRate(unittest.TestCase):
    """The regression for finch:work #1086.

    _pick_anchor() used to analyse the RING ALONE -- [oldest ring sample,
    newest ring sample] -- while main() publishes growth_mb_24h over
    [anchor.ts, now]. The tail between the last saved sample and the reading
    was therefore never covered by the dominance test, and the note quoted a
    span that could not reproduce the headline. On the real 22:26Z ring the
    note implied +5,712.4 MB/24h (MET) while the headline published +4,245.4
    (UNMET): the label certified a rate that was never reported.

    Every fixture here is built so the assertion FAILS against the pre-fix
    behaviour -- the tail is the only decrease, so ring-only analysis reports
    "no step" while the published rate has a different sign and magnitude.
    """

    def setUp(self):
        self.now = 1790895999.545625  # 2026-10-01T22:26:39Z, the live reading

    def _ring(self):
        return as_samples(RING_WITH_UNMEASURED_TAIL, self.now)

    def test_tail_change_is_in_the_window_under_analysis(self):
        rows = RING_WITH_UNMEASURED_TAIL
        now_anchor, _n, _s, _sp = dw._pick_anchor(as_samples(rows, self.now), self.now)
        anchor, _n2, _s2, _sp2 = dw._pick_anchor(
            as_samples(rows, self.now), self.now, current_mb=TAIL_READING_MB)
        self.assertIsNotNone(anchor)
        self.assertEqual(anchor["used_mb"], now_anchor["used_mb"],
                         "the tail must not move the anchor")

    def test_published_rate_is_reproduced_by_the_note(self):
        """The number in the note must BE the number in growth_mb_24h.

        This is the assertion that cannot pass against the old code: it
        compares the note's own span, normalised exactly as main() normalises
        growth_mb_24h, against the published rate.
        """
        anchor, note, _step, _spans = dw._pick_anchor(
            self._ring(), self.now, current_mb=TAIL_READING_MB)
        self.assertIsNotNone(anchor, "a real ring must still produce a rate")

        # Exactly main()'s arithmetic.
        dt_h = (self.now - float(anchor["ts"])) / 3600.0
        published = (TAIL_READING_MB - float(anchor["used_mb"])) * (24.0 / dt_h)

        # And exactly what the note claims it rested on.
        m = re.search(r"endpoints (\S+)\.\.(\S+) \(([0-9.]+)h, ([+-][0-9.]+) MB, "
                      r"(\d+) samples, rate ([+-][0-9.]+) MB/24h", note)
        self.assertIsNotNone(m, "note must quote the rate it justifies: %r" % note)
        span_h, span_mb = float(m.group(3)), float(m.group(4))
        self.assertAlmostEqual(span_h, dt_h, delta=0.01,
                               msg="note's duration must be the rate's duration")
        self.assertAlmostEqual(
            span_mb, TAIL_READING_MB - float(anchor["used_mb"]), delta=0.2,
            msg="note's MB must be the rate's numerator")
        self.assertAlmostEqual(
            float(m.group(6)), published, delta=1.0,
            msg="note's quoted rate must equal growth_mb_24h")

    def test_step_dominance_sees_the_unmeasured_tail(self):
        """A huge drop in the TAIL must be reported, not hidden by the ring.

        The old code reported spans_step=False for this fixture because the
        ring alone never declines. The tail is where a rate's numerator is
        decided, so a step there is exactly the one worth reporting.
        """
        ring = self._ring()
        _a, _n_ring, _step_ring, spans_ring = dw._pick_anchor(ring, self.now)
        self.assertFalse(spans_ring,
                         "fixture premise: the ring alone must look clean")

        # A tail large enough to dominate everything else in the window.
        huge_tail = float(ring[-1]["used_mb"]) - 9000.0
        _a2, note2, step2, spans2 = dw._pick_anchor(
            ring, self.now, current_mb=huge_tail)
        self.assertTrue(spans2,
                        "a dominating step in the tail must set spans_step")
        self.assertGreater(step2, 8000.0)
        self.assertIn("SIGN", note2,
                      "a dominating step must warn that the sign is endpoint-dependent")

    def test_tail_containing_the_only_decline_is_not_a_step_but_is_measured(self):
        """The live fixture: -158 MB in the tail is ordinary churn, not a step.

        It must NOT trip spans_step (that would cry wolf on ordinary traffic),
        but it MUST change the rate -- and the rate and the note must agree.
        """
        anchor, note, _step, spans = dw._pick_anchor(
            self._ring(), self.now, current_mb=TAIL_READING_MB)
        self.assertFalse(spans, "158 MB is not a dominant step")
        dt_h = (self.now - float(anchor["ts"])) / 3600.0
        published = (TAIL_READING_MB - float(anchor["used_mb"])) * (24.0 / dt_h)
        m = re.search(r"rate ([+-][0-9.]+) MB/24h", note)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(float(m.group(1)), published, delta=1.0)

        # And the rate must differ from the ring-only rate -- otherwise this
        # fixture could not distinguish the two behaviours at all.
        _a2, _n2, _s2, _sp2 = dw._pick_anchor(self._ring(), self.now)
        newest = max(self._ring(), key=lambda s: s["ts"])
        ring_dt = (float(newest["ts"]) - float(anchor["ts"])) / 3600.0
        ring_only = (float(newest["used_mb"]) - float(anchor["used_mb"])) * (24.0 / ring_dt)
        self.assertNotAlmostEqual(published, ring_only, delta=1.0,
                                  msg="fixture is vacuous if both rates are equal")

    def test_explicit_none_current_mb_preserves_previous_behaviour(self):
        """Callers that pass nothing keep the ring-only analysis."""
        ring = self._ring()
        _a1, _n1, _s1, _sp1 = dw._pick_anchor(ring, self.now)
        _a2, _n2, _s2, _sp2 = dw._pick_anchor(ring, self.now, current_mb=None)
        self.assertEqual(_s1, _s2)
        self.assertEqual(_sp1, _sp2)


def spans_step_is_true(v):
    return bool(v)


class TestWindowSteps(unittest.TestCase):
    def test_adjacent_deltas_oldest_first(self):
        samples = [
            {"ts": 1.0, "used_mb": 100.0},
            {"ts": 2.0, "used_mb": 150.0},
            {"ts": 3.0, "used_mb": 140.0},
        ]
        self.assertEqual(dw._window_steps(samples), [50.0, -10.0])

    def test_single_sample_has_no_steps(self):
        self.assertEqual(dw._window_steps([{"ts": 1.0, "used_mb": 1.0}]), [])


class TestPruneKeepsRecentSamples(unittest.TestCase):
    def test_prune_drops_only_expired(self):
        now = time.time()
        kept, dropped = dw._prune_samples(
            [{"ts": now - 10.0 * 3600, "used_mb": 1.0},
             {"ts": now - 0.5 * 3600, "used_mb": 2.0}],
            now=now)
        self.assertEqual(dropped, 1)
        self.assertEqual(len(kept), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
