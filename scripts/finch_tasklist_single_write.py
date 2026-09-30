#!/usr/bin/env python3
"""Single-shot writer: append one work_log entry + update signal/notes on a task.

One process, read-modify-write, atomic replace, then json.load() to confirm.
Parallel patches on task-list.json interleave and corrupt it, and a read_file
after the fact is not validation -- so the whole update and its confirmation
happen in this single process, under an exclusive lock.
"""
import argparse
import datetime as _dt
import fcntl
import json
import os
import re
import sys
import tempfile

# A stamp is a claim about WHEN a pass happened, and this script is the only
# sanctioned way a pass makes that claim into the ledger. Every forward stamp
# the guard has ever found on this file was authored here, by hand, in a
# payload -- "22:04:00Z" is a round number, and round numbers are what a pass
# writes when it is summarising rather than reading a clock.
#
# The rule is therefore: refuse a stamp that is later than the moment of the
# write. Refusing, not clamping. Clamping would substitute a time the pass never
# witnessed and report the write as clean, which is precisely the optimistic
# misreport this guard exists to catch -- a repair the pass did not make,
# attributed to a pass that did.
#
# Tolerance covers clock skew and a stamp truncated to the second; anything
# beyond that is a hand-entered future time, not a rounding artefact.
FUTURE_TOLERANCE_S = 60.0

# ISO-8601 with a Z or an explicit numeric offset, optionally preceded by a
# human prefix ("2026-09-30T22:04:00Z (finch:work, scan_number 1053)"). The
# prefix is why the pattern is searched rather than the whole field parsed: the
# free text after the stamp is a pass's prose and is not ours to interpret.
_ISO = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2}):(\d{2})"
    r"(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?")


