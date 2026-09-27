#!/usr/bin/env python3
"""Fixtures for officehours_panel_watch.py, built from the REAL corpus subjects
observed 2026-09-26 (45 panel messages, 2025-08..2026-09). A fixture set written
from the pattern under test only proves the pattern matches itself."""
import sys
import os
from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import officehours_panel_watch as w

FAILS = []


def ck(cond, name):
    if cond:
        print("  PASS %s" % name)
    else:
        print("  FAIL %s" % name)
        FAILS.append(name)


# --- subject filter, real subjects (including the historical 'Follow Up:'
#     phrasing that a `re:`-anchored pattern would miss) ---
# --- sender gate is the filter; the SUBJECT gate was removed and the fixtures
#     are what proved it. Both failure directions are pinned here. ---
ck(w.panel_sender("Kai Seed <kai@onboarding.officehours.com>"), "gate: real sender")  # pii-allow: fixture asserts on a real sender shape
ck(w.panel_sender("Cari Miller <cari@officehours.com>"), "gate: parent domain")  # pii-allow: fixture asserts on a real sender shape
ck(not w.panel_sender("Field House at Bay Meadows <pm@fieldhousesm.com>"), "gate: unrelated 2016 sender")  # pii-allow: fixture asserts on a real sender shape
ck(not w.panel_sender("Projector <hello@projector.com>"), "gate: projector.com 2021")  # pii-allow: fixture asserts on a real sender shape

# The defect the fixtures caught: is_panel MISSED real panel mail that carries
# none of the subject keywords, and would have matched unrelated non-panel mail
# if applied to a subject-only corpus. Sender-domain scoping replaces it.
ck(not w.is_panel("Re-connecting on AI Compute Hardware Selection research"),
   "REGRESSION: subject gate misses real panel mail (reason it was replaced)")
ck(not w.is_panel("Holiday Office Hours"),
   "REGRESSION: the only defect in is_panel is the MISS direction")
# The sender gate is strictly wider than the subject gate (47 vs 45 live
# messages): two from-domain messages carry none of the subject keywords.
# Wider is the correct direction here -- under-counting the thing you watch
# manufactures false confidence -- so the count is reported from the sender gate.

# --- the parsed-timestamp regression: a 2024 message must never beat a 2026 one ---
jan8 = {"Date": format_datetime(datetime(2024, 1, 8, 22, 15, 38, tzinfo=timezone.utc))}
sep22 = {"Date": format_datetime(datetime(2026, 9, 22, 6, 24, 27, tzinfo=timezone.utc))}
ck(w._ts(sep22) > w._ts(jan8), "REGRESSION: parsed sort puts 2026 above 2024 (raw-string sort inverts this)")
ck(w._ts(jan8) < w._ts(sep22), "REGRESSION: inverse direction")
ck(w._ts({}) == datetime.min.replace(tzinfo=timezone.utc), "unparseable Date -> tz-aware datetime.min, no exception")
ck(w._ts({"Date": "garbage"}) == datetime.min.replace(tzinfo=timezone.utc), "garbage Date -> datetime.min")
naive = {"Date": format_datetime(datetime(2026, 9, 26, 12, 0, 0))}
ck(w._ts(naive).tzinfo is not None, "naive header gets a tz so subtraction cannot raise")

# --- verdict branches ---
base = [{"id": "a", "subj": "s", "labels": ["CATEGORY_PROMOTIONS"], "ts": w._ts(sep22)}]
ck("routine" in w.verdict(base, [1], [], 0), "verdict: 0 inbox -> routine")
ck("OUTSTANDING" in w.verdict([dict(base[0], labels=["INBOX"])], [], [], 0), "verdict: INBOX -> OUTSTANDING")
ck("1 unread" in w.verdict([dict(base[0], labels=["UNREAD"])], [], [], 0),
   "verdict: UNREAD alone is read-state, not outstanding")
ck("OUTSTANDING" in w.verdict([dict(base[0], labels=["INBOX", "UNREAD"])], [], [], 0),
   "verdict: INBOX+UNREAD -> outstanding")

# --- pagination: a partially-configured mock makes .get('nextPageToken') truthy
#     and hangs the loop forever; the full chain must be configured. ---
svc = MagicMock()
svc.users().messages().list.return_value.execute.side_effect = [
    {"messages": [{"id": "1"}], "nextPageToken": "T1"},
    {"messages": [{"id": "2"}], "nextPageToken": None},
]
ck(w._pages(svc, "x") == ["1", "2"], "pagination: loops to completion, returns bare ids")
bad = MagicMock()
bad.users().messages().list.return_value.execute.return_value = {"messages": [{"id": "1"}]}
print("\n%d failure(s): %s" % (len(FAILS), FAILS or "none"))
sys.exit(1 if FAILS else 0)
