#!/usr/bin/env python3
"""finch_ledger_write.py -- the WRITER side of the finch ledger clock.

WHY THIS EXISTS
---------------
`finch_ledger_guard.py` is a DETECTOR. Detection has already been shown to lose:
on 2026-09-27 finch:scan #179 wrote six stamps 259s ahead of the file's own
mtime (the scheduler's `next_run_at` mistaken for `datetime.now()`), then
reported the ledger clean -- because it read the guard's PRE-write result and
believed it. The violation was not seen again until 21 minutes later, and by then
a later write had advanced the mtime past the stamps, so the ordinary check
could no longer see it either. The guard's own docstring calls this out: "the
writers are ad-hoc per-run scripts (no single choke point)". A detector that
every writer must remember to run, and that has now been skipped once in the
runs that the receipts cover, is not a control.

This is the choke point. It is the ONLY sanctioned way to write task-list.json:

    1. read the ledger;
    2. apply a patch (full document, or a set of field writes);
    3. CLAMP every stamp that is later than `now()` down to `now()`;
    4. write atomically (mkstemp + os.replace, mode preserved);
    5. re-read from disk and re-measure with the guard's OWN `check()`.

Step 3 is the whole point. It is impossible to write a forward stamp through
this function, so "did the pass remember to run the guard" stops being a
question with a failure mode.

THE CLAMP IS NOT A REPAIR AND NOT A FABRICATION
-----------------------------------------------
A stamp later than `now()` is a claim about a moment the writer has not reached,
so there is no true value to recover -- only a false one to remove. Clamping to
`now()` states the truth the writer actually has: this write happened, and at this
moment. This differs from the guard's `--repair`, which clamps down to the file
MTIME; that is right for post-hoc repair of a file on disk and wrong here,
because at write time the mtime is the moment we are creating. Both agree on the
important part: the value changes, so the value is no longer a carried-through
lie, and no receipt can launder it.

A stamp that is merely STALE (earlier than now) is left completely alone. This
tool is not a clock-freshness police; rewriting honest history would be its own
kind of lie.

EXIT CODES
----------
    0  written, and the re-read measurement shows no forward stamp
    1  nothing written (pre-write validation failed)
    2  ledger unreadable / not JSON
    3  written, but the re-read measurement STILL shows a forward stamp --
       which means something other than this function wrote to the path
    4  nothing written -- this write introduced a narrative entry carrying an
       unexpanded %-format lead, i.e. a pass-time claim with NO instant in it.
       Unrepairable by a clamp, so it is refused rather than guessed at.
    5  nothing written -- this write introduced a task record that contradicts
       itself: `last_finch_review` older than a work_log entry in the same
       record. Every other control here compares one stamp to an external
       clock; this class is two stamps disagreeing with each other. Which side
       is false is not knowable from the record, so neither is rewritten.

USAGE
-----
    # whole document
    python3 finch_ledger_write.py --doc /path/new.json

    # header fields
    python3 finch_ledger_write.py --set as_of=2026-09-27T12:00:00Z

    # one task's fields
    python3 finch_ledger_write.py --task email-foo --set status=done \
        --set updated_at=2026-09-27T12:00:00Z

    # preview only
    python3 finch_ledger_write.py --set as_of=... --dry-run

    # bare repair: clamp whatever is forward, change nothing else
    python3 finch_ledger_write.py --clamp-only
"""

import argparse
import datetime
import importlib.util
import json
import os
import re
import sys
import tempfile

UTC = datetime.timezone.utc
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

_HERE = os.path.dirname(os.path.abspath(__file__))


