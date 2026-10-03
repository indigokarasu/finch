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

# ── FIXTURE WINDOW, NOT A CLOCK ─────────────────────────────────────────────
# The 72h window this suite was written against has EMPTIED: the newest real
# block on disk (a91fa1c8214e, 09-29 07:05) fell out of 72h on the morning of
# 2026-10-03, so a hardcoded window contained zero rows and both non-vacuity
# floors failed -- the suite reported 1/3 PASS against a real store that had
# simply aged. That is the same class as the watcher's own bug: an assertion
# keyed on a window whose contents are pruned.
#
# So the window is chosen by OBSERVED evidence, not by the calendar. This is
# NOT "widen until green": MIN_ROWS below is a floor, and if no width can meet
# it the suite FAILS loudly rather than passing on a thin fixture.
MIN_ROWS = 3
_needed, _res = None, None
for _h in (72, 168, 336, 720, 2000, 8000):
    _res, out_root = sweep(_h)
    if _res is None:
        print("NOT MEASURED: evidence dir absent (%s)" % out_root)
        sys.exit(2)
    if len(_res["rows"]) >= MIN_ROWS:
        _needed = _h
        break
if _needed is None:
    print("FAIL  no window up to 8000h contains %d rows -- the DECAY fixture "
          "is gone; this suite can no longer prove anything" % MIN_ROWS)
    sys.exit(1)
res, out_root = sweep(_needed)
rows = res["rows"]
reg, _ = _registry()
annotate_registry(rows, reg)
by_id = {r["job_id"]: r for r in rows}
print("fixture window=%dh rows=%d live=%d cleared=%d"
      % (_needed, len(rows),
         sum(1 for r in rows if r["live"]),
         sum(1 for r in rows if not r["live"])))

# 0. Non-vacuity of the FIXTURE, not of the calendar. A suite that can pass on
#    a window with no decay in it is a suite that cannot fail.
check("fixture contains at least %d rows" % MIN_ROWS,
      len(rows) >= MIN_ROWS, True)
check("fixture contains at least one CLEARED row (decay is observable)",
      any(not r["live"] for r in rows), True)

# 1. Invariant: a row is live exactly when its newest block is its newest run.
check("live == (newest_block == newest_run) for every row",
      all(r["live"] == (r["newest_block"] == r["newest_run"]) for r in rows), True)

# 2. Real cleared job: EHCS blocked 09-27, ran clean 09-29. Its newest run is
#    the clean one, so the block must be reported as history, not state. This is
#    the CLEARED half of the classifier, borrowed from real evidence; if it ages
#    out the row is skipped, never silently inverted.
ehcs = by_id.get("dfd7f742d4f2")
if ehcs is None:
    print("SKIP  EHCS row absent from the %dh window" % _needed)
else:
    check("EHCS: block in window is NOT live", ehcs["live"], False)
    check("  ...the block is still recorded, not dropped",
          "2026-09-27_03-07-20.md" in ehcs["runs"], True)
    check("  ...a cleared row is never a registry contradiction",
          ehcs["registry_contradiction"], False)

# 3. The LIVE half, and the gz half, on BUILT fixtures.
#
#    Both used to be borrowed from real jobs, and both rotted for the same
#    reason: a fixture pinned to a specific job's history dies the moment that
#    history moves. sands:evening-brief's 09-29 block has since been superseded
#    by a later real run, so `live == True` became false there through no fault
#    of the code. Pinning a live assertion to real evidence means the suite
#    cannot outlive the event it witnessed.
#
#    So these are built. The shape mirrors the real writer
#    (cron/jobs.py::save_job_output): a block file has no '## Prompt'/'##
#    Response' and carries the status line in its header; a success file has
#    both. The clock is not stubbed -- fixture timestamps are derived from the
#    real now, so this cannot expire the way a hardcoded date does.
import gzip
import shutil
import tempfile
import time as _time

from finch_blocked_config_watch import (  # noqa: E402
    _preflight_block, evidence_coverage)

BLOCK_FILE = """# Cron Run

**Status:** BLOCKED (configuration)
**Reason:** attached skill 'ocas-dispatch' is not ready: missing env GATEWAY_TOKEN

No prompt was sent: preflight refused.
"""
SUCCESS_FILE = """# Cron Run

**Status:** ok

## Prompt

do the thing

## Response

did the thing
"""


def _stamp(offset_s):
    return _time.strftime("%Y-%m-%d_%H-%M-%S",
                          _time.localtime(_time.time() - offset_s))


def _iso_offset(offset_s):
    """An ISO-8601 timestamp `offset_s` in the past, as jobs.json spells it.

    Built with the SAME parser the watcher uses on real registry records. A
    float epoch would silently fall through the `fromisoformat` guard and be
    treated as 'age unknown', which is the safe direction but would make every
    coverage assertion here pass for the wrong reason.
    """
    import datetime as _dt
    return _dt.datetime.fromtimestamp(
        _time.time() + offset_s).astimezone().isoformat()


def _write_run(job_dir, offset_s, body, gz=False):
    os.makedirs(job_dir, exist_ok=True)
    name = _stamp(offset_s)
    path = os.path.join(job_dir, name + (".md.gz" if gz else ".md"))
    if gz:
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(body)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
    return name