def _stamp_instants(text):
    """(value, datetime) for every parseable ISO stamp in `text`.

    A trailing-less stamp (no Z, no offset) is interpreted as UTC, which is what
    this ledger uses throughout; guessing a local zone would be a second,
    silent interpretation layered on top of the first.
    """
    out = []
    for m in _ISO.finditer(str(text)):
        d, hh, mm, ss, off = m.groups()
        try:
            if off in (None, "Z"):
                dt = _dt.datetime.strptime(
                    f"{d} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S").replace(
                        tzinfo=_dt.timezone.utc)
            else:
                sign = 1 if off[0] == "+" else -1
                off = off[1:].replace(":", "")
                delta = _dt.timedelta(hours=int(off[:2]), minutes=int(off[2:]))
                dt = _dt.datetime.strptime(
                    f"{d} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=_dt.timezone(sign * delta))
        except ValueError:
            continue
        out.append((m.group(0), dt))
    return out


def _forward_stamps(payload_fields, now):
    """Fields whose embedded stamp is later than `now`, as (field, value, s)."""
    bad = []
    for field, value in payload_fields:
        for text, dt in _stamp_instants(value):
            delta = (dt - now).total_seconds()
            if delta > FUTURE_TOLERANCE_S:
                bad.append((field, text, delta))
    return bad

USAGE = """\
Single-shot writer: append one work_log entry + update signal/notes on a task.

One process, read-modify-write, atomic replace, then json.load() to confirm.
Parallel patches on task-list.json interleave and corrupt it, and a read_file
after the fact is not validation -- so the whole update and its confirmation
happen in this single process, under an exclusive lock.

The ledger path is resolved from the ENVIRONMENT, never hardcoded. A committed
absolute host path is both a PII leak (this repo is public, and the PII gate
rejects it) and wrong on every machine but the author's. Resolution order,
matching finch_ledger_guard.py:

    FINCH_TASKLIST  explicit ledger file override, wins over everything
    FINCH_LEDGER    the guard's own override, honoured for consistency
    HERMES_ROOT / HERMES_HOME / FINCH_DATA_DIR
                    install-root variants, each with the plain and the
                    <root>/profiles/$HERMES_PROFILE shapes
    fallback        walk up from this script: <install>/profiles/<name>/skills/
                    <skill>/scripts/ -> the profile root holding commons/

USAGE
-----
    python3 finch_tasklist_single_write.py PAYLOAD.json
    python3 finch_tasklist_single_write.py --help

PAYLOAD is a JSON object with keys: id, signal, notes, work_log,
last_finch_review, updated_at, and optionally "set": {field: value}.
"""


def _hermes_roots():
    """Candidate install roots, most explicit first. Empty when none is set."""
    roots = []
    for var in ("FINCH_DATA_DIR", "HERMES_ROOT", "HERMES_HOME"):
        val = os.environ.get(var)
        if val:
            roots.append(os.path.expanduser(val))
    return roots


def _under(root, *parts):
    return os.path.join(root, *parts)


def _candidate_ledger_files():
    """Every ledger path this host could plausibly own, in priority order."""
    profile = os.environ.get("HERMES_PROFILE", "")
    files = []
    for var in ("FINCH_TASKLIST", "FINCH_LEDGER"):
        val = os.environ.get(var)
        if val:
            files.append(os.path.expanduser(val))
    roots = _hermes_roots()
    rel = ("commons", "data", "ocas-finch", "task-list.json")
    for root in roots:
        files.append(_under(root, *rel))
        if profile:
            files.append(_under(root, "profiles", profile, *rel))
    here = os.path.dirname(os.path.abspath(__file__))
    for up in ("..", "..", "..", ".."):
        files.append(_under(here, up, *rel))
    # Dedupe while preserving order, so a repeated root cannot make the first
    # candidate that exists differ from the intended one.
    seen, out = set(), []
    for f in files:
        key = os.path.abspath(f)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _resolve_tasklist(override=None):
    """First existing ledger file, else the best-effort default (may not exist).

    Returning a path that does not exist yet is deliberate: main() opens it and
    lets the resulting FileNotFoundError say so with the path in the message.
    Silently resolving to None instead would print a path-less error.
    """
    if override:
        return os.path.abspath(os.path.expanduser(override))
    cands = _candidate_ledger_files()
    for f in cands:
        if os.path.isfile(f):
            return f
    return cands[0] if cands else None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Answer --help BEFORE touching the payload or the ledger. argparse exits 0
    # on --help, which is what the CI "every script must answer --help" step and
    # tests/test_finch.py ScriptsExposeHelp both require -- and it is why the
    # module-level constants below are resolved lazily rather than at import.
    if any(a in ("-h", "--help") for a in argv):
        print(USAGE)
        return 0

    ap = argparse.ArgumentParser(add_help=False, description=USAGE)
    ap.add_argument("payload", help="JSON file with the task update to apply")
    ap.add_argument("--tasklist", default=None,
                    help="override the ledger path (default: resolve from env)")
    args = ap.parse_args(argv)

    tasklist = _resolve_tasklist(args.tasklist)
    if tasklist is None:
        print("ERROR: cannot resolve a ledger path; set FINCH_TASKLIST or "
              "HERMES_HOME", file=sys.stderr)
        return 2

    payload_path = args.payload
    with open(payload_path) as fh:
        payload = json.load(fh)

    task_id = payload["id"]

    # Refuse a future stamp BEFORE the lock and before any read-modify-write,
    # so a rejected payload leaves the ledger byte-identical. The check covers
    # every field the writer copies onto the task, not just updated_at: a
    # forward stamp smuggled into signal or work_log launders just as
    # effectively, because the guard reports per-field and the next pass reads
    # whichever field it happens to quote.
    now = _dt.datetime.now(_dt.timezone.utc)
    checked = [(k, payload[k]) for k in
               ("updated_at", "last_finch_review", "signal", "notes", "work_log")
               if k in payload]
    forward = _forward_stamps(checked, now)
    if forward:
        print("ABORT: payload carries stamp(s) later than the moment of the "
              f"write (now {now.isoformat()}):")
        for field, text, delta in forward:
            print(f"  {field}: {text}  (+{delta:.0f}s in the future)")
        print("  Refusing rather than clamping: a clamped time is one the pass "
              "never witnessed,\n  and reporting it clean would be the "
              "optimistic misreport this check exists to prevent.")
        print("  Pass the real clock reading as updated_at, e.g. "
              "`date -u +%Y-%m-%dT%H:%M:%SZ`.")
        return 1
    lock_path = tasklist + ".lock"
    with open(lock_path, "a") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        with open(tasklist) as fh:
            data = json.load(fh)

        tasks = data["tasks"] if isinstance(data, dict) and "tasks" in data else data
        matches = [t for t in tasks if t.get("id") == task_id]
        if len(matches) != 1:
            raise SystemExit(f"ABORT: {len(matches)} tasks match id={task_id!r}, expected exactly 1")

        t = matches[0]
        before_status = t.get("status")

        # A work_log that is a bare STRING cannot be prepended to, and
        # `[new] + "old"` raises TypeError. One task on this ledger carries
        # exactly that shape, written by finch:work #214 on 2026-09-27. The
        # effect is that the ONLY sanctioned writer cannot write that task at
        # all: the pass does its whole analysis, passes the pre-write ledger
        # guard (which does not inspect this shape), and then dies on the last
        # step, after the work, with the finding unrecorded.
        #
        # Normalise the shape here rather than refusing: the content is
        # preserved verbatim as a single-element list, so the record is
        # repaired in form and untouched in substance. Refusing would only
        # convert a data defect into a permanent inability to log.
        prior_log = t.get("work_log")
        normalised_prior = False
        if isinstance(prior_log, str):
            prior_log = [prior_log]
            normalised_prior = True
        elif prior_log is not None and not isinstance(prior_log, list):
            raise SystemExit(
                f"ABORT: task {task_id!r} has work_log of type "
                f"{type(prior_log).__name__}; refusing to guess its shape"
            )
        before_log = len(prior_log or [])

        t["signal"] = payload["signal"]
        t["notes"] = payload["notes"]
        t["work_log"] = [payload["work_log"]] + (prior_log or [])
        t["last_finch_review"] = payload["last_finch_review"]
        t["updated_at"] = payload["updated_at"]
        for k, v in payload.get("set", {}).items():
            t[k] = v

        out = json.dumps(data, indent=1, sort_keys=True) + "\n"
        json.loads(out)  # refuse to write a file we cannot read back
        d = os.path.dirname(tasklist)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(out)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, tasklist)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # Confirmation is a fresh read of the file on disk, not the in-memory copy.
    with open(tasklist) as fh:
        final = json.load(fh)
    ftasks = final["tasks"] if isinstance(final, dict) and "tasks" in final else final
    hit = [t for t in ftasks if t.get("id") == task_id]
    assert len(hit) == 1, f"post-write read found {len(hit)} matches"
    ft = hit[0]
    checks = {
        "json.loads ok": True,
        "work_log +1": len(ft.get("work_log") or []) == before_log + 1,
        "signal updated": ft.get("signal") == payload["signal"],
        "updated_at": ft.get("updated_at") == payload["updated_at"],
        "not a literal @file": not str(ft.get("signal", "")).startswith("@"),
        "entry is new first": (ft.get("work_log") or [None])[0] == payload["work_log"],
    }
    bad = [k for k, v in checks.items() if not v]
    print(f"WROTE {tasklist}")
    print(f"  id={task_id} status {before_status} -> {ft.get('status')} (unchanged)"
          if before_status == ft.get("status") else f"  id={task_id} status {before_status} -> {ft.get('status')}")
    print(f"  work_log {before_log} -> {len(ft.get('work_log') or [])}")
    if normalised_prior:
        print("  note: prior work_log was a bare string; normalised to a 1-element list")
        print("        (content preserved verbatim, shape repaired)")
    print(f"  bytes={os.path.getsize(tasklist)}  total_tasks={len(ftasks)}")
    for k in checks:
        print(("  ok   " if checks[k] else "  FAIL ") + k)
    if bad:
        print("POST-WRITE VERIFICATION FAILED: " + ", ".join(bad))
        sys.exit(1)
    print("VERIFIED CLEAN")


if __name__ == "__main__":
    sys.exit(main() or 0)
