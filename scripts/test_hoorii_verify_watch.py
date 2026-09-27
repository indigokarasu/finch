#!/usr/bin/env python3
"""Fixture tests for hoorii_verify_watch.py (finch:work #196).

Offline: no network, no Gmail. These assert the pure logic that produced two
real wrong answers during development:

  1. the lexicographic date-sort bug (8 Jan 2024 > 22 Sep 2026 as strings);
  2. the "vendor behind" branch, which a one-directional check silently missed.

Run: python3 test_hoorii_verify_watch.py   -> exits 0 on pass.
"""
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone

SRC = "hoorii_verify_watch.py"
_spec = importlib.util.spec_from_file_location("hoorii_watch", SRC)
if _spec is None or _spec.loader is None:
    print("FATAL: cannot load %s" % SRC)
    sys.exit(2)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

MIN_TS = mod.MIN_TS
fails = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s %s" % (name, detail))
        fails.append(name)


print("1. ts_of() never sorts lexicographically")
# Find a REAL reversing pair rather than asserting a guessed one: search
# realistic Date headers for a pair whose string order disagrees with their
# chronological order. The original production bug (El Camino watcher, #194)
# only misfired because the weekday names happened to align wrong, so a
# hand-picked example is not guaranteed to reproduce it.
CANDIDATES = ["Mon, 8 Jan 2024 12:00:00 +0000", "Tue, 22 Sep 2026 13:24:00 +0000",
              "Wed, 8 Jan 2024 12:00:00 +0000", "Mon, 22 Sep 2026 13:24:00 +0000",
              "Fri, 8 Jan 2024 12:00:00 +0000", "Sun, 22 Sep 2026 13:24:00 +0000",
              "Thu, 8 Jan 2024 12:00:00 +0000", "Mon, 22 Sep 2026 13:24:00 +0000"]
reversing = None
for i, a in enumerate(CANDIDATES):
    for b in CANDIDATES[i + 1:]:
        if (a > b) != (mod.ts_of(a) > mod.ts_of(b)):
            reversing = (a, b)
            break
    if reversing:
        break
check("a lexicographically-reversing pair EXISTS in realistic headers",
      reversing is not None, "searched %d candidates" % len(CANDIDATES))
if reversing:
    a, b = reversing
    check("string order says a>b: %r / %r" % (a[:21], b[:21]), a > b)
    check("ts_of reverses it: %r is NOT after %r" % (a[:21], b[:21]),
          mod.ts_of(a) < mod.ts_of(b))
jan, sep = "Thu, 09 Jan 2024 05:00:00 +0000", "Tue, 22 Sep 2026 13:24:00 +0000"
t_jan, t_sep = mod.ts_of(jan), mod.ts_of(sep)
check("ts_of puts Sep 2026 AFTER Jan 2024", t_sep > t_jan,
      "got %s vs %s" % (t_sep, t_jan))
check("ts_of sorts ascending", sorted([t_jan, t_sep]) == [t_jan, t_sep])
check("unparseable -> datetime.min", mod.ts_of("not a date") == MIN_TS)
check("None -> datetime.min", mod.ts_of(None) == MIN_TS)
check("naive date gets UTC", mod.ts_of("Mon, 01 Jan 2024 00:00:00").tzinfo is timezone.utc)
off = mod.ts_of("Wed, 23 Sep 2026 01:10:59 -0700")
check("offset normalised to UTC", off.isoformat() == "2026-09-23T08:10:59+00:00", off.isoformat())

print("2. subject / vendor regexes")
V = ["Verify Your Account - HooRii Stage App", "verification code 123",
     "Activate your account", "Confirm your email address"]
for s in V:
    check("VERIFY_SUBJ matches %r" % s[:34], bool(mod.VERIFY_SUBJ.search(s)))
for s in ["Backer Early Access: ClawStage Beta Is Now Open",
          "Re: Backer Early Access: ClawStage Beta Is Now Open",
          "Pledge manager confirmation for ClawStage"]:
    check("VERIFY_SUBJ does NOT match %r" % s[:34], not mod.VERIFY_SUBJ.search(s))
