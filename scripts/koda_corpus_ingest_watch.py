#!/usr/bin/env python3
"""koda_corpus_ingest_watch.py -- read-only, no LLM, re-runnable health check for the
Koda corpus-ingest cron job (5e7a5ce29d50).

Answers, in one command, the questions a task note cannot:
  * is the job still pinned, and to what
  * what runtime provider/base_url does it actually resolve to INSIDE the koda scope
  * how many runs failed with the provider error vs actually ran
  * what is the delivery verdict (a SEPARATE failure class -- not execution)

Usage:  koda_corpus_ingest_watch.py [--json]
Exit:   0 = execution healthy, 1 = provider error has returned, 2 = could not measure
"""
import argparse, glob, json, os, subprocess, sys, datetime

JOB = "5e7a5ce29d50"
# Layout is RESOLVED, never hardcoded: this repo is public, so a real filesystem
# root or a concrete profile name is a leak and useless on another host.
HERMES_HOME = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
TARGET_PROFILE = os.environ.get("OCAS_KODA_PROFILE", "<profile>")
SCRATCH_PROFILE = os.environ.get("OCAS_SCRATCH_PROFILE", "<profile>")
KODA_HOME = os.path.join(HERMES_HOME, "profiles", TARGET_PROFILE)
KODA_CRON = os.path.join(KODA_HOME, "cron")
JOBS = os.path.join(KODA_CRON, "jobs.json")
OUT = os.path.join(KODA_CRON, "output", JOB)
SCRATCH = os.path.join(HERMES_HOME, "profiles", SCRATCH_PROFILE, "cache", "scratch")
PROVIDER_ERR = "No LLM provider configured"


def scheduler_env():
    """The cron scheduler's own interpreter + PYTHONPATH, read from /proc when live."""
    py = os.path.join(SCRATCH, "real_python.txt")
    pp = os.path.join(SCRATCH, "real_pythonpath.txt")
    if not (os.path.exists(py) and os.path.exists(pp)):
        pid = subprocess.run(["pgrep", "-f", "cron.scheduler"],
                             capture_output=True, text=True).stdout.split()
        if not pid:
            return None, None
        exe = os.readlink("/proc/%s/exe" % pid[0])
        raw = open("/proc/%s/environ" % pid[0], "rb").read().split(b"\0")
        env = dict(k.split(b"=", 1) for k in raw if b"=" in k)
        pp_val = env.get(b"PYTHONPATH", os.path.join(HERMES_HOME, "hermes-agent").encode()).decode()
        open(py, "w").write(exe)
        open(pp, "w").write(pp_val)
    return open(py).read().strip(), open(pp).read().strip()


def resolve_in_koda_scope():
    """Resolve the job's runtime provider through the scheduler's own function."""
    py, pp = scheduler_env()
    if not py or not os.path.exists(py):
        return {"measured": False, "reason": "scheduler interpreter not found"}
    probe = os.path.join(SCRATCH, "_koda_probe_inline.py")
    with open(probe, "w") as f:
        f.write(
            "import os,sys,json\n"
            "for p in %r.split(':'):\n"
            "    if p not in sys.path: sys.path.insert(0,p)\n"
            "os.environ['HERMES_HOME']=%r\n"
            "os.environ['HERMES_PROFILE']=%r\n"
            "import cron.scheduler as S\n"
            "reg=json.load(open(%r))\n"
            "jobs=reg['jobs'] if isinstance(reg,dict) and 'jobs' in reg else reg\n"
            "if isinstance(jobs,dict): jobs=list(jobs.values())\n"
            "job=next(j for j in jobs if j.get('id')==%r)\n"
            "out={'measured':True,'pinned':S._job_route_pinned(job),\n"
            "     'record_provider':job.get('provider'),'record_model':job.get('model')}\n"
            "try:\n"
            "    jc=S._load_cron_job_config(job,%r,job.get('name') or %r)\n"
            "    rt,m=S._resolve_job_runtime(job,%r,jc)\n"
            "    out.update(resolved_model=m,provider=rt.get('provider'),\n"
            "               base_url=rt.get('base_url'),\n"
            "               api_key_present=bool(rt.get('api_key')))\n"
            "except Exception as e:\n"
            "    out.update(error='%s: %%s'%%(type(e).__name__,str(e)[:160]))\n"
            "print('@@'+json.dumps(out))\n"
            % (pp, KODA_HOME, TARGET_PROFILE, JOBS, JOB, JOB, JOB, JOB, "resolve_failed")
        )
    env = {**os.environ, "PYTHONPATH": pp,
           "HERMES_HOME": KODA_HOME, "HERMES_PROFILE": TARGET_PROFILE}
    r = subprocess.run([py, probe], env=env, capture_output=True, text=True,
                       cwd=KODA_HOME)
    for line in r.stdout.splitlines():
        if line.startswith("@@"):
            return json.loads(line[2:])
    return {"measured": False, "reason": (r.stderr.strip().splitlines() or ["no output"])[-1][:200]}


