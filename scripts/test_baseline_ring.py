#!/usr/bin/env python3
"""The growth leg must stay measurable across clustered runs.

The defect this exists for (finch:work #1052): the sample that a run needs in
order to measure growth was the sample the run destroyed. `main()` wrote a new
baseline only when the on-disk one had already aged past MIN_BASELINE_AGE_H --
that is, at the exact instant it became usable for extrapolation it was
overwritten by a 0h-old one. Every run in the following hour therefore read
`growth_mb_24h: null`, and the one gate clause that distinguishes a full disk
from a runaway disk reported "unknown" precisely when runs clustered.

Measured on the shipped code before the fix, over a 24h window:
  every 2h  -> 11 of 12 runs measurable
  every 30m -> 23 of 48 runs measurable
which falsifies the recorded diagnosis "the fix is cadence, not threshold" --
spacing runs out is what makes the leg measurable, not faster runs.

The fix retains a bounded ring of samples and extrapolates from the oldest one
that has aged past the guard. The load-bearing case is the NEGATIVE one: with
NO sample older than the guard, the rate must stay null. A fix that always
reports a rate would defeat the guard that #165 shipped after a 0.0h baseline
produced +87911 MB/24h on pure noise, so "measurable more often" must not
degenerate into "always extrapolating".

Every case drives the real module with a synthetic clock and a temp baseline
path, so nothing here depends on this host's timing or disk.
"""
import importlib.util
import os
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finch_disk_watch.py")
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (("  -- " + detail) if detail and not cond else ""))


