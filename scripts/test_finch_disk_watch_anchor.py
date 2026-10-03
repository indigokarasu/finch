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
import time as _real_time
import time
import json
import re
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finch_disk_watch as dw  # noqa: E402


class _FrozenClock:
    """A `time` stand-in that never advances.

    Any test that drives main() against a ring whose samples are pinned to a
    fixed epoch must install this. main() reads time.time() to choose the
    anchor and save_baseline() reads it again to prune against
    _retention_h(), so a live clock silently deletes any fixture older than
    retention and the test then asserts on a ring that no longer exists.
    save_baseline() also stamps `iso` through time.strftime/gmtime.
    """

    def __init__(self, instant):
        self._t = float(instant)

    def time(self):
        return self._t

    def strftime(self, fmt, t=None):
        return _real_time.strftime(fmt, t if t is not None else self._t)

    def gmtime(self, t=None):
        return _real_time.gmtime(t if t is not None else self._t)

    def __getattr__(self, name):
        return getattr(_real_time, name)

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


class TestAnchorSurvivesItsOwnWrite(unittest.TestCase):
    """The run that PUBLISHES a rate must not destroy the sample it rests on.

    Measured 2026-10-02 (finch:work #1091). `main()` anchors on the OLDEST
    retained sample, and `save_baseline()` prunes everything older than
    `_retention_h()`. The two windows differ by the write gap, so on any job
    that is not running continuously the anchor is ALWAYS older than retention
    by the time the run finishes -- and the run publishes a rate whose own
    evidence it deletes.

    Observed live that pass: rate +905.0 MB/24h over a 4.90 h window anchored
    on a sample 4.90 h old against 4.00 h retention; the same write pruned it,
    leaving the ring alone reading -1086.5 MB/24h -- the opposite sign.

    The cases pin the ARITHMETIC of `growth_anchor_retained_after_write`, not a
    host fact, and both directions must be asserted: a field that is only ever
    True is decoration, which is the failure mode the ledger rules warn about.
    """

    def _anchor_kept(self, anchor_ts, now):
        """Mirror of the published field, driven off the module's own retention.

        DEPRECATED as an oracle for the shipped field -- see
        `test_field_reads_the_written_ring_not_a_stale_clock` below. Kept only
        because it still expresses the retention RULE, which remains true.
        """
        return bool(anchor_ts >= now - dw._retention_h() * 3600.0)

    def _run_with_clock(self, base_path, clock):
        """Drive main() with the baseline redirected and time under control.

        main() takes no arguments and RETURNS NOTHING -- with --json it prints
        and returns None -- so the report is read back off stdout, not off a
        return value. And the baseline is redirected by patching the function
        that resolves it (`_baseline_path`), because the module resolves the
        path per call rather than storing a module-level constant.

        `clock` replaces `dw.time` so the two instants the defect depends on --
        the pre-write `now` used to CHOOSE the anchor and the post-write
        time.time() used to PRUNE -- can be separated deterministically instead
        of by sleeping.
        """
        import io
        import contextlib
        orig_argv = sys.argv
        orig_time = dw.time
        sys.argv = ["finch_disk_watch.py", "--json"]
        buf = io.StringIO()
        try:
            dw._baseline_path = lambda: base_path
            dw.time = clock
            with contextlib.redirect_stdout(buf):
                dw.main()
        finally:
            dw.time = orig_time
            sys.argv = orig_argv
        return json.loads(buf.getvalue())

    class _Clock:
        """The first call is the pre-write instant; later calls advance.

        main() reads time.time() once to pick the anchor, then save_baseline()
        reads it again to prune. Returning a later value on the second and
        subsequent calls reproduces the real gap between the two without a
        wall-clock sleep.
        """

        def __init__(self, start, later, stride=1.0):
            self._t = start
            self._later = later
            self._stride = stride

        def time(self):
            val, self._t = self._t, self._t + self._stride
            return val

        # save_baseline() also stamps the sample's iso field through these.
        def strftime(self, fmt, t=None):
            return _real_time.strftime(fmt, t if t is not None else self._t)

        def gmtime(self, t=None):
            return _real_time.gmtime(t if t is not None else self._t)

        def __getattr__(self, name):
            return getattr(_real_time, name)

    def _write_fixture(self, base, now, anchor_ts, newest_ts):
        with open(base, "w") as fh:
            json.dump({
                "used_mb": 70000.0, "pct": 71.3,
                "ts": anchor_ts, "iso": "fixture-anchor",
                "samples": [
                    {"used_mb": 70000.0, "pct": 71.3, "ts": anchor_ts,
                     "iso": "fixture-anchor"},
                    {"used_mb": 70050.0, "pct": 71.4, "ts": newest_ts,
                     "iso": "fixture-newest"},
                ],
                "retention_hours": dw._retention_h(),
            }, fh)

    def test_field_reads_the_written_ring_not_a_stale_clock(self):
        """The shipped field must be FALSE when the write deleted its anchor.

        Measured 2026-10-02 (finch:work #1125). The field
        `growth_anchor_retained_after_write` re-derived survival from the clock
        captured when the anchor was CHOSEN, while the prune that actually
        removed the sample ran inside save_baseline() at a LATER time.time().
        A run whose anchor sat within its own report-construction time of the
        boundary published TRUE for an anchor it had just deleted. Live
        measurement: anchor 78,456.2 MB @ 19:04:14Z, margin under retention at
        eval time 91 s, report build 92 s, prune cutoff 19:04:15Z -- the anchor
        is 1 s before the cutoff and ABSENT from the ring on disk.

        This drives main() end to end rather than re-implementing the
        predicate, because the defect WAS the mismatch between the two: a
        mirror test asserts the rule is right while the shipped code is wrong,
        and `_anchor_kept` above is precisely such a test -- it passed against
        the broken expression for its entire life.
        """
        now = _real_time.time()
        ret = dw._retention_h() * 3600.0
        base = os.path.join(tempfile.mkdtemp(), "disk_watch_baseline.json")

        # Anchor 2 s inside retention by the PRE-WRITE clock, then the clock
        # jumps 300 s -- the report-build gap. 2 < 300 is the whole defect.
        self._write_fixture(base, now, now - ret + 2.0, now - 0.05)
        clock = self._Clock(now, now + 300.0, stride=300.0)
        rep = self._run_with_clock(base, clock)

        on_disk = json.load(open(base))["samples"]
        anchor_survived = any(
            abs(float(s["used_mb"]) - 70000.0) < 0.5 for s in on_disk
        )
        field = rep["growth_anchor_retained_after_write"]

        self.assertFalse(
            anchor_survived,
            "fixture is wrong: the write kept the anchor, so it cannot "
            "exercise a false TRUE",
        )
        self.assertIs(
            field, False,
            "the field published %r for an anchor the same run deleted from "
            "the ring -- it re-derived survival from the pre-write clock "
            "instead of reading the written payload" % (field,),
        )

    def test_field_is_true_when_the_anchor_actually_survived(self):
        """The same field must still say TRUE on the ordinary case.

        A fix that always answers False is not a fix; it moves the false
        negative into the other direction. The anchor here sits 900 s inside
        retention while the clock advances 300 s, so it survives -- and only
        this distinguishes a correct field from a permanently-False one.
        """
        now = _real_time.time()
        ret = dw._retention_h() * 3600.0
        base = os.path.join(tempfile.mkdtemp(), "disk_watch_baseline.json")

        self._write_fixture(base, now, now - ret + 900.0, now - 0.05)
        clock = self._Clock(now, now + 300.0, stride=300.0)
        rep = self._run_with_clock(base, clock)

        on_disk = json.load(open(base))["samples"]
        self.assertTrue(any(
            abs(float(s["used_mb"]) - 70000.0) < 0.5 for s in on_disk
        ))
        self.assertIs(rep["growth_anchor_retained_after_write"], True)

    def test_anchor_within_retention_survives(self):
        now = time.time()
        self.assertTrue(self._anchor_kept(now - 0.5 * 3600.0, now))

    def test_anchor_older_than_retention_is_pruned(self):
        now = time.time()
        self.assertFalse(self._anchor_kept(now - 4.5 * 3600.0, now))

    def test_retention_is_derived_not_hardcoded(self):
        """The rule cannot be satisfied by editing a constant elsewhere.

        #1091 measured that a >=6h anchor (the standing clause from #1090) is
        unreachable from the current ring because retention is 4.0h. That is
        only a fact ABOUT the ring if retention is derived from the guard, so
        pin the derivation: raising the guard raises the reachable anchor, and
        a retention shorter than the guard's own age requirement is impossible.
        """
        self.assertEqual(dw._retention_h(), max(dw.MIN_BASELINE_AGE_H * 4.0, 4.0))
        self.assertGreaterEqual(dw._retention_h(), 4.0)

    def test_anchor_age_cannot_exceed_retention_plus_write_gap(self):
        """The ceiling that makes the >=6h clause unreachable.

        The anchor ages across the interval since the previous write, so its
        maximum age is retention + that gap. With a 30 min-ish cadence the
        ceiling sits near 4.9h -- which is why the observed anchor was 4.90h.
        """
        now = time.time()
        gap_h = 0.94
        ceiling_h = dw._retention_h() + gap_h
        anchor_age_h = 4.90
        self.assertLessEqual(anchor_age_h, ceiling_h)
        self.assertLess(ceiling_h, 6.0)  # the >=6h rule is unreachable as shipped


