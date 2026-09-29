#!/usr/bin/env python3
"""finch_ledger_guard.py -- creation-time assertion for the finch task ledger.

WHY THIS EXISTS
---------------
`task-list.json` stamps its own fields (`as_of`, `updated_at`, per-task
`created_at`/`done_at`/`last_finch_review`). A stamp later than the file's own
mtime is impossible: a run cannot review itself at a time it has not reached
yet. Such a stamp silently corrupts scan ordering and every "last reviewed"
claim built on it -- a false-completion variant that reads in the OPTIMISTIC
direction.

CONFIRMED ROOT CAUSE (2026-09-26): the stamp was taken from the scheduler's
PLANNED slot rather than from `datetime.now()` at write. A ledger written at
17:39:03Z carried `as_of=18:30:00Z`, which is exactly the `next_run_at` of
`finch:work` in the live registry. The scheduler publishes the next slot in the
registry, so it is a plausible value to reach for by mistake.

Because the writers are ad-hoc per-run scripts (no single choke point), a
correction to one pass does not survive the next. This guard is that choke
point: it must run BEFORE a ledger write is believed, and it can repair what
is already on disk.

USAGE
-----
    python3 finch_ledger_guard.py                 # validate only, exit 1 on violation
    python3 finch_ledger_guard.py --json          # machine-readable, *_measured flags
    python3 finch_ledger_guard.py --repair        # clamp forward stamps down to mtime

REPAIR SEMANTICS
----------------
A forward stamp is clamped DOWN TO THE FILE MTIME, never up to `now()`. The mtime
is the last moment the content is known to have existed; `now()` would be a
second fabrication. Every repair is reported with its delta so a later pass can
see what was rewritten.

EXIT CODES
----------
    0  no forward stamps (or --repair applied cleanly)
    1  LEDGER forward stamps present and not repaired
    2  ledger unreadable / not JSON

THE MTIME-LAUNDERING BLIND SPOT (fixed 2026-09-27, finch:work #204)
---------------------------------------------------------------------
This guard compares each stamp to the file's CURRENT mtime. That reference is
itself an artifact of the file, so a LATER write launders an EARLIER violation:

    finch:work #203 wrote the ledger at 07:39:45Z stamping fields 07:50:00Z
      -> forward by +615s, real violation, guard exit 1 (measured 07:58Z)
    finch:scan #956 then rewrote the SAME ledger at 07:58:25Z, copying the
    07:50:00Z values through unchanged
      -> mtime is now 8m40s PAST the stamp, so the same bytes read as clean
      -> guard exit 0. The defect was never repaired; it was made invisible
         by the very pass that ran this guard.

Proven, not assumed: the live file and a copy of it with its mtime set back to
07:39:45Z are BYTE-IDENTICAL and hold the same 07:50:00Z strings, yet the copy
reports 25 forward stamps and the live file reports 0. The only difference is
the mtime. See finch:work #204's work log.

The fix is a RECEIPT: an append-only `<ledger>.guard-receipts.jsonl` recording,
for every run, the mtime observed, the sha256 of the exact bytes read, and
every forward stamp found. A later run replays the receipts and reports a
stamp LAUNDERED when the same (id, field, value) is still in the file, was
flagged against an EARLIER mtime, and was never changed since -- which is the
signature of a rewrite that copied the stamp through instead of repairing it.

This finding is NOT the historical-journal class below. A laundered stamp has a
repair path (`--repair` clamps it, the value changes, the receipt retires), so
it earns exit 1 and clears on its own. Journal self-stamps have no repair path
at all, so exit-coding them would pin a clean ledger at non-zero forever. The
distinction is not convenience: it is whether a writer can do anything about it.

WHAT JOURNAL FINDINGS DO *NOT* DO TO THE EXIT CODE
--------------------------------------------------
The journal self-stamp check (added 2026-09-26) reports 24 of 275 action
journals naming a moment later than their own mtime. They are HISTORICAL and
there is no journal repair path, so no caller can ever clear them. Folding them
into the exit code -- whether as 1 or as a separate 3 -- was tried and reverted:
it makes a genuinely CLEAN ledger return non-zero forever, so callers learn to
ignore the code, which is exactly how a guard stops guarding. My own test suite
caught it (cases 4 and 5, "clean ledger must PASS", went red).

The rule the fix settles: the EXIT CODE answers only "must a writer act on the
ledger?" Journal findings are REPORTED (text + `self_stamp_forward` in --json)
so nothing is hidden, but they never touch the code. A coverage claim belongs in
the report; an action claim belongs in the exit code.
"""

import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import sys
from collections import Counter

# Resolve the ledger from the environment or the script's own location -- never
# from a hardcoded host path. A committed absolute path is both a PII leak (this
# repo is public) and wrong on every machine but the author's.
#
#   FINCH_LEDGER   explicit ledger override, wins over everything
#   HERMES_ROOT / HERMES_HOME   the install root, same as the rest of this repo
#   fallback       walk up from the script: <install>/profiles/<name>/skills/
#                  <skill>/scripts/ -> the profile root holding commons/
_HERE = os.path.dirname(os.path.abspath(__file__))


def _hermes_roots():
    """Candidate install roots, most explicit first. Empty when none is set."""
    roots = []
    for var in ("HERMES_ROOT", "HERMES_HOME"):
        val = os.environ.get(var)
        if val:
            roots.append(os.path.expanduser(val))
    return roots


def _under(root, *parts):
    return os.path.join(root, *parts)


_CANDIDATE_DIRS = (
    [d for r in _hermes_roots()
     for d in (_under(r, "commons", "data", "ocas-finch"),
               _under(r, "profiles", os.environ.get("HERMES_PROFILE", ""), "commons",
                      "data", "ocas-finch") if os.environ.get("HERMES_PROFILE") else None)]
    + [_under(_HERE, "..", "..", "..", "commons", "data", "ocas-finch"),
       _under(_HERE, "..", "..", "..", "..", "commons", "data", "ocas-finch")]
)
_CANDIDATE_DIRS = [d for d in _CANDIDATE_DIRS if d]

