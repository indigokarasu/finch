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
    1  forward stamps present and not repaired
    2  ledger unreadable / not JSON
"""

import argparse
import datetime
import glob
import json
import os
import re
import sys
from collections import Counter

# Resolve the ledger from the script's own location, not a hardcoded host path.
# .../profiles/<name>/skills/<skill>/scripts/ -> walk up to the profile root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_LEGACY = "/root/.hermes/commons/data/ocas-finch/task-list.json"
_CANDIDATE_DIRS = [
    os.path.join(_HERE, "..", "..", "..", "commons", "data", "ocas-finch"),
    os.path.join(_HERE, "..", "..", "..", "..", "commons", "data", "ocas-finch"),
]
_JOURNAL_DIRS = [
    os.path.join(_HERE, "..", "..", "..", "commons", "journals", "ocas-finch"),
    os.path.join(_HERE, "..", "..", "..", "..", "commons", "journals", "ocas-finch"),
]

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
        path = os.path.join(d, "task-list.json") if d else _LEGACY
    rep["ledger"] = path

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
    jd = journal_dir or _resolve(_JOURNAL_DIRS)
    if not jd:
        rep["journals"] = {"measured": False,
                           "note": "NOT MEASURED -- journal dir not resolvable"}
        return rep
    files = sorted(glob.glob(os.path.join(jd, "**", "scan-*.json"), recursive=True))
    if not files:
        rep["journals"] = {"measured": False, "note": "NOT MEASURED -- no scan-*.json found"}
        return rep

    cohort, filename_mismatch = [], []
    for f in files:
        try:
            with open(f) as fh:
                j = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(j, dict) or not isinstance(j.get("scan_number"), int):
            continue
        cohort.append(j["scan_number"])
        base = os.path.basename(f)[5:9]           # HHMM
        jmt = datetime.datetime.fromtimestamp(os.path.getmtime(f), UTC)
        if base.isdigit() and len(base) == 4:
            claim = int(base[:2]) * 60 + int(base[2:])
            if abs(claim - (jmt.hour * 60 + jmt.minute)) > 5:
                filename_mismatch.append({"file": os.path.basename(f),
                                          "scan_number": j["scan_number"],
                                          "mtime_utc": jmt.strftime("%H:%M:%S")})

    cohort = sorted(cohort)
    dupes = {n: c for n, c in Counter(cohort).items() if c > 1}
    rep["journals"] = {
        "measured": True,
        "dir": jd,
        "files": len(files),
        "with_scan_number": len(cohort),
        "cohort_range": [cohort[0], cohort[-1]] if cohort else None,
        "duplicate_scan_numbers": dupes,
        "filename_clock_mismatch": filename_mismatch,
        "note": "filename HHMM is not a reliable clock; scan_number and mtime are",
    }
    rep["journals_measured"] = True
    return rep


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
        msg = "LEDGER UNREADABLE: %s (%s)" % (rep["ledger"], rep["ledger_error"])
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
            print("\njournals    : %d files, %d carry scan_number, range %s"
                  % (j["files"], j["with_scan_number"], j["cohort_range"]))
            if j["duplicate_scan_numbers"]:
                print("   DUPLICATE scan_number: %s" % j["duplicate_scan_numbers"])
            if j["filename_clock_mismatch"]:
                print("   filename-HHMM vs mtime DISAGREES on %d file(s): %s"
                      % (len(j["filename_clock_mismatch"]),
                         ", ".join("%s=#%s" % (m["file"][5:9], m["scan_number"])
                                   for m in j["filename_clock_mismatch"])))
        if repaired:
            print("\nrepairs%s:" % (" (DRY RUN, nothing written)" if a.dry_run else ""))
            for c in repaired:
                print("   %-8s %-44s %-18s %s -> %s  (-%.0fs)"
                      % (c["scope"], c["id"], c["field"], c["from"], c["to"], c["delta_s"]))
        print("\nVERDICT: %s" % (
            "CLEAN" if rep["forward_count"] == 0
            else "%d FORWARD STAMP(S) PRESENT" % rep["forward_count"]))
    return 0 if rep["forward_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
