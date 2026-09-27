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