_JOURNAL_DIRS = (
    [d for r in _hermes_roots()
     for d in (_under(r, "commons", "journals", "ocas-finch"),
               _under(r, "profiles", os.environ.get("HERMES_PROFILE", ""), "commons",
                      "journals", "ocas-finch") if os.environ.get("HERMES_PROFILE") else None)]
    + [_under(_HERE, "..", "..", "..", "commons", "journals", "ocas-finch"),
       _under(_HERE, "..", "..", "..", "..", "commons", "journals", "ocas-finch")]
)
_JOURNAL_DIRS = [d for d in _JOURNAL_DIRS if d]

UTC = datetime.timezone.utc
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
# A timestamp PLUS its offset, so isolating a stamp from a trailing
# ' (finch:scan #N)' cannot truncate the offset away again. `TS_RE` matches
# only the 19 naive characters; matching it and re-using `.group(0)` is the
# original bug reproduced inside the fix, which is exactly how the offset fix
# appeared to pass and then did not.
_STAMP_WITH_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?")

# Top-level fields that claim to describe THIS ledger's current state.
HEADER_FIELDS = ("as_of", "last_scan_at", "scan_cycle", "updated_at", "last_work_at")
# Dotted paths that carry the same claim one level down. The header records the
# same instant TWICE, in two forms, and each form used to defeat the guard
# differently: `last_scan.at` is nested so a flat `if k not in doc` walk skips
# it silently, and it is the form scan writers emit in Z. Coverage is
# therefore the union -- a field is checked if EITHER shape carries it.
NESTED_HEADER_FIELDS = ("last_scan.at",)
# Per-task fields that assert a moment in time.
TASK_FIELDS = ("created_at", "updated_at", "done_at", "last_finch_review")


def _resolve(dirs, extra=None):
    """Return the first existing directory, else the legacy path, else None."""
    for c in list(dirs) + ([extra] if extra else []):
        if c and os.path.isdir(c):
            return os.path.abspath(c)
    return None


def _env_ledger():
    """An explicit FINCH_LEDGER override, expanded. None when unset."""
    val = os.environ.get("FINCH_LEDGER")
    return os.path.expanduser(val) if val else None


def _parse(v):
    """Parse a ledger timestamp to an aware UTC datetime, or None.

    FIXED 2026-09-28 (finch:work #231). The previous body was
    `fromisoformat(v[:19]).replace(tzinfo=UTC)`: it truncated to the first 19
    characters and FORCED UTC, discarding any offset the writer emitted. For a
    `-07:00` stamp that is a 7-hour error in the SAFE direction -- the true
    instant is read as 7h earlier, so a stamp 43 minutes FORWARD of the file
    mtime measured as -22631s and reported clean. Verified: the header of the
    live ledger carried exactly that shape and the guard exited 0 on it.

    The correct parser was ALREADY in this file for the journal-coherence path
    (`_parse_offset`, ~40 lines below) and was simply not used here. Delegate
    to it rather than writing a third variant -- the defect was two readings of
    one rule, and a third reading would recreate it.

    A NAIVE stamp (no offset) is still read as UTC, unchanged: the ledger
    format has always been UTC, and defaulting it to the host's local zone
    would re-open the same class of error from the other side.

    The Suffix guard below is load-bearing and was found by the regression suite
    rather than by reading. The old `v[:19]` truncation happened to tolerate the
    ' (finch:scan #N)' suffix that `last_finch_review` carries; handing the
    WHOLE string to `fromisoformat` makes it raise, so delegating naively made
    every suffixed task stamp unparseable -- and an unparseable forward stamp
    is a MISSED violation, the same safe-direction false negative in a new
    place. So the timestamp is isolated first, then handed over.
    """
    if not isinstance(v, str):
        return None
    m = _STAMP_WITH_OFFSET_RE.match(v)
    if not m:
        return None
    return _parse_offset(m.group(0))


def _resolve_field(doc, path):
    """Resolve a flat-or-dotted field path to (found, value).

    `as_of` is a top-level key; `last_scan.at` is one level down. Both are
    ledger header stamps and the guard must read both, so every lookup goes
    through here rather than through a bare `in doc` membership test. Setting
    is done by the caller, which owns the container it wants to mutate.
    """
    if not isinstance(doc, dict):
        return False, None
    if path in doc:
        return True, doc[path]
    parts = path.split(".")
    node = doc
    for p in parts[:-1]:
        if not isinstance(node, dict) or p not in node:
            return False, None
        node = node[p]
    leaf = parts[-1]
    if isinstance(node, dict) and leaf in node:
        return True, node[leaf]
    return False, None


def _set_field(doc, path, value):
    """Write a flat-or-dotted field path in place. Returns True if written."""
    if not isinstance(doc, dict):
        return False
    if path in doc:
        doc[path] = value
        return True
    if "." not in path:
        return False
    parts = path.split(".")
    node = doc
    for p in parts[:-1]:
        if not isinstance(node, dict) or p not in node:
            return False
        node = node[p]
    if isinstance(node, dict) and parts[-1] in node:
        node[parts[-1]] = value
        return True
    return False