def load_guard():
    """Import finch_ledger_guard.py by path, so the two never drift apart.

    The clamp below must agree with the check below. If the two were separate
    implementations, a field one stamps and the other cannot parse would be a
    hole, so the stamp field lists are READ from the guard rather than restated.
    """
    path = os.path.join(_HERE, "finch_ledger_guard.py")
    spec = importlib.util.spec_from_file_location("_finch_ledger_guard", path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _now():
    return datetime.datetime.now(UTC)


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _suffix(v):
    """The ' (finch:scan #N)' tail that last_finch_review carries. Keep it."""
    if isinstance(v, str):
        m = re.search(r"(\s*\(finch:.*\))\s*$", v)
        if m:
            return m.group(1)
    return ""


# Narrative keys whose strings are this system's own record of a pass. The
# guard reads stamp FIELDS, so a forward stamp written into one of these was
# invisible to it -- which is how 6 survived finch:scan #1016's own repair on
# 2026-09-29 (see clamp_narrative_leads).
NARRATIVE_FIELDS = (
    "work_log", "signal", "notes", "blocked_reason", "resolved",
    "resolution_note", "note", "entry",
)

# Only a stamp at the very START of a narrative string is a pass-identity
# claim ("<when this pass ran> (finch:scan #N): ..."). Measured over the live
# ledger, 802 work_log / 154 signal / 6 notes / 4 resolved entries carry a
# leading stamp and all of them are that claim, while due_date -- a deadline,
# legitimately in the future -- is excluded by key. A timestamp quoted
# MID-sentence is history, and rewriting history is worse than the defect, so
# the pattern is anchored and the rest of the string is never inspected.
_LEAD_STAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})")

# An UNEXPANDED %-format lead is the same false claim as a forward stamp, one
# step further out: the entry does not merely assert the WRONG instant, it
# asserts NO instant and carries the template's '%s' into the ledger verbatim.
# Measured live 2026-09-29: 2 entries document-wide (ledger-scan167 work_log[0]
# "%s (finch:work #200)", ledger-scan180 work_log[6] "%s (finch:work, scan
# _number 1000)"), each authored by a pass that built a '%s ... % (now)' string
# and stored the TEMPLATE rather than the result. Nothing in the guard, the
# sweep or the watcher can see this class: there is no timestamp to compare, so
# a clamp has no value to pull forward -- and the entry reads as a finished
# record forever. A missing claim is repaired the only honest way, by refusing
# the write rather than by inventing the instant.
_UNEXPANDED_LEAD_RE = re.compile(r"^\s*%(?:[sdfgr%])")

# A pass-identity claim can also be wrong WITHOUT being forward, and that class
# is invisible to every other instrument in this system because all of them
# compare ONE stamp to ONE EXTERNAL clock (the mtime, or now()):
#
#   finch_ledger_guard.py        -> stamp field vs file mtime
#   ledger_forward_sweep.py      -> timestamp-shaped string vs now (fields only)
#   clamp_narrative_leads        -> narrative LEAD stamp vs now
#   finch_forward_event_watch    -> receipts, (scope,id,field,value)
#   find_unexpanded_lead_formats -> a lead with NO instant in it
#
# None of them compares two stamps that claim to describe the SAME event. This
# one does. `last_finch_review` asserts "when this task was last reviewed"; a
# work_log entry that leads with an instant asserts "a pass ran at T". If the
# review field is the OLDER of the two, the record contradicts itself: the
# newest claim of a review is not the field that names the review.
#
# Measured live, re-measured 2026-09-30T03:2xZ because the first recording of
# it did not survive re-measurement. It claimed "106 comparable records: 98
# non-negative, 8 negative, and the negative population starts at -1.205h".
# The SIGN was inverted: those 8 are the ones that FIRE, and they are POSITIVE
# (an entry newer than its own review field), running +1.205h .. +24.981h. The
# 8 numbers matched by coincidence, which is the worst way for a measurement to
# be wrong -- a reader checking only the count would confirm it.
#
# Corrected, over 112 comparable records:
#   lag = (newest entry lead) - (last_finch_review), so lag > 0 FIRES.
#   exactly 0     78 records   the same write stamps both, as intended
#   0 < lag       8 records    +1.205h .. +24.981h   ALL FIRE
#   lag < 0       26 records   -80s .. -40.290h      none fire, correctly
# So the violations are separated from zero by 1.205h and 5 minutes sits 14.5x
# below the smallest one: the gap is real and the tolerance is read off it
# rather than guessed.
#
# ONE CLAIM WAS FALSE AND IT MATTERS. The original said the buckets
# "<=1min / 1-5min / 5-15min / 15-60min are all 0", i.e. nothing anywhere near
# zero. There IS one: headhunter-ledger-comp-and-status-enforcement sits at
# lag = -80s. It is on the side that does not fire, so behaviour is unaffected
# -- but it falsifies "nothing near zero", and it does so on the UNTESTED side
# of the comparison (see test direction 26). A tolerance justified by an
# overstated gap is one edit away from being wrong: the live record is 3.75x
# below it, not "an order of magnitude away from it". Stated here so the next
# reader knows which number the tolerance rests on, and that the margin is
# thinner than the previous text claimed.
REVIEW_LAG_TOLERANCE_S = 300


