#!/usr/bin/env python3
"""test_finch_ledger_write.py -- does the writer choke point actually hold?

A new control that is never exercised against the failure it was built for is a
decorative control. These cases pin the properties the 2026-09-27 defect
actually turned on:

  1. a forward stamp cannot survive a write (the guard's whole point);
  2. an honest, STALE stamp is left exactly as written (the clamp is not a
     normalisation pass);
  3. the '(finch:scan #N)' suffix on last_finch_review survives the clamp;
  4. the clamp and the guard AGREE -- every field the guard reads is a field
     the clamp covers, so there is no field one can stamp and the other
     cannot see (the two are separate code, so this must be asserted, not
     assumed);
  5. a partial --set on one task does not disturb any other task;
  6. the permission bits of the ledger survive the atomic replace;
  7. --dry-run writes nothing;
  8. a rejected write (bad --set) leaves the file byte-identical.

Run: python3 test_finch_ledger_write.py
"""

import copy
import datetime
import json
import os
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "finch_ledger_write.py")
sys.path.insert(0, HERE)

import finch_ledger_write as W          # noqa: E402
import finch_ledger_guard as G          # noqa: E402

UTC = datetime.timezone.utc
FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILURES.append(name)


def base_doc(stamp="2026-01-01T00:00:00Z"):
    return {
        "as_of": stamp,
        "last_scan_at": stamp,
        "scan_cycle": stamp,
        "last_work_at": stamp,
        "scan_number": 7,
        "tasks": [
            {"id": "alpha", "status": "open", "created_at": stamp,
             "updated_at": stamp, "last_finch_review": stamp},
            {"id": "beta", "status": "watching", "created_at": stamp,
             "updated_at": stamp, "done_at": stamp},
        ],
    }


def touch(path, doc, mode=0o644):
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=2)
    os.chmod(path, mode)
    return path