def check(ledger_path=None, journal_dir=None, now=None):
    """Validate the ledger. Never raises on ledger content; returns a report dict."""
    now = now or datetime.datetime.now(UTC)
    rep = {"ledger": None, "ledger_found": False, "ledger_error": None,
           "mtime_utc": None, "now_utc": now.isoformat(),
           "header": [], "task_fields": [], "journals": {},
           "ledger_clock_measured": False, "journals_measured": False,
           "forward_count": 0}

    path = ledger_path
    if path is None:
        d = _resolve(_CANDIDATE_DIRS)
        path = _env_ledger() or (os.path.join(d, "task-list.json") if d else None)
    rep["ledger"] = path

    if path is None:
        rep["ledger_error"] = ("no ledger resolvable -- set FINCH_LEDGER or "
                               "HERMES_ROOT, or pass --ledger")
        return rep

    try:
        with open(path) as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        rep["ledger_error"] = "ledger not found"
        return rep
    except json.JSONDecodeError as e:
        rep["ledger_error"] = "JSONDecodeError: %s" % e
        return rep
    except OSError as e:
        rep["ledger_error"] = "OSError: %s" % e
        return rep

    rep["ledger_found"] = True
    mt = os.path.getmtime(path)
    mtu = datetime.datetime.fromtimestamp(mt, UTC)
    rep["mtime_utc"] = mtu.isoformat()
    rep["ledger_clock_measured"] = True
    rep["sha256"] = _file_sha256(path)

    # --- header fields -----------------------------------------------------
    # Coverage is the UNION of flat and dotted paths, so the same instant
    # recorded as `last_scan_at` and as `last_scan.at` is checked twice rather
    # than once-and-silently-skipped. A `k not in doc` skip is fine for an
    # absent field and wrong for a present one at another depth: the guard read
    # as "this field is clean" when it had never looked.
    for k in HEADER_FIELDS + NESTED_HEADER_FIELDS:
        found, val = _resolve_field(doc, k)
        if not found:
            continue
        t = _parse(val)
        if t is None:
            continue
        delta = (t - mtu).total_seconds()
        rep["header"].append({"field": k, "value": val,
                              "delta_s": round(delta, 1), "forward": delta > 0})

    # --- per-task fields ---------------------------------------------------
    for task in doc.get("tasks", []) or []:
        tid = task.get("id", "<no-id>")
        for k in TASK_FIELDS:
            t = _parse(task.get(k))
            if t is None:
                continue
            delta = (t - mtu).total_seconds()
            if delta > 0:  # only forward stamps are violations; old review
                rep["task_fields"].append({"id": tid, "field": k,  # stamps are
                                           "value": task[k],         # normal, and
                                           "delta_s": round(delta, 1)})  # only
    rep["forward_count"] = sum(1 for h in rep["header"] if h["forward"]) \
        + len(rep["task_fields"])

    # --- laundered stamps (mtime moved past an unrepaired violation) --------
    # Runs BEFORE the receipt is appended, so a run never launders itself.
    rep["laundered"], rep["launder_meta"] = laundered_stamps(rep)
    rep["laundered_count"] = len(rep["laundered"])

    # --- journal coherence -------------------------------------------------
    rep["journals"] = _journal_coherence(journal_dir, now=now)
    rep["journals_measured"] = bool(rep["journals"].get("measured"))
    return rep


# ---------------------------------------------------------------------------
# RECEIPTS -- the witness that survives the mtime laundering (#204)
# ---------------------------------------------------------------------------
# Without this, the ONLY record of a violation is the exit code of a run whose
# reference clock is the very file it is judging. A later write moves that
# reference and the violation stops being visible, so the defect is repaired by
# nothing and closed by nothing. The receipt is that record: append-only, so no
# later pass can silently rewrite it, and it stores the mtime the run actually
# judged against rather than re-deriving one.
#
#   sha256 -- binds the receipt to the exact bytes that were read. Without it a
#             receipt could be attributed to a file that never held those
#             stamps, which is precisely the false-completion direction.
#   delta_s -- the violation's size at the moment it was caught, so a later run
#             can show the ORIGINAL magnitude even though the stamp now looks
#             backward relative to the current mtime.


def _receipt_path(ledger_path):
    return ledger_path + ".guard-receipts.jsonl"


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _stamp_key(scope, ident, field, value):
    """Identity of a single stamped value, independent of the file's mtime."""
    return "%s|%s|%s|%s" % (scope, ident, field, value)


def append_receipt(rep):
    """Append one receipt line for this run. Never raises into the caller.

    A failure to write the receipt must not change the guard's verdict -- but it
    IS reported, because silently losing the witness is how this blind spot
    came back. That is the same rule as the exit code: report what a writer can
    act on, act on nothing silently.
    """
    path = _receipt_path(rep["ledger"])
    forward = ([{"scope": "header", "id": "-", "field": h["field"],
                 "value": h["value"], "delta_s": h["delta_s"]}
                for h in rep["header"] if h["forward"]]
               + [{"scope": "task", "id": t["id"], "field": t["field"],
                   "value": t["value"], "delta_s": t["delta_s"]}
                  for t in rep["task_fields"]])
    line = {
        "at": rep["now_utc"],
        "ledger_sha256": rep.get("sha256"),
        "mtime_utc": rep["mtime_utc"],
        "forward": forward,
        "forward_count": len(forward),
    }
    try:
        with open(path, "a") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        return None
    except OSError as e:
        return "receipt append failed: %s" % e


def read_receipts(ledger_path):
    """All receipts, oldest first. Unparseable lines are skipped and counted."""
    path = _receipt_path(ledger_path)
    out, bad = [], 0
    if not os.path.exists(path):
        return out, bad
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    return out, bad


