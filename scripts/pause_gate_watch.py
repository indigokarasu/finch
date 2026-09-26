#!/usr/bin/env python3
"""pause_gate_watch.py — re-runnable, read-only, no LLM.

Reports the gap between the `paused` boolean an operator (or a mitigation
script) sets in jobs.json and the gate the scheduler actually enforces.

WHY THIS EXISTS
---------------
Two of the 2026-09-17 mitigation passes ("paused-for-openrouter-402" and
"paused-throttle-recovery") bulk-set `paused: true` to cut host load. That
mitigation never engaged. cron/jobs.py:516-524 defines the gate as:

    def _has_pause_marker(job): return state == "paused" or bool(paused_at)
    def is_job_runnable(job):  return enabled and not _has_pause_marker(job)

The bare boolean `paused` is never consulted. So a record can display as
paused in the registry and still fire on every tick.

This script answers, in one run, the four questions a task note cannot:
  1. how many records CLAIM to be paused, and how many actually are
  2. which of them have demonstrably run since the mitigation
  3. which genuinely-paused jobs exist (the real markers)
  4. whether anything is newly off -- so the count does not drift silently

Nothing is written. No repair is attempted: converting inert booleans into
real pause markers is a 120-record edit to the cron registry and needs
operator approval. This script exists so that decision can be made once,
against current numbers, instead of re-derived per pass.

EXIT CODES
----------
  0  read succeeded (regardless of finding count)
  1  read failed -- registry unreadable or scheduler module not importable
  2  DRIFT: the runnable-paused count differs from the recorded baseline by
     more than --tolerance. Means the registry changed under us and the
     numbers in the task list need refreshing.

USAGE
-----
  pause_gate_watch.py                    # human-readable
  pause_gate_watch.py --json             # machine-readable
  pause_gate_watch.py --tolerance 5      # widen the drift gate
  pause_gate_watch.py --quiet            # one-line VERDICT only
"""

import argparse
import datetime
import importlib
import json
import os
import sys
from pathlib import Path

# Where this Hermes install lives. Resolved from the environment, never
# committed as a literal absolute path: this script ships in a PUBLIC repo and
# a host-specific path is both a leak and useless on another machine (see
# references/reference-file-workflow.md). Set HERMES_ROOT to point at a
# non-default install root; otherwise fall back to ~/.hermes.
HERMES_ROOT = Path(os.path.expanduser(os.environ.get("HERMES_ROOT", "~/.hermes")))
JOBS = str(HERMES_ROOT / "cron" / "jobs.json")
SCHEDULER_PKG = str(HERMES_ROOT / "hermes-agent")
# Baseline recorded 2026-09-26 by finch:work #178. finch:work #175 first
# observed the gap; #178 re-derived it against the real gate and pinned it here.
# Refresh BASELINE whenever a registry edit is made deliberately, so the
# drift gate measures change rather than accumulating noise.
BASELINE = {"total": 155, "claims_paused": 123, "runnable_paused": 120, "real": 3}


def load_jobs(path):
    d = json.load(open(path))
    jobs = d["jobs"] if isinstance(d, dict) and "jobs" in d else d
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    return jobs


def load_gate():
    """Import the REAL gate. Never reimplement it -- that is how the 09-17
    mitigation and #175 initially disagreed."""
    if SCHEDULER_PKG not in sys.path:
        sys.path.insert(0, SCHEDULER_PKG)
    mod = importlib.import_module("cron.jobs")
    missing = [f for f in ("is_job_runnable", "_has_pause_marker")
               if not hasattr(mod, f)]
    if missing:
        raise ImportError(f"cron.jobs missing {missing}")
    return mod.is_job_runnable, mod._has_pause_marker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--quiet", action="store_true", help="one-line VERDICT only")
    ap.add_argument("--tolerance", type=int, default=5,
                    help="allowed drift from baseline before EXIT=2")
    a = ap.parse_args()

    try:
        jobs = load_jobs(JOBS)
        is_runnable, has_marker = load_gate()
    except Exception as e:                                    # noqa: BLE001
        print(f"pause_gate_watch: READ FAILED: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1

    claims = [j for j in jobs if j.get("paused")]
    runnable = [j for j in claims if is_runnable(j)]
    real = [j for j in claims if has_marker(j)]
    off = [j for j in jobs if j.get("enabled") is False]
    today = datetime.date.today().isoformat()
    ran_today = [j for j in runnable if str(j.get("last_run_at") or "").startswith(today)]

    drift = len(runnable) - BASELINE["runnable_paused"]
    res = {
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_jobs": len(jobs),
        "claims_paused": len(claims),
        "runnable_paused": len(runnable),
        "real_pause_markers": len(real),
        "enabled_false": len(off),
        "runnable_paused_that_fired_today": len(ran_today),
        "baseline": BASELINE,
        "drift": drift,
        "real_paused_jobs": sorted(
            ({"name": j.get("name"), "state": j.get("state"),
              "paused_at": j.get("paused_at")} for j in real),
            key=lambda x: str(x["name"])),
        "noisiest": sorted(
            ({"name": j.get("name"), "last_run_at": j.get("last_run_at"),
              "last_status": j.get("last_status")} for j in ran_today),
            key=lambda x: str(x["last_run_at"]), reverse=True)[:10],
    }

    if a.json:
        print(json.dumps(res, indent=2))
    elif a.quiet:
        print(f"VERDICT: {len(runnable)} of {len(claims)} jobs claim paused "
              f"but are still runnable ({len(real)} really paused); "
              f"drift {drift:+d} vs baseline.")
    else:
        print("=== pause gate: claim vs enforcement ===")
        print(f"  registry                     : {JOBS}")
        print(f"  gate source                  : {SCHEDULER_PKG}/cron/jobs.py")
        print(f"  checked at                   : {res['checked_at']}")
        print(f"  total jobs                   : {res['total_jobs']}")
        print(f"  records with paused=true     : {res['claims_paused']}")
        print(f"  ...that are STILL RUNNABLE   : {res['runnable_paused']}")
        print(f"  ...with a REAL pause marker   : {res['real_pause_markers']}")
        print(f"  enabled=false (genuinely off): {res['enabled_false']}")
        print(f"  paused-but-running that fired TODAY ({today}): "
              f"{res['runnable_paused_that_fired_today']}")
        print(f"  drift vs baseline            : {drift:+d} "
              f"(baseline {BASELINE['runnable_paused']}, tolerance {a.tolerance})")
        print("\n  --- genuinely paused (state=='paused' or paused_at set) ---")
        for j in res["real_paused_jobs"]:
            print(f"    {str(j['name'])[:48]:<50} state={j['state']} "
                  f"paused_at={j['paused_at']}")
        print("\n  --- loudest inert ones (fired today) ---")
        for j in res["noisiest"]:
            print(f"    {str(j['name'])[:48]:<50} {str(j['last_run_at'])[:19]} "
                  f"{j['last_status']}")
        print("\n  INTERPRETATION")
        print("   A bare paused=true is inert. The gate reads state=='paused' or")
        print("   paused_at. Any mitigation that only flips the boolean -- such as")
        print("   the 2026-09-17 openrouter-402 and throttle-recovery passes -- did")
        print("   not pause anything. Converting these to real markers is a")
        print("   ~120-record edit to the cron registry and needs operator approval;")
        print("   this script makes no change.")

    if abs(drift) > a.tolerance:
        print("DRIFT: counts moved vs recorded baseline; refresh the task list.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
