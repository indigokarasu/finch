#!/usr/bin/env python3
"""Fixture tests for elcamino_link_watch.py.

Run: python3 test_elcamino_link_watch.py   (EXIT 0 = all pass)

The regression these exist for is a REAL one measured 2026-09-26: the
watcher's Gmail query concatenated a Python regex containing '|' onto a
{from:X OR from:Y} clause. Gmail parses the bare '|' as OR, which dissolves
the intersection -- the query returned 4 messages, 3 of them from 2022, and
MISSED the very notice under investigation ("a new app was linked to your
account", 2026-09-23). A watcher that under-counts the thing it watches is
worse than no watcher, so the intersection is pinned here.
"""
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import elcamino_link_watch as W

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print("  PASS  %s" % name)
    else:
        print("  FAIL  %s %s" % (name, detail))
        FAILS.append(name)


print("== ts_of: never sort on the raw Date header ==")
# The exact regression pair from the EDD watcher: lexicographic max() picks
# the 2024 message over the 2026 one because '8' > '2'.
a = W.ts_of("Wed, 22 Sep 2026 08:58:02 -0700")
b = W.ts_of("Mon, 08 Jan 2024 22:15:38 -0800")
check("2026 parses after 2024", a > b, "(%s vs %s)" % (a, b))
check("monotonic under max()", max([b, a], key=lambda d: d) is a)
check("naive header gets UTC", W.ts_of("Wed, 23 Sep 2026 08:58:02").tzinfo is not None)
check("garbage header -> datetime.min", W.ts_of("not a date") == W.MIN_TS)
check("None header -> datetime.min", W.ts_of(None) == W.MIN_TS)

print("== LINK_SUBJ matches every real subject in the corpus ==")
REAL = [
    "Jared, a new device was linked to your account",      # 2026-09-23 08:58
    "Jared, a new app was linked to your account",         # 2026-09-23 00:15
    "New App Linked to your myCare Account",               # 18 of them
    "New Device Linked to your myCare Account",            # 2024-09-28
    "New Link to your myCare Account",                     # 2022
]
for s in REAL:
    check("matches %r" % s[:44], bool(W.LINK_SUBJ.search(s)))

print("== LINK_SUBJ does NOT match unrelated care mail ==")
UNRELATED = [
    "Jared, your visit is scheduled",
    "Jared, you have a new myCare message",
    "Notes from your visit at Privia Health are now available",
    "Winter News from El Camino Health Foundation",
    "Virtual Appointments Are Now Available",
    "You have a new message in myCare",
    "myCare Verification Code",
    "The mobile number for your myCare account has been updated",
]
for s in UNRELATED:
    check("rejects %r" % s[:44], not W.LINK_SUBJ.search(s))

print("== visibility() ==")
check("inbox", W.visibility(["INBOX", "UNREAD"]) == "inbox")
check("unread-archived", W.visibility(["UNREAD", "IMPORTANT"]) == "unread-archived")
check("archived", W.visibility(["IMPORTANT", "CATEGORY_PERSONAL"]) == "archived")

print("== the GMAQL bug this file exists for ==")
# Gmail's search grammar has no regex. Any '|' in a concatenated pattern is
# OR, so a {from:...} clause followed by such a pattern is no longer an
# intersection. The watcher must therefore scope by sender in GMAQL and
# filter the subject in Python. Assert the invariant that keeps that true.
check("LINK_SUBJ contains a bare '|' (so never concatenate it into GMAQL)",
      "|" in W.LINK_SUBJ.pattern)
check("watcher scopes by sender in GMAQL only",
      "allcare = q(clause)" in open(__file__.rsplit("/", 1)[0] + "/elcamino_link_watch.py").read()
      and 'q(clause + " " + LINK_SUBJ.pattern)' not in
          open(__file__.rsplit("/", 1)[0] + "/elcamino_link_watch.py").read())

print()
if FAILS:
    print("FAILED: %d -- %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("ALL PASS (%d assertions groups)" % (5 + len(REAL) + len(UNRELATED) + 3 + 2))