class TestPostStepResidual(unittest.TestCase):
    """The rate with the dominant step's INTERVAL removed (#1127).

    The fixture is this pass's real 2026-10-02 ring, so the numbers are pinned
    to a disk rather than to values chosen to satisfy the assertion. The
    headline over the full window is +16,219.2 MB/24h (MET); the residual over
    the same window minus the +2,523.3 MB step's interval is +2,735.7 (UNMET).
    A suite that only pinned the headline would have been green throughout.
    """

    NOW = 1790984562.93  # 2026-10-02T23:42:42Z

    def _ring(self):
        h = 3600.0
        return [
            {"ts": self.NOW - 3.974 * h, "used_mb": 78472.6},
            {"ts": self.NOW - 3.831 * h, "used_mb": 78519.2},
            {"ts": self.NOW - 3.146 * h, "used_mb": 78341.0},
            {"ts": self.NOW - 3.033 * h, "used_mb": 78384.2},
            {"ts": self.NOW - 2.175 * h, "used_mb": 80907.5},  # +2523.3 step
            {"ts": self.NOW - 1.278 * h, "used_mb": 80901.4},
            {"ts": self.NOW - 0.640 * h, "used_mb": 81232.3},
            {"ts": self.NOW - 0.557 * h, "used_mb": 81254.8},
            {"ts": self.NOW - 0.364 * h, "used_mb": 81320.0},
            {"ts": self.NOW - 0.279 * h, "used_mb": 81057.8},
        ]

    def test_residual_is_far_below_a_met_headline(self):
        cur = 81155.4
        h = 3600.0
        ring = self._ring()
        steps = dw._window_steps(ring + [{"ts": self.NOW, "used_mb": cur}])
        headline = (cur - ring[0]["used_mb"]) / ((self.NOW - ring[0]["ts"]) / h) * 24.0
        res = dw._post_step_residual(ring, abs(max(steps, key=abs)), cur, self.NOW)
        self.assertIsNotNone(res)
        self.assertGreater(headline, dw.TRIGGER_GROWTH_MB_24H)   # MET
        self.assertLess(res[0], dw.TRIGGER_GROWTH_MB_24H)          # UNMET
        # same disk, same window, opposite sides of the trigger
        self.assertGreater(headline, res[0] * 5)

    def test_residual_window_starts_after_the_step(self):
        res = dw._post_step_residual(
            self._ring(), 2523.3, 81155.4, self.NOW)
        # 11 samples, 10 intervals, step at index 3 -> 7 samples survive
        self.assertEqual(res[3], 7)
        self.assertAlmostEqual(res[2], 2.175, places=2)
        self.assertLess(res[2], 3.974)       # strictly shorter than the headline

    def test_no_step_means_no_residual_rather_than_a_zero(self):
        # Flat window: biggest is not dominant, so there is nothing to remove.
        ring = [{"ts": self.NOW - 3 * 3600 + i * 900, "used_mb": 100.0}
                for i in range(9)]
        self.assertIsNone(dw._post_step_residual(ring, 0.0, 100.0, self.NOW))

    def test_short_tail_abstains_instead_of_normalising_churn(self):
        """A step in the FINAL interval leaves two samples, not zero.

        Without the age guard this returns 0.0 MB/24h today and would return a
        large positive number on a smaller tail -- the same 24h-normalisation
        artifact that produced #1028's retracted 13,665 MB/24h.
        """
        ring = [
            {"ts": self.NOW - 3 * 3600, "used_mb": 100.0},
            {"ts": self.NOW - 2 * 3600, "used_mb": 101.0},
            {"ts": self.NOW - 1 * 3600, "used_mb": 5000.0},
        ]
        self.assertIsNone(dw._post_step_residual(ring, 4999.0, 5000.0, self.NOW))

    def test_too_few_samples_returns_none(self):
        ring = [{"ts": self.NOW - 2 * 3600, "used_mb": 100.0},
                {"ts": self.NOW - 1 * 3600, "used_mb": 9000.0}]
        self.assertIsNone(dw._post_step_residual(ring, 8900.0, 9000.0, self.NOW))

    def test_non_dominant_largest_step_still_yields_none(self):
        """The function re-checks dominance, so a wrong step_mb cannot fool it."""
        h = 3600.0
        ring = [{"ts": self.NOW - 4 * h + i * h, "used_mb": 1000.0 + i * 100.0}
                for i in range(5)]
        # every step is +100, so no single one dominates; the caller passed a
        # value implying otherwise
        res = dw._post_step_residual(ring, 100.0, 1500.0, self.NOW)
        self.assertIsNone(res)

    def test_residual_does_not_mutate_its_input(self):
        ring = self._ring()
        before = json.dumps(ring, sort_keys=True)
        dw._post_step_residual(ring, 2523.3, 81155.4, self.NOW)
        self.assertEqual(json.dumps(ring, sort_keys=True), before)

    def test_report_publishes_the_residual_when_the_step_dominates(self):
        """The field must reach the JSON, not merely exist as a function.

        Both halves of the host state this test depends on must be pinned, not
        one. (1) The CLOCK: the fixture is pinned to NOW =
        2026-10-02T23:42:42Z and its oldest sample sits on the 4.0h retention
        boundary, so a live clock prunes the ring the assertions read -- the
        +2,523.3 MB step and every sample before it are gone. (2) The READING:
        main() appends THIS RUN's own used_mb to the window before the step
        test runs, and that value comes from fs_usage() against the live disk.
        The fixture's newest sample is 81,057.8 MB while the real filesystem
        reads ~78,700, so the live reading injects a second ~-2,300 MB step
        that rivals the fixture's own and the dominance predicate correctly
        refuses to call either one dominant -- spans_step reads False for a
        reason that has nothing to do with the residual.

        A fixture that pins the epoch but not the measurement is half a
        fixture, and the half it left open was this host's disk.
        """
        import io
        import contextlib
        out = io.StringIO()
        base = {"samples": self._ring()}
        cur = 81155.4   # the value this fixture's prose already quotes
        argv = sys.argv
        saved = (dw.save_baseline, dw.load_baseline, dw.time, dw.fs_usage)
        try:
            dw.load_baseline = lambda path=None: base
            dw.save_baseline = lambda *a, **k: {"samples": base["samples"]}
            dw.time = _FrozenClock(self.NOW)
            dw.fs_usage = lambda: (cur, 98147.9, cur / 98147.9 * 100.0)
            sys.argv = ["finch_disk_watch.py", "--json"]
            with contextlib.redirect_stdout(out):
                dw.main()
        finally:
            (dw.save_baseline, dw.load_baseline,
             dw.time, dw.fs_usage) = saved
            sys.argv = argv
        rep = json.loads(out.getvalue())
        self.assertTrue(rep["growth_window_spans_step"])
        self.assertAlmostEqual(rep["growth_window_step_mb"], 2523.3, places=1)
        self.assertIsNotNone(rep["growth_post_step_residual_mb_24h"])
        self.assertEqual(rep["growth_post_step_residual_samples"], 7)
        # the whole point: the two disagree about the gate
        self.assertTrue(rep["growth_met"])
        self.assertFalse(rep["growth_post_step_residual_met"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