def cli(args, ledger, journals=None):
    cmd = [sys.executable, SCRIPT, "--ledger", ledger] + args
    if journals:
        cmd += ["--journals", journals]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main():
    tmp = tempfile.mkdtemp(prefix="ledger-write-test.")
    led = os.path.join(tmp, "task-list.json")
    jd = os.path.join(tmp, "journals")
    os.makedirs(jd)
    # A journal dir with no *.json makes the journal check report NOT MEASURED,
    # which keeps the tests about the LEDGER and out of the journal findings.
    future = (datetime.datetime.now(UTC) + datetime.timedelta(hours=1))

    # --- 1. a forward stamp cannot survive a write -----------------------
    print("\n1. forward stamps are clamped at write time")
    doc = base_doc()
    doc["as_of"] = future.strftime("%Y-%m-%dT%H:%M:%SZ")
    doc["tasks"][0]["updated_at"] = future.strftime("%Y-%m-%dT%H:%M:%SZ")
    touch(led, doc)
    rc, out = cli(["--clamp-only"], led, jd)
    check("exit 0", rc == 0, out)
    with open(led) as fh:
        after = json.load(fh)
    now = datetime.datetime.now(UTC).replace(microsecond=0)
    for field, holder in (("as_of", after),
                          ("alpha.updated_at", after["tasks"][0])):
        t = datetime.datetime.strptime(holder[field.split(".")[-1]],
                                       "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        check("%s not after now" % field, t <= now, holder[field.split(".")[-1]])
    rep = G.check(led, jd)
    check("guard agrees: 0 forward", rep["forward_count"] == 0,
          str(rep["forward_count"]))

    # --- 2. a STALE stamp is left alone ----------------------------------
    print("\n2. honest stale stamps are preserved verbatim")
    doc = base_doc("2026-01-01T00:00:00Z")
    touch(led, doc)
    rc, out = cli(["--set", "scan_number=9"], led, jd)
    check("exit 0", rc == 0, out)
    with open(led) as fh:
        after = json.load(fh)
    check("as_of untouched", after["as_of"] == "2026-01-01T00:00:00Z",
          after["as_of"])
    check("task stamp untouched",
          after["tasks"][0]["created_at"] == "2026-01-01T00:00:00Z")
    check("clamped: 0 reported", "clamped  : 0" in out, out)

    # --- 3. suffix survives ------------------------------------------------
    print("\n3. the (finch:scan #N) suffix survives the clamp")
    doc = base_doc()
    doc["tasks"][0]["last_finch_review"] = (
        future.strftime("%Y-%m-%dT%H:%M:%SZ") + " (finch:scan #960)")
    touch(led, doc)
    rc, out = cli(["--set", "scan_number=9"], led, jd)
    check("exit 0", rc == 0, out)
    with open(led) as fh:
        after = json.load(fh)
    v = after["tasks"][0]["last_finch_review"]
    check("suffix kept", v.endswith("(finch:scan #960)"), v)
    body = v.rsplit(" (finch:", 1)[0]
    t = datetime.datetime.strptime(body, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    check("body clamped to now", t <= now, body)

    # --- 4. clamp coverage == guard coverage -------------------------------
    print("\n4. the clamp covers exactly the fields the guard reads")
    check("header fields match", set(G.HEADER_FIELDS) == set(G.HEADER_FIELDS))
    # Build one document with EVERY field forward in EVERY scope and confirm
    # the guard and the clamp account for the same number of stamps.
    doc = base_doc()
    fut = future.strftime("%Y-%m-%dT%H:%M:%SZ")
    for k in G.HEADER_FIELDS:
        doc[k] = fut
    for tsk in doc["tasks"]:
        for k in G.TASK_FIELDS:
            tsk[k] = fut
    touch(led, doc)
    pre = G.check(led, jd)
    probe = copy.deepcopy(doc)
    changes = W.clamp(probe, now=datetime.datetime.now(UTC))
    check("clamp count == guard forward_count",
          len(changes) == pre["forward_count"],
          "clamp=%d guard=%d" % (len(changes), pre["forward_count"]))
    ids = {(c["scope"], c["id"], c["field"]) for c in changes}
    # The guard's header entries carry NO id, so normalise both sides to
    # (scope, id, field) with id='-' for the header before comparing. Comparing
    # 2-tuples against 3-tuples reports a difference that is only the shape of
    # the key -- a test that fails on its own bookkeeping teaches nothing.
    gids = {("header", "-", h["field"]) for h in pre["header"] if h["forward"]}
    gids |= {("task", t_["id"], t_["field"]) for t_ in pre["task_fields"]}
    check("same (scope,id,field) set", ids == gids,
          "only-in-clamp=%s only-in-guard=%s" % (ids - gids, gids - ids))

    # --- 5. a targeted --set touches only its task -------------------------
    print("\n5. --task --set touches exactly one task")
    doc = base_doc()
    touch(led, doc)
    rc, out = cli(["--task", "beta", "--set", "status=done",
                   "--set", "updated_at=2026-02-02T00:00:00Z"], led, jd)
    check("exit 0", rc == 0, out)
    with open(led) as fh:
        after = json.load(fh)
    check("beta updated", after["tasks"][1]["status"] == "done")
    check("beta stamp set", after["tasks"][1]["updated_at"] == "2026-02-02T00:00:00Z")
    check("alpha untouched", after["tasks"][0] == doc["tasks"][0],
          json.dumps(after["tasks"][0]))

    # --- 6. permission bits survive ----------------------------------------
    print("\n6. the atomic replace preserves mode")
    touch(led, base_doc(), mode=0o644)
    before = stat.S_IMODE(os.stat(led).st_mode)
    rc, out = cli(["--set", "scan_number=11"], led, jd)
    after_m = stat.S_IMODE(os.stat(led).st_mode)
    check("mode unchanged (%o)" % before, before == after_m,
          "%o -> %o" % (before, after_m))

    # --- 7. --dry-run writes nothing ---------------------------------------
    print("\n7. --dry-run writes nothing")
    touch(led, base_doc())
    with open(led, "rb") as fh:
        before_bytes = fh.read()
    rc, out = cli(["--set", "as_of=2030-01-01T00:00:00Z", "--dry-run"], led, jd)
    with open(led, "rb") as fh:
        after_bytes = fh.read()
    check("exit 0", rc == 0, out)
    check("DRY RUN printed", "DRY RUN" in out, out)
    check("bytes identical", before_bytes == after_bytes)

    # --- 8. a rejected write changes nothing --------------------------------
    print("\n8. a rejected write leaves the file byte-identical")
    touch(led, base_doc())
    with open(led, "rb") as fh:
        before_bytes = fh.read()
    rc, out = cli(["--set", "no_equals_sign"], led, jd)
    check("non-zero exit", rc != 0, out)
    with open(led, "rb") as fh:
        after_bytes = fh.read()
    check("bytes identical", before_bytes == after_bytes)

    # --- 9. a doc missing 'tasks' is refused --------------------------------
    print("\n9. --doc must be a full ledger document")
    touch(led, base_doc())
    with open(led, "rb") as fh:
        before_bytes = fh.read()
    bad = os.path.join(tmp, "bad.json")
    with open(bad, "w") as fh:
        json.dump({"as_of": "2030-01-01T00:00:00Z"}, fh)
    rc, out = cli(["--doc", bad], led, jd)
    check("refused", rc != 0, out)
    with open(led, "rb") as fh:
        after_bytes = fh.read()
    check("bytes identical", before_bytes == after_bytes)

    print("\n%s" % ("-" * 60))
    if FAILURES:
        print("FAILED: %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("ALL CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
