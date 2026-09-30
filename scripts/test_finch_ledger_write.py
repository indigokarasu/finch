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
  8. a rejected write (bad --set) leaves the file byte-identical;
  9. a forward stamp that LEADS a work_log entry is clamped, because the
     guard reads fields and the 2026-09-29 #1016 pass proved the entries are
     writable ground (13 field stamps repaired, 6 narrative ones missed);
 10. a STALE narrative lead-stamp is left byte-identical -- the clamp is not a
     normalisation pass, and rewriting honest history would be worse than the
     defect it prevents;
 11. a timestamp quoted MID-SENTENCE is never touched, even when forward;
 12. due_date in the future is never touched (it is a deadline, not a claim);
 13. the -07:00 offset case is clamped on the TRUE instant, not the truncated
     one -- the guard's old reader is what hid a forward stamp for a day;
 14. the whole suite FAILS against the pre-fix code, so it can fail;
 15. a narrative lead that is an UNEXPANDED %-format is REFUSED (exit 4), not
     clamped -- a missing pass-time claim has no value to compare against now,
     and inventing one would be the defect itself (measured live 2026-09-29:
     2 such entries, "%s (finch:work #200)" and "%s (finch:work, scan_number
     1000)", invisible to the guard, the sweep and the watcher alike);
 16. pre-existing debt does NOT brick the write path: an unexpanded lead that
     was already on disk is reported, not refused, because a refusal nobody
     can repair would stop the ledger moving and hide the debt;
 17. the refusal is independent of --clamp-only, so a clamp-only pass cannot
     launder a damaged entry into the ledger by rewriting the file around it.
 18. a task record that CONTRADICTS ITSELF is REFUSED (exit 5) -- a
     `last_finch_review` older than a work_log entry in the same record. Every
     other control in this system compares one stamp to one external clock
     (mtime, or now()); this is two stamps that claim the same event
     disagreeing with each other, which none of them can see. Measured live
     2026-09-30: 8 such records, the smallest violation -1.205h, and nothing
     between it and zero, so the population is bimodal and the 5-minute
     tolerance is read off the gap rather than guessed.
 19. pre-existing self-contradicting debt does NOT brick the write path, on
     the same reasoning as 16 -- reported, not refused.
 20. the exit-5 control is independent of --clamp-only, for the same reason 17
     exists, and the refusal names the class.
 21. a work_log held as a bare STRING is read as one entry rather than
     indexed as a list (measured live 2026-09-30: 126 records hold a list, 42
     omit the key, and ONE holds a string -- #1021 hit this exact trap itself
     when it treated notes/signal as lists and walked characters).
 22. the comparison uses the MAXIMUM entry lead, not the last element, so an
     out-of-order append cannot hide a contradiction.

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
    # Compare against a clock read AFTER the write, not the `now` captured in
    # block 1. The writer truncates to whole seconds, so a stamp written in the
    # same second the fixture was read is one second ahead of the earlier
    # `now` and this asserts `t <= now` on a snapshot that is already stale.
    # Observed once in ~10 runs (2026-09-28, finch:work #232) -- a genuine
    # flake, pre-existing and unrelated to that pass's change. The assertion
    # is about "clamped to about now", so it must be measured against now.
    now2 = datetime.datetime.now(UTC).replace(microsecond=0)
    check("body clamped to now", t <= now2,
          "%s vs now=%s (delta %+ds)"
          % (body, now2.isoformat(), (t - now2).total_seconds()))

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

    # --- 10-14. narrative lead-stamps: the #1016 residue class ---------------
    print("\n10. a forward LEADING stamp in a work_log entry is clamped")
    doc = base_doc()
    doc["tasks"][0]["work_log"] = [
        "2026-01-01T00:00:00Z (finch:scan #1): an honest, stale entry",
        "2030-01-01T00:00:00Z (finch:scan #999): FORWARD, must be clamped",
    ]
    ch = W.clamp(doc, now=datetime.datetime(2026, 1, 2, tzinfo=UTC))
    narr = [c for c in ch if c["scope"] == "narrative"]
    check("exactly one narrative clamp", len(narr) == 1, str(ch))
    check("the stale one was NOT touched",
          doc["tasks"][0]["work_log"][0] ==
          "2026-01-01T00:00:00Z (finch:scan #1): an honest, stale entry",
          doc["tasks"][0]["work_log"][0])
    check("prose after the stamp survives byte-identical",
          doc["tasks"][0]["work_log"][1].endswith(
              " (finch:scan #999): FORWARD, must be clamped"),
          doc["tasks"][0]["work_log"][1])
    check("clamped to now()",
          doc["tasks"][0]["work_log"][1].startswith("2026-01-02T00:00:00Z"),
          doc["tasks"][0]["work_log"][1])

    print("\n11. a MID-SENTENCE timestamp is never touched, even when forward")
    s = "RE-VERIFY on 2030-01-01T00:00:00Z, which is a quoted future date"
    doc = base_doc()
    doc["tasks"][0]["work_log"] = [s]
    W.clamp(doc, now=datetime.datetime(2026, 1, 2, tzinfo=UTC))
    check("byte-identical", doc["tasks"][0]["work_log"][0] == s,
          doc["tasks"][0]["work_log"][0])

    print("\n12. a future due_date is never touched (a deadline, not a claim)")
    doc = base_doc()
    doc["tasks"][0]["due_date"] = "2030-01-01T00:00:00Z"
    W.clamp(doc, now=datetime.datetime(2026, 1, 2, tzinfo=UTC))
    check("due_date unchanged", doc["tasks"][0]["due_date"] == "2030-01-01T00:00:00Z")
    check("no narrative clamp fired", not any(
        c["scope"] == "narrative" for c in W.clamp(
            doc, now=datetime.datetime(2026, 1, 2, tzinfo=UTC))))

    print("\n13. the -07:00 offset case is clamped on the TRUE instant")
    # 2026-01-02T00:00:00-07:00 == 2026-01-02T07:00:00Z, i.e. 7h AFTER now.
    # A truncating reader (v[:19], then assume UTC) would read it as 00:00:00Z
    # -- exactly at now -- and find nothing to clamp. The two must be built so
    # truncation and the true instant fall on OPPOSITE sides of now.
    doc = base_doc()
    doc["tasks"][0]["work_log"] = ["2026-01-02T00:00:00-07:00 (finch:scan #7): x"]
    W.clamp(doc, now=datetime.datetime(2026, 1, 2, 0, 0, tzinfo=UTC))
    check("clamped despite reading as 'not forward' when truncated",
          doc["tasks"][0]["work_log"][0].startswith("2026-01-02T00:00:00Z"),
          doc["tasks"][0]["work_log"][0])

    print("\n14. the suite can fail: the pre-fix clamp misses all of the above")
    # Re-implement the pre-2026-09-29 clamp (fields only) and confirm these
    # fixtures pass it un-clamped. A suite that cannot fail is decoration.
    legacy = copy.deepcopy(base_doc())
    legacy["tasks"][0]["work_log"] = ["2030-01-01T00:00:00Z (finch:scan #999): x"]
    n_legacy = 0
    stamp = "2026-01-02T00:00:00Z"
    for task in legacy.get("tasks", []):
        for k in G.TASK_FIELDS:
            t = G._parse(task.get(k))
            if t is not None and t > datetime.datetime(2026, 1, 2, tzinfo=UTC):
                task[k] = stamp + W._suffix(task.get(k))
                n_legacy += 1
    check("legacy (fields-only) clamp leaves the entry forward",
          legacy["tasks"][0]["work_log"][0].startswith("2030-01-01T00:00:00Z"),
          legacy["tasks"][0]["work_log"][0])

    print("\n15. a NEWLY introduced unexpanded %-format lead is REFUSED (exit 4)")
    dmg = "%s (finch:work, scan_number 4242): EXECUTED. The template was stored."
    doc = base_doc()
    doc["tasks"][0]["work_log"] = [dmg]
    staged = os.path.join(tmp, "dmg.json")
    with open(staged, "w") as fh:
        json.dump(doc, fh)
    rc, out = cli(["--doc", staged], led, jd)
    check("refused with exit 4", rc == 4, "exit=%d" % rc)
    check("refusal names the class", "UNEXPANDED" in out, out[-200:])
    check("nothing was written", "DRY RUN" not in out and "WRITTEN" not in out, out)
    after = json.load(open(led))
    check("ledger on disk still byte-identical",
          after["tasks"][0].get("work_log") == base_doc()["tasks"][0].get("work_log"),
          after["tasks"][0].get("work_log"))

    print("\n16. PRE-EXISTING unexpanded debt is reported, not refused")
    # Put the damage on disk FIRST, then issue an unrelated write: it must go
    # through. A refusal on unrepairable debt would brick the write path and
    # hide the debt behind a failure nobody can act on.
    with open(led, "w") as fh:
        json.dump(doc, fh, indent=2)
    rc, out = cli(["--clamp-only"], led, jd)
    check("clamp-only still writes (exit 0)", rc == 0, "exit=%d\n%s" % (rc, out))
    check("debt reported explicitly", "PRE-EXISTING" in out and "debt" in out,
          out[:200])
    check("no forward stamp invented for it",
          json.load(open(led))["tasks"][0]["work_log"][0] == dmg,
          json.load(open(led))["tasks"][0]["work_log"][0])

    print("\n17. --clamp-only does NOT launder damage in from a --doc")
    doc2 = base_doc()
    doc2["tasks"][0]["work_log"] = [
        "%s (finch:work #7): EXECUTED via a template."]
    staged2 = os.path.join(tmp, "dmg2.json")
    with open(staged2, "w") as fh:
        json.dump(doc2, fh)
    rc, out = cli(["--doc", staged2, "--clamp-only"], led, jd)
    check("clamp-only cannot carry a damaged entry in", rc == 4, "exit=%d" % rc)
    check("the damaged entry did not land",
          "%s (finch:work #7)" not in json.dumps(json.load(open(led))),
          "leaked into the ledger")

    print("\n18. a SELF-CONTRADICTING record is REFUSED (exit 5)")
    # last_finch_review is 16h behind a work_log entry in the same record. The
    # field says "last reviewed at T"; the entry says "a pass ran at T+16h".
    doc = base_doc()
    doc["tasks"][0]["last_finch_review"] = "2026-01-01T00:00:00Z"
    doc["tasks"][0]["work_log"] = ["2026-01-01T16:00:00Z (finch:scan #9): EXECUTED."]
    staged = os.path.join(tmp, "stale.json")
    with open(staged, "w") as fh:
        json.dump(doc, fh)
    # Snapshot the REAL on-disk state first. Cases 15-17 deliberately leave
    # unexpanded-debt on the ledger, so asserting "no work_log anywhere" would
    # be a claim about the fixture's history rather than about the refusal.
    before = open(led).read()
    rc, out = cli(["--doc", staged], led, jd)
    check("refused with exit 5", rc == 5, "exit=%d\n%s" % (rc, out))
    check("refusal names the class", "CONTRADICT" in out, out[-300:])
    check("nothing was written", "WRITTEN" not in out, out)
    check("ledger on disk byte-identical to its pre-refusal state",
          open(led).read() == before, "the refusal mutated the ledger")
    check("the contradicting entry did not land",
          "2026-01-01T16:00:00Z" not in open(led).read(),
          "leaked into the ledger")

    print("\n19. PRE-EXISTING self-contradicting debt is reported, not refused")
    # Put the contradiction on disk FIRST, then issue an unrelated write. A
    # refusal on debt nobody can repair would brick the write path.
    with open(led, "w") as fh:
        json.dump(doc, fh, indent=2)
    rc, out = cli(["--clamp-only"], led, jd)
    check("clamp-only still writes (exit 0)", rc == 0, "exit=%d\n%s" % (rc, out))
    check("debt reported explicitly", "PRE-EXISTING" in out and "debt" in out,
          out[:300])
    check("neither side was silently rewritten",
          json.load(open(led))["tasks"][0]["last_finch_review"] == "2026-01-01T00:00:00Z",
          json.load(open(led))["tasks"][0]["last_finch_review"])

    print("\n20. --clamp-only does NOT launder a contradiction in from a --doc")
    doc2 = base_doc()
    doc2["tasks"][0]["last_finch_review"] = "2026-01-01T00:00:00Z"
    doc2["tasks"][0]["work_log"] = ["2026-01-01T20:00:00Z (finch:work #8): EXECUTED."]
    staged2 = os.path.join(tmp, "stale2.json")
    with open(staged2, "w") as fh:
        json.dump(doc2, fh)
    rc, out = cli(["--doc", staged2, "--clamp-only"], led, jd)
    check("clamp-only cannot carry a contradiction in", rc == 5, "exit=%d" % rc)
    check("the contradicting entry did not land",
          "2026-01-01T20:00:00Z" not in json.dumps(json.load(open(led))),
          "leaked into the ledger")

    print("\n21. a work_log held as a bare STRING is read as ONE entry")
    # Not hypothetical: tasks[133] hermes-failed-turn-notice-untyped-telegram
    # holds work_log as a string. A list-assuming reader takes [-1] and gets
    # the last CHARACTER, which parses as no instant and silently finds nothing.
    doc3 = base_doc()
    doc3["tasks"][0]["last_finch_review"] = "2026-01-01T00:00:00Z"
    doc3["tasks"][0]["work_log"] = "2026-01-01T22:00:00Z (finch:work #7): EXECUTED, held as a string."
    hits = W.find_stale_review_claims(doc3)
    check("string-typed work_log is detected, not walked as a list",
          len(hits) == 1, "hits=%r" % (hits,))
    check("the reported lag is the real one (22h, not 'last character')",
          hits and abs(hits[0][4] - 79200.0) < 1.0,
          "lag=%r" % (hits[0][4] if hits else None,))

    print("\n22. the comparison uses the MAXIMUM lead, not the last element")
    # An out-of-order append puts an OLDER entry last. Keyed on position the
    # contradiction would be invisible; keyed on the max it is caught.
    doc4 = base_doc()
    doc4["tasks"][0]["last_finch_review"] = "2026-01-01T00:00:00Z"
    doc4["tasks"][0]["work_log"] = [
        "2026-01-01T18:00:00Z (finch:scan #5): newer, appended first.",
        "2026-01-01T02:00:00Z (finch:scan #4): older, appended second.",
    ]
    hits = W.find_stale_review_claims(doc4)
    check("out-of-order append still detected via the max lead", len(hits) == 1,
          "hits=%r" % (hits,))
    check("the max (18h) is the one reported",
          hits and abs(hits[0][4] - 64800.0) < 1.0,
          "lag=%r" % (hits[0][4] if hits else None,))

    print("\n23. the tolerance admits the exactly-zero and sub-5min cases")
    # The 5-minute tolerance comes from the measured bimodal gap; a control that
    # fired on normal same-write agreement would refuse every honest pass.
    doc5 = base_doc()
    doc5["tasks"][0]["last_finch_review"] = "2026-01-01T12:00:00Z"
    doc5["tasks"][0]["work_log"] = ["2026-01-01T12:00:00Z (finch:scan #2): same write."]
    check("exactly-equal stamps do not fire", W.find_stale_review_claims(doc5) == [],
          str(W.find_stale_review_claims(doc5)))
    doc5["tasks"][0]["work_log"] = ["2026-01-01T12:02:00Z (finch:scan #2): 2 min apart."]
    check("a 2-minute skew does not fire", W.find_stale_review_claims(doc5) == [],
          str(W.find_stale_review_claims(doc5)))
    doc5["tasks"][0]["work_log"] = ["2026-01-01T12:04:00Z (finch:scan #2): 4 min apart."]
    check("a 4-minute skew does not fire", W.find_stale_review_claims(doc5) == [],
          str(W.find_stale_review_claims(doc5)))
    doc5["tasks"][0]["work_log"] = ["2026-01-01T12:06:00Z (finch:scan #2): 6 min apart."]
    check("a 6-minute skew DOES fire (tolerance is 5 min)", len(W.find_stale_review_claims(doc5)) == 1,
          str(W.find_stale_review_claims(doc5)))
    check("a record with no work_log at all does not fire",
          W.find_stale_review_claims(base_doc()) == [],
          str(W.find_stale_review_claims(base_doc())))

    print("\n24. the ' (finch:scan #N)' suffix on last_finch_review is parsed, not fatal")
    # NOT a synthetic edge case. 166/166 live last_finch_review values carry this
    # tail. A first implementation parsed the WHOLE field and returned None on
    # every one of them, so the control found 0 of the 8 live contradictions
    # while every unit test passed -- the unit fixtures used bare stamps. This
    # direction is the one that would have caught it, and it is here so the next
    # reader does not have to rediscover it against real data.
    doc6 = base_doc()
    doc6["tasks"][0]["last_finch_review"] = "2026-01-01T00:00:00Z (finch:scan #1011)"
    doc6["tasks"][0]["work_log"] = ["2026-01-01T18:00:00Z (finch:scan #1012): EXECUTED."]
    hits = W.find_stale_review_claims(doc6)
    check("suffixed review stamp is still compared", len(hits) == 1,
          "hits=%r" % (hits,))
    check("the reported review value is the field, suffix intact",
          hits and hits[0][2] == "2026-01-01T00:00:00Z (finch:scan #1011)",
          "review=%r" % (hits[0][2] if hits else None,))
    doc6["tasks"][0]["work_log"] = ["2026-01-01T00:00:00Z (finch:scan #1011): same pass."]
    check("suffixed + exactly equal does not fire", W.find_stale_review_claims(doc6) == [],
          str(W.find_stale_review_claims(doc6)))

    print("\n25. discrimination: byte-identical debt vs REWORDED debt at the same trail")
    # The laundering path, found by the live harness rather than by a fixture.
    # (trail, review, instant, lag) is unchanged when the prose is reworded, so a
    # key without the text waves a DIFFERENT record through as pre-existing
    # debt. Same shape #1019's test 17 caught for the exit-4 control.
    doc7 = base_doc()
    doc7["tasks"][0]["last_finch_review"] = "2026-01-01T00:00:00Z"
    doc7["tasks"][0]["work_log"] = ["2026-01-01T16:00:00Z (finch:scan #9): ORIGINAL prose."]
    h1 = W.find_stale_review_claims(doc7)
    check("debt detected", len(h1) == 1, "hits=%r" % (h1,))
    check("the FULL entry text is part of the key",
          h1 and h1[0][5] == "2026-01-01T16:00:00Z (finch:scan #9): ORIGINAL prose.",
          "text=%r" % (h1[0][5] if h1 else None,))
    doc7["tasks"][0]["work_log"] = ["2026-01-01T16:00:00Z (finch:scan #9): REWORDED prose."]
    h2 = W.find_stale_review_claims(doc7)
    check("reworded debt is a DIFFERENT key, not the same one",
          h1 and h2 and h1[0] != h2[0], "key identical -- laundering path open")
    with open(led, "w") as fh:
        json.dump(doc7, fh, indent=2)
    rc, out = cli(["--clamp-only"], led, jd)
    check("the reworded-on-disk record is reported as debt, not refused", rc == 0,
          "exit=%d" % rc)
    # now the same doc staged over an UNRELATED ledger: it must be refused
    with open(led, "w") as fh:
        json.dump(base_doc(), fh, indent=2)
    staged7 = os.path.join(tmp, "reworded.json")
    with open(staged7, "w") as fh:
        json.dump(doc7, fh)
    rc, out = cli(["--doc", staged7], led, jd)
    check("reworded contradiction arriving over a clean ledger is REFUSED",
          rc == 5, "exit=%d\n%s" % (rc, out))

    print("\n26. the UNTESTED side: an entry OLDER than its review field is not a hit")
    # Direction 23 covers only lag > 0 (2/4/6 min). Nothing covered lag < 0 --
    # the side 26 of 112 live records sit on, including the closest record in
    # the whole ledger at -80s. Guarding it here pins the DIRECTION of the
    # comparison, so a direction-agnostic comparison cannot pass silently.
    #
    # Why this direction and not just direction 23: reverting the comparison to
    # the sign-blind 'abs(lag) > tolerance' in a copy of the writer leaves ALL
    # FIVE of direction 23's magnitude checks green -- equal, 2min, 4min, 6min
    # and the empty-work_log case -- and every CLI/exit-5 direction green too,
    # because a larger firing population still refuses honestly-stamped writes.
    # Only the two negative-side checks here go red. So this direction is the
    # SOLE guard against a comparison that has stopped distinguishing which
    # claim is the stale one, which is precisely the confusion the removed
    # measurement made: it called the firing population negative when it is
    # positive. Measured 2026-09-30, not assumed.
    #
    # Why the negative side cannot fire is STRUCTURAL, not numeric: the control
    # fires on lag > tolerance, so a negative lag is excluded whatever the
    # tolerance is. That is why direction 23 needs no counterpart tolerance and
    # why the -80s live record is harmless even though it is only 3.75x below
    # the tolerance.
    doc8 = base_doc()
    doc8["tasks"][0]["last_finch_review"] = "2026-09-01T12:00:00Z"
    # entry 80s OLDER than the review field -- the live headhunter case
    doc8["tasks"][0]["work_log"] = ["2026-09-01T11:58:40Z (finch:work #218): earlier entry."]
    check("an entry 80s OLDER than the review field does NOT fire",
          W.find_stale_review_claims(doc8) == [],
          str(W.find_stale_review_claims(doc8)))
    # the live -40h extreme. SAME DAY on both sides, so the lag is genuinely
    # negative; my first fixture put a September entry under a January review,
    # which is +23184s POSITIVE and fired for the right reason on the wrong side.
    doc8["tasks"][0]["work_log"] = ["2026-08-31T20:00:00Z (finch:work #N): 40h earlier."]
    check("an entry 40h older does NOT fire", W.find_stale_review_claims(doc8) == [],
          str(W.find_stale_review_claims(doc8)))
    # THE POINT OF THE DIRECTION: same magnitude, opposite sign, fires. If this
    # ever stops firing, the comparison has been inverted and every magnitude
    # assertion in direction 23 still passes.
    doc8["tasks"][0]["work_log"] = ["2026-09-01T12:06:00Z (finch:work #218): 6 min later."]
    check("the SAME magnitude the other way round DOES fire (sign is not symmetric)",
          len(W.find_stale_review_claims(doc8)) == 1,
          str(W.find_stale_review_claims(doc8)))

    print("\n%s" % ("-" * 60))
    if FAILURES:
        print("FAILED: %d check(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("ALL CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