def _narrative_entries(task):
    """A task's narrative log entries, whatever container holds them.

    Measured live 2026-09-30: 126 records hold work_log as a LIST, 42 omit it,
    and ONE (hermes-failed-turn-notice-untyped-telegram) holds it as a bare
    STRING. A reader that assumes a list indexes the last CHARACTER there and
    silently walks prose -- the exact failure #1021 hit itself when it treated
    notes/signal as lists. Normalising here is cheaper than asserting away.
    """
    wl = task.get("work_log")
    if isinstance(wl, list):
        return [e for e in wl if isinstance(e, str)]
    if isinstance(wl, str):
        return [wl]
    return []


def _lead_instant(value):
    """Instant from the LEAD of a stamp field, tolerating a trailing suffix.

    `last_finch_review` is stored as "<instant> (finch:scan #N)" -- the guard
    keeps that tail and _suffix() preserves it. Feeding the WHOLE field to
    fromisoformat raises on every live record and returns None, so a detector
    written that way is INERT on the real ledger while passing every unit test
    whose fixture carried a bare stamp. Measured 2026-09-30: 166/166 live
    last_finch_review values carry the suffix, and a first implementation that
    parsed the whole field found 0 of the 8 contradictions an independent probe
    found. The regex is applied first, exactly as clamp_narrative_leads does,
    and only the matched span is parsed.
    """
    if not isinstance(value, str):
        return None
    m = _LEAD_STAMP_RE.match(value.strip())
    return _parse_instant(m.group(0)) if m else None


def find_stale_review_claims(doc, tolerance=REVIEW_LAG_TOLERANCE_S):
    """Records whose `last_finch_review` predates a pass record in the same task.

    Read-only. Returns [(trail, task_id, review, newest_instant, lag_s, text)].

    Compares against the MAXIMUM entry lead, not the last element: entries are
    appended out of order often enough that a chronologically-last entry is not
    reliably the newest one, and a comparison keyed on position would let an
    out-of-order append hide the contradiction.

    Returns the FULL TEXT of the newest entry as the last element, not a
    preview, for the same reason find_unexpanded_lead_formats does: the caller
    keys new-vs-known on this tuple, and a key built from (trail, review,
    instant, lag) is UNCHANGED when the entry's prose is reworded. Measured
    live 2026-09-30 against a copy of the real ledger: debt rewording at the
    same trail and the same list index returned EXIT 0 instead of 5, so a
    reworded record -- which is a DIFFERENT record, and may carry different
    damage -- was waved through as pre-existing. Same laundering path #1019's
    test 17 caught in the exit-4 control; a trail-only key cannot tell a new
    contradiction from an old one.

    This is a REFUSAL, not a correction, and deliberately so. Unlike a forward
    stamp there is a true value to restore here -- the entry proves a pass ran
    at T -- but which of the two stamps is the false one is NOT knowable from
    the record, and rewriting either side would be inventing a fact, which is
    the defect this whole tool exists to stop. (Measured live 2026-09-30: 4
    tasks hold two entries sharing ONE lead instant under distinct prose, so a
    lead stamp is not even reliably a true pass-time claim; propagating one into
    a field would launder it further.)
    """
    hits = []
    for i, task in enumerate(doc.get("tasks", []) or []):
        if not isinstance(task, dict):
            continue
        review = _lead_instant(task.get("last_finch_review"))
        if review is None:
            continue
        best = None
        best_text = None
        for entry in _narrative_entries(task):
            m = _LEAD_STAMP_RE.match(entry)
            if not m:
                continue
            t = _parse_instant(m.group(0))
            if t is not None and (best is None or t > best):
                best, best_text = t, entry
        if best is None:
            continue
        lag = (best - review).total_seconds()
        if lag > tolerance:
            hits.append(("tasks[%d]" % i, task.get("id"),
                         task.get("last_finch_review"),
                         _fmt(best), round(lag, 1), best_text))
    return hits


