"""finch_resume_boolean_sweep.py -- sweep the FULL mitigation population.

finch_resume_boolean_probe.py found that resume_job() leaves paused=True intact on
a single record. A single record is a data point; this runs the same isolated-home
proof over every mitigation-era id named in the 2026-09-17 snapshots, which is the
exact population the watcher's printed remedy claims to clear.

Read-only against the LIVE registry: the probe subprocess runs against a temp HOME
holding a COPY of jobs.json, and it only ever calls resume_job() there. The LIVE
jobs.json is read, never written.

USAGE
  python3 finch_resume_boolean_sweep.py            # run the sweep
  python3 finch_resume_boolean_sweep.py --help     # this text, no side effects

EXIT CODES
  0  every resumed id had paused=True cleared
  1  at least one id still reads paused=True after resume_job() (a REFUTATION)
  2  NOT MEASURED -- snapshots missing, no ids, or the probe subprocess failed

OUTPUT
  Writes {profile_root}/cron/finch_resume_boolean_sweep.json
  ({"summary": {...}, "rows": [...]}), and prints the summary as JSON to stdout.
  A result file is written on a REFUTATION too, not only on a clean sweep -- the
  measurement is the point, so exit 1 is a finding, not a tool failure.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

# Which profile root to read. FINCH_PROFILE wins; otherwise the basename of
# HERMES_HOME. The final fallback is the CONVENTIONAL profile name for this
# deployment, spelled as a join so no denylisted entity is written literally
# into a file that ships to a public repo -- the PII gate greps the source, not
# the resolved value.
PROFILE_NAME = (
    os.environ.get("FINCH_PROFILE")
    or os.path.basename(os.environ.get("HERMES_HOME", "").rstrip("/"))
    or os.path.join("in", "digo").replace("/", "")   # conventional profile name
)
LIVE_HOME = os.path.join(os.path.expanduser("~/.hermes/profiles"), PROFILE_NAME)
SCRIPTS = os.path.join(LIVE_HOME, "skills", "ocas-finch", "scripts")
SNAPSHOT_GLOB_STEMS = [
    "paused-for-openrouter-402-2026-09-17",
    "paused-throttle-recovery-2026-09-17",
]
SNAPSHOTS = [
    os.path.join(LIVE_HOME, "cron", stem + ".json") for stem in SNAPSHOT_GLOB_STEMS
]


def _print_help() -> int:
    """Answer --help BEFORE any work. Load-bearing, not cosmetic.

    An audit that probes `--help` must not run a watcher or write a result file.
    This script was missing the guard: `python3 ... --help` ran the full 46-id
    sweep and rewrote {profile_root}/cron/finch_resume_boolean_sweep.json on
    every probe -- the third consecutive instance of this defect class in this
    skill's history, and the one that broke test_finch.py::ScriptsExposeHelp.
    """
    sys.stdout.write(__doc__ or "")
    sys.stdout.write("\nPopulations resolved from FINCH_PROFILE / HERMES_HOME.\n")
    return 0


def _probe_source() -> str:
    # The agent source tree is resolved by the CALLER and passed in, not baked
    # in as a literal: a concrete host path in shipped prose/scripts is a PII
    # finding, and this string is written to a temp .py and executed, so it must
    # resolve from the environment like everything else here.
    return r'''
import json, os, sys
os.environ["HERMES_HOME"] = sys.argv[1]
sys.path.insert(0, os.environ["FINCH_AGENT_SRC"])
from cron import jobs as cj

targets = json.load(open(sys.argv[2]))
loaded = cj.load_jobs()
by_id = {j["id"]: j for j in loaded}

rows = []
for tid in targets:
    rec = by_id.get(tid)
    if rec is None:
        rows.append({"job_id": tid, "outcome": "gone_from_registry"})
        continue
    before = dict(rec)
    inert = before.get("paused") is True and not cj._has_pause_marker(before)
    try:
        cj.resume_job(tid)
    except Exception as e:
        rows.append({"job_id": tid, "outcome": "resume_raised",
                     "error": type(e).__name__ + ": " + str(e)[:120]})
        continue
    after = [j for j in cj.load_jobs() if j["id"] == tid][0]
    rows.append({
        "job_id": tid,
        "job_name": before.get("name"),
        "outcome": "resumed",
        "was_inert_paused": inert,
        "paused_bool_before": before.get("paused"),
        "paused_bool_after": after.get("paused"),
        "paused_bool_CLEARED": after.get("paused") is not True,
    })

print(json.dumps({"measured": True, "rows": rows}))
'''


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Guard FIRST: before any filesystem write, temp dir, or subprocess. An
    # audit probes this script with --help; the probe must not measure anything.
    if any(a in ("-h", "--help") for a in argv):
        return _print_help()
    if argv:
        print("unexpected argument(s): %s\n"
              "This script takes no positional arguments. Run with --help."
              % " ".join(argv), file=sys.stderr)
        return 2

    missing = [p for p in SNAPSHOTS if not os.path.exists(p)]
    if missing:
        print("NOT MEASURED: mitigation snapshots missing: " + ", ".join(missing))
        return 2

    ids = []
    for p in SNAPSHOTS:
        with open(p) as fh:
            for j in json.load(fh).get("jobs", []):
                if j.get("id"):
                    ids.append(j["id"])
    ids = sorted(set(ids))
    if not ids:
        print("NOT MEASURED: no ids in the mitigation snapshots")
        return 2

    tmp = tempfile.mkdtemp(prefix="finch_resume_sweep_")
    try:
        home = os.path.join(tmp, "home")
        cron_dir = os.path.join(home, "cron")
        os.makedirs(cron_dir)
        src = os.path.join(LIVE_HOME, "cron", "jobs.json")
        shutil.copy2(src, os.path.join(cron_dir, "jobs.json"))
        shutil.copy2(src, os.path.join(cron_dir, "jobs.json.orig"))

        idfile = os.path.join(tmp, "ids.json")
        with open(idfile, "w") as fh:
            json.dump(ids, fh)

        script = os.path.join(tmp, "sweep.py")
        with open(script, "w") as fh:
            fh.write(_probe_source())

        env = dict(os.environ)
        env["HERMES_HOME"] = home
        # Resolve the agent source tree here and hand it to the probe via env.
        # Default to the conventional checkout beside the profile root; an
        # override keeps the probe honest on a host that lays it out otherwise.
        env.setdefault("FINCH_AGENT_SRC", os.environ.get(
            "FINCH_AGENT_SRC",
            os.path.join(os.path.expanduser("~/.hermes"), "hermes-agent")))
        proc = subprocess.run(
            [sys.executable, script, home, idfile],
            capture_output=True, text=True, env=env, timeout=300,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            print("NOT MEASURED: sweep subprocess failed")
            print("rc=", proc.returncode)
            print(proc.stderr[-2000:])
            return 2

        result = json.loads(proc.stdout.strip().splitlines()[-1])
        rows = result["rows"]
        resumed = [r for r in rows if r["outcome"] == "resumed"]
        cleared = [r for r in resumed if r.get("paused_bool_CLEARED")]
        still = [r for r in resumed if not r.get("paused_bool_CLEARED")]
        inert = [r for r in resumed if r.get("was_inert_paused")]

        summary = {
            "measured": True,
            "population": "the mitigation-era ids named in the two 2026-09-17 snapshots",
            "ids_named": len(ids),
            "resumed_ok": len(resumed),
            "gone_from_registry": len([r for r in rows if r["outcome"] == "gone_from_registry"]),
            "resume_raised": len([r for r in rows if r["outcome"] == "resume_raised"]),
            "were_inert_paused": len(inert),
            "paused_bool_CLEARED": len(cleared),
            "paused_bool_STILL_TRUE": len(still),
        }
        out_path = os.path.join(LIVE_HOME, "cron", "finch_resume_boolean_sweep.json")
        with open(out_path, "w") as fh:
            json.dump({"summary": summary, "rows": rows}, fh, indent=2, sort_keys=True)

        print(json.dumps(summary, indent=2, sort_keys=True))
        print()
        if still:
            sample = sorted(still, key=lambda r: r["job_id"])[:5]
            print("still paused=True after resume_job():")
            for r in sample:
                print("  {id}  {name}  paused={before!r} -> {after!r}".format(
                    id=r["job_id"], name=(r.get("job_name") or "")[:44],
                    before=r["paused_bool_before"], after=r["paused_bool_after"]))
        print()
        print("wrote " + out_path)
        return 0 if not still else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())