def laundered_stamps(rep):
    """Stamps a LATER write made invisible by advancing the file's mtime.

    A stamp is LAUNDERED when all three hold:
      1. a receipt recorded it forward against some mtime M;
      2. M is EARLIER than the current mtime -- otherwise it is still
         forward and the ordinary check already caught it;
      3. the exact same value is STILL in the file, unchanged, right now.

    (3) is what makes this safe. A stamp that was genuinely repaired changes
    value, so it retires its receipt. A stamp that was merely overwritten by a
    newer, honest pass also changes value. Only one that a later pass copied
    THROUGH verbatim -- repairing nothing -- keeps matching.
    """
    receipts, bad = read_receipts(rep["ledger"])
    if not receipts:
        return [], {"receipts": 0, "unparseable": bad, "receipt_path": _receipt_path(rep["ledger"])}

    try:
        cur_mt = datetime.datetime.fromisoformat(rep["mtime_utc"])
    except (TypeError, ValueError):
        return [], {"receipts": len(receipts), "unparseable": bad,
                    "receipt_path": _receipt_path(rep["ledger"])}

    # Current value of every stamp in the file, keyed the same way.
    present = {}
    for h in rep["header"]:
        present[_stamp_key("header", "-", h["field"], h["value"])] = True
    for t in rep["task_fields"]:
        present[_stamp_key("task", t["id"], t["field"], t["value"])] = True

    # Receipts only see FORWARD stamps (that is all they record), so a stamp
    # currently forward is in `present` only if it is in rep["task_fields"].
    # For the header, rep["header"] holds every parsed header field, forward or
    # not, so both branches are covered by the same loop above.
    with open(rep["ledger"]) as fh:
        doc = json.load(fh)
    for k in HEADER_FIELDS:
        v = doc.get(k)
        if isinstance(v, str):
            present.setdefault(_stamp_key("header", "-", k, v), True)
    for task in doc.get("tasks", []) or []:
        for k in TASK_FIELDS:
            v = task.get(k)
            if isinstance(v, str):
                present.setdefault(_stamp_key("task", task.get("id", "<no-id>"), k, v), True)

    hits, seen = [], set()
    for r in receipts:
        try:
            rmt = datetime.datetime.fromisoformat(r["mtime_utc"])
        except (TypeError, ValueError, KeyError):
            continue
        if rmt >= cur_mt:
            continue  # measured against this same mtime: ordinary check owns it
        for f in r.get("forward", []):
            key = _stamp_key(f.get("scope"), f.get("id"), f.get("field"), f.get("value"))
            if key in present and key not in seen:
                seen.add(key)
                hits.append({"id": f.get("id"), "field": f.get("field"),
                             "value": f.get("value"),
                             "flagged_at_mtime": r["mtime_utc"],
                             "flagged_by": r.get("at"),
                             "original_delta_s": f.get("delta_s"),
                             "laundered_by_s": round((cur_mt - rmt).total_seconds(), 1)})
    return hits, {"receipts": len(receipts), "unparseable": bad,
                  "receipt_path": _receipt_path(rep["ledger"])}


# Journal self-timestamp keys, in priority order. A journal names the moment it
# ran; that moment cannot be later than the file's own mtime. Same invariant as
# the ledger header, applied to the Action Journal the SKILL.md requires.
_SELF_STAMP_KEYS = ("timestamp", "as_of", "started_at", "scan_cycle")
# Tolerate small filesystem/clock skew, and a writer that truncates to the
# minute and commits a few seconds before the second hand catches up.
_SKEW_TOLERANCE_S = 60
# How far a self-stamp's digits may sit BEHIND its own mtime and still read as
# "the named moment was a real moment just before the commit". A run writes its
# journal at the END, so a start stamp normally lands minutes to an hour before
# the file's mtime. Four hours is loose on purpose: the question is not "how long
# did the run take" but "could these digits be a UTC wall clock", and a
# timestamp that is 5h behind the commit cannot be that. A run that genuinely
# takes longer than this still reads as clock-forward, which is the safe
# direction -- it keeps the stamp in the bucket a reviewer must look at.
_SELF_STAMP_COHESION_WINDOW_S = 4 * 3600
# The forward end of the same window reuses the skew tolerance: digits may sit
# at most _SKEW_TOLERANCE_S ahead of the commit before "digits are UTC" stops
# being a coherent story.
_SELF_STAMP_SKEW_TOLERANCE_S = _SKEW_TOLERANCE_S
# Age at which a forward self-stamp stops being "a writer is still doing it".
# One day is chosen against the cadence of the thing that writes journals, not
# against a round number: finch:work runs every 30 min, so anything under a few
# hours is a run in flight or just finished. The report uses this to say how many
# members of the set are live rather than asserting the whole set is historical.
_SELF_STAMP_RECENT_S = 24 * 3600
# Filename prefixes by NAMESPACE. `work-*` journals carry a scan_number that is
# NOT their own -- it is the scan they executed AGAINST (see work-0258.json
# #144). Sorting those into a scan-number monotonicity series is a category
# error: a number can legitimately sit between two scan numbers.
_JOURNAL_NAMESPACES = ("scan", "work", "daily", "weekly", "finch-work")
# A scan number, wherever it appears in a journal. The digit bound is loose on
# purpose: the series is at 176 and climbing, and a 2-3 digit bound silently
# drops every number outside it -- a coverage number derived from a partial
# match is the same false-completion class as a summary that hides a second
# page. Both the guard and finch_scan_counter MUST use this same pattern, or
# the two tools disagree about which numbers exist (that drift is what left
# the allocator blind to 26 numbers on 2026-09-27).
_PROSE_NUM_RE = re.compile(r"finch:scan\s*#\s*(\d{1,4})\b")


def _journal_namespace(path):
    """Return the journal's namespace, or None if unrecognised."""
    base = os.path.basename(path)
    for ns in _JOURNAL_NAMESPACES:
        if base.startswith(ns + "-"):
            return ns
    return None


def _parse_offset(v):
    """Parse a timestamp that may carry a UTC offset, to aware UTC."""
    if not isinstance(v, str):
        return None
    m = TS_RE.match(v)
    if not m:
        return None
    try:
        dt = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _offset_tag(v):
    """The offset suffix on a stamp, or 'Z' / None for a Z or naive stamp.

    The distinction is load-bearing, not cosmetic. A stamp tagged 'Z' or
    '+00:00' has no tag to be wrong about, so if it is forward the CLOCK is
    forward and the only possible cause is the writer. A stamp carrying a
    LOCAL offset has a tag that can disagree with its own digits, and that
    disagreement is a separate, much more common defect.
    """
    if not isinstance(v, str):
        return None
    s = v[10:]
    if s.endswith("Z"):
        return "Z"
    if "+" in s:
        return "+" + s.split("+", 1)[1]
    if "-" in s:
        return "-" + s.split("-", 1)[1]
    return None


# A tag equal to the writer's own local offset, as opposed to a zero offset.
# A local tag means the digits are LOCAL by the stamp's own claim, so the
# question becomes whether they are local-but-forward (a real forward clock)
# or local-shaped-but-actually-UTC (a mislabelled tag).
def _tag_is_local(tag):
    return bool(tag) and tag not in ("Z", "+00:00")