def find_unexpanded_lead_formats(doc):
    """Every narrative entry whose lead is an unexpanded %-format.

    Read-only. Returns [(trail, text)]. Separate from clamp() because this
    is a REFUSAL, not a correction: the tool cannot know the instant the author
    meant, and guessing one is the defect it already exists to stop.

    Returns the FULL text, not a preview, so callers can key on content. A
    caller that keyed on the trail alone would treat a DIFFERENT damaged entry
    written to the same list index as pre-existing debt and wave it through --
    which is the laundering this control exists to stop.
    """
    hits = []

    def walk(node, key=None, trail=""):
        if isinstance(node, dict):
            for k in list(node):
                walk(node[k], k, "%s.%s" % (trail, k))
            return
        if isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, key, "%s[%d]" % (trail, i))
            return
        if isinstance(node, str) and key in NARRATIVE_FIELDS \
                and _UNEXPANDED_LEAD_RE.match(node):
            hits.append((trail.lstrip("."), node))

    walk(doc)
    return hits



def clamp_narrative_leads(node, now, key=None, trail="", changes=None):
    """Clamp a forward stamp that leads a narrative string. Returns changes.

    A work_log entry that opens with a clock is claiming WHEN THIS PASS RAN,
    and that claim is subject to exactly the same rule as `updated_at` next to
    it: no stamp may be later than the file carrying it. The 2026-09-29 #1016
    pass proved the gap is live -- it stamped 13 fields and 6 narrative
    entries forward by 130s, then repaired the 13 and missed the 6, because
    the guard reads fields and nothing read the entries.

    Anchored to the START of the string on purpose. Only the matched span is
    rewritten; a stamp quoted inside a sentence is not this system's claim
    about its own clock and is left byte-identical.
    """
    if changes is None:
        changes = []
    stamp = _fmt(now)
    if isinstance(node, dict):
        for k in list(node):
            node[k] = clamp_narrative_leads(
                node[k], now, k, f"{trail}.{k}", changes)
        return node
    if isinstance(node, list):
        for i, v in enumerate(node):
            node[i] = clamp_narrative_leads(
                v, now, key, f"{trail}[{i}]", changes)
        return node
    if not isinstance(node, str) or key not in NARRATIVE_FIELDS:
        return node
    m = _LEAD_STAMP_RE.match(node)
    if not m:
        return node
    t = _parse_instant(m.group(0))
    if t is None or t <= now:
        return node
    changes.append({"scope": "narrative", "id": trail.lstrip(".") or key,
                    "field": key, "from": m.group(0), "to": stamp,
                    "delta_s": round((t - now).total_seconds(), 1)})
    # Only the matched span is replaced; the prose after it is byte-identical.
    return stamp + node[m.end():]


def _parse_instant(v):
    """Parse a full ISO stamp, offset included. Never raises.

    Deliberately NOT the guard's truncating reader: that one is what hid a
    -07:00 forward stamp for a day, and 'the one field the narrative path had
    never checked' is precisely where a permissive parser would hide the next
    one. An unparseable value is left alone -- this tool removes false claims,
    it does not normalise what it does not recognise.
    """
    try:
        t = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def clamp(doc, now=None, dry_run=False):
    """Clamp every forward stamp down to `now`. Returns a change list.

    Never raises on document content -- a value that is not a parseable stamp is
    left exactly as it is, because this tool's job is to remove false claims,
    not to normalise everything it does not recognise.
    """
    now = now or _now()
    stamp = _fmt(now)
    guard = load_guard()
    changes = []

    for k in guard.HEADER_FIELDS:
        v = doc.get(k)
        t = guard._parse(v)
        if t is not None and t > now:
            changes.append({"scope": "header", "id": "-", "field": k,
                            "from": v, "to": stamp,
                            "delta_s": round((t - now).total_seconds(), 1)})
            doc[k] = stamp

    for task in doc.get("tasks", []) or []:
        for k in guard.TASK_FIELDS:
            v = task.get(k)
            t = guard._parse(v)
            if t is not None and t > now:
                changes.append({"scope": "task", "id": task.get("id"), "field": k,
                                "from": v, "to": stamp + _suffix(v),
                                "delta_s": round((t - now).total_seconds(), 1)})
                task[k] = stamp + _suffix(v)

    # Narrative lead-stamps last, and only as a sweep of the whole document:
    # the field lists above are the guard's, and the guard has never read a
    # work_log entry. Order matters for the same reason it does in rule 4(c) --
    # clamp first, stamp second -- so a caller cannot re-introduce a forward
    # narrative stamp with a --set that lands after this returns.
    clamp_narrative_leads(doc, now, changes=changes)

    return changes