def delivery_verdict():
    py, pp = scheduler_env()
    if not py or not os.path.exists(py):
        return {"measured": False}
    probe = os.path.join(SCRATCH, "_koda_deliv_inline.py")
    with open(probe, "w") as f:
        f.write(
            "import os,sys,json\n"
            "for p in %r.split(':'):\n"
            "    if p not in sys.path: sys.path.insert(0,p)\n"
            "os.environ['HERMES_HOME']=%r\n"
            "os.environ['HERMES_PROFILE']=%r\n"
            "import cron.scheduler as S\n"
            "reg=json.load(open(%r))\n"
            "jobs=reg['jobs'] if isinstance(reg,dict) and 'jobs' in reg else reg\n"
            "if isinstance(jobs,dict): jobs=list(jobs.values())\n"
            "job=next(j for j in jobs if j.get('id')==%r)\n"
            "try:\n"
            "    t=S._resolve_delivery_targets(job)\n"
            "    print('@@'+json.dumps({'measured':True,'targets':t,\n"
            "        'count':len(t) if hasattr(t,'__len__') else None,\n"
            "        'deliver':job.get('deliver')}))\n"
            "except Exception as e:\n"
            "    print('@@'+json.dumps({'measured':True,'error':str(e)[:160]}))\n"
            % (pp, KODA_HOME, TARGET_PROFILE, JOBS, JOB)
        )
    env = {**os.environ, "PYTHONPATH": pp,
           "HERMES_HOME": KODA_HOME, "HERMES_PROFILE": TARGET_PROFILE}
    r = subprocess.run([py, probe], env=env, capture_output=True, text=True,
                       cwd=KODA_HOME)
    for line in r.stdout.splitlines():
        if line.startswith("@@"):
            return json.loads(line[2:])
    return {"measured": False, "reason": (r.stderr.strip().splitlines() or ["no output"])[-1][:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(JOBS):
        print("VERDICT: NOT MEASURED -- registry missing: %s" % JOBS)
        return 2

    reg = json.load(open(JOBS))
    jobs = reg["jobs"] if isinstance(reg, dict) and "jobs" in reg else reg
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    job = next((j for j in jobs if j.get("id") == JOB), None)
    if job is None:
        print("VERDICT: NOT MEASURED -- job %s absent from the koda registry" % JOB)
        return 2

    files = sorted(glob.glob(os.path.join(OUT, "*.md")), key=os.path.getmtime)
    provider_fail, real = [], []
    for p in files:
        (provider_fail if PROVIDER_ERR in open(p, errors="replace").read() else real).append(p)

    res = resolve_in_koda_scope()
    dlv = delivery_verdict()

    report = {
        "job": JOB,
        "name": job.get("name"),
        "checked_at": datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat(),
        "registry": {
            "record_provider": job.get("provider"),
            "record_model": job.get("model"),
            "last_status": job.get("last_status"),
            "failure_streak": job.get("failure_streak"),
            "last_error": (job.get("last_error") or None),
            "deliver": job.get("deliver"),
            "last_delivery_error": job.get("last_delivery_error"),
        },
        "resolution_in_koda_scope": res,
        "delivery": dlv,
        "runs": {
            "total_outputs": len(files),
            "provider_failures": len(provider_fail),
            "real_runs": len(real),
            "newest_output": os.path.basename(files[-1]) if files else None,
            "newest_is_real_run": bool(files) and files[-1] in real,
        },
    }

    # Decision. Distinguish "not measured" from "measured clean" (the #181 lesson).
    if not res.get("measured"):
        verdict, code = "NOT MEASURED -- %s" % res.get("reason", "unknown"), 2
    elif res.get("error") or res.get("pinned"):
        verdict, code = "DEFECT -- job cannot resolve a provider", 1
    elif real and report["runs"]["newest_is_real_run"]:
        verdict, code = ("HEALTHY (execution) -- delivery is a SEPARATE "
                         "%s" % ("FAILURE" if (dlv.get("count") in (0, None) and dlv.get("measured"))
                                 else "ok")), 0
    else:
        verdict, code = "DEFECT -- no successful run on record", 1

    report["verdict"] = verdict
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("koda corpus-ingest watch -- %s" % JOB)
        print("  record provider/model : %r / %r" % (job.get("provider"), job.get("model")))
        print("  pinned                : %s" % res.get("pinned"))
        print("  resolved in koda scope: provider=%r base_url=%r api_key=%s"
              % (res.get("provider"), res.get("base_url"),
                 "present" if res.get("api_key_present") else "ABSENT"))
        print("  last_status/streak    : %r / %r" % (job.get("last_status"), job.get("failure_streak")))
        print("  runs                  : %d total, %d provider-fail, %d real"
              % (len(files), len(provider_fail), len(real)))
        print("  delivery targets      : %s" % dlv.get("count", "not measured"))
        print()
        print("VERDICT: %s" % verdict)
    return code


if __name__ == "__main__":
    sys.exit(main())