def _attribute_self_stamp(value, jmt):
    """Decide WHY a self-stamp is forward. Returns (cause, digits_as_utc_s).

    Two causes, discriminated by the TAG, never by the digits alone:

      offset-tag-mislabelled  the digits are UTC; the local offset tag lies.
                              Read as written the stamp jumps a whole
                              timezone forward. Corroborated 2026-09-28
                              against the guard's own receipt log -- a clock
                              written by a different process -- which places
                              the run 8.6 min BEFORE its own commit, so
                              reading the tag as written is the error.

      clock-forward           the stamp really is ahead of the file. Nothing
                              to excuse it: either the clock moved or a later
                              writer touched the file. Reported as-is.

    The discrimination is deliberately asymmetric. A local tag on a forward
    stamp is enough to suspect a mislabel, but the stamp is only RELABELLED
    when its digits read back coherently as UTC against the file's own mtime
    -- i.e. within a window in which "started at HH:MM, committed minutes
    later" is the ordinary case. Outside that window the tag is the more
    likely error and the cause stays clock-forward, so a real forward stamp is
    never quietly absorbed into the mislabel bucket. That asymmetry matters
    because the mislabel bucket is the one a reviewer reads as benign.
    """
    tag = _offset_tag(value)
    if not _tag_is_local(tag):
        return "clock-forward", None
    # Digits read back as if they were UTC, ignoring the tag entirely.
    try:
        naive = datetime.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return "clock-forward", None
    digits_utc = naive.replace(tzinfo=UTC)
    delta = (digits_utc - jmt).total_seconds()
    if -_SELF_STAMP_COHESION_WINDOW_S <= delta <= _SELF_STAMP_SKEW_TOLERANCE_S:
        return "offset-tag-mislabelled", round(delta, 1)
    return "clock-forward", None


