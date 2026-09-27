#!/usr/bin/env python3
"""test_vendor_welcome_watch.py -- fixtures for vendor_welcome_watch.py.

Fixtures are built from the REAL subject strings / Date headers the live corpus
actually contained, not from the pattern under test: a fixture set written from the
pattern only ever proves the pattern matches itself.  Two of the cases below are
regressions for bugs this watcher had on first run.

Run:  python3 test_vendor_welcome_watch.py     # EXIT 0 = all pass
"""
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

os.environ.setdefault("VENDOR", "acme")
os.environ.setdefault("PREDRIP_SUBJECTS", "interested in teaching a course")

import vendor_welcome_watch as W

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(name)


print("=" * 78)
print("1) parse_ts -- regression: must NOT sort on the raw Date-header string")
# The exact pair that inverted the ordering: '8' > '2' lexicographically.
a = W.parse_ts("8 Jan 2024 22:15:38 -0800")
b = W.parse_ts("22 Sep 2026 06:24:27 -0700")
check("2024 header parses", a.year, 2024)
check("2026 header is NEWER than 2024 (string sort gets this backwards)",
      b > a, True)
check("raw string sort WOULD have failed (proves the bug is real)",
      "8 Jan 2024 22:15:38 -0800" > "22 Sep 2026 06:24:27 -0700", True)
check("naive header gets UTC attached", W.parse_ts("Fri, 25 Sep 2026 00:43:23 -0700").tzinfo is not None, True)
check("unparseable -> aware datetime.min (no subtraction TypeError)",
      W.parse_ts("garbage") == datetime.min.replace(tzinfo=timezone.utc), True)
check("empty string -> aware datetime.min", W.parse_ts("").tzinfo is not None, True)

print()
print("2) PREDRIP filter -- the stale 2022 vendor thread must be excluded")
predrip = ["Re: Interested in teaching a course?", "Interested in teaching a course?"]
drip = ["Your roadmap to building on Acme", "Book your Acme welcome session",
        "Welcome to Acme! Important info inside", "Verify your email for Acme",
        "Learn directly from Annie Duke"]
is_predrip = lambda s: any(p in s.lower() for p in W.PREDRIP)
check("2 of 7 real subjects classified pre-drip",
      sum(1 for s in predrip + drip if is_predrip(s)), 2)
check("'Re: Interested in teaching a course?' is pre-drip",
      is_predrip("Re: Interested in teaching a course?"), True)
check("'Book your Acme welcome session' is NOT pre-drip",
      is_predrip("Book your Acme welcome session"), False)

print()
print("3) config is env-overridable so the published repo carries no real vendor")
check("VENDOR read from env", W.VENDOR, "acme")
check("DOMAINS derives from VENDOR", W.DOMAINS, ("acme.com",))
check("FROM_QUERIES are server-side from: scopes", W.FROM_QUERIES, ("from:acme.com",))
check("no pageToken baked into any query", any("pageToken" in q for q in W.FROM_QUERIES), False)

print()
print("4) verdict() -- regression: OUTBOUND must be 0, not the 2022 thread")
NOW = datetime(2026, 9, 26, 23, 0, tzinfo=timezone.utc)


def row(subj, raw_date, age, inbox, unread=False):
    return {"subject": subj, "date_raw": raw_date, "age_days": age,
            "in_inbox": inbox, "unread": unread, "ts": NOW}


base = {"drip": [row("Your roadmap to building on Acme", "Sat, 26 Sep 2026 00:43:23 +0000", 0.93, False)],
        "self_opened": True, "grant": {"date_raw": "Mon, 21 Sep 2026 17:46:48 -0700",
                                       "subject": "You shared some Google Account data with Acme"},
        "shadowing_filters": 0, "filter_count": 19, "outbound": [],
        "calendar_events_scanned": 16666, "calendar_vendor_events": []}

v = W.verdict(base)
check("self-opened origin reported", "ORIGIN=SELF-OPENED" in v, True)
check("outbound 0", "OUTBOUND=0" in v, True)
check("no INBOX residue -> anti_churn", "anti_churn" in v, True)
check("0 of 16666 calendar events", "SESSION_ON_CALENDAR=0 (of 16666 events scanned)" in v, True)
check("newest is the 0.93d newsletter", "'Your roadmap to building on Acme'" in v, True)

inbound = {**base, "self_opened": False, "grant": None}
check("absent grant -> INBOUND", "ORIGIN=INBOUND" in W.verdict(inbound), True)

dirty = {**base, "drip": [row("Book your Acme welcome session", "Thu, 24 Sep 2026 00:43:18 +0000", 2.93, True, True)]}
check("INBOX residue -> 'genuinely untriaged'", "genuinely untriaged" in W.verdict(dirty), True)

shadowed = {**base, "shadowing_filters": 1}
check("shadowing filter suppresses the anti_churn call",
      "anti_churn" in W.verdict(shadowed), False)

print()
print("5) verdict() survives an EMPTY corpus (no IndexError on newest=None)")
empty = {**base, "drip": [], "calendar_vendor_events": []}
ve = W.verdict(empty)
check("empty corpus -> NEWEST=none", "NEWEST=none" in ve, True)
check("empty corpus still yields a verdict", ve.startswith("ORIGIN=SELF-OPENED"), True)

print()
print("6) filters() call shape -- unpaginated, takes userId and NO pageToken")
# NOTE: the list mocks must return real dicts.  A bare MagicMock makes
# r.get("nextPageToken") truthy, so sweep()'s paging loop never terminates.
EMPTY_PAGE = {"messages": [], "nextPageToken": None}


def make_svc():
    svc = MagicMock()
    lst = svc.users.return_value.messages.return_value.list.return_value
    lst.execute.return_value = EMPTY_PAGE
    svc.users.return_value.settings.return_value.filters.return_value.list.return_value.execute.return_value = {
        "filter": [{"criteria": {"from": "mail.notion.so"}}]}
    return svc


def make_cal():
    cal = MagicMock()
    # Must configure the FULL call chain cal.events().list(...).execute() -- a
    # partially-configured mock hands .execute() a truthy MagicMock, and
    # .get("nextPageToken") is then truthy, so the paging loop spins forever.
    cal.events.return_value.list.return_value.execute.return_value = {
        "items": [], "nextPageToken": None}
    return cal


svc = make_svc()
W.analyse(svc, make_cal())
_, kwargs = svc.users.return_value.settings.return_value.filters.return_value.list.call_args
check("userId='me' passed", kwargs.get("userId"), "me")
check("NO pageToken passed (TypeError if it were)", "pageToken" in kwargs, False)
check("analyse() returns on an empty corpus", isinstance(W.analyse(svc, make_cal()), dict), True)

print()
print("=" * 78)
if FAILS:
    print(f"FAILED {len(FAILS)}: {FAILS}")
    sys.exit(1)
print("ALL PASS")
sys.exit(0)
