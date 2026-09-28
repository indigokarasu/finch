"""Prove repair() can CLEAR a stamp that check() can SEE.

An instrument that detects but cannot repair is half a fix: --repair would
report 'nothing to do' on a ledger the guard just called dirty, which is the
same safe-direction false negative one layer down. Both nested and offset
shapes are exercised, on a copy, and the file is never the live ledger.
"""
import datetime
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "flg", os.path.join(HERE, "finch_ledger_guard.py"))
flg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flg)

UTC = datetime.timezone.utc
MTIME = datetime.datetime(2026, 9, 28, 3, 17, 11, tzinfo=UTC)
RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok))
    print("%-4s %-44s %s" % ("PASS" if ok else "FAIL", name, detail))


def roundtrip(doc, label, expect_clean_after):
    with tempfile.TemporaryDirectory() as td:
        lp = os.path.join(td, "task-list.json")
        with open(lp, "w") as fh:
            json.dump(doc, fh)
        os.utime(lp, (MTIME.timestamp(), MTIME.timestamp()))
        rep = flg.check(lp, journal_dir=os.path.join(td, "nojournals"))
        seen = rep["forward_count"]
        changes, out = flg.repair(lp)
        if not changes:
            rep2 = flg.check(lp, journal_dir=os.path.join(td, "nojournals"))
            record(label, (expect_clean_after and rep2["forward_count"] == 0)
                   or (not expect_clean_after and seen == 0),
                   "seen=%d changes=0 (no-op) after=%d"
                   % (seen, rep2["forward_count"]))
            return
        with open(lp, "w") as fh:
            json.dump(out, fh, indent=2)
        os.utime(lp, (MTIME.timestamp(), MTIME.timestamp()))
        rep2 = flg.check(lp, journal_dir=os.path.join(td, "nojournals"))
        record(label, seen > 0 and rep2["forward_count"] == 0,
               "seen=%d clamped=%d fields=%s after=%d"
               % (seen, len(changes), [c["field"] for c in changes],
                  rep2["forward_count"]))


# nested stamp: check() must see it AND repair() must clear it
roundtrip({"as_of": "2026-09-28T03:00:00Z",
           "last_scan": {"at": "2026-09-28T03:20:00Z", "scan_number": 983},
           "tasks": []},
          "nested_stamp_detected_and_repaired", True)

# offset stamp
roundtrip({"as_of": "2026-09-28T03:00:00Z",
           "last_scan_at": "2026-09-27T21:00:00-07:00",
           "tasks": []},
          "offset_stamp_detected_and_repaired", True)

# both at once
roundtrip({"as_of": "2026-09-28T03:00:00Z",
           "last_scan_at": "2026-09-27T21:00:00-07:00",
           "last_scan": {"at": "2026-09-28T03:20:00Z"},
           "tasks": []},
          "both_shapes_detected_and_repaired", True)

# a clean ledger must be a no-op for repair
roundtrip({"as_of": "2026-09-28T03:00:00Z",
           "last_scan_at": "2026-09-28T02:00:00Z",
           "last_scan": {"at": "2026-09-28T02:30:00Z"},
           "tasks": [{"id": "t", "updated_at": "2026-09-28T01:00:00Z"}]},
          "clean_ledger_repair_is_noop", False)

# a task-level forward stamp still clamps (regression guard)
roundtrip({"as_of": "2026-09-28T03:00:00Z", "tasks": [
    {"id": "t", "updated_at": "2026-09-28T04:00:00Z",
     "last_finch_review": "2026-09-28T04:00:00Z (finch:scan #990)"}]},
    "task_stamp_still_clamped", True)

# a due_date that is genuinely in the future must NOT be clamped
roundtrip({"as_of": "2026-09-28T03:00:00Z", "tasks": [
    {"id": "t", "due_date": "2026-09-30T10:00:00Z"}]},
    "future_due_date_untouched", False)

failed = sum(1 for _, ok in RESULTS if not ok)
print("\n%d/%d repair directions behaved as required."
      % (len(RESULTS) - failed, len(RESULTS)))
sys.exit(1 if failed else 0)