def _journal_coherence(journal_dir, now=None):
    """Measure journal self-stamps and scan-number monotonicity.

    FIXED 2026-09-26: the previous implementation globbed only `scan-*.json`
    and so could not see the 24 journals whose own `timestamp`/`as_of` is later
    than their mtime -- while still reporting `measured: true`. A coverage claim
    is a claim about the read, not about the world. Two further defects: it
    never checked a journal's OWN timestamp, and it folded `work-*` journals
    into the scan series even though their scan_number references another run.

    FIXED 2026-09-28 (finch:work #232): each self-stamp now carries the CAUSE
    of its forwardness. Measured against the live corpus: 27 forward, of which 3
    carry a local offset tag whose digits are UTC, so reading the tag as
    written moves them a whole timezone forward -- and one of the 3 is 1.2h
    old, written by a run that was still executing. The report also stopped
    calling the whole set "historical". A 4th candidate
    (2026-09-23/work-1755.json) was REJECTED: its digits read back 279s AFTER
    the commit, past the 60s skew tolerance, so the mislabel is not the only
    story and it stays clock-forward. The stricter reading is deliberate --
    see _attribute_self_stamp.
    """
    jd = journal_dir or _resolve(_JOURNAL_DIRS)
    if not jd:
        return {"measured": False, "note": "NOT MEASURED -- journal dir not resolvable"}
    files = sorted(glob.glob(os.path.join(jd, "**", "*.json"), recursive=True))
    if not files:
        return {"measured": False, "note": "NOT MEASURED -- no *.json found"}

    by_ns, self_stamp_fwd, skipped = {}, [], 0
    now = now or datetime.datetime.now(UTC)
    # A stamp on a file younger than this is a writer that is still running, not
    # a historical artefact. Kept as a separate count so the report cannot call
    # the whole set "historical" while its newest member is an hour old.
    recent_cutoff_s = _SELF_STAMP_RECENT_S
    for f in files:
        rel = os.path.relpath(f, jd)
        try:
            with open(f) as fh:
                j = json.load(fh)
        except (json.JSONDecodeError, OSError):
            skipped += 1
            continue
        if not isinstance(j, dict):
            skipped += 1
            continue
        jmt = datetime.datetime.fromtimestamp(os.path.getmtime(f), UTC)
        by_ns.setdefault(_journal_namespace(f) or "other", []).append((rel, j, jmt))

        # (1) self-stamp invariant, same shape as the ledger's.
        for k in _SELF_STAMP_KEYS:
            t = _parse_offset(j.get(k))
            if t is None:
                continue
            delta = (t - jmt).total_seconds()
            if delta > _SKEW_TOLERANCE_S:
                cause, digits_s = _attribute_self_stamp(j[k], jmt)
                self_stamp_fwd.append({
                    "file": rel, "field": k, "value": j[k],
                    "mtime_utc": jmt.isoformat(),
                    "delta_min": round(delta / 60, 1),
                    # Why it is forward. 'offset-tag-mislabelled' is not the
                    # benign bucket it looks like: the digits are UTC and the
                    # tag lies, so every consumer of this stamp reads the
                    # wrong instant. It is counted, not excused.
                    "cause": cause,
                    "offset_tag": _offset_tag(j[k]),
                    "digits_as_utc_delta_s": digits_s,
                    "age_h": round((now - jmt).total_seconds() / 3600.0, 2),
                    "live": (now - jmt).total_seconds() <= recent_cutoff_s})
            break

    # (2) scan-number monotonicity, WITHIN the scan namespace only.
    #
    # A journal may carry `scan_number_suffix` when its number collided with
    # another run's and the collision was adjudicated by hand (finch:work #199
    # did this for #174). A suffixed journal IS a distinct run, so counting it
    # as a duplicate of the number it collides with would re-report an
    # adjudicated finding forever. It is excluded from the duplicate and
    # monotonicity series and reported separately as ADJUDICATED, so the
    # distinction between "unresolved collision" and "resolved collision" is
    # visible rather than assumed.
    def _adjudicated(j):
        return bool(j.get("scan_number_suffix"))

    series = sorted([(r, j, m) for r, j, m in by_ns.get("scan", [])
                     if isinstance(j.get("scan_number"), int)
                     and not _adjudicated(j)], key=lambda t: t[2])
    adjudicated = sorted([(r, j) for r, j, _m in by_ns.get("scan", [])
                          if isinstance(j.get("scan_number"), int)
                          and _adjudicated(j)])
    non_mono, dupes, prev = [], Counter(), None
    for rel, j, _m in series:
        sn = j["scan_number"]
        dupes[sn] += 1
        if prev is not None and sn <= prev:
            non_mono.append({"file": rel, "previous": prev, "seen": sn})
        prev = max(prev, sn) if prev is not None else sn
    nums = sorted(dupes)
    dup_map = {n: c for n, c in dupes.items() if c > 1}

    # (3) filename-HHMM vs mtime, retained but scoped to the scan namespace.
    fn_mismatch = []
    for rel, j, jmt in by_ns.get("scan", []):
        base = os.path.basename(rel)[5:9]
        if base.isdigit() and len(base) == 4:
            claim = int(base[:2]) * 60 + int(base[2:])
            if abs(claim - (jmt.hour * 60 + jmt.minute)) > 5:
                fn_mismatch.append({"file": rel,
                                    "scan_number": j.get("scan_number"),
                                    "mtime_utc": jmt.strftime("%H:%M:%S")})

    # (4) Archive recoverability. A scan that allocated a number but persisted
    # it under a prose field (`run: "finch:scan #165"`) instead of `scan_number`
    # is invisible to every check above, so measure the gap explicitly rather
    # than let "cohort range 33-169" imply full coverage. Measured 2026-09-26:
    # 92 of 275 journals carry a recoverable number (53 as `scan_number`, 39 in
    # prose) covering 79 numbers; 58 allocated numbers left no recoverable trace.
    # The live writer is monotonic and healthy, so this is a REPORTING gap, not
    # lost work -- reported, never repaired, never exit-coded.
    seen_all = set(nums)
    prose_hits = []
    for rel, j, _m in by_ns.get("scan", []) + by_ns.get("work", []):
        if isinstance(j.get("scan_number"), int):
            continue
        # FIXED 2026-09-27: this used `re.search`, which returns the FIRST
        # prose number in the document and discards the rest. A journal can
        # carry more than one (2026-09-21/scan-93.json holds both 91 and 93),
        # so the wider one was invisible here and the [COVERAGE] line
        # OVER-REPORTED the unrecoverable count by counting #91 as lost. The
        # digit bound was also `(\d{2,3})`, while the series passed 176 -- a
        # 2-3 digit bound silently drops any number outside it. Same defect
        # class as the allocator's 3-field harvest (finch:work #200): a
        # coverage number derived from a partial read, presented as a fact
        # about the corpus. Use finditer and a bound the series can exceed.
        m_all = _PROSE_NUM_RE.findall(json.dumps(j, ensure_ascii=False))
        if m_all:
            nums_here = sorted({int(x) for x in m_all})
            prose_hits.append({"file": rel, "via": "prose", "number": nums_here[0],
                               "numbers": nums_here})
            seen_all.update(nums_here)
    unrecoverable = ([n for n in range(nums[0], nums[-1] + 1) if n not in seen_all]
                     if nums else [])

    return {
        "measured": True,
        "dir": jd,
        "files": len(files),
        "unreadable_skipped": skipped,
        "namespaces": {k: len(v) for k, v in sorted(by_ns.items())},
        "with_scan_number": len(series),
        "cohort_range": [nums[0], nums[-1]] if nums else None,
        "duplicate_scan_numbers": dup_map,
        "adjudicated_scan_collisions": [
            {"file": r, "scan_number": j.get("scan_number"),
             "suffix": j.get("scan_number_suffix")} for r, j in adjudicated],
        "non_monotonic": non_mono,
        "self_stamp_forward": self_stamp_fwd,
        "self_stamp_forward_count": len(self_stamp_fwd),
        # Split by cause, and split by age. Both were missing, which let one
        # 2026-08-17 daily and a 1.09h-old scan-0329 share a single clause
        # calling the whole set "historical".
        "self_stamp_cause_counts": dict(Counter(
            s.get("cause", "unknown") for s in self_stamp_fwd)),
        "self_stamp_recent_count": sum(1 for s in self_stamp_fwd if s.get("live")),
        "self_stamp_recent_files": [s["file"] for s in self_stamp_fwd if s.get("live")],
        "filename_clock_mismatch": fn_mismatch,
        "work_scan_numbers_excluded": [r for r, j, _m in by_ns.get("work", [])
                                       if isinstance(j.get("scan_number"), int)],
        "scan_number_in_prose": len(prose_hits),
        "scan_numbers_unrecoverable": unrecoverable,
        "note": ("scan_number is compared only WITHIN the scan-* namespace: a "
                 "work-* journal's scan_number names the scan it ran against, "
                 "not its own number. filename HHMM is not a reliable clock; "
                 "mtime is. scan_numbers_unrecoverable is a coverage measure, "
                 "not a violation: the ledger's own scan_number is the "
                 "authoritative counter."),
    }


def repair(path, dry_run=False):
    """Clamp forward stamps DOWN to the file mtime. Returns a change list."""
    with open(path) as fh:
        doc = json.load(fh)
    mt = os.path.getmtime(path)
    mtu = datetime.datetime.fromtimestamp(mt, UTC)
    stamp = mtu.strftime("%Y-%m-%dT%H:%M:%SZ")
    changes = []

    for k in HEADER_FIELDS + NESTED_HEADER_FIELDS:
        found, val = _resolve_field(doc, k)
        if not found:
            continue
        t = _parse(val)
        if t and t > mtu:
            changes.append({"scope": "header", "id": "-", "field": k,
                            "from": val, "to": stamp,
                            "delta_s": round((t - mtu).total_seconds(), 1)})
            _set_field(doc, k, stamp)

    for task in doc.get("tasks", []) or []:
        for k in TASK_FIELDS:
            t = _parse(task.get(k))
            if t and t > mtu:
                # last_finch_review carries a "(finch:scan #N)" suffix -- keep it.
                suffix = ""
                if isinstance(task[k], str):
                    m = re.search(r"(\s*\(finch:.*\))\s*$", task[k])
                    if m:
                        suffix = m.group(1)
                changes.append({"scope": "task", "id": task.get("id"), "field": k,
                                "from": task[k], "to": stamp + suffix,
                                "delta_s": round((t - mtu).total_seconds(), 1)})
                task[k] = stamp + suffix

    if not changes or dry_run:
        return changes, doc

    # Atomic write: mkstemp + os.replace. os.replace preserves the TEMP file's
    # mode, not the original's, and mkstemp defaults to 0600 -- which silently
    # locks out every non-root reader of the ledger. Set the mode explicitly.
    import tempfile
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".finch_ledger_guard.")
    try:
        os.fchmod(fd, os.stat(path).st_mode & 0o7777)
        with os.fdopen(fd, "w") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return changes, doc