# Live: the block is the job's NEWEST run.
td_live = tempfile.mkdtemp()
try:
    jl = os.path.join(td_live, "deadbeefdead")
    _write_run(jl, 3600, BLOCK_FILE)      # older block
    live_run = _write_run(jl, 60, BLOCK_FILE)   # newest run IS a block
    r_live, _ = sweep(24, td_live)
    live_rows = {r["job_id"]: r for r in (r_live["rows"] if r_live else [])}
    check("fixture: newest run IS a block -> live",
          live_rows.get("deadbeefdead", {}).get("live"), True)
    check("fixture: the newest run is the block file, not the older one",
          live_rows.get("deadbeefdead", {}).get("newest_run"), live_run + ".md")

    # A second job in the same tree with DEEP history: its oldest run is 30h
    # old, so it reaches back past a 24h window and must NOT be reported as
    # blind. deadbeefdead is its opposite -- 1h of evidence for a job that
    # predates the window, which is exactly the blind case.
    _deep = os.path.join(td_live, "aaaabbbbcccc")
    _write_run(_deep, 30 * 3600, BLOCK_FILE)
    _write_run(_deep, 3600, BLOCK_FILE)

    # A registry saying BOTH jobs are older than the window, so the only thing
    # separating them is evidence depth. ISO form, matching jobs.json.
    _reg_old = {
        "deadbeefdead": {"created_at": _iso_offset(-200 * 3600)},
        "aaaabbbbcccc": {"created_at": _iso_offset(-200 * 3600)},
    }
    _cov_rows, _cov_shallow = evidence_coverage(td_live, 24, registry=_reg_old)
    _pruned = {r["job_id"]: r["pruned"] for r in _cov_rows}
    _depths = {r["job_id"]: r["depth_hours"] for r in _cov_rows}
    check("coverage: a job whose evidence reaches past the window is NOT blind",
          _pruned.get("aaaabbbbcccc"), False)
    check("coverage: an older job whose evidence is shallower IS blind",
          _pruned.get("deadbeefdead"), True)
    check("coverage: the deep/shallow split is a real depth difference",
          _depths.get("aaaabbbbcccc", 0) > _depths.get("deadbeefdead", 0), True)
    check("coverage: the shallow count matches the per-job flags",
          _cov_shallow, sum(1 for v in _pruned.values() if v))

    _cov2_rows, _cov2_shallow = evidence_coverage(td_live, 999999,
                                                   registry=_reg_old)
    check("coverage: an absurdly wide window counts BOTH jobs blind",
          _cov2_shallow >= 2, True)

    # A NEW job is not a blind window. A daily job created an hour ago has a
    # one-hour history because that is all the time there has been; calling that
    # pruned evidence would be the loud-direction false positive this watcher
    # exists to avoid.
    _cov_new_rows, _cov_new = evidence_coverage(
        td_live, 24,
        registry={"deadbeefdead": {"created_at": _iso_offset(-3600)}})
    _cov_old_rows, _cov_old = evidence_coverage(
        td_live, 24,
        registry={"deadbeefdead": {"created_at": _iso_offset(-200 * 3600)}})
    check("coverage: a job created INSIDE the window is NOT counted as blind",
          {r["job_id"]: r["pruned"] for r in _cov_new_rows}.get("deadbeefdead"),
          False)
    check("coverage: the same job IS counted when it predates the window",
          {r["job_id"]: r["pruned"] for r in _cov_old_rows}.get("deadbeefdead"),
          True)
    check("coverage: the two registry snapshots disagree, so this can fail",
          _cov_new != _cov_old, True)
finally:
    shutil.rmtree(td_live, ignore_errors=True)

check("fixture: a SUCCESS file is not classified as a block",
      _preflight_block(SUCCESS_FILE), False)
check("fixture: a BLOCK file is classified as a block",
      _preflight_block(BLOCK_FILE), True)

# Cleared: a success file is newer than the block.
with tempfile.TemporaryDirectory() as td_clr:
    jc = os.path.join(td_clr, "c0ffee00c0ffee")
    _write_run(jc, 3600, BLOCK_FILE)
    _write_run(jc, 60, SUCCESS_FILE)
    r_clr, _ = sweep(24, td_clr)
clr_rows = {r["job_id"]: r for r in (r_clr["rows"] if r_clr else [])}
check("fixture: a later success CLEARS the block",
      clr_rows.get("c0ffee00c0ffee", {}).get("live"), False)

# gz-only: the block survives ONLY compressed -- the leg the old *.md glob
# dropped. Borrowing a real gz block would rot like direction 3 did. The job id
# is a plain placeholder rather than realistic hex: a hex-shaped string reads as
# a Gmail/message thread id to the PII gate and would ship a registry id in a
# public repo. The suffix length is what the fixture needs, not the flavour.
with tempfile.TemporaryDirectory() as td_gz:
    jg = os.path.join(td_gz, "gzblock01")
    _write_run(jg, 120, BLOCK_FILE, gz=True)
    r_gz, _ = sweep(24, td_gz)
gz_rows = {r["job_id"]: r for r in (r_gz["rows"] if r_gz else [])}
check("fixture: a block surviving ONLY as .md.gz is still found",
      gz_rows.get("gzblock01", {}).get("live"), True)

# Anti-vacuity: the classifier is exercised in BOTH directions on built
# fixtures, so a constant-True or constant-False `live` cannot pass.
check("built fixtures cover BOTH live and cleared (non-vacuous)",
      live_rows.get("deadbeefdead", {}).get("live") is True
      and clr_rows.get("c0ffee00c0ffee", {}).get("live") is False, True)
check("built fixtures cover BOTH .md and .md.gz",
      live_rows.get("deadbeefdead") is not None
      and gz_rows.get("gzblock01") is not None, True)

n = len(results)
p = sum(1 for r in results if r)
print("\n%d/%d directions PASS" % (p, n))
sys.exit(0 if p == n else 1)
