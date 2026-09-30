#!/usr/bin/env python3
"""finch:work -- directions test for the blocked-config watcher's DECAY clause.

The defect: `sweep()` counted every job that EVER produced a preflight block
inside the window, so a block that a later run of the same job had cleared
stayed on the list as a live registry contradiction. That is the safe-direction
false negative this watcher's own verdict was supposed to rule out, and it is
what makes a closed task look open again on stale evidence.

Every direction below is built from REAL run files on disk, and each asserts
the OPPOSITE direction too, so a fixture cannot pass for a trivial reason. The
last direction is deliberately non-vacuous: it requires at least one CLEARED
row to exist, so if the decay check ever stops working the suite fails instead
of passing on an all-live window.

EXIT 0 all pass / 1 any fail.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ── --help guard ───────────────────────────────────────────────────────────
# BEFORE the dependency import, not after. This is a LIVE-fixture directions
# test whose only guide to its arguments is --help, so an unguarded --help
# would execute the real job and rewrite the very state it measures. Same class
# as the writer-order bug in finch_ledger_write.py, one layer up.
#
# The guard must also sit above the import because
# finch_blocked_config_watch is a HOST-LOCAL watcher: .gitignore:66 keeps
# scripts/*_watch.py unpublished, so on a CI runner that import raises
# ModuleNotFoundError and the whole --help contract breaks. Serving --help
# needs no dependency, so it is answered before anything is imported. This was
# the real defect behind runs 36681538632 / 36683617802 / 36684493294 (2026-09-30
# 07:03-07:34Z), where test_all_scripts_help failed on this file alone.
if any(a in ("-h", "--help", "help") for a in sys.argv[1:]):
    sys.stdout.write((__doc__ or "").strip() + "\n")
    sys.exit(0)

from finch_blocked_config_watch import sweep, annotate_registry, _registry  # noqa: E402

results = []


def check(name, got, want):
    ok = got == want
    results.append(ok)
    print("%-4s %-64s got=%-5s want=%-5s" % (
        "PASS" if ok else "FAIL", name, got, want))


res, out_root = sweep(72)
if res is None:
    print("NOT MEASURED: evidence dir absent (%s)" % out_root)
    sys.exit(2)
rows = res["rows"]
reg, _ = _registry()
annotate_registry(rows, reg)
by_id = {r["job_id"]: r for r in rows}

# 1. Invariant: a row is live exactly when its newest block is its newest run.
check("live == (newest_block == newest_run) for every row",
      all(r["live"] == (r["newest_block"] == r["newest_run"]) for r in rows), True)

# 2. Real cleared job: EHCS blocked 09-27, ran clean 09-29. Its newest run is
#    the clean one, so the block must be reported as history, not state.
ehcs = by_id.get("dfd7f742d4f2")
if ehcs is None:
    print("SKIP  EHCS row absent from the 72h window")
else:
    check("EHCS: block in window is NOT live", ehcs["live"], False)
    check("  ...newest run is the 09-29 clean run",
          ehcs["newest_run"], "2026-09-29_00-42-01.md")
    check("  ...the block is still recorded, not dropped",
          "2026-09-27_03-07-20.md" in ehcs["runs"], True)
    check("  ...a cleared row is never a registry contradiction",
          ehcs["registry_contradiction"], False)

# 3. Real live job: sands:evening-brief's newest run IS its 09-29 block.
ev = by_id.get("93fcd86467c5")
if ev is None:
    print("SKIP  sands:evening-brief row absent")
else:
    check("sands:evening-brief: newest run is the block", ev["live"], True)
    check("  ...newest run is the 09-29 03:52 block",
          ev["newest_run"], "2026-09-29_03-52-42.md")
    check("  ...registry agrees (blocked_config), so no contradiction",
          ev["registry_contradiction"], False)

# 4. Non-vacuity: the fixture must contain at least one of each, otherwise the
#    assertions above are testing a window with no decay in it.
check("window contains at least one CLEARED row",
      any(not r["live"] for r in rows), True)
check("window contains at least one LIVE row (a live defect exists)",
      any(r["live"] for r in rows), True)

n = len(results)
p = sum(1 for r in results if r)
print("\n%d/%d directions PASS" % (p, n))
sys.exit(0 if p == n else 1)
