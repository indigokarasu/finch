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
import shutil
import subprocess
import sys
import tempfile

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

    tmpdir = tempfile.mkdtemp(prefix="ledger_guard_test_")
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
    finally:
        shutil.rmtree(tmpdir)

    print("\n%s" % ("ALL CASES PASSED" if not fails
                    else "FAILURES:\n  " + "\n  ".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
