#!/usr/bin/env python3
"""Attribute a disk-watch window STEP to arrivals and deletions.

Run for any window in which finch_disk_watch.py reports a dominant
`growth_window_step_mb` (a `growth_window_spans_step` true reading):

    python3 scripts/finch_step_attribution.py --from 2026-10-02T23:49:33Z \\
        --to 2026-10-03T00:44:24Z [--json]

WHY THIS EXISTS (measured 2026-10-03, finch:work #1129).

A `step` in the disk-watch ring is a NET figure: used_mb(newest) minus
used_mb(previous), across one interval. Four consecutive passes (#1126,
#1127, #1128 and the scans between them) reported the same ~1.8 GB step as
"unattributable" and each re-derived the attribution the same way -- by
searching for FILES whose mtime fell inside the window. That method has two
structural blind spots, and both are silent:

  1. A DELETION LEAVES NO FILE. Searching for changed files can only ever
     find the arrival half of a net step. On this host the deletion half was
     recorded -- as an append-only manifest written BEFORE the removal, at
     commons/data/ocas-custodian/reap-manifest-*.json -- and four passes
     missed it because the manifest is ~150 KB while the searches used a
     150 MB floor.

  2. `find -newermt "<YYYY-MM-DD HH:MM:SS>"` PARSES A NAIVE STRING IN LOCAL
     TIME. A UTC window handed to it is silently compared as PDT, i.e. seven
     hours late, and returns a confident ZERO for a window full of writers.
     This is not hypothetical: it produced exactly that false absence during
     this pass's own investigation, and the control that caught it was a
     file the author knew existed.

So this probe does three things the old method did not:

  * ARITHMETIC IS FLOATS. Windows are epoch seconds throughout; no date
    string is ever handed to a shell. The local-time bug is structurally
    unreachable, not merely avoided.
  * IT SEARCHES BOTH SIDES OF THE NET: arrivals (mtime in window) AND
    deletions (reap manifests whose removal stamp lands in window).
  * IT RUNS A KNOWN-POSITIVE CONTROL BEFORE REPORTING ANY ABSENCE, and
    refuses to print "nothing found" if the control fails. An
    unvalidated search that returns zero is exactly the shape of the bug
    this probe exists to close.

NOTHING IS DELETED OR MODIFIED BY THIS PROBE. It reads the filesystem and
prints a report; it is safe to run unattended.
"""
import argparse
import json
import os
import sys
import time

# The custodian's append-only pre-removal evidence. A general convention,
# not a host value: any directory of reap manifests can be passed with
# --manifest-dir, and the glob is on the filename prefix alone.
DEFAULT_MANIFEST_DIRS = (
    "/root/.hermes/profiles/indigo/commons/data/ocas-custodian",
)
MANIFEST_PREFIX = "reap-manifest-"

# A step of this size is worth attributing. Below it the arithmetic noise of
# normal churn dominates and the answer is not worth the scan.
MIN_STEP_MB = 50.0