def _repair_laundered(path, hit, dry_run=False):
    """Clamp a LAUNDERED stamp down to the mtime its receipt recorded.

    The ordinary clamp uses the CURRENT mtime, which for a laundered stamp is
    already later than the value -- so it would be a no-op. The receipt's
    mtime is the correct bound: it is the last moment the content is known to
    have been self-consistent. The "(finch:...)" suffix on last_finch_review is
    preserved exactly as the forward clamp preserves it.
    """
    with open(path) as fh:
        doc = json.load(fh)
    try:
        bound = datetime.datetime.fromisoformat(hit["flagged_at_mtime"])
    except (TypeError, ValueError):
        return [], doc
    stamp = bound.strftime("%Y-%m-%dT%H:%M:%SZ")
    changes = []

    if hit["id"] == "-" and _resolve_field(doc, hit["field"])[0] \
            and _resolve_field(doc, hit["field"])[1] == hit["value"]:
        changes.append({"scope": "header", "id": "-", "field": hit["field"],
                        "from": hit["value"], "to": stamp,
                        "delta_s": 0.0, "note": "laundered"})
        _set_field(doc, hit["field"], stamp)
    else:
        for task in doc.get("tasks", []) or []:
            if task.get("id") != hit["id"]:
                continue
            if task.get(hit["field"]) != hit["value"]:
                continue
            suffix = ""
            if isinstance(task[hit["field"]], str):
                m = re.search(r"(\s*\(finch:.*\))\s*$", task[hit["field"]])
                if m:
                    suffix = m.group(1)
            changes.append({"scope": "task", "id": hit["id"], "field": hit["field"],
                            "from": hit["value"], "to": stamp + suffix,
                            "delta_s": 0.0, "note": "laundered"})
            task[hit["field"]] = stamp + suffix
    return changes, doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--repair", action="store_true",
                    help="clamp forward stamps down to the ledger mtime")
    ap.add_argument("--dry-run", action="store_true", help="with --repair: show only")
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--journals", default=None)
    a = ap.parse_args()

    rep = check(a.ledger, a.journals)

    if not rep["ledger_found"]:
        where = rep["ledger"] or "<none resolvable>"
        msg = "LEDGER UNREADABLE: %s (%s)" % (where, rep["ledger_error"])
        print(json.dumps({"error": msg, "report": rep}, indent=2) if a.json else msg)
        return 2

    repaired = []
    if a.repair and (rep["forward_count"] or rep["laundered_count"]):
        path = rep["ledger"]
        # A laundered stamp is already BACKWARD against the current mtime, so
        # the existing clamp (which only touches forward stamps) would skip it
        # and the repair would look like it ran and did nothing. Clamp to the
        # receipt's own flagged mtime instead: that is the latest instant the
        # content is known to have been clean.
        changes, _ = repair(path, dry_run=a.dry_run)
        repaired = changes
        for l in rep["laundered"]:
            path_l = rep["ledger"]
            changes_l, doc_l = _repair_laundered(path_l, l, dry_run=a.dry_run)
            repaired.extend(changes_l)
            if not a.dry_run and changes_l:
                with open(path_l, "w") as fh:
                    json.dump(doc_l, fh, indent=2, ensure_ascii=False)
                    fh.write("\n")
        if not a.dry_run:
            rep = check(path, a.journals)   # re-measure, do not assume
        else:
            print("   [dry-run] %d laundered stamp(s) would be clamped"
                  % len(rep["laundered"]))

    receipt_err = append_receipt(rep)

    if a.json:
        print(json.dumps({"report": rep, "repairs": repaired,
                          "receipt_error": receipt_err}, indent=2))
    else:
        print("ledger      : %s" % rep["ledger"])
        print("mtime (UTC) : %s" % rep["mtime_utc"])
        print("now   (UTC) : %s" % rep["now_utc"])
        hfwd = [h for h in rep["header"] if h["forward"]]
        print("\nheader stamps: %d checked, %d forward" % (len(rep["header"]), len(hfwd)))
        for h in hfwd:
            print("   FORWARD  %-16s %s  (+%.0fs vs mtime)"
                  % (h["field"], h["value"], h["delta_s"]))
        print("task stamps : %d forward" % len(rep["task_fields"]))
        for t in rep["task_fields"]:
            print("   FORWARD  %-44s %-18s %s  (+%.0fs)"
                  % (t["id"], t["field"], t["value"], t["delta_s"]))
        lm = rep.get("launder_meta", {})
        if rep["laundered"]:
            print("\nLAUNDERED  %d stamp(s) a later write made invisible by advancing"
                  " the file mtime" % len(rep["laundered"]))
            for l in rep["laundered"]:
                print("   LAUNDERED %-40s %-18s %s" % (l["id"], l["field"], l["value"]))
                print("            was +%.0fs vs mtime %s; mtime has since advanced"
                      " +%.0fs and the value is STILL unchanged in the file"
                      % (l.get("original_delta_s") or 0,
                         l["flagged_at_mtime"], l["laundered_by_s"]))
            print("   Repairable: --repair clamps it to the receipt's mtime, which"
                  " changes the value and retires the receipt.")
        if lm:
            print("receipts    : %d recorded, %d unparseable  (%s)"
                  % (lm.get("receipts", 0), lm.get("unparseable", 0),
                     lm.get("receipt_path", "?")))
        if receipt_err:
            print("receipt_err : %s" % receipt_err)
        j = rep["journals"]
        if not j.get("measured"):
            print("\njournals    : %s" % j.get("note"))
        else:
            print("\njournals    : %d files (%s), %d scan-* carry scan_number, range %s"
                  % (j["files"],
                     ", ".join("%s=%d" % kv for kv in j["namespaces"].items()),
                     j["with_scan_number"], j["cohort_range"]))
            if j["self_stamp_forward"]:
                print("   JOURNAL SELF-STAMP FORWARD on %d file(s), BY CAUSE:"
                      % len(j["self_stamp_forward"]))
                for cause, n in sorted(j.get("self_stamp_cause_counts", {}).items()):
                    print("      %-24s %d" % (cause, n))
                for s in j["self_stamp_forward"]:
                    print("      %-34s %-9s %-28s mtime=%s  (+%.0f min)  cause=%s"
                          "  tag=%s  age=%.1fh%s"
                          % (s["file"], s["field"], s["value"],
                             s["mtime_utc"][11:19], s["delta_min"],
                             s.get("cause"), s.get("offset_tag"),
                             s.get("age_h", 0.0),
                             "  LIVE (<=24h, writer still active)"
                             if s.get("live") else ""))
                _rc = j.get("self_stamp_recent_count", 0)
                if _rc:
                    print("      %d of these are <=24h old, so NOT historical:"
                          " a current writer is producing them." % _rc)
                print("      cause=offset-tag-mislabelled means the DIGITS are UTC"
                      " and the local tag lies; the stamp stays counted"
                      " because every consumer reads the wrong instant.")
            for n in j["non_monotonic"]:
                print("   NON-MONOTONIC scan_number: %s  #%s after #%s"
                      % (n["file"], n["seen"], n["previous"]))
            if j["duplicate_scan_numbers"]:
                print("   DUPLICATE scan_number: %s"
                      % ", ".join("#%s x%d" % kv for kv in j["duplicate_scan_numbers"].items()))
            if j.get("adjudicated_scan_collisions"):
                print("   ADJUDICATED collision (suffixed, excluded from the series): %s"
                      % ", ".join("#%s%s (%s)" % (c["scan_number"], c["suffix"], c["file"])
                                  for c in j["adjudicated_scan_collisions"]))
            if j.get("scan_number_in_prose"):
                print("   [COVERAGE] %d journal(s) carry their scan number in prose only"
                      " (`run: finch:scan #N`); %d allocated number(s) left no"
                      " recoverable trace."
                      % (j["scan_number_in_prose"], len(j["scan_numbers_unrecoverable"])))
            if j["work_scan_numbers_excluded"]:
                print("   excluded from scan series (work-*, scan_number is the"
                      " scan it ran against): %s"
                      % ", ".join(j["work_scan_numbers_excluded"]))
            if j["filename_clock_mismatch"]:
                _mm = j["filename_clock_mismatch"]
                print("   [LOW SIGNAL] filename-HHMM vs mtime DISAGREES on %d file(s): %s"
                      % (len(_mm),
                         ", ".join("%s=#%s" % (os.path.basename(m["file"]),
                                               m["scan_number"])
                                   for m in _mm[:6])
                         + (" ... (+%d more)" % (len(_mm) - 6) if len(_mm) > 6 else "")))
                print("      No action implied: measured 2026-09-26, the signed skew is"
                      " BIDIRECTIONAL (98 files written later than their slot, 59"
                      " earlier, median +2 min), so a disagreement carries no"
                      " forward-stamp information. Listed for completeness only.")
        if repaired:
            print("\nrepairs%s:" % (" (DRY RUN, nothing written)" if a.dry_run else ""))
            for c in repaired:
                print("   %-8s %-44s %-18s %s -> %s  (-%.0fs)"
                      % (c["scope"], c["id"], c["field"], c["from"], c["to"], c["delta_s"]))
        jf = (rep["journals"].get("self_stamp_forward_count", 0)
              if rep["journals"].get("measured") else 0)
        if rep["forward_count"]:
            print("\nVERDICT: %d LEDGER FORWARD STAMP(S) PRESENT" % rep["forward_count"])
        elif rep.get("laundered_count"):
            print("\nVERDICT: %d LAUNDERED LEDGER STAMP(S) PRESENT -- previously"
                  " forward, unrepaired, and now hidden by an advanced mtime"
                  % rep["laundered_count"])
        elif jf:
            # NOT "historical": measured 2026-09-28 the newest member of this set
            # is 1.09h old, written by a run that was still executing. Calling
            # the whole set historical hid a live writer behind a dead-looking
            # clause, which is the safe-direction misreport this file exists to
            # prevent. Say how many are live, and what the causes are.
            _live = rep["journals"].get("self_stamp_recent_count", 0) \
                if rep["journals"].get("measured") else 0
            _causes = rep["journals"].get("self_stamp_cause_counts", {}) \
                if rep["journals"].get("measured") else {}
            print("\nVERDICT: LEDGER CLEAN; %d JOURNAL SELF-STAMP(S) PRESENT"
                  " (%d live, <=24h; not written by this run)"
                  " -- causes: %s"
                  % (jf, _live,
                     ", ".join("%s=%d" % kv for kv in sorted(_causes.items()))
                     or "unattributed"))
        else:
            print("\nVERDICT: CLEAN")
    # The EXIT CODE answers only "must a writer act on the ledger?" Journal
    # self-stamps are historical with no repair path, so they are reported but
    # never change the code -- otherwise a clean ledger stays non-zero forever
    # and callers stop reading the code at all.
    #
    # A LAUNDERED stamp does change the code (#204). Unlike a journal self-stamp
    # it is still sitting in the file, still wrong, and --repair can clamp it,
    # at which point the value changes and the receipt retires. A clean ledger
    # therefore still returns 0, which is the property cases 4/5 pin.
    return 0 if (rep["forward_count"] == 0 and rep.get("laundered_count", 0) == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
