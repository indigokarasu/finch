"""Test the two LIVE shapes scan #983 recorded, and the anti-inversion case.

The point of (1) and (2) together: a fix that makes the guard flag everything
is not a fix, and a fix that makes it flag nothing is the defect itself. Both
must hold.

Run:  python3 test_finch_ledger_guard_parse.py
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
    "flg", os.path.join(HERE, "finch_ledger_guard.py"))
flg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flg)

UTC = datetime.timezone.utc
RESULTS = []


def record(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print("%-4s %-46s %s" % ("PASS" if ok else "FAIL", name, detail))


# --- direction 1: the two live shapes must be CAUGHT ------------------------
# The offset case is chosen for the FALSE NEGATIVE, not merely for being
# forward. With a -07:00 stamp the true instant is 7h LATER than the truncated
# one, so a stamp whose truncated reading is BACKWARD of the mtime can have a
# true instant that is FORWARD. That is the direction the old parser got wrong
# in the safe direction (it reported clean). A fixture using a stamp that stays
# forward either way would pass before AND after the fix and prove nothing.
OFFSET_SHAPE = "2026-09-27T21:00:00-07:00"   # true 2026-09-28T04:00:00Z (+2571s)
                                               # truncated 21:00:00Z (-22411s)
NESTED_SHAPE = "2026-09-28T03:20:00Z"          # +169s
MTIME = datetime.datetime(2026, 9, 28, 3, 17, 11, tzinfo=UTC)

bad = {"as_of": MTIME.isoformat().replace("+00:00", "Z"),
       "last_scan_at": OFFSET_SHAPE,
       "last_scan_at": None}
del bad["last_scan_at"]

doc = {
    "as_of": "2026-09-28T03:00:00Z",          # clean, backward
    "last_scan_at": OFFSET_SHAPE,             # forward once offset is honoured
    "last_work_at": "2026-09-28T03:00:00Z",   # clean, backward
    "last_scan": {"at": NESTED_SHAPE, "scan_number": 983, "closed": 0},
    "tasks": [],
}

with tempfile.TemporaryDirectory() as td:
    lp = os.path.join(td, "task-list.json")
    with open(lp, "w") as fh:
        json.dump(doc, fh)
    os.utime(lp, (MTIME.timestamp(), MTIME.timestamp()))
    rep = flg.check(lp, journal_dir=os.path.join(td, "nojournals"))

# Both the offset-bearing and the nested stamp must be forward.
fields = {(h["field"]): h["forward"] for h in rep["header"]}
record("offset_form_is_caught",
       fields.get("last_scan_at") is True,
       "last_scan_at=%r forward=%r delta=%s (pre-fix delta was -22411.0)"
       % (OFFSET_SHAPE, fields.get("last_scan_at"),
          next((h["delta_s"] for h in rep["header"]
                if h["field"] == "last_scan_at"), "n/a")))

nested_hits = [h for h in rep["header"] if h["field"].startswith("last_scan.")]
record("nested_field_is_caught",
       len(nested_hits) == 1 and nested_hits[0]["forward"] is True,
       "nested hit=%r" % (nested_hits,))

record("forward_count_is_two",
       rep["forward_count"] == 2,
       "forward_count=%r (expected 2)" % (rep["forward_count"],))

# The parser must agree with the true instant, not the truncated one.
parsed = flg._parse(OFFSET_SHAPE)
true_inst = datetime.datetime.fromisoformat(OFFSET_SHAPE)
record("parse_is_offset_aware",
       parsed == true_inst.astimezone(UTC),
       "_parse(%r) -> %s ; true instant %s"
       % (OFFSET_SHAPE, parsed.isoformat() if parsed else None,
          true_inst.astimezone(UTC).isoformat()))


# --- direction 2: a genuinely clean ledger must stay clean -----------------
clean = {
    "as_of": "2026-09-28T03:00:00Z",
    "last_scan_at": "2026-09-28T02:00:00-07:00",   # = 09:00Z ... see below
    "last_work_at": "2026-09-28T03:00:00Z",
    "last_scan": {"at": "2026-09-28T03:00:00Z"},
    "tasks": [{"id": "t1", "created_at": "2026-09-01T00:00:00Z",
               "updated_at": "2026-09-28T02:00:00Z",
               "last_finch_review": "2026-09-28T02:30:00Z (finch:scan #980)"}],
}
# 02:00 local (-07:00) = 09:00Z would be forward; use 2026-09-27T20:00 local
# instead, which is 2026-09-28T03:00Z -- just backward of the 03:17 mtime.
clean["last_scan_at"] = "2026-09-27T20:00:00-07:00"

with tempfile.TemporaryDirectory() as td:
    lp = os.path.join(td, "task-list.json")
    with open(lp, "w") as fh:
        json.dump(clean, fh)
    os.utime(lp, (MTIME.timestamp(), MTIME.timestamp()))
    rep2 = flg.check(lp, journal_dir=os.path.join(td, "nojournals"))

record("clean_ledger_stays_clean",
       rep2["forward_count"] == 0,
       "forward_count=%r header=%r"
       % (rep2["forward_count"],
          [(h["field"], h["delta_s"], h["forward"]) for h in rep2["header"]]))

# --- direction 3: a backward nested stamp is not a violation ---------------
back = dict(clean)
back["last_scan"] = {"at": "2026-09-28T01:00:00Z"}
with tempfile.TemporaryDirectory() as td:
    lp = os.path.join(td, "task-list.json")
    with open(lp, "w") as fh:
        json.dump(back, fh)
    os.utime(lp, (MTIME.timestamp(), MTIME.timestamp()))
    rep3 = flg.check(lp, journal_dir=os.path.join(td, "nojournals"))
record("backward_nested_not_flagged",
       rep3["forward_count"] == 0,
       "forward_count=%r" % (rep3["forward_count"],))

# --- direction 4: naive stamps still parse (no regression) -----------------
record("naive_stamp_still_parses",
       flg._parse("2026-09-28T03:00:00") == datetime.datetime(
           2026, 9, 28, 3, 0, 0, tzinfo=UTC),
       "_parse('2026-09-28T03:00:00') -> %s"
       % (flg._parse("2026-09-28T03:00:00"),))
record("z_suffix_accepted",
       flg._parse("2026-09-28T03:00:00Z") == datetime.datetime(
           2026, 9, 28, 3, 0, 0, tzinfo=UTC),
       "_parse('2026-09-28T03:00:00Z') -> %s"
       % (flg._parse("2026-09-28T03:00:00Z"),))
record("junk_returns_none",
       flg._parse("not-a-time") is None and flg._parse(None) is None
       and flg._parse(12345) is None,
       "junk inputs return None")

failed = [r for r in RESULTS if not r[1]]
print("\n%d/%d directions behaved as required."
      % (len(RESULTS) - len(failed), len(RESULTS)))
sys.exit(1 if failed else 0)
