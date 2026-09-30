#!/usr/bin/env python3
"""Negative + fixture test for finch_ledger_guard.py.

A guard that only ever returns CLEAN is indistinguishable from no guard. Each
case below asserts the guard FAILS on a synthetic violation and that --repair
actually fixes it, then restores.

The fixtures are BUILT HERE, not copied from a live ledger. An earlier version
shutil.copy2'd the live task list out of an absolute host path, so on any
machine without that file the suite died with a FileNotFoundError traceback
before asserting anything -- the test could only ever pass on the author's host.
A committed absolute path is also a PII leak in a public repo. Case 9 keeps the
one invariant that genuinely needs the live file: this suite never writes to it.

Run: python3 test_finch_ledger_guard.py [--help]   (exit 0 = all cases pass)
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# ── Confined delete ────────────────────────────────────────────────────────
# A test that deletes real data is a worse defect than a test that fails, so
# every removal in this suite goes through one function with a structural
# check rather than a bare shutil.rmtree. The invariant is REGISTER-AT-
# CREATION, not "lives under /tmp": two suites here deliberately build their
# fixture tree outside /tmp (a profile-scoped scratch dir, a synthetic $HOME)
# so the watcher's path resolution is exercised against the real layout, and
# a /tmp-only allowlist would make the guard refuse the fixtures' own
# directories -- a test failing for a reason that has nothing to do with the
# world. A path is therefore deletable only if THIS MODULE created it, which
# catches the dangerous shape (a path assembled from an env var, a glob, or a
# fixture string) without constraining where the suite may work.
_CREATED = set()


def _register(path):
    _CREATED.add(os.path.realpath(path))
    return path


def mkfixture(*args, **kwargs):
    """tempfile.mkdtemp that remembers what it made."""
    return _register(tempfile.mkdtemp(*args, **kwargs))


def rmtree_confined(path, *, allow_missing=True):
    """Delete `path` only if this module created it. Refuse otherwise."""
    real = os.path.realpath(path)
    # A registered root OR anything beneath it: fixtures legitimately build
    # sub-trees (a launder/ dir inside a ledger temp dir) and deleting those
    # individually is still deleting only what this suite made. Anything else
    # -- a path assembled from an env var, a glob, or a fixture string -- is
    # refused, because that is the shape that eats live state.
    if not any(real == r or real.startswith(r + os.sep) for r in _CREATED):
        raise RuntimeError(
            "refusing to delete %s: not created by this suite. A test fixture "
            "must never name a path it did not make -- that shape is how a "
            "suite deletes live state." % real)
    if not os.path.exists(real):
        if allow_missing:
            return
        raise FileNotFoundError(real)
    shutil.rmtree(real, ignore_errors=True)
HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "finch_ledger_guard.py")
UTC = datetime.timezone.utc

# A fixed past instant. Every fixture stamp is derived from this, so "in the
# past" is a property of the fixture and not of when the suite happens to run.
BASE_STAMP = "2020-01-01T00:00:00Z"
# The task the forward-stamp cases operate on. Synthetic: the guard reads an id
# off the document, it does not know any real one.
SAMPLE_ID = "sample-task-forward-stamp"
# The review suffix the guard must preserve across a repair.
SUFFIX = "(finch:scan #999)"

fails = []


def run(path, extra=()):
    p = subprocess.run([sys.executable, GUARD, "--ledger", path, *extra],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def load(p):
    with open(p) as fh:
        return json.load(fh)


def save(p, d):
    with open(p, "w") as fh:
        json.dump(d, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def fingerprint(p):
    """Byte identity of a file: size, mtime and content hash together."""
    st = os.stat(p)
    with open(p, "rb") as fh:
        return (st.st_size, st.st_mtime_ns,
                hashlib.sha256(fh.read()).hexdigest())


def fixture():
    """A minimal ledger with every field the guard measures, all in the past."""
    return {
        "as_of": BASE_STAMP,
        "last_scan_at": BASE_STAMP,
        "last_work_at": BASE_STAMP,
        "scan_cycle": 0,
        "updated_at": BASE_STAMP,
        "tasks": [
            {"id": SAMPLE_ID, "status": "open",
             "created_at": BASE_STAMP, "updated_at": BASE_STAMP,
             "done_at": None, "last_finch_review": BASE_STAMP},
            {"id": "sample-task-ancient", "status": "done",
             "created_at": BASE_STAMP, "updated_at": "2019-06-01T00:00:00Z",
             "done_at": "2019-06-01T00:00:00Z",
             "last_finch_review": "2019-06-01T00:00:00Z"},
        ],
    }


def resolve_live():
    """Ask the guard itself where the live ledger is, so the two never drift."""
    spec = importlib.util.spec_from_file_location("finch_ledger_guard", GUARD)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.check().get("ledger")


def main():
    ap = argparse.ArgumentParser(
        description="Negative + fixture test for finch_ledger_guard.py.")
    ap.add_argument("--ledger", default=None,
                    help="also re-check this ledger (case 9); never written to")
    ap.parse_args()

    tmpdir = mkfixture(prefix="ledger_guard_test_")
    try:
        led = os.path.join(tmpdir, "task-list.json")
        base = fixture()
        save(led, base)
        os.chmod(led, 0o644)
        future = (datetime.datetime.now(UTC)
                  + datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # --- case 1: forward header stamp must be CAUGHT ------------------
        d = json.loads(json.dumps(base))
        d["as_of"] = future
        save(led, d)
        rc, out = run(led)
        print("[1] forward as_of           -> exit=%d %s"
              % (rc, "CAUGHT" if rc == 1 else "*** MISSED ***"))
        if rc != 1:
            fails.append("case1 header forward not caught")
        if "FORWARD" not in out:
            fails.append("case1 no FORWARD line")

        # --- case 2: forward per-task stamp must be CAUGHT ----------------
        d = json.loads(json.dumps(base))
        t = next(x for x in d["tasks"] if x.get("id") == SAMPLE_ID)
        t["updated_at"] = future
        t["last_finch_review"] = future + " " + SUFFIX
        save(led, d)
        rc, out = run(led)
        caught = rc == 1 and SAMPLE_ID in out
        print("[2] forward task stamp      -> exit=%d %s"
              % (rc, "CAUGHT" if caught else "*** MISSED ***"))
        if not caught:
            fails.append("case2 task forward not caught")

        # --- case 3: --repair fixes it and preserves the suffix -----------
        rc, out = run(led, ("--repair",))
        d = load(led)
        t = next(x for x in d["tasks"] if x.get("id") == SAMPLE_ID)
        suffixed = t["last_finch_review"].endswith(SUFFIX)
        stamp = datetime.datetime.fromtimestamp(
            os.path.getmtime(led), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        past = t["updated_at"] <= stamp
        print("[3] repair clamps + suffix   -> suffix_kept=%s in_past=%s %s"
              % (suffixed, past, "OK" if suffixed and past else "*** FAIL ***"))
        if not (suffixed and past):
            fails.append("case3 repair wrong")

        # --- case 4: clean ledger must PASS (exit 0) ---------------------
        rc, out = run(led)
        print("[4] clean ledger            -> exit=%d %s"
              % (rc, "CLEAN" if rc == 0 else "*** FALSE POSITIVE ***"))
        if rc != 0:
            fails.append("case4 false positive on clean ledger")

        # --- case 5: PAST stamps must NOT be flagged (no false positive) --
        d = json.loads(json.dumps(base))
        d["as_of"] = "2015-01-01T00:00:00Z"
        for x in d["tasks"][:5]:
            x["updated_at"] = "2015-01-01T00:00:00Z"
        save(led, d)
        rc, out = run(led)
        print("[5] ancient past stamps     -> exit=%d %s"
              % (rc, "CLEAN" if rc == 0 else "*** FALSE POSITIVE ***"))
        if rc != 0:
            fails.append("case5 ancient stamps misflagged")

        # --- case 6: unreadable/missing ledger -> exit 2, NOT a silent pass -
        missing = os.path.join(tmpdir, "nope.json")
        rc, out = run(missing)
        ok = rc == 2 and "UNREADABLE" in out
        print("[6] missing ledger          -> exit=%d %s"
              % (rc, "SIGNALLED" if ok else "*** SILENT PASS ***"))
        if not ok:
            fails.append("case6 missing ledger not signalled")

        # --- case 7: corrupt JSON -> exit 2 --------------------------------
        bad = os.path.join(tmpdir, "bad.json")
        with open(bad, "w") as fh:
            fh.write("{not json")
        rc, out = run(bad)
        ok = rc == 2
        print("[7] corrupt JSON            -> exit=%d %s"
              % (rc, "SIGNALLED" if ok else "*** SILENT PASS ***"))
        if not ok:
            fails.append("case7 corrupt json not signalled")

        # --- case 8: --repair preserves file mode 644 ---------------------
        d = json.loads(json.dumps(base))
        d["as_of"] = future
        save(led, d)
        run(led, ("--repair",))
        mode = oct(os.stat(led).st_mode & 0o777)
        ok = mode == "0o644"
        print("[8] mode preserved by repair-> %s %s"
              % (mode, "OK" if ok else "*** MODE CHANGED ***"))
        if not ok:
            fails.append("case8 repair changed file mode")

        # --- case 9: this suite must not write to a live ledger ------------
        live = resolve_live()
        if not live or not os.path.isfile(live):
            print("[9] live ledger             -> none resolvable; "
                  "suite reads no host state (expected off-host)")
        else:
            before = fingerprint(live)
            rc, out = run(live)          # read-only: no --repair
            after = fingerprint(live)
            ok = before == after
            print("[9] live ledger untouched   -> exit=%d unchanged=%s %s"
                  % (rc, ok, "OK" if ok else "*** MUTATED LIVE LEDGER ***"))
            if not ok:
                fails.append("case9 suite modified the live ledger")

        # --- cases 17-20: MTIME LAUNDERING (finch:work #204) --------------
        #
        # The guard compares stamps to the file's CURRENT mtime, so a later
        # write that copies an offending stamp through unchanged makes the
        # violation disappear -- the very pass that ran the guard hides what
        # the guard found. Live 2026-09-27: finch:work #203 stamped 07:50:00Z
        # into a ledger at mtime 07:39:45Z (+615s, exit 1); finch:scan #956 then
        # rewrote the same ledger at 07:58:25Z carrying the identical value, and
        # the same bytes read CLEAN. The receipt is what makes it catchable.
        #
        # The three instants are RELATIVE, and each one is load-bearing:
        #   M0 < stamp < M1.  Against M0 the stamp is forward (caught).  A
        # later write advances the mtime to M1, past the stamp, without
        # touching the value -- the laundering.  All three must be computed
        # from now(): a hardcoded fixture date sits in the past relative to a
        # present-day mtime, so nothing is ever forward and the case passes
        # vacuously. (That is exactly how a first draft of this block failed
        # -- it asserted exit=1 and got exit=0 for the right reason.)
        ltmp2 = os.path.join(tmpdir, "launder")
        os.makedirs(ltmp2)
        led2 = os.path.join(ltmp2, "task-list.json")
        now = datetime.datetime.now(UTC)
        m0 = now - datetime.timedelta(hours=3)      # when the bad write landed
        m1 = now - datetime.timedelta(minutes=30)   # when a later write moved past it
        stamp = (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        d2 = json.loads(json.dumps(base))
        d2["last_work_at"] = stamp
        t2 = next(x for x in d2["tasks"] if x.get("id") == SAMPLE_ID)
        t2["updated_at"] = stamp
        save(led2, d2)
        os.utime(led2, (m0.timestamp(), m0.timestamp()))

        # run 1: genuinely forward -> exit 1, and a receipt is written
        rc, out = run(led2)
        got_receipt = os.path.exists(led2 + ".guard-receipts.jsonl")
        ok = rc == 1 and got_receipt
        print("[17] forward + receipt      -> exit=%d receipt=%s %s"
              % (rc, got_receipt, "OK" if ok else "*** WRONG ***"))
        if not ok:
            fails.append("case17 forward run wrote no receipt (rc=%s, receipt=%s)"
                         % (rc, got_receipt))

        # run 2: THE LAUNDERING. Same bytes, mtime advanced past the stamp.
        os.utime(led2, (m1.timestamp(), m1.timestamp()))
        rc, out = run(led2)
        ok = rc == 1 and "LAUNDERED" in out
        print("[18] laundered by mtime    -> exit=%d %s"
              % (rc, "CAUGHT" if ok else "*** MISSED ***"))
        if not ok:
            fails.append("case18 laundered stamp not caught (rc=%s)" % rc)

        # run 3: --repair must clamp it AND the receipt must RETIRE. A
        # receipt that never retires would pin a clean ledger at exit 1
        # forever -- the exact regression the exit-code docstring warns about.
        rc, out = run(led2, ("--repair",))
        d3b = load(led2)
        t3b = next(x for x in d3b["tasks"] if x.get("id") == SAMPLE_ID)
        clamped = d3b["last_work_at"] != stamp and t3b["updated_at"] != stamp
        rc2, out2 = run(led2)
        ok = clamped and rc2 == 0 and "LAUNDERED" not in out2
        print("[19] repair retires receipt-> clamped=%s post_exit=%d %s"
              % (clamped, rc2, "OK" if ok else "*** WRONG ***"))
        if not ok:
            fails.append("case19 repair did not clamp and retire (clamped=%s, rc=%s)"
                         % (clamped, rc2))

        # run 4: an HONEST later pass rewrites the value. The old value is
        # gone, so nothing may be reported laundered -- the receipt must not
        # fire on a value that was legitimately replaced.
        led3 = os.path.join(ltmp2, "honest.json")
        d4 = json.loads(json.dumps(base))
        d4["last_work_at"] = stamp
        t4 = next(x for x in d4["tasks"] if x.get("id") == SAMPLE_ID)
        t4["updated_at"] = stamp
        save(led3, d4)
        os.utime(led3, (m0.timestamp(), m0.timestamp()))
        run(led3)                                   # forward -> receipt written
        os.utime(led3, (m1.timestamp(), m1.timestamp()))
        d4b = load(led3)
        newval = (now - datetime.timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        d4b["last_work_at"] = newval
        t4b = next(x for x in d4b["tasks"] if x.get("id") == SAMPLE_ID)
        t4b["updated_at"] = newval
        save(led3, d4b)
        nowts = datetime.datetime.now(UTC).timestamp()
        os.utime(led3, (nowts, nowts))
        rc, out = run(led3)
        ok = rc == 0 and "LAUNDERED" not in out
        print("[20] honest rewrite        -> exit=%d %s"
              % (rc, "OK" if ok else "*** FALSE POSITIVE ***"))
        if not ok:
            fails.append("case20 honest rewrite falsely reported as laundered (rc=%s)" % rc)
        rmtree_confined(ltmp2)
    finally:
        rmtree_confined(tmpdir)

    journal_cases()
    print("\n%s" % ("ALL CASES PASSED" if not fails
                    else "FAILURES:\n  " + "\n  ".join(fails)))
    return 0 if not fails else 1


# =========================================================================
# Journal self-stamp + namespace cases.
#
# These live in a FUNCTION, not at module level, because the ledger cases above
# are wrapped in main() -- keeping the journal cases at module scope would make
# them run on import, and a test module that acts on import is a trap.
#
# Ported from the pre-rewrite suite (which held them at module scope) so the
# coverage survives the restructure; the fixtures are identical, only the
# enclosing scope changed. A synthetic journal dir is used: the REAL journal
# tree is never written to.
# =========================================================================
def journal_cases():
    jtmp = mkfixture(prefix="journal_guard_test_")
    ltmp = mkfixture(prefix="journal_guard_ledger_")
    try:
        # A SEPARATE, valid ledger for these cases. The original module-scope
        # version reused the main fixture ledger, which no longer exists once
        # the cases live in a function. It must be a real, CLEAN ledger, not
        # os.devnull: the guard checks the ledger FIRST and exits 2 on an
        # unreadable one, so passing /dev/null made every journal case
        # report MISSED / FALSE POSITIVE while testing nothing. Seven
        # consecutive green-to-red cases from one bad fixture argument.
        jled = os.path.join(ltmp, "task-list.json")
        save(jled, fixture())
        os.chmod(jled, 0o644)

        def mkjournal(name, payload, mtime_offset_s=0):
            p = os.path.join(jtmp, name)
            save(p, payload)
            t = datetime.datetime.now(UTC).timestamp() - mtime_offset_s
            os.utime(p, (t, t))
            return p

        def run_j(extra=()):
            p = subprocess.run(
                [sys.executable, GUARD, "--ledger", jled, "--journals", jtmp, *extra],
                capture_output=True, text=True)
            return p.returncode, p.stdout + p.stderr

        past = (datetime.datetime.now(UTC) - datetime.timedelta(hours=3)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
        fut = (datetime.datetime.now(UTC) + datetime.timedelta(hours=4)
               ).strftime("%Y-%m-%dT%H:%M:%SZ")

        # --- case 10: forward journal self-stamp must be CAUGHT (this is
        # the whole point of the new check: the old glob 'scan-*.json' could
        # not see it) --------------------------------------------------
        mkjournal("scan-0100.json", {"scan_number": 900, "timestamp": past})
        mkjournal("scan-0200.json", {"scan_number": 901, "timestamp": fut})
        rc, out = run_j()
        # Reported in the text, but the exit code stays 0: journal findings are
        # not actionable by a writer and must not redden a clean ledger.
        caught = "JOURNAL SELF-STAMP FORWARD" in out and "scan-0200.json" in out
        print("[10] journal self-stamp    -> exit=%d %s"
              % (rc, "CAUGHT" if caught else "*** MISSED ***"))
        if not caught:
            fails.append("case10 forward journal self-stamp not caught")
        if rc != 0:
            fails.append("case10 journal finding wrongly changed the exit code")

        # --- case 11: clean journals must NOT be flagged -------------------
        rmtree_confined(jtmp)
        os.makedirs(jtmp)
        mkjournal("scan-0300.json", {"scan_number": 1, "timestamp": past})
        mkjournal("scan-0400.json", {"scan_number": 2, "timestamp": past})
        rc, out = run_j()
        print("[11] clean journals        -> exit=%d %s"
              % (rc, "CLEAN" if rc == 0 else "*** FALSE POSITIVE ***"))
        if rc != 0:
            fails.append("case11 false positive on clean journals")

        # --- case 12: a work-* journal's scan_number must NOT break
        # monotonicity -- work-*.json carries the scan it ran AGAINST, so #5
        # between scan #4 and #6 is legitimate. The pre-fix code flagged this.
        rmtree_confined(jtmp)
        os.makedirs(jtmp)
        mkjournal("scan-0500.json", {"scan_number": 4, "timestamp": past}, 0)
        mkjournal("work-0600.json", {"scan_number": 5, "source": "finch:work",
                                    "timestamp": past}, 0)
        mkjournal("scan-0700.json", {"scan_number": 6, "timestamp": past}, 0)
        rc, out = run_j()
        ok = rc == 0 and "NON-MONOTONIC" not in out
        print("[12] work-* not a violation -> exit=%d %s"
              % (rc, "OK" if ok else "*** FALSE POSITIVE ***"))
        if not ok:
            fails.append("case12 work-* scan_number misread as non-monotonic")

        # --- case 13: genuine duplicate scan_number IS reported -----------
        rmtree_confined(jtmp)
        os.makedirs(jtmp)
        mkjournal("scan-0800.json", {"scan_number": 7, "timestamp": past}, 0)
        mkjournal("scan-0900.json", {"scan_number": 7, "timestamp": past}, 60)
        rc, out = run_j()
        ok = rc == 0 and "DUPLICATE scan_number" in out and "7" in out
        print("[13] duplicate scan_number -> exit=%d %s"
              % (rc, "REPORTED" if ok else "*** MISSED ***"))
        if not ok:
            fails.append("case13 duplicate scan_number not reported")

        # --- case 14: unreadable journal must not abort the measurement ---
        rmtree_confined(jtmp)
        os.makedirs(jtmp)
        mkjournal("scan-1000.json", {"scan_number": 8, "timestamp": past})
        with open(os.path.join(jtmp, "scan-1100.json"), "w") as fh:
            fh.write("{not json")
        rc, out = run_j()
        ok = rc == 0
        print("[14] corrupt journal file  -> exit=%d %s"
              % (rc, "SURVIVED" if ok else "*** CRASHED ***"))
        if not ok:
            fails.append("case14 corrupt journal broke measurement")

        # --- case 15: offset-aware parsing (timestamps with -07:00) -------
        rmtree_confined(jtmp)
        os.makedirs(jtmp)
        off = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-7)))
               - datetime.timedelta(hours=3)).isoformat()
        mkjournal("scan-1200.json", {"scan_number": 9, "timestamp": off})
        rc, out = run_j()
        print("[15] offset-aware stamp    -> exit=%d %s"
              % (rc, "CLEAN" if rc == 0 else "*** FALSE POSITIVE ***"))
        if rc != 0:
            fails.append("case15 offset timestamp misparsed")

        # --- case 16: a journal carrying MORE THAN ONE prose number -------
        # The [COVERAGE] count used re.search, which returns only the FIRST
        # prose number in a document. 2026-09-21/scan-93.json holds both 91
        # and 93, so 91 was invisible and the unrecoverable count
        # OVER-REPORTED by one. Pin the multi-number harvest.
        #
        # The unrecoverable range runs from the lowest to the highest
        # STRUCTURAL scan_number, so the fixture needs two of those to span
        # the prose numbers -- with only one, the range collapses and the case
        # proves nothing.
        rmtree_confined(jtmp)
        os.makedirs(jtmp)
        mkjournal("scan-2000.json", {"scan_number": 10, "timestamp": past}, 0)
        mkjournal("scan-2050.json", {"scan_number": 14, "timestamp": past}, 0)
        mkjournal("scan-2100.json",
                  {"timestamp": past, "run": "finch:scan #11 and again finch:scan #12"}, 0)
        rc, out = run_j()
        m = re.search(r"(\d+) allocated number\(s\) left no recoverable trace", out)
        got = int(m.group(1)) if m else None
        # Range 10..14. Structural: 10, 14. Prose (2 numbers, both must
        # count): 11, 12. Unseen: 13 alone -> exactly 1 unrecoverable. The
        # pre-fix search-only code harvested 11 and dropped 12, reporting 2.
        ok = rc == 0 and got == 1
        print("[16] multi-prose-number    -> exit=%d unrecoverable=%s %s"
              % (rc, got, "OK" if ok else "*** WRONG ***"))
        if not ok:
            fails.append("case16 only the first prose number was harvested (got %s, want 1)" % got)

    finally:
        rmtree_confined(jtmp)
        rmtree_confined(ltmp)


if __name__ == "__main__":
    sys.exit(main())