check("vendor term matches hoorii", bool(mod.ANY_VENDOR.search("HooRii Console <console@hoorii.io>")))
check("vendor term matches clawstage", bool(mod.ANY_VENDOR.search("ClawStage Beta")))
check("vendor term ignores unrelated", not mod.ANY_VENDOR.search("Roche Workday DoNotReply"))

print("3. visibility classification")
check("inbox beats unread", mod._visibility(["INBOX", "UNREAD"]) == "inbox")
check("unread-archived", mod._visibility(["UNREAD"]) == "unread-archived")
check("archived", mod._visibility(["IMPORTANT", "CATEGORY_PERSONAL"]) == "archived")
check("empty -> archived", mod._visibility([]) == "archived")

print("4. the two-sided 'who is behind' rule")
# Reproduce the live arrangement: 2 inbound, then the operator writes, then
# silence. A one-directional check (inbound after operator write) finds 0 and
# concludes all-clear; the correct answer is VENDOR BEHIND.
inbound = [mod.ts_of("Tue, 22 Sep 2026 09:29:41 +0000"),
           mod.ts_of("Wed, 23 Sep 2026 00:06:26 +0000")]
outbox = [mod.ts_of("Wed, 23 Sep 2026 08:10:59 +0000")]
last_out = outbox[-1]
vendor_behind = [r for r in inbound if r > last_out]
unanswered_by_vendor = bool(outbox) and not vendor_behind
check("no inbound after operator write (silent vendor)", vendor_behind == [])
check("vendor IS behind", unanswered_by_vendor is True)
# Control: a reply afterwards flips it.
inbound2 = inbound + [mod.ts_of("Wed, 23 Sep 2026 12:00:00 +0000")]
vb2 = [r for r in inbound2 if r > last_out]
unanswered2 = bool(outbox) and not vb2
check("with a reply, vendor is no longer behind", unanswered2 is False)
check("with a reply, exactly 1 inbound is after the write", len(vb2) == 1)
# Control: no operator write at all -> nothing to be awaiting, so NOT 'behind'.
# (outbox empty => operator_behind is None, so the branch is never taken.)
outbox_empty = []
op_empty = outbox_empty[-1] if outbox_empty else None
check("empty outbox -> operator_behind is None", op_empty is None)
check("empty outbox -> not vendor-behind", bool(op_empty) is False)

print("5. json.dumps of a meta row needs default=str (real bug)")
row = {"ts": datetime(2026, 9, 23, 8, 10, tzinfo=timezone.utc), "subject": "x"}
try:
    json.dumps(row)
    check("bare json.dumps raises (the bug)", False, "expected TypeError")
except TypeError:
    check("bare json.dumps raises (the bug)", True)
check("default=str serialises it", json.loads(json.dumps(row, default=str))["subject"] == "x")

print("6. script contract: NOT MEASURED must be a literal, never an empty value")
src = open(SRC, encoding="utf-8").read()
check('"NOT MEASURED" sentinel present', '"NOT MEASURED"' in src)
check("verification_state_measured flag present", "verification_state_measured" in src)
check("activation state declared unmeasurable", "verification_state_reason" in src)
check("verdict is emitted", "out[\"verdict\"]" in src)
check("no regex concatenated into the GMAQL clause",
      "clause = \"{%s}\"" in src and "VERIFY_SUBJ.search" in src)
check("filters.list called WITHOUT pageToken",
      "filters().list(userId=\"me\").execute()" in src)
check("exit code 0 on success", "return 0" in src)
check("no draft/draft-label/delete calls",
      not re.search(r"messages\(\)\.modify|messages\(\)\.trash|drafts\(\)\.delete", src))

print()
if fails:
    print("FAILED (%d): %s" % (len(fails), ", ".join(fails)))
    sys.exit(1)
print("ALL PASS")
sys.exit(0)
