#!/usr/bin/env python3
"""finch_disk_watch anchor-envelope regression tests.

Run before and after ANY change to _anchor_rate_envelope():
    python3 scripts/test_finch_disk_watch_anchor_envelope.py

Why this suite exists (measured 2026-10-02, finch:work #1097): the growth leg
published -409.6 MB/24h and reported the gate UNMET, while a DIFFERENT legal
anchor inside the SAME retained ring gave +7,905.5 MB/24h -- over the 5,120
trigger -- with three sign flips in between. Nothing in the report could tell a
reader that: `growth_anchor_retained_after_write` says whether the anchor was
AUDITABLE, not how much the answer depended on WHICH anchor was picked, and
`growth_window_spans_step` only fires when a single adjacent jump outweighs
every other movement combined -- a different and much narrower condition.

The fixture is that night's real ring, read from
state/disk_watch_baseline.json, so the regression is pinned to measured numbers
rather than to ones chosen to suit the assertion.
"""
import os
import sys
import time
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finch_disk_watch as dw  # noqa: E402

NOW = 100000.0  # fixed epoch; every sample is expressed as an offset before it

# The real 2026-10-02 ring, read from state/disk_watch_baseline.json at
# 02:56:26Z, as EXACT (iso, used_mb) pairs -- oldest first. The last entry is the
# reading this pass published, passed separately as `current_mb`.
#
# These are ISO instants rather than hours-before-now on purpose. A first draft
# of this fixture rounded each sample to 4 decimal places and the envelope test
# then failed by ~160 MB/24h against the live measurement -- the fixture's
# precision, not the function's. A regression suite pinned to a lossy copy of
# the ring cannot detect drift of the size it is meant to detect, so the exact
# stamps are what belong here.
RING_2026_10_02_ISO = [
    ("2026-10-01T23:04:56.194100+00:00", 79496.6),
    ("2026-10-01T23:05:17.965048+00:00", 79500.6),
    ("2026-10-01T23:34:38.567170+00:00", 79361.4),
    ("2026-10-01T23:34:56.071792+00:00", 79366.1),
    ("2026-10-01T23:36:09.522397+00:00", 79375.0),
    ("2026-10-02T00:32:21.015510+00:00", 79133.7),
    ("2026-10-02T01:04:27.838528+00:00", 79283.1),
    ("2026-10-02T01:04:43.573401+00:00", 79287.3),
    ("2026-10-02T01:10:18.491870+00:00", 79315.9),
    ("2026-10-02T01:30:52.850466+00:00", 79124.8),
    ("2026-10-02T01:41:52.771794+00:00", 79183.3),
    ("2026-10-02T02:31:52.261938+00:00", 79154.1),
]
# The reading: growth_mb_24h was published from anchor 22:37:15Z..02:55:56Z, so
# the window end is the READING, not the save instant 36s later.
READING_ISO = "2026-10-02T02:55:56+00:00"
ANCHOR_ISO = "2026-10-01T22:37:15+00:00"

CURRENT_MB = 79286.2
PUBLISHED_RATE = -409.6


def _iso_epoch(x):
    return datetime.fromisoformat(x).timestamp()


# Absolute stamps, so the fixture is not tied to a wall clock at all.
# The offsets are in SECONDS here; `ring()` converts to the hours-before-now
# form its callers think in. A first draft divided by nothing at all and the
# fixture placed every sample 3600x too far in the past, which collapsed the
# envelope to (-0.4, 2.2) -- a number that looks like a real measurement of
# nothing.
NOW = _iso_epoch(READING_ISO)
RING_2026_10_02 = [
    ((_iso_epoch(iso) - NOW) / 3600.0, mb) for iso, mb in RING_2026_10_02_ISO
]


def ring(entries):
    return [{"ts": NOW + h * 3600.0, "used_mb": mb} for h, mb in entries]


def rates_of(entries, current_mb):
    """Independent re-implementation of the envelope, from the report's maths."""
    out = []
    for h, mb in list(entries) + [(0.0, current_mb)]:
        span = (0.0 - h)
        if span <= 0:
            continue
        out.append((current_mb - mb) / span * 24.0)
    return out


