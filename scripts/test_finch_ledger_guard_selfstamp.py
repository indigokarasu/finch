"""Journal self-stamp: the cause must be attributed, and 'historical' must go.

Measured 2026-09-28 (finch:work #232). The guard reports 27 journal
self-stamps forward and labels the set "(historical, not written by this
run)" in one flat clause. Both halves of that are wrong for the newest
member:

  * 2026-09-28/scan-0329.json is 1.2h old -- written 7 minutes before this
    pass began, with a started_at 411 minutes ahead of its own mtime. It is
    not historical, and a current writer is still producing them.
  * Its started_at is '2026-09-28T03:20:00-07:00'. Corroborated against a
    clock that never saw the journal (the guard's own append-only receipt,
    written by a different process): the run started at 03:20Z and committed
    at 03:28:58Z, i.e. it started BEFORE it committed. The digits are UTC and
    the '-07:00' TAG is wrong, so the +24661s is a parsing artefact. Reading
    the tag as written puts the start 7h after the commit, which cannot be.

3 of the 27 carry a local offset tag AND read back coherently as UTC
(scan-0329 -539s, scan-1000 -2233s, scan-1021 -3062s).

The attribution is a DISCRIMINATION, not a suppression. A mislabelled tag is
still a real defect -- every consumer of that stamp reads the wrong instant --
so the stamp stays in `self_stamp_forward` and stays in the count. Only the
cause changes, and only where the tag is a local offset. A stamp carrying Z
or +00:00 that is genuinely forward is a forward clock, and must never be
absorbed by the mislabel bucket: that would launder a real violation.

And the EXIT CODE does not move. Journal findings never changed it, and this
fix must not start.

Run:  python3 test_finch_ledger_guard_selfstamp.py
Exit 0 = all directions behaved as required; 1 = a direction failed.
"""
import datetime
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "flg2", os.path.join(HERE, "finch_ledger_guard.py"))
flg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flg)

UTC = datetime.timezone.utc
RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print("%-4s %-46s %s" % ("PASS" if ok else "FAIL", name, detail))


COMMIT = datetime.datetime(2026, 9, 28, 3, 28, 58, 906576, tzinfo=UTC)
NOW = datetime.datetime(2026, 9, 28, 4, 35, 0, tzinfo=UTC)


def _journals(specs, ledger_mtime, ledger=None):
    """Build a journal dir + ledger and return (ledger_path, report)."""
    td = tempfile.mkdtemp()
    jd = os.path.join(td, "journals")
    os.makedirs(jd)
    for name, doc in specs:
        p = os.path.join(jd, name)
        with open(p, "w") as fh:
            json.dump(doc, fh)
        os.utime(p, (ledger_mtime.timestamp(), ledger_mtime.timestamp()))
    lp = os.path.join(td, "task-list.json")
    with open(lp, "w") as fh:
        json.dump(ledger or {"as_of": "2026-09-28T03:00:00Z", "tasks": []}, fh)
    os.utime(lp, (ledger_mtime.timestamp(), ledger_mtime.timestamp()))
    return lp, jd, flg.check(lp, journal_dir=jd)


# --- direction 1: the LIVE shape, attributed to the mislabelled tag ---------
# started_at digits are UTC (03:20Z), the tag says -07:00. Read as written it
# is +24661s forward. The cause is the tag, not a clock.
_lp, _jd, rep = _journals(
    [("scan-0329.json", {"scan_number": 983, "started_at": "2026-09-28T03:20:00-07:00"})],
    COMMIT)
ss = rep["journals"]["self_stamp_forward"]
record("live_shape_is_caught", len(ss) == 1,
       "self_stamp_forward=%d" % len(ss))
record("live_shape_cause_is_tag",
       bool(ss) and ss[0].get("cause") == "offset-tag-mislabelled",
       "cause=%r tag=%r digits_as_utc_delta_s=%r age_h=%r"
       % (ss[0].get("cause") if ss else None,
          ss[0].get("offset_tag") if ss else None,
          ss[0].get("digits_as_utc_delta_s") if ss else None,
          ss[0].get("age_h") if ss else None))
record("live_shape_count_not_suppressed",
       rep["journals"]["self_stamp_forward_count"] == 1,
       "count=%r -- a mislabelled tag is a REAL defect and stays counted"
       % (rep["journals"]["self_stamp_forward_count"],))
record("cause_counts_reported",
       rep["journals"].get("self_stamp_cause_counts", {})
       == {"offset-tag-mislabelled": 1},
       "cause_counts=%r" % (rep["journals"].get("self_stamp_cause_counts"),))