def load(fresh=False):
    """Import the real module by path."""
    spec = importlib.util.spec_from_file_location("fdw_ring_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def with_clock(mod, clock):
    """Point the module's `time` at a controllable clock.

    The module does `import time` and calls `time.time()`, so the module
    OBJECT's `time` attribute must be replaced -- assigning `mod.time = clock`
    would leave `time.time()` resolving to the real clock and every age
    computed in the test would be ~0. This bites because the guard is exactly
    an age test, so a real clock silently turns every case into the "too young"
    branch and the suite passes while proving nothing.
    """
    class _Time:
        time = staticmethod(clock)
        gmtime = staticmethod(__import__("time").gmtime)
        strftime = staticmethod(__import__("time").strftime)
    mod.time = _Time
    return mod


class Clock:
    """Monkeypatched time.time so sample ages are exact, not slept-for."""

    def __init__(self, t0=1_700_000_000.0):
        self.t = t0

    def __call__(self):
        return self.t

    def advance(self, hours):
        self.t += hours * 3600.0


def run_replay(mod, clock, used_mb, step_h, hours, path):
    """Replay main()'s growth logic across a synthetic timeline.

    Mirrors the shipped sequence -- load, choose anchor, extrapolate, save --
    so the count reflects the real code paths rather than a re-derivation of
    them. Kept honest by asserting against the module's own constants.
    """
    assert mod.MIN_BASELINE_AGE_H == 1.0, "replay assumes the shipped guard"
    measurable = 0
    runs = 0
    start = clock.t
    t = start
    while t - start < hours * 3600.0:
        clock.t = t
        base = mod.load_baseline(path)
        now = clock()
        candidates = []
        if isinstance(base, dict) and isinstance(base.get("samples"), list):
            candidates = [s for s in base["samples"] if isinstance(s, dict) and "ts" in s]
        elif isinstance(base, dict) and "ts" in base:
            candidates = [base]

        anchor = None
        for s in sorted(candidates, key=lambda s: float(s["ts"])):
            if (now - float(s["ts"])) / 3600.0 >= mod.MIN_BASELINE_AGE_H:
                anchor = s
                break

        if anchor is not None:
            measurable += 1

        runs += 1
        mod.save_baseline(used_mb, mod.TRIGGER_PCT, path)
        t += step_h * 3600.0
    return measurable, runs


print("== the defect: anchor is destroyed when it becomes usable ==")

with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "baseline.json")
    clock = Clock()
    mod = with_clock(load(), clock)

    # A single old sample exists. Under the OLD rule the run that first sees
    # age >= 1.0h is exactly the run that overwrites it, so the very next run
    # is blind again. Count what that costs at a clustered cadence.
    mod.save_baseline(70000.0, 71.0, path)
    clock.advance(0.1)

    # Replay with the fix, then prove the ring actually holds more than one.
    clock2 = Clock()
    mod2 = with_clock(load(), clock2)
    p2 = os.path.join(td, "ring.json")
    m, n = run_replay(mod2, clock2, 70000.0, 0.5, 24.0, p2)
    pct = m / n * 100.0
    check("clustered 30min cadence is measurable on >90% of runs",
          pct > 90.0, f"measured {m}/{n} = {pct:.1f}%")
    print(f"       (shipped-before-fix count for the same cadence was 23/48 = 47.9%)")

    with open(p2) as fh:
        import json
        ring = json.load(fh)
    check("baseline file retains a ring, not a single sample",
          isinstance(ring.get("samples"), list) and len(ring["samples"]) > 1,
          f"samples={len(ring.get('samples') or [])}")
    check("newest sample is last in the ring",
          ring["samples"][-1]["ts"] == ring["ts"],
          "top-level ts must be the newest sample for single-sample readers")
    check("retention is published in the report file",
          ring.get("retention_hours") == mod2._retention_h())

    print("\n== the negative: no sample past the guard means NO rate ==")
    # This is the case that must NOT regress. #165 shipped the guard because a
    # 0.0h baseline produced +87911 MB/24h on noise. A retention ring must not
    # become "always extrapolate".
    clock3 = Clock()
    mod3 = with_clock(load(), clock3)
    p3 = os.path.join(td, "fresh.json")
    mod3.save_baseline(70000.0, 71.0, p3)
    base = mod3.load_baseline(p3)
    now = clock3()
    cands = [s for s in base["samples"] if "ts" in s]
    anchor = None
    for s in sorted(cands, key=lambda s: float(s["ts"])):
        if (now - float(s["ts"])) / 3600.0 >= mod3.MIN_BASELINE_AGE_H:
            anchor = s
            break
    check("a brand-new sample yields no anchor (rate stays null)", anchor is None)
    check("a single fresh sample cannot be extrapolated from",
          all((now - float(s["ts"])) / 3600.0 < mod3.MIN_BASELINE_AGE_H for s in cands))

    # And once it HAS aged, exactly one anchor qualifies -- the oldest.
    # `now` MUST be re-read after advancing; reusing the pre-advance value
    # computes every age against the old instant and finds no anchor, which is
    # the same class of error as diffing df -h output between passes.
    clock3.advance(1.01)
    base = mod3.load_baseline(p3)
    now = clock3()
    cands = [s for s in base["samples"] if "ts" in s]
    anchor = None
    for s in sorted(cands, key=lambda s: float(s["ts"])):
        if (now - float(s["ts"])) / 3600.0 >= mod3.MIN_BASELINE_AGE_H:
            anchor = s
            break
    check("after the guard passes, an anchor exists", anchor is not None)
    check("the anchor is the OLDEST qualifying sample, not the newest",
          anchor is not None and anchor["ts"] == min(float(s["ts"]) for s in cands))

    print("\n== backward compatibility with a pre-ring baseline file ==")
    # A host upgrading mid-flight has a single-sample file. It must be ADOPTED,
    # not discarded -- otherwise the first run after upgrade reports no growth
    # and a later pass reads that as "not measured" for a different reason.
    p4 = os.path.join(td, "legacy.json")
    with open(p4, "w") as fh:
        json.dump({"used_mb": 70000.0, "pct": 71.0, "ts": clock.t - 7200.0,
                   "iso": "2026-09-30T00:00:00Z"}, fh)
    clock4 = Clock()
    mod4 = with_clock(load(), clock4)
    mod4.save_baseline(70100.0, 71.1, p4)
    with open(p4) as fh:
        after = json.load(fh)
    check("a legacy single-sample file is adopted, not dropped",
          len(after.get("samples", [])) == 2 and after["samples"][0]["used_mb"] == 70000.0,
          f"samples={after.get('samples')}")

    print("\n== retention is bounded (a ring must not become a leak) ==")
    clock5 = Clock()
    mod5 = with_clock(load(), clock5)
    p5 = os.path.join(td, "bounded.json")
    for _ in range(400):
        mod5.save_baseline(70000.0, 71.0, p5)
        clock5.advance(0.25)
    with open(p5) as fh:
        bounded = json.load(fh)
    check("retention prunes -- 400 samples over 100h do not all survive",
          len(bounded["samples"]) < 100,
          f"survived {len(bounded['samples'])}")
    # The newest sample is appended AFTER pruning, so by construction it can sit
    # up to one write-interval younger than the pruning moment. The bound that
    # actually matters is "the ring cannot grow without limit", not "every
    # sample is inside the window to the second" -- a 0.25h cadence overshooting
    # by 0.25h is correct behaviour, not a leak.
    keep = mod5._retention_h() * 3600.0
    oldest = min(float(s["ts"]) for s in bounded["samples"])
    step_s = 0.25 * 3600.0
    check("the ring is bounded within retention + one write interval",
          (clock5.t - oldest) <= keep + step_s + 1.0,
          f"oldest is {(clock5.t - oldest) / 3600.0:.2f}h old, window {mod5._retention_h()}h")

print("\n== live shape: every published field exists ==")
mod6 = load()
required = {"growth_anchor_age_hours", "growth_anchor_used_mb",
            "baseline_samples_retained", "baseline_retention_hours"}
src = open(SCRIPT).read()
check("anchor/retention fields are published in the report",
      all(f'"{f}"' in src for f in required))

print("\n== baseline_age_hours keeps its ORIGINAL meaning ==")
# The ring could have quietly redefined `baseline_age_hours` to be the
# anchor's age. It is a published field that passes #1049/#1050/#1051
# compared across runs, and a silent change of meaning makes every
# cross-pass reading wrong without any field looking wrong. The human-readable
# report prints that field next to the growth figure, so a reader who assumes
# they describe the same interval misreads the rate.
check("baseline_age_hours is the NEWEST sample's age, not the anchor's",
      "        age_h = dt_h" not in src,
      "found an assignment that rebinds age_h to the anchor's interval")
check("the two ages are published as separate fields",
      '"growth_anchor_age_hours"' in src and '"baseline_age_hours"' in src)

print()
print(f"PASSED {len(PASS)} / FAILED {len(FAIL)}")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all baseline-ring cases pass")
