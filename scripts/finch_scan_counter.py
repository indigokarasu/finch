#!/usr/bin/env python3
"""finch_scan_counter.py -- atomic scan-number allocator for the finch ledger.

WHY THIS EXISTS
---------------
`scan_number` is allocated ad-hoc, by whichever pass happens to write
`task-list.json` first. There is no choke point and no lock, so two runs that
overlap in wall-clock time read the SAME counter and both mint the same number.
That is not hypothetical: scans #174 (`scan-174.json`, mtime 01:04:28Z) and
`scan-2000.json` (mtime 03:15:19Z) BOTH carry `scan_number: 174`, while the
live ledger header is still stuck at 173. The duplicate reads as
"one scan happened twice" and silently breaks scan-ordering, exactly like the
forward-stamp defect this skill already guards.

So the counter has to stop being a field each pass edits by hand, and become
something allocated under a lock.

DESIGN
------
  * Authoritative floor is the MAXIMUM of every number anyone can see:
    the ledger header, every journal `scan_number`, and every scan number
    mentioned in journal prose (`run: finch:scan #N`). Taking the max of all
    three means a counter that has drifted behind reality -- the failure being
    repaired right now -- still cannot be reused.
  * The lock is an exclusive `flock` on a sidecar file, so allocation is atomic
    across concurrent cron passes. `flock` is released by the kernel if a pass
    dies mid-allocation; there is no stale-lockfile class of bug here.
  * The number is recorded in a durable `scan-counter.json` sidecar BEFORE the
    caller's ledger write. If the caller crashes after allocating, the number is
    burned rather than reused -- burning is the safe direction, reusing is the
    one that corrupts the series.

USAGE
-----
    python3 finch_scan_counter.py            # print the next number, allocate it
    python3 finch_scan_counter.py --peek     # print floor+1, allocate nothing
    python3 finch_scan_counter.py --json     # machine-readable
    python3 finch_scan_counter.py --floor    # report the evidence, allocate nothing

EXIT CODES
----------
    0  allocated (or peeked) successfully
    1  ledger unreadable -- NOT clean, must not be read as "no signal"
    2  could not take the lock (another pass holds it)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
from datetime import datetime, timezone

# Resolve the ledger and journals from this script's own location rather than
# hardcoding a host path -- same convention as finch_ledger_guard.py, and what
# the PII gate (check_no_pii.py) requires for a public repo.
# .../profiles/<name>/skills/<skill>/scripts/ -> walk up to the profile root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATE_DIRS = [
    os.path.join(_HERE, "..", "..", "..", "commons", "data", "ocas-finch"),
    os.path.join(_HERE, "..", "..", "..", "..", "commons", "data", "ocas-finch"),
]
_JOURNAL_DIRS = [
    os.path.join(_HERE, "..", "..", "..", "commons", "journals", "ocas-finch"),
    os.path.join(_HERE, "..", "..", "..", "..", "commons", "journals", "ocas-finch"),
]


def _resolve(dirs, fallback):
    for c in dirs:
        if os.path.isdir(c):
            return os.path.abspath(c)
    return fallback


HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
LEDGER = os.path.join(
    _resolve(_CANDIDATE_DIRS, os.path.join(HERMES_HOME, "commons", "data", "ocas-finch")),
    "task-list.json")
JOURNALS = _resolve(
    _JOURNAL_DIRS, os.path.join(HERMES_HOME, "commons", "journals", "ocas-finch"))
COUNTER = os.path.join(os.path.dirname(LEDGER), "scan-counter.json")
LOCK = COUNTER + ".lock"

PROSE_RE = re.compile(r"finch:scan\s*#\s*(\d{1,4})\b")
# The digit bound is deliberately loose: the series passed 176 on 2026-09-26, so
# a 2-digit anchor silently drops every number past 99 from the prose harvest,
# and the guard's copy of this pattern was itself bounded to 2-3 digits until
# 2026-09-27. Two different patterns over one corpus is two different answers
# to "which numbers exist" -- that disagreement is exactly how this allocator
# ended up blind to 26 numbers the guard could see (finch:work #200).
#
# These two patterns are duplicated literals, NOT a shared import, on purpose:
# importing the guard here would couple two tools that must each run alone and
# would add a silent fallback if the import failed -- a wrong pattern that
# nobody notices is worse than two literals that a test compares. So the
# coupling lives in the test instead: test_finch_scan_counter.py asserts this
# pattern is byte-identical to the guard's _PROSE_NUM_RE and that the
# allocator sees every number the guard sees. Drift fails the suite loudly.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _sidecar_path(ledger: str | None = None) -> str:
    """Path of the allocator sidecar for `ledger`, resolved AT CALL TIME.

    Same trap as `evidence()`'s paths: COUNTER is a module global bound once at
    import, so a caller (notably the test suite) that repoints LEDGER at a
    fixture still reads the REAL sidecar. That is a fixture silently
    inheriting live state -- measured 2026-09-27: the fixture floor cases began
    failing the moment this host's counter advanced to 953, having nothing to do
    with the fixtures themselves. Derive the sidecar from the ledger that is
    actually in play, so a redirected ledger gets a redirected sidecar.
    """
    led = LEDGER if ledger is None else ledger
    return os.path.join(os.path.dirname(led), "scan-counter.json")


def _sidecar_last_allocated(ledger: str | None = None) -> int | None:
    """Last number handed out, or None if no sidecar exists yet.

    The sidecar is part of the floor, NOT just a log. Without it, two passes
    that allocate in sequence both read the same ledger header and mint the
    same number -- which is the duplicate this script exists to prevent. The
    sidecar is written only under the lock, so reading it under the lock is
    race-free.
    """
    path = _sidecar_path(ledger)
    try:
        with open(path, "r") as fh:
            return _parse_int(json.load(fh).get("last_allocated"))
    except FileNotFoundError:
        return None
    except Exception:
        return None  # a corrupt sidecar must not block allocation; floor still holds


def evidence(ledger: str | None = None, journals: str | None = None) -> dict:
    """Collect every visible scan number. Never raises on journal noise.

    Paths resolve to the module globals AT CALL TIME, not as default
    arguments. Default arguments are bound once at import, so a test (or any
    caller) that repoints LEDGER/JOURNALS would silently be ignored and the
    real ledger read instead -- a coverage claim that is not a measurement,
    which is the exact failure class this skill keeps finding.
    """
    ledger = LEDGER if ledger is None else ledger
    journals = JOURNALS if journals is None else journals
    ev = {
        "ledger_scan_number": None,
        "ledger_readable": True,
        "journal_scan_numbers": [],
        "prose_scan_numbers": [],
        "journal_files": 0,
    }
    with open(ledger, "r") as fh:
        doc = json.load(fh)
    ev["ledger_scan_number"] = _parse_int(doc.get("scan_number"))

    for root, _dirs, files in os.walk(journals):
        for name in files:
            if not name.endswith(".json"):
                continue
            ev["journal_files"] += 1
            path = os.path.join(root, name)
            try:
                with open(path, "r") as fh:
                    doc = json.load(fh)
            except Exception:
                continue  # a malformed journal must not block allocation
            num = _parse_int(doc.get("scan_number"))
            if num is not None:
                ev["journal_scan_numbers"].append(num)
            # Harvest prose numbers from the WHOLE serialized document, not a
            # short list of named fields. Measured 2026-09-27 (finch:work #200):
            # a 3-field harvest (`run`/`source`/`summary`) saw 7 of the 33
            # prose-carried numbers, leaving 26 -- 33, 42, 45, 74 ... 157 --
            # invisible to the floor while the guard could see every one of
            # them. Two tools reading the same journals and disagreeing about
            # what exists is a coverage claim presented as a measurement.
            # Journals carry the number in at least `findings`, `scan_cycle`,
            # `scan_id`, `next_scheduled`, `scan_ref` and `cycle`, and that
            # list is not closed.
            #
            # Over-approximation is the SAFE direction for a floor: a spurious
            # match can only raise it, burning a number that goes unused,
            # whereas a missed one can re-mint a number already spent. So
            # harvest wide.
            for m in PROSE_RE.finditer(blob := json.dumps(doc, ensure_ascii=False)):
                ev["prose_scan_numbers"].append(int(m.group(1)))

    for key in ("journal_scan_numbers", "prose_scan_numbers"):
        ev[key] = sorted(set(ev[key]))

    # HEADROOM BAND -- DELIBERATELY NOT IMPLEMENTED, and the test suite is why.
    # Two bounds were drafted here this pass and BOTH were reverted, because
    # each broke a property test_finch_scan_counter.py deliberately pins:
    #   (a) A headroom band (prose may only raise the floor to within N of the
    #       highest structural number). Broke 12 cases, including "prose #612
    #       harvested from a non-run field" and "floor reflects the widest
    #       number seen anywhere (618)" -- asserted against a header of 10.
    #   (b) Quoted-example rejection (a match preceded by ' " or ` is a
    #       citation). Broke 8, including "prose #613/614/617 harvested from a
    #       non-run field" -- because a value that LEGITIMATELY reads
    #       {"scan_cycle": "finch:scan #613"} is itself preceded by a quote.
    # WIDTH is the pinned property, and deliberately so: a narrow harvest is
    # what caused the blind spot in #200. Width protects against re-minting a
    # number already spent (a collision, which corrupts the series). The
    # 2026-09-27 #950 incident cost 775 BURNED numbers -- a gap, not a
    # collision. A gap is recoverable; a collision is not. So the width stays.
    #
    # The real fix for #950 belongs in the WRITER: a work-log entry should not
    # quote a literal `finch:scan #N` that never ran. That is a discipline
    # rule, not a parser rule, and no bound on the harvest can distinguish a
    # cited example from a real low-numbered claim without one.
    ev["prose_scan_numbers"] = ev["prose_scan_numbers"]
    numbers = [n for n in (ev["ledger_scan_number"], _sidecar_last_allocated(ledger)) if n is not None]
    numbers += ev["journal_scan_numbers"] + ev["prose_scan_numbers"]
    ev["sidecar_last_allocated"] = _sidecar_last_allocated(ledger)
    ev["sidecar_path"] = _sidecar_path(ledger)
    ev["floor"] = max(numbers) if numbers else 0
    ev["next"] = ev["floor"] + 1
    return ev


def _take_lock():
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    fh = open(LOCK, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--peek", action="store_true", help="do not allocate")
    ap.add_argument("--floor", action="store_true", help="evidence only")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    lock = None if args.peek or args.floor else _take_lock()
    if lock is None and not (args.peek or args.floor):
        sys.stderr.write("finch_scan_counter: lock held by another pass\n")
        return 2

    try:
        sidecar = _sidecar_path(LEDGER)
        try:
            ev = evidence()
        except FileNotFoundError:
            sys.stderr.write("finch_scan_counter: ledger missing -> exit 1, NOT clean\n")
            return 1
        except Exception as exc:  # corrupt JSON is unreadable, not clean
            sys.stderr.write("finch_scan_counter: ledger unreadable: %s\n" % exc)
            return 1

        if args.floor or args.peek:
            if args.json:
                print(json.dumps(ev, indent=2, sort_keys=True))
            else:
                print("floor          :", ev["floor"])
                print("ledger header  :", ev["ledger_scan_number"])
                print("journal numbers:", ev["journal_scan_numbers"][-8:])
                print("prose numbers  :", ev["prose_scan_numbers"][-8:])
                print("sidecar last   :", ev["sidecar_last_allocated"], "(%s)" % ev["sidecar_path"])
                print("next (no alloc):", ev["next"])
            return 0

        n = ev["next"]
        state = {
            "last_allocated": n,
            "allocated_at": _now(),
            "floor_observed": ev["floor"],
            "ledger_scan_number": ev["ledger_scan_number"],
        }
        tmp = sidecar + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, sidecar)
        os.chmod(sidecar, 0o644)
        if args.json:
            print(json.dumps({"allocated": n, **state}, indent=2, sort_keys=True))
        else:
            print(n)
        return 0
    finally:
        if lock is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