record("recent_member_is_not_called_historical",
       rep["journals"].get("self_stamp_recent_count") == 1,
       "recent(<=24h)=%r" % (rep["journals"].get("self_stamp_recent_count"),))

# --- direction 2: ANTI-INVERSION, a genuinely forward clock ----------------
# A Z-tagged stamp that really is ahead of the commit. The digits read back
# as UTC exactly as written, so there is no mislabel to point at: this is a
# forward clock and must be reported as one.
_lp, _jd, rep2 = _journals(
    [("scan-9999.json", {"scan_number": 9999, "timestamp": "2026-09-28T09:00:00Z"})],
    COMMIT)
ss2 = rep2["journals"]["self_stamp_forward"]
record("genuine_forward_is_caught", len(ss2) == 1,
       "self_stamp_forward=%d" % len(ss2))
record("genuine_forward_cause_is_clock",
       bool(ss2) and ss2[0].get("cause") == "clock-forward",
       "cause=%r (must NOT be absorbed by the mislabel bucket)"
       % (ss2[0].get("cause") if ss2 else None,))

# --- direction 3: a real forward stamp with a local tag is NOT absorbed -----
# The guard is deliberately biased: a local tag only wins when the digits read
# back COHERENTLY as UTC, because that bucket is the one a reviewer reads as
# benign. So a stamp whose digits are incoherent either way must stay in
# clock-forward. '2026-09-28T09:00:00-07:00' against a 03:28:58Z commit reads
# 09:00Z as UTC (+329 min, forward) and 16:00Z as tagged (+750 min, forward):
# no reading places the start before the commit, so the tag cannot be the
# explanation and absorbing it would hide a live violation.
_lp, _jd, rep3 = _journals(
    [("scan-8888.json", {"scan_number": 8888,
                         "timestamp": "2026-09-28T09:00:00-07:00"})],
    COMMIT)
ss3 = rep3["journals"]["self_stamp_forward"]
record("incoherent_local_tag_stays_clock_forward",
       bool(ss3) and ss3[0].get("cause") == "clock-forward",
       "value=%r fwd=%smin digits_as_utc=%ss cause=%r -- a real forward stamp"
       " must not be absorbed into the mislabel bucket"
       % (ss3[0].get("value") if ss3 else None,
          ss3[0].get("delta_min") if ss3 else None,
          ss3[0].get("digits_as_utc_delta_s") if ss3 else None,
          ss3[0].get("cause") if ss3 else None))

# --- direction 4: a clean journal dir reports nothing at all ---------------
_lp, _jd, rep4 = _journals(
    [("scan-0001.json", {"scan_number": 1, "timestamp": "2026-09-28T03:00:00Z"})],
    COMMIT)
record("clean_journal_reports_nothing",
       rep4["journals"]["self_stamp_forward_count"] == 0
       and not rep4["journals"].get("self_stamp_cause_counts"),
       "count=%r causes=%r"
       % (rep4["journals"]["self_stamp_forward_count"],
          rep4["journals"].get("self_stamp_cause_counts")))

# --- direction 5: the EXIT CODE is unmoved in both directions --------------
# Journal findings have never touched it. Pin that this fix did not start.
import io
import contextlib


def _exit_code_for(journal_specs, mtime):
    lp, jd, _r = _journals(journal_specs, mtime)
    saved = sys.argv
    sys.argv = ["finch_ledger_guard.py", "--ledger", lp, "--journals", jd]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = flg.main()
    finally:
        sys.argv = saved
    return rc, buf.getvalue()


rc_clean, out_clean = _exit_code_for(
    [("scan-0001.json", {"scan_number": 1, "timestamp": "2026-09-28T03:00:00Z"})],
    COMMIT)
record("clean_still_exits_zero", rc_clean == 0,
       "exit=%r (a journal finding must not pin a clean ledger non-zero)" % rc_clean)

rc_viol, out_viol = _exit_code_for(
    [("scan-0329.json", {"scan_number": 983,
                         "started_at": "2026-09-28T03:20:00-07:00"})],
    COMMIT)
record("journal_finding_still_exits_zero", rc_viol == 0,
       "exit=%r -- journal findings are reported, never exit-coded" % rc_viol)
record("report_no_longer_says_flatly_historical",
       "historical, not written by this run" not in out_viol
       and "offset-tag-mislabelled" in out_viol,
       "the '(historical, not written by this run)' clause is gone from a"
       " report whose newest member is 1.2h old, and the cause is shown")

failed = [r for r in RESULTS if not r[1]]
print("\n%d/%d directions behaved as required."
      % (len(RESULTS) - len(failed), len(RESULTS)))
sys.exit(1 if failed else 0)
