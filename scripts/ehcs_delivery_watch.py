#!/usr/bin/env python3
"""EHCS refill cron (dfd7f742d4f2) delivery-target health check.

Read-only. Answers, in one command, the question the registry's
``last_delivery_error`` field cannot: does this job's ``deliver`` target
resolve to a live, enabled transport RIGHT NOW?

The failure that opened the task ("platform 'telegram' not configured/enabled")
is stamped at the END of a run and is only overwritten by the NEXT run. This
job is weekly-ish, so a config state that was fixed after the last run keeps
reporting "broken" for days. `hermes cron list` / `cron doctor` both read that
field, so the stale value is surfaced as a live issue.

What it checks (all via the scheduler's OWN functions, not a reimplementation):
  1. registry record: deliver, last_status, last_run_at, last_delivery_error
  2. target resolution:   cron.scheduler_delivery._resolve_delivery_targets
  3. transport resolution: cron.scheduler_delivery._resolve_target_transport
  4. whether the stamped error is older than the config it describes

Usage:  python3 scripts/ehcs_delivery_watch.py [--json]

EXIT:   0 = target resolves now (or genuinely unverifiable offline)
        1 = target does NOT resolve now -- a real, live defect
        2 = job record unreadable
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

JOB_ID = "dfd7f742d4f2"
AGENT_ROOT = os.environ.get("OCAS_AGENT_ROOT", "/root/.hermes/profiles/indigo")
HERMES_SRC = "/root/.hermes/hermes-agent"
REGISTRY = os.path.join(AGENT_ROOT, "cron", "jobs.json")
CONFIG = os.path.join(AGENT_ROOT, "config.yaml")


def _now():
    return datetime.now(timezone.utc)


def _ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def load_job():
    with open(REGISTRY) as fh:
        data = json.load(fh)
    jobs = data.get("jobs", data) if isinstance(data, dict) else data
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    for job in jobs:
        if job.get("id") == JOB_ID:
            return job
    return None


def config_mtime():
    try:
        return datetime.fromtimestamp(os.path.getmtime(CONFIG), timezone.utc)
    except OSError:
        return None


def resolve_live(job):
    """Run the scheduler's own delivery resolution against the live config.

    SCOPE MATTERS, and getting it wrong inverts the verdict. This job's
    registry is SHARED (profiles/indigo/cron/jobs.json and /root/.hermes/cron/
    jobs.json are one inode), but ``load_gateway_config()`` reads
    ``$HERMES_HOME``. Under the ROOT home the telegram PlatformConfig is
    ``enabled=False`` and this target -- plus EVERY other telegram-delivering
    job -- reports "not configured/enabled". Under the INDIGO profile scope the
    same block is ``enabled=True`` and it resolves, which is what the live
    gateway does (multiplex mode serves the indigo profile from the root
    process). So resolution MUST happen inside the indigo profile scope; the
    root-home reading is a true statement about the wrong config.
    """
    if not os.path.isdir(HERMES_SRC):
        return {"checked": False, "reason": f"{HERMES_SRC} absent"}
    sys.path.insert(0, HERMES_SRC)
    try:
        from pathlib import Path
        from gateway.run import _load_profile_secret_scope, _profile_runtime_scope
        from gateway.config import load_gateway_config, Platform
        import cron.scheduler_delivery as sd
    except Exception as exc:  # import-time plugin noise lands here
        return {"checked": False, "reason": f"{type(exc).__name__}: {exc}"}

    try:
        secrets = _load_profile_secret_scope(Path(AGENT_ROOT))
        with _profile_runtime_scope(Path(AGENT_ROOT), secrets):
            cfg = load_gateway_config()
            targets = sd._resolve_delivery_targets(job)
    except Exception as exc:
        return {"checked": False, "reason": f"config load: {type(exc).__name__}: {exc}"}

    pconfig = cfg.platforms.get(Platform.TELEGRAM)
    scope = {"telegram_enabled": getattr(pconfig, "enabled", None) if pconfig else None}

    try:
        targets = sd._resolve_delivery_targets(job)
    except Exception as exc:
        return {"checked": False, "scope": scope,
                "reason": f"target resolution: {type(exc).__name__}: {exc}"}

    if not targets:
        return {"checked": True, "scope": scope, "targets": [], "ok": True,
                "note": "deliver resolves to local -- no external transport required"}

    results = []
    ok = True
    for target in targets:
        name = str(target.get("platform"))
        try:
            platform = Platform(name)
        except Exception:
            results.append({"platform": name, "ok": False,
                            "error": f"unknown platform {name!r}"})
            ok = False
            continue
        try:
            _resolved, err = sd._resolve_target_transport(
                job, platform, name, target, {}, cfg)
        except Exception as exc:
            err, _resolved = f"{type(exc).__name__}: {exc}", None
        entry = {"platform": name, "chat_id": str(target.get("chat_id")),
                 "ok": err is None, "error": err}
        results.append(entry)
        ok = ok and err is None
    return {"checked": True, "scope": scope, "targets": results, "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    try:
        job = load_job()
    except Exception as exc:
        print(f"UNREADABLE registry: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if not job:
        print(f"job {JOB_ID} is not in {REGISTRY}", file=sys.stderr)
        return 2

    live = resolve_live(job)
    stamped = job.get("last_delivery_error")
    last_run = _ts(job.get("last_run_at"))
    cfg_mtime = config_mtime()
    stamp_age_h = round((_now() - last_run).total_seconds() / 3600, 1) if last_run else None
    config_newer = bool(last_run and cfg_mtime and cfg_mtime > last_run)

    stale = bool(stamped and live.get("checked") and live.get("ok"))
    verdict = "TARGET RESOLVES NOW"
    if not live.get("checked"):
        verdict = "UNVERIFIABLE OFFLINE"
    elif not live.get("ok"):
        verdict = "TARGET DOES NOT RESOLVE -- LIVE DEFECT"

    report = {
        "job_id": JOB_ID,
        "name": job.get("name"),
        "deliver": job.get("deliver"),
        "last_status": job.get("last_status"),
        "last_run_at": job.get("last_run_at"),
        "next_run_at": job.get("next_run_at"),
        "last_delivery_error": stamped,
        "last_delivery_error_stale": stale,
        "error_age_hours": stamp_age_h,
        "config_mtime": cfg_mtime.isoformat() if cfg_mtime else None,
        "config_newer_than_last_run": config_newer,
        "live": live,
        "verdict": verdict,
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"job            : {JOB_ID}  {job.get('name')}")
        print(f"deliver        : {job.get('deliver')}")
        last_run_line = f"last run       : {job.get('last_run_at')}"
        if stamp_age_h is not None:
            last_run_line += f"  ({stamp_age_h}h ago)"
        print(last_run_line)
        print(f"next run       : {job.get('next_run_at')}")
        print(f"last_status    : {job.get('last_status')}")
        print(f"stamped error  : {stamped or '(none)'}")
        if stamped:
            age = "STALE -- does not reproduce live" if stale else "LIVE"
            print(f"                ^ {age}")
        if config_newer:
            print(f"note           : config.yaml changed {cfg_mtime.isoformat()}, "
                  "AFTER the last run -- it is the change the stamp predates")
        if live.get("checked"):
            for t in live.get("targets", []):
                mark = "OK  " if t.get("ok") else "FAIL"
                print(f"live target    : [{mark}] {t.get('platform')}:{t.get('chat_id')}"
                      + (f"  {t.get('error')}" if t.get("error") else ""))
        else:
            print(f"live target    : NOT CHECKED -- {live.get('reason')}")
        print(f"VERDICT        : {verdict}")

    if live.get("checked") and not live.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