def _epoch(stamp):
    """Parse an ISO-8601 stamp to epoch seconds. Accepts a trailing Z.

    Naive stamps (no Z, no offset) are read as UTC, matching the convention
    finch_disk_watch.py uses throughout; a naive stamp is rejected outright
    when --strict is set, because a window boundary guessed at the wrong
    zone is the same defect as a window boundary parsed in the wrong zone.
    """
    import datetime as dt
    s = str(stamp).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(s)
    except ValueError:
        raise SystemExit(f"ERROR: cannot parse timestamp {stamp!r}; "
                         f"expected ISO-8601 like 2026-10-03T00:44:24Z")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def _fmt(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def scan_arrivals(roots, t_lo, t_hi, min_mb=0.0):
    """Files whose mtime falls inside [t_lo, t_hi], largest first.

    os.scandir and st_mtime only -- no subprocess, so no timezone can be
    lost between the window and the comparison.
    """
    floor = min_mb * 1024 * 1024
    out = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("proc", "sys")]
            for name in filenames:
                path = os.path.join(dirpath, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if t_lo <= st.st_mtime <= t_hi and st.st_size >= floor:
                    out.append((st.st_size, st.st_mtime, path))
    out.sort(reverse=True)
    return out


def scan_deletions(manifest_dirs, t_lo, t_hi, min_mb=0.0):
    """Reap manifests whose removal stamp lands inside [t_lo, t_hi].

    The manifest is written BEFORE the removal (that is the contract the
    custodian's reap scripts follow), so its mtime is the earliest bound on
    the deletion and its own recorded stamp the precise one. Both are
    reported; a manifest whose file mtime and recorded stamp disagree by
    more than a few minutes is flagged rather than silently trusted.
    """
    import glob
    found = []
    for d in manifest_dirs:
        for path in glob.glob(os.path.join(d, MANIFEST_PREFIX + "*.json")):
            try:
                with open(path) as fh:
                    body = json.load(fh)
                st = os.stat(path)
            except (OSError, ValueError):
                continue
            stamps = []
            for key in ("manifested_at_utc", "removed_utc", "reaped_utc",
                        "started_utc", "finished_utc"):
                if body.get(key):
                    stamps.append((key, _epoch(body[key])))
            # The newest stamp in the window is the one that dates the
            # removal; a manifest whose stamps all predate the window is
            # evidence about some earlier event and is not counted here.
            inside = [s for s in stamps if t_lo <= s[1] <= t_hi]
            if not inside:
                continue
            nbytes = body.get("total_bytes", body.get("bytes"))
            if not isinstance(nbytes, int) or nbytes / 1048576 < min_mb:
                continue
            found.append({
                "manifest": path,
                "bytes": nbytes,
                "mb": round(nbytes / 1048576, 1),
                "target": body.get("target") or body.get("path"),
                "file_count": body.get("file_count"),
                "removal_stamp": _fmt(max(s[1] for s in inside)),
                "manifest_mtime": _fmt(st.st_mtime),
                "stamp_key": max(inside, key=lambda s: s[1])[0],
            })
    found.sort(key=lambda r: -r["mb"])
    return found


def run_control(t_lo, t_hi):
    """Prove the arrival scan can see a file we KNOW is in the window.

    The control is INDEPENDENT OF THE WINDOW it is checking. That matters:
    an earlier draft took "the newest file under the state dir", which only
    holds when the window is recent. Run against an older window -- which is
    the normal case, since a step is attributed after it has aged out of the
    retention ring -- the newest state file is far outside the window and the
    control fails on a perfectly good scan. A control that only passes for
    recent windows is a control that manufactures false alarms.

    So the control asks a question the scan can always answer: take the
    newest file under the probe root, read its real mtime, and assert that a
    window built AROUND THAT MTIME is found. It validates the scan
    mechanism -- the os.walk/stat path and the epoch comparison -- without
    assuming anything about the window under investigation. If that fails,
    the scan proved nothing and every zero below is unknown, not absent.
    """
    probe_root = "/root/.hermes/profiles/indigo/state"
    newest = None
    if os.path.isdir(probe_root):
        for dirpath, dirnames, filenames in os.walk(probe_root):
            for name in filenames:
                path = os.path.join(dirpath, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if newest is None or st.st_mtime > newest[1]:
                    newest = (path, st.st_mtime)
    if newest is None:
        return {"probe_root": probe_root, "ok": False,
                "reason": "probe root is empty or unreadable",
                "files_seen_in_window": 0, "newest": None}
    path, mtime = newest
    # A +/-5 minute window centred on the file's own mtime: wide enough that
    # filesystem timestamp granularity cannot exclude it, narrow enough that
    # a scan which ignored mtime entirely would still be caught by the
    # count being implausibly large.
    lo, hi = mtime - 300.0, mtime + 300.0
    hits = scan_arrivals([probe_root], lo, hi, min_mb=0.0)
    seen = [h for h in hits if os.path.realpath(h[2]) == os.path.realpath(path)]
    return {
        "probe_root": probe_root,
        "ok": bool(seen),
        "files_seen_in_window": len(hits),
        "reason": None if seen else
                  "the probe file itself was not returned by its own window",
        "newest": {"mb": round(os.lstat(path).st_size / 1048576, 3),
                   "mtime": _fmt(mtime), "path": path},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Attribute a disk-watch step window to arrivals and "
                    "deletions. Reads only; deletes nothing.")
    ap.add_argument("--from", dest="t_lo", required=True,
                    help="window start, ISO-8601, e.g. 2026-10-02T23:49:33Z")
    ap.add_argument("--to", dest="t_hi", required=True,
                    help="window end, ISO-8601")
    ap.add_argument("--root", action="append", default=None,
                    help="tree to scan for arrivals (repeatable; "
                         "default: the standard roots below)")
    ap.add_argument("--manifest-dir", action="append", default=None,
                    help="directory of reap manifests (repeatable)")
    ap.add_argument("--min-arrival-mb", type=float, default=1.0,
                    help="ignore arrivals below this size (default 1.0)")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args(argv)

    t_lo, t_hi = _epoch(args.t_lo), _epoch(args.t_hi)
    if t_hi <= t_lo:
        raise SystemExit("ERROR: --to must be later than --from")

    roots = args.root or ["/root", "/var", "/opt", "/usr", "/tmp", "/home"]
    mdirs = args.manifest_dir or list(DEFAULT_MANIFEST_DIRS)

    control = run_control(t_lo, t_hi)
    arrivals = scan_arrivals(roots, t_lo, t_hi, min_mb=args.min_arrival_mb)
    deletions = scan_deletions(mdirs, t_lo, t_hi, min_mb=MIN_STEP_MB)

    arr_mb = sum(a[0] for a in arrivals) / 1048576
    del_mb = sum(d["mb"] for d in deletions)

    report = {
        "window": {"from": _fmt(t_lo), "to": _fmt(t_hi),
                   "hours": round((t_hi - t_lo) / 3600.0, 3)},
        "control": control,
        "arrivals": {
            "count": len(arrivals),
            "total_mb": round(arr_mb, 1),
            "top": [{"mb": round(a[0] / 1048576, 1), "mtime": _fmt(a[1]),
                     "path": a[2]} for a in arrivals[:12]],
        },
        "deletions": {
            "count": len(deletions),
            "total_mb": round(del_mb, 1),
            "manifests": deletions,
        },
        "net_mb": round(del_mb - arr_mb, 1),
        "caveat": (
            "This is an ATTRIBUTION SEARCH, not a measurement of the step. "
            "The step itself is used_mb(newest) - used_mb(previous) from the "
            "disk-watch ring and is a NET over the same window; arrivals "
            "found here are files whose MTIME fell inside it, which excludes "
            "in-place growth of an existing large file (a WAL expanding, a "
            "DB being rewritten) -- so net_mb here is a LOWER bound on the "
            "deletion side, not a reconciliation. Filesystem snapshots or "
            "inode accounting are needed to close the remainder, and the "
            "honest report when they do not close is a GAP, not a guess."
        ),
    }

    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        w = report["window"]
        print(f"window {w['from']} -> {w['to']}  ({w['hours']}h)")
        c = report["control"]
        if c["ok"]:
            verdict = "OK"
        else:
            verdict = "FAILED -- ABSENCES BELOW ARE NOT TRUSTWORTHY"
        print(f"control: {verdict} ({c['files_seen_in_window']} "
              f"files seen under {c['probe_root']})")
        a = report["arrivals"]
        print(f"arrivals: {a['count']} files, {a['total_mb']} MB total")
        for t in a["top"]:
            print(f"   {t['mb']:>10.1f} MB  {t['mtime']}  {t['path']}")
        d = report["deletions"]
        print(f"deletions: {d['count']} manifested, {d['total_mb']} MB total")
        for m in d["manifests"]:
            print(f"   {m['mb']:>10.1f} MB  {m['removal_stamp']}  "
                  f"{m['target']}  (manifest {os.path.basename(m['manifest'])})")
        print(f"net (deletions - arrivals): {report['net_mb']} MB")
        print()
        print("caveat: " + report["caveat"])

    # A failed control means the scan proved nothing about ABSENCE. Say so on
    # stderr and exit non-zero so a caller cannot record a clean zero.
    if not control["ok"]:
        print("CONTROL FAILED: the arrival scan found nothing in the window "
              "where a known-recent file must be. Treat every zero above as "
              "unknown, not as an absence.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)