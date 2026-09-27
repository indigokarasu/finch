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

# Top-level fields that claim to describe THIS ledger's current state.
HEADER_FIELDS = ("as_of", "last_scan_at", "scan_cycle", "updated_at", "last_work_at")
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
    """Parse a ledger timestamp to an aware UTC datetime, or None."""
    if not isinstance(v, str) or not TS_RE.match(v):
        return None
    try:
        return datetime.datetime.fromisoformat(v[:19]).replace(tzinfo=UTC)
    except ValueError:
        return None


def check(ledger_path=None, journal_dir=None):
    """Validate the ledger. Never raises on ledger content; returns a report dict."""
    rep = {"ledger": None, "ledger_found": False, "ledger_error": None,
           "mtime_utc": None, "now_utc": datetime.datetime.now(UTC).isoformat(),
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

    # --- header fields -----------------------------------------------------
    for k in HEADER_FIELDS:
        if k not in doc:
            continue
        t = _parse(doc[k])
        if t is None:
            continue
        delta = (t - mtu).total_seconds()
        rep["header"].append({"field": k, "value": doc[k],
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

    # --- journal coherence -------------------------------------------------
    rep["journals"] = _journal_coherence(journal_dir)
    rep["journals_measured"] = bool(rep["journals"].get("measured"))
    return rep


# Journal self-timestamp keys, in priority order. A journal names the moment it
# ran; that moment cannot be later than the file's own mtime. Same invariant as
# the ledger header, applied to the Action Journal the SKILL.md requires.
_SELF_STAMP_KEYS = ("timestamp", "as_of", "started_at", "scan_cycle")
# Tolerate small filesystem/clock skew, and a writer that truncates to the
# minute and commits a few seconds before the second hand catches up.
_SKEW_TOLERANCE_S = 60
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


def _journal_coherence(journal_dir):
    """Measure journal self-stamps and scan-number monotonicity.

    FIXED 2026-09-26: the previous implementation globbed only `scan-*.json`
    and so could not see the 24 journals whose own `timestamp`/`as_of` is later
    than their mtime -- while still reporting `measured: true`. A coverage claim
    is a claim about the read, not about the world. Two further defects: it
    never checked a journal's OWN timestamp, and it folded `work-*` journals
    into the scan series even though their scan_number references another run.
    """
    jd = journal_dir or _resolve(_JOURNAL_DIRS)
    if not jd:
        return {"measured": False, "note": "NOT MEASURED -- journal dir not resolvable"}
    files = sorted(glob.glob(os.path.join(jd, "**", "*.json"), recursive=True))
    if not files:
        return {"measured": False, "note": "NOT MEASURED -- no *.json found"}

    by_ns, self_stamp_fwd, skipped = {}, [], 0
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
                self_stamp_fwd.append({"file": rel, "field": k, "value": j[k],
                                       "mtime_utc": jmt.isoformat(),
                                       "delta_min": round(delta / 60, 1)})
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

    for k in HEADER_FIELDS:
        t = _parse(doc.get(k))
        if t and t > mtu:
            changes.append({"scope": "header", "id": "-", "field": k,
                            "from": doc[k], "to": stamp,
                            "delta_s": round((t - mtu).total_seconds(), 1)})
            doc[k] = stamp

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
    if a.repair and rep["forward_count"]:
        path = rep["ledger"]
        changes, _ = repair(path, dry_run=a.dry_run)
        repaired = changes
        if not a.dry_run:
            rep = check(path, a.journals)   # re-measure, do not assume

    if a.json:
        print(json.dumps({"report": rep, "repairs": repaired}, indent=2))
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
        j = rep["journals"]
        if not j.get("measured"):
            print("\njournals    : %s" % j.get("note"))
        else:
            print("\njournals    : %d files (%s), %d scan-* carry scan_number, range %s"
                  % (j["files"],
                     ", ".join("%s=%d" % kv for kv in j["namespaces"].items()),
                     j["with_scan_number"], j["cohort_range"]))
            if j["self_stamp_forward"]:
                print("   JOURNAL SELF-STAMP FORWARD on %d file(s):"
                      % len(j["self_stamp_forward"]))
                for s in j["self_stamp_forward"]:
                    print("      %-34s %-9s %-28s mtime=%s  (+%.0f min)"
                          % (s["file"], s["field"], s["value"],
                             s["mtime_utc"][11:19], s["delta_min"]))
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
        elif jf:
            print("\nVERDICT: LEDGER CLEAN; %d JOURNAL SELF-STAMP(S) PRESENT"
                  " (historical, not written by this run)" % jf)
        else:
            print("\nVERDICT: CLEAN")
    # The EXIT CODE answers only "must a writer act on the ledger?". Journal
    # self-stamps are historical with no repair path, so they are reported but
    # never change the code -- otherwise a clean ledger stays non-zero forever
    # and callers stop reading the code at all.
    return 0 if rep["forward_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
