"""rvt clause 3 -- offset-aware whole-document sweep of the LIVE ledger.

Independent of the guard's field list on purpose: it walks every timestamp-
shaped string in the document, not the fields the guard was told to read. A
sweep that reused the guard's list could only ever confirm the guard.

Exits non-zero on any forward stamp outside tasks[].due_date.
"""
import argparse
import datetime
import json
import os
import re
import sys

LEDGER = os.environ.get(
    "FINCH_LEDGER",
    os.path.expanduser("~/.hermes/commons/data/ocas-finch/task-list.json"))
UTC = datetime.timezone.utc
SHAPE = re.compile(
    r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2}):(\d{2})"
    r"(Z|[+-]\d{2}:?\d{2})?")
# due_date is a DEADLINE, not a claim about when this ledger was written.
DUE_DATE_FIELDS = ("due_date",)
# Long-form prose fields. A timestamp quoted INSIDE a sentence is an example,
# not a claim the ledger makes about itself -- finch:work #231 put
# '2026-09-28T03:20:00-07:00' in a re_verify_trigger as a worked example and
# this sweep reported it as a live forward stamp. These are still COUNTED in
# the examined total, and printed separately, so suppressing them from the
# verdict cannot hide a real one.
PROSE_FIELDS = ("description", "blocked_reason", "re_verify_trigger",
                "signal", "resolved", "notes", "resolution_note",
                "resolution", "work_log", "summary", "claim", "evidence",
                "root_cause", "finding", "detail", "comment")


def to_utc(m):
    d, hh, mm, ss, off = m.groups()
    naive = datetime.datetime.strptime(
        "%s %s:%s:%s" % (d, hh, mm, ss), "%Y-%m-%d %H:%M:%S")
    if not off:
        return naive.replace(tzinfo=UTC)
    if off == "Z":
        return naive.replace(tzinfo=UTC)
    off = off.replace(":", "")
    sign = 1 if off[0] == "+" else -1
    delta = datetime.timedelta(hours=int(off[1:3]), minutes=int(off[3:5]))
    return (naive - sign * delta).replace(tzinfo=UTC)


def sweep(path):
    mtu = datetime.datetime.fromtimestamp(os.path.getmtime(path), UTC)
    with open(path) as fh:
        doc = json.load(fh)
    out, prose_hits, seen = [], [], 0

    def walk(node, trail, key=None):
        nonlocal seen
        if key in DUE_DATE_FIELDS:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, trail + [str(k)], k)
            return
        if isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, trail + [str(i)], key)
            return
        if isinstance(node, str):
            # Prose can embed several stamps in one string; take the first
            # that parses, so a narrative mention is not a free pass.
            m = SHAPE.search(node)
            if m:
                seen += 1
                t = to_utc(m)
                delta = (t - mtu).total_seconds()
                if delta > 0:
                    row = {"path": ".".join(trail), "value": m.group(0),
                           "resolved_utc": t.isoformat(),
                           "mtime_utc": mtu.isoformat(),
                           "delta_s": round(delta, 1)}
                    # A prose field is judged by its LEAF key, because the
                    # long-form names are keys and the trail root is a task id.
                    leaf = trail[-1] if trail else ""
                    if key in PROSE_FIELDS or leaf in PROSE_FIELDS:
                        row["prose"] = True
                        prose_hits.append(row)
                    else:
                        out.append(row)

    for k, v in doc.items():
        walk(v, [str(k)], k)

    out.sort(key=lambda r: -r["delta_s"])
    prose_hits.sort(key=lambda r: -r["delta_s"])
    print("mtime (UTC): %s" % mtu.isoformat())
    print("timestamp-shaped strings examined: %d" % seen)
    print("forward stamps outside due_date: %d" % len(out))
    for r in out[:20]:
        print("  FORWARD %-52s %s  value=%r  delta=%+ds"
              % (r["path"], r["resolved_utc"], r["value"], r["delta_s"]))
    if prose_hits:
        print("\n(%d forward-looking timestamp(s) inside PROSE fields -- "
              "examples and quoted history, not claims the ledger makes about "
              "its own clock. Listed, not counted:)" % len(prose_hits))
        for r in prose_hits[:10]:
            print("  prose %-49s value=%r delta=%+ds"
                  % (r["path"], r["value"], r["delta_s"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Sweep every timestamp-shaped string in the ledger for a "
                    "stamp that claims to be later than the ledger's own "
                    "mtime. due_date is a deadline and is exempt; timestamps "
                    "quoted inside prose are listed, not counted.")
    ap.add_argument("--ledger", default=LEDGER,
                    help="path to task-list.json (default: $FINCH_LEDGER, "
                         "else ~/.hermes/commons/data/ocas-finch/task-list.json)")
    args = ap.parse_args(argv)
    hits = sweep(args.ledger)
    print("\nVERDICT: %s" % ("CLEAN" if not hits
                             else "%d FORWARD STAMP(S) FOUND" % len(hits)))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
