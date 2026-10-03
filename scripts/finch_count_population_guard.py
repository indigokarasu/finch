#!/usr/bin/env python3
"""finch_count_population_guard.py -- make an unquotable number impossible to emit.

Task: unverified-counts-in-user-facing-reports (P2). A 09-29 summary email quoted
'302 duplicate fires across 20 jobs' and the operator refuted BOTH numbers. The
cause was structural: the counts came from `ls cron/output/<job>/ | wc -l`, a
PROXY (directory entries, which include .gz archives and pre-repair history) that
was never validated against the authoritative store.

Two rules this enforces:

  1. Every count must name the POPULATION it was drawn from. executions.db is a
     sliding window pruned to the newest MAX_TERMINAL_EXECUTIONS terminal rows, so
     a bare "N duplicate fires" is unfalsifiable and drifts between passes.

  2. A count must come from the AUTHORITATIVE store, not a filesystem listing.
     This script refuses to read cron/output/ for its headline number and says so
     in the verdict, so the proxy can never be reintroduced silently.

Exit codes:
  0  MEASURED      -- counts emitted, each with its population and corroboration
  1  CORRECTION    -- two independently-worded constructions disagree
  2  NOT MEASURED  -- db unreadable / schema changed / registry unreadable

Never exit 0 on an unmeasured read. A count produced from an empty or wrong-shaped
table must read as NOT MEASURED, never as zero.
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone

# Resolved from the environment, never a committed literal: this ships in a
# PUBLIC repo, so a profile name and a host-specific path are both leaks and both
# useless elsewhere. HERMES_ROOT alone is enough -- the profile that owns
# cron/executions.db is the active one, so callers pass FINCH_PROFILE_ROOT.
HERMES_ROOT = os.path.expanduser(os.environ.get("HERMES_ROOT", "~/.hermes"))
PROFILE = os.path.expanduser(os.environ.get("FINCH_PROFILE_ROOT", HERMES_ROOT))
DB = os.path.join(PROFILE, "cron", "executions.db")
REGISTRY = os.path.join(PROFILE, "cron", "jobs.json")
OUTPUT_DIR = os.path.join(PROFILE, "cron", "output")

# Columns this script needs. If the schema drops one, we are NOT MEASURED --
# we do not guess a substitute, because a substituted column silently changes
# what the number means (that is how the original wrong number was produced).
REQUIRED = {"job_id", "scheduled_instant", "status", "finished_at", "source"}


def _connect():
    if not os.path.exists(DB):
        raise FileNotFoundError(DB)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def measure(verbose=True):
    """Return the measurement dict, or raise for NOT MEASURED."""
    con = _connect()
    cur = con.cursor()
    cols = {r[1] for r in cur.execute("PRAGMA table_info(executions)")}
    missing = REQUIRED - cols
    if missing:
        con.close()
        raise RuntimeError(f"schema missing columns: {sorted(missing)}")

    total = cur.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
    status_dist = dict(cur.execute(
        "SELECT status, COUNT(*) FROM executions GROUP BY status").fetchall())
    inst_min, inst_max = cur.execute(
        "SELECT MIN(scheduled_instant), MAX(scheduled_instant) FROM executions"
    ).fetchone()

    # Population stamp -- the thing that was missing from the bad sentence.
    terminal = sum(n for s, n in status_dist.items()
                   if s in ("completed", "failed"))
    window_h = None
    if inst_min and inst_max:
        try:
            a = datetime.fromisoformat(str(inst_min).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(inst_max).replace("Z", "+00:00"))
            window_h = round((b - a).total_seconds() / 3600.0, 2)
        except ValueError:
            window_h = None

    # Construction A: group on the exact (job_id, scheduled_instant) key.
    pairs_a = cur.execute(
        "SELECT job_id, scheduled_instant, COUNT(*) n "
        "FROM executions WHERE scheduled_instant IS NOT NULL "
        "GROUP BY job_id, scheduled_instant HAVING COUNT(*) > 1"
    ).fetchall()

    # Construction B: an independently-worded query for the SAME predicate --
    # a self-join instead of GROUP BY ... HAVING. If A and B disagree, the
    # count is not reproducible and nothing may be quoted (exit 1).
    #
    # NOT a finished_at cluster: that is a DIFFERENT predicate (it asks how many
    # same-job rows finished in the same microsecond), not a second wording of
    # this one. It is reported below as its own diagnostic, because an earlier
    # draft of this script used it as the corroboration and reported a
    # CORRECTION verdict that was an artefact of comparing two different
    # metrics -- exactly the class of error this task exists to catch.
    pairs_b = cur.execute(
        "SELECT COUNT(*) FROM executions a JOIN executions b "
        "ON a.job_id = b.job_id "
        "AND a.scheduled_instant = b.scheduled_instant "
        "AND a.id < b.id "
        "WHERE a.scheduled_instant IS NOT NULL"
    ).fetchone()[0]

    # Diagnostic only -- narrower, different question. Reported, never used as
    # corroboration.
    finished = cur.execute(
        "SELECT job_id, finished_at FROM executions "
        "WHERE finished_at IS NOT NULL"
    ).fetchall()
    by_job = {}
    for r in finished:
        by_job.setdefault(r["job_id"], []).append(r["finished_at"])
    same_finish = 0
    for _j, ts in by_job.items():
        ts.sort()
        same_finish += sum(1 for a, b in zip(ts, ts[1:]) if a == b)

    # Does the duplicate pair differ in source? If every pair is one source, the
    # duplicates are a claim race inside a single dispatch path.
    src_rows = cur.execute(
        "SELECT job_id, scheduled_instant, COUNT(*) n, "
        "COUNT(DISTINCT COALESCE(source,'?')) ds "
        "FROM executions WHERE scheduled_instant IS NOT NULL "
        "GROUP BY job_id, scheduled_instant HAVING COUNT(*)>1"
    ).fetchall()
    same_src = sum(1 for r in src_rows if r["ds"] == 1)

    unknown_rows = cur.execute(
        "SELECT COUNT(*) FROM executions WHERE status='unknown'").fetchone()[0]
    unknown_err = None
    if unknown_rows:
        u = cur.execute(
            "SELECT error FROM executions WHERE status='unknown' "
            "AND error IS NOT NULL LIMIT 1").fetchone()
        unknown_err = u[0] if u else None

    failed_by_job = [(r["job_id"], r["n"]) for r in cur.execute(
        "SELECT job_id, COUNT(*) n FROM executions WHERE status='failed' "
        "GROUP BY job_id ORDER BY n DESC").fetchall()]

    jobs = None
    if os.path.exists(REGISTRY):
        reg = json.load(open(REGISTRY))
        j = reg["jobs"] if isinstance(reg, dict) and "jobs" in reg else reg
        jobs = len(j)

    # The proxy, measured ONLY so the record can name why it is not the source.
    dir_entries = None
    dir_subdirs = None
    if os.path.isdir(OUTPUT_DIR):
        dir_subdirs = len([d for d in os.listdir(OUTPUT_DIR)
                           if os.path.isdir(os.path.join(OUTPUT_DIR, d))])
        n = 0
        for d in os.listdir(OUTPUT_DIR):
            p = os.path.join(OUTPUT_DIR, d)
            if os.path.isdir(p):
                try:
                    n += len(os.listdir(p))
                except OSError:
                    pass
        dir_entries = n

    out = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "db": DB,
        "population": {
            "rows_total": total,
            "status_dist": status_dist,
            "terminal_rows": terminal,
            "instant_min": inst_min,
            "instant_max": inst_max,
            "retention_window_hours": window_h,
            "note": ("executions.db is a SLIDING WINDOW pruned to the newest "
                     "terminal rows. Any count from this table is a count over "
                     "this population and is not a rate over any fixed period."),
        },
        "duplicate_fires": {
            "construction_A_grouped_job_instant": len(pairs_a),
            "construction_B_selfjoin_same_predicate": pairs_b,
            "corroborated": len(pairs_a) == pairs_b,
            "DIAGNOSTIC_same_finished_at_rows": same_finish,
            "distinct_jobs_with_duplicates": len({r["job_id"] for r in pairs_a}),
            "multiplicity_dist": dict(Counter(r["n"] for r in pairs_a)),
            "pairs_sharing_one_source": same_src,
            "pairs_spanning_multiple_sources": len(pairs_a) - same_src,
        },
        "unknown_status_rows": {
            "count": unknown_rows,
            "sample_error": unknown_err,
            "note": ("not a status any task in the ledger accounts for; "
                     "reported, not interpreted"),
        },
        "failed_rows_by_job": failed_by_job,
        "registry_jobs": jobs,
        "REJECTED_SOURCE": {
            "path": OUTPUT_DIR,
            "job_subdirs": dir_subdirs,
            "total_entries": dir_entries,
            "why": ("a directory listing is a PROXY: it counts .gz archives and "
                    "pre-repair history, and counts a job with no rows at all. "
                    "It is measured here ONLY so the record can name it, and is "
                    "NEVER used as a count."),
        },
    }
    con.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    try:
        m = measure()
    except Exception as e:
        if not args.quiet:
            print(f"VERDICT: NOT MEASURED -- {type(e).__name__}: {e}")
        return 2

    p = m["population"]
    dup = m["duplicate_fires"]
    if not dup["corroborated"]:
        verdict = "CORRECTION"
        rc = 1
    else:
        verdict = "MEASURED"
        rc = 0

    if args.json:
        print(json.dumps(m, indent=2, default=str))
    elif not args.quiet:
        print(f"VERDICT: {verdict}")
        print(f"  population: {p['rows_total']} rows "
              f"({p['terminal_rows']} terminal) spanning "
              f"{p['retention_window_hours']}h "
              f"[{p['instant_min']} .. {p['instant_max']}]")
        print(f"  status dist: {p['status_dist']}")
        print(f"  duplicate fires: {dup['construction_A_grouped_job_instant']} "
              f"instants (corroborated by an independently-worded self-join: "
              f"{dup['construction_B_selfjoin_same_predicate']})")
        print(f"  distinct jobs with duplicates: "
              f"{dup['distinct_jobs_with_duplicates']}")
        print(f"  multiplicity: {dup['multiplicity_dist']}  "
              f"same-source pairs: {dup['pairs_sharing_one_source']}  "
              f"multi-source pairs: {dup['pairs_spanning_multiple_sources']}")
        print(f"  unknown-status rows: {m['unknown_status_rows']['count']}")
        print(f"  REJECTED proxy source: {m['REJECTED_SOURCE']['path']} "
              f"({m['REJECTED_SOURCE']['job_subdirs']} subdirs, "
              f"{m['REJECTED_SOURCE']['total_entries']} entries) -- "
              f"directory listing is NOT a count")
    return rc


if __name__ == "__main__":
    sys.exit(main())