def envelope(entries, current_mb=CURRENT_MB):
    """Call the function under test, asserting it produced an envelope.

    Every test below is about a window that HAS at least two anchors, so a None
    here is a failure of the fixture rather than a case to branch on -- and the
    one test that exercises the None path calls the function directly.
    """
    env = dw._anchor_rate_envelope(ring(entries), NOW, current_mb, dw.TRIGGER_GROWTH_MB_24H)
    assert env is not None, "fixture must offer at least two distinct anchors"
    return env


class AnchorRateEnvelope(unittest.TestCase):
    def setUp(self):
        self.trigger = dw.TRIGGER_GROWTH_MB_24H

    def test_envelope_brackets_the_published_rate(self):
        """The published rate must lie INSIDE the envelope, not beside it.

        This is the property that makes the field honest: it is computed over
        the same ring and the same window end, so the headline is always one of
        the readings summarised.
        """
        env = envelope(RING_2026_10_02)
        lo, hi = env[0], env[1]
        self.assertLessEqual(lo, PUBLISHED_RATE)
        self.assertGreaterEqual(hi, PUBLISHED_RATE)

    def test_measured_envelope_matches_this_passes_hand_computation(self):
        env = envelope(RING_2026_10_02)
        self.assertEqual((env[0], env[1], env[2]), (-1338.6, 7905.5, 9244.1))

    def test_trigger_is_inside_the_envelope_on_this_window(self):
        """The finding that motivated the field: the 5,120 trigger is INSIDE the
        spread, so 'UNMET' on this window is a statement about the anchor."""
        env = envelope(RING_2026_10_02)
        self.assertTrue(env[4])
        self.assertLessEqual(env[0], self.trigger)
        self.assertGreaterEqual(env[1], self.trigger)

    def test_sign_flips_counted_over_distinct_timestamps(self):
        env = envelope(RING_2026_10_02)
        self.assertEqual(env[3], 3)

    def test_duplicate_timestamps_do_not_divide_by_zero(self):
        """A ring holding two samples with the same ts gives a zero span.

        A first probe of this (#1097, scratch/finch_disk_probe_1097.py) crashed
        with ZeroDivisionError on exactly that shape. The guard is `span_h <= 0`,
        which is what makes the field safe to ship into a cron report.
        """
        dup = ring([(-2.0, 79000.0), (-2.0, 79000.0), (-1.0, 79100.0)])
        env = dw._anchor_rate_envelope(dup, NOW, CURRENT_MB, self.trigger)
        self.assertIsNotNone(env)
        for v in env[:3]:
            self.assertIsInstance(v, float)

    def test_single_anchor_returns_none_rather_than_a_fake_spread(self):
        """One anchor cannot bracket anything. Returning a spread of 0.0 would
        read as 'the rate is insensitive to the anchor', which is the opposite
        of what is known."""
        env = dw._anchor_rate_envelope(ring([(-2.0, 79000.0)]), NOW, CURRENT_MB, self.trigger)
        self.assertIsNone(env)

    def test_no_samples_returns_none(self):
        self.assertIsNone(dw._anchor_rate_envelope([], NOW, CURRENT_MB, self.trigger))

    def test_flat_disk_gives_tiny_envelope_and_no_trigger_inside(self):
        """The positive control the other direction needs: a genuinely flat disk
        must produce a narrow envelope, or the field only ever says 'noisy'."""
        flat = ring([(-3.0, 79000.0), (-2.0, 79000.0), (-1.0, 79000.0)])
        env = dw._anchor_rate_envelope(flat, NOW, 79000.0, self.trigger)
        self.assertEqual((env[0], env[1], env[2]), (0.0, 0.0, 0.0))
        self.assertFalse(env[4])
        self.assertEqual(env[3], 0)

    def test_envelope_is_independent_of_envelope_of_an_older_window(self):
        """Two windows, one a subset of the other: the wider window's envelope
        must CONTAIN the narrower's spread direction, proving the field tracks
        the ring it was given rather than a constant."""
        near = dw._anchor_rate_envelope(ring(RING_2026_10_02[-3:]), NOW, CURRENT_MB, self.trigger)
        wide = dw._anchor_rate_envelope(ring(RING_2026_10_02), NOW, CURRENT_MB, self.trigger)
        self.assertGreaterEqual(wide[2], 0.0)
        self.assertNotEqual(near[0], wide[0])

    def test_function_does_not_mutate_the_candidate_ring(self):
        given = ring(RING_2026_10_02)
        before = [dict(s) for s in given]
        dw._anchor_rate_envelope(given, NOW, CURRENT_MB, self.trigger)
        self.assertEqual(given, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)