def write_atomic(path, doc, mode_from=None):
    """Replace `path` with `doc`, preserving the original's permission bits.

    mkstemp creates 0600 and os.replace keeps the TEMP file's mode, so a writer
    that skips this silently locks every non-root reader out of the ledger.
    """
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".finch_ledger_write.")
    try:
        ref = mode_from or path
        os.fchmod(fd, os.stat(ref).st_mode & 0o7777)
        with os.fdopen(fd, "w") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _coerce(v):
    """Keep a value as the string it almost always is, but do not mangle JSON."""
    if isinstance(v, str):
        low = v.strip().lower()
        if low in ("true", "false"):
            return low == "true"
        if low == "null":
            return None
        try:
            return int(v)
        except ValueError:
            return v
    return v


def _parse_sets(sets):
    out = []
    for s in sets or []:
        if "=" not in s:
            raise ValueError("--set expects key=value, got %r" % s)
        k, v = s.split("=", 1)
        out.append((k.strip(), _coerce(v)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", help="a JSON file holding the full new document")
    ap.add_argument("--clamp-only", action="store_true",
                    help="clamp whatever is forward and change nothing else")
    ap.add_argument("--task", help="task id to apply --set fields to")
    ap.add_argument("--set", action="append", dest="sets",
                    help="key=value; applies to the header, or to --task")
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--journals", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-clamp-report", action="store_true",
                    help="suppress the per-clamp lines")
    a = ap.parse_args()

    if not a.doc and not a.sets and not a.clamp_only:
        print("nothing to do: pass --doc, --set and/or --clamp-only")
        return 1

    guard = load_guard()
    rep0 = guard.check(a.ledger, a.journals)
    if not rep0["ledger_found"]:
        print("LEDGER UNREADABLE: %s (%s)" % (rep0["ledger"], rep0["ledger_error"]))
        return 2
    path = rep0["ledger"]

    try:
        with open(path) as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print("LEDGER UNREADABLE: %s" % e)
        return 2

    # Debt already ON DISK, captured before any merge. Unexpanded %-format leads
    # are not repairable by this tool, so they cannot simply be made to vanish --
    # and a refusal that fires on them would brick the write path until a human
    # intervened. The control therefore refuses NEWLY INTRODUCED damage and
    # reports pre-existing debt instead, so the ledger keeps moving and the
    # debt stays visible. Measured 2026-09-29: 2 such entries live.
    pre_existing = set(find_unexpanded_lead_formats(doc))
    pre_stale = set(find_stale_review_claims(doc))

    if a.doc:
        try:
            with open(a.doc) as fh:
                incoming = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            print("--doc unreadable: %s" % e)
            return 1
        # An explicit --doc is a full replacement, but keep the task list sane
        # if the caller meant a partial: refuse a doc with no tasks at all.
        if not isinstance(incoming, dict) or "tasks" not in incoming:
            print("--doc must be a full ledger document (no 'tasks' key)")
            return 1
        doc = incoming

    sets = _parse_sets(a.sets)
    if sets:
        if a.task:
            hits = [t for t in doc.get("tasks", []) if t.get("id") == a.task]
            if not hits:
                print("no task with id %r in %s" % (a.task, path))
                return 1
            for k, v in sets:
                hits[0][k] = v
        else:
            for k, v in sets:
                if k in ("tasks",):
                    print("refusing to --set tasks")
                    return 1
                doc[k] = v

    now = _now()
    changes = clamp(doc, now=now, dry_run=a.dry_run)

    # A narrative lead that is an unexpanded %-format is a MISSING pass-time
    # claim, and it is not repairable: the tool has no way to know the instant
    # the author meant, and a clamp needs a value to compare. Refuse rather
    # than write a record that is permanently missing its own time. This runs
    # after the doc/--set merge so it judges exactly what would be written,
    # and it is independent of --clamp-only: a clamp-only pass must not launder
    # a damaged entry into the ledger by rewriting the file around it.
    unexpanded = find_unexpanded_lead_formats(doc)
    new_damage = [(t, p) for t, p in unexpanded if (t, p) not in pre_existing]
    if new_damage:
        print("VERDICT: REFUSED -- %d narrative entr(y/ies) in this write carry an"
              " UNEXPANDED %%-format lead, which is a pass-time claim with no"
              " instant in it." % len(new_damage))
        for trail, preview in new_damage:
            print("   %-52s %r" % (trail, preview[:72]))
        print("   These are not forward stamps and cannot be clamped: the true")
        print("   instant is unrecoverable from the entry. Store the")
        print("   %%-substituted string, not the template, and re-run.")
        print("   Nothing was written.")
        return 4
    if unexpanded:
        print("debt    : %d PRE-EXISTING unexpanded %%-format lead(s) carried"
              " through, not written by this run and not repairable here:" % len(unexpanded))
        for trail, preview in unexpanded:
            print("   %-52s %r" % (trail, preview[:72]))

    # A record that contradicts ITSELF: last_finch_review is older than a pass
    # record in the same task. Every other control here compares one stamp to an
    # external clock, so this class is invisible to all of them (see
    # find_stale_review_claims). It is a refusal rather than a correction
    # because neither side is provably the false one -- writing the entry's lead
    # into the field would invent a fact. Runs after the merge, so it judges
    # exactly what would be written, and is independent of --clamp-only for the
    # same reason the exit-4 control is: a clamp-only pass must not launder a
    # contradictory record in by rewriting the file around it.
    stale = find_stale_review_claims(doc)
    new_stale = [h for h in stale if h not in pre_stale]
    if new_stale:
        print("VERDICT: REFUSED -- %d task record(s) in this write CONTRADICT"
              " THEMSELVES: last_finch_review is older than a work_log entry in"
              " the same record." % len(new_stale))
        for trail, tid, review, newest, lag, _text in new_stale:
            print("   %-12s %-44s review=%s entry=%s  (%+.1fh)"
                  % (trail, str(tid)[:44], review, newest, lag / 3600.0))
        print("   Two records of the same event disagree and no clamp can tell")
        print("   which is false, so neither is rewritten. Re-stamp the task's")
        print("   last_finch_review to the instant the entry names, or correct the")
        print("   entry, and re-run. Nothing was written.")
        return 5
    if stale:
        print("debt    : %d PRE-EXISTING self-contradicting record(s) carried"
              " through, not written by this run and not repairable here:"
              % len(stale))
        for trail, tid, review, newest, lag, _text in stale:
            print("   %-12s %-44s review=%s entry=%s  (%+.1fh)"
                  % (trail, str(tid)[:44], review, newest, lag / 3600.0))


    print("ledger   : %s" % path)
    print("now      : %s" % now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if changes:
        print("clamped  : %d forward stamp(s) down to now()" % len(changes))
        if not a.no_clamp_report:
            for c in changes:
                print("   %-6s %-44s %-18s %s -> %s  (-%.0fs)"
                      % (c["scope"], c["id"], c["field"], c["from"], c["to"],
                         c["delta_s"]))
    else:
        print("clamped  : 0 (every stamp is at or before now)")

    if a.dry_run:
        print("\nVERDICT: DRY RUN, nothing written")
        return 0

    write_atomic(path, doc)

    # Re-measure from disk with the guard's own check(). Do not report the
    # in-memory result: this file is the witness, and a claim about it made
    # before it was read back is the exact failure this tool exists to stop.
    rep1 = guard.check(path, a.journals)
    fwd = rep1["forward_count"]
    lau = rep1.get("laundered_count", 0)
    print("\nre-read  : mtime %s, sha %s" % (rep1["mtime_utc"],
                                              (rep1.get("sha256") or "")[:8]))
    if fwd or lau:
        print("VERDICT: %d FORWARD, %d LAUNDERED -- a writer other than this"
              " function is writing the ledger" % (fwd, lau))
        return 3
    print("VERDICT: WRITTEN CLEAN -- 0 forward, 0 laundered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
