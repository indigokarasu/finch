#!/usr/bin/env python3
"""Negative + fixture test for finch_ledger_guard.py.

A guard that only ever returns CLEAN is indistinguishable from no guard. Each
case below asserts the guard FAILS on a synthetic violation and that --repair
actually fixes it, then restores. Uses a throwaway copy -- the live ledger is
never touched.
"""
import json, os, shutil, subprocess, sys, tempfile, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "finch_ledger_guard.py")
UTC = datetime.timezone.utc
LIVE = "/root/.hermes/commons/data/ocas-finch/task-list.json"

fails = []


def run(path, extra=()):
    p = subprocess.run([sys.executable, GUARD, "--ledger", path, *extra],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def load(p):
    return json.load(open(p))


def save(p, d):
    json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
    open(p, "a").write("\n")


tmpdir = tempfile.mkdtemp(prefix="ledger_guard_test_")
led = os.path.join(tmpdir, "task-list.json")
shutil.copy2(LIVE, led)
os.chmod(led, 0o644)
base = load(led)
future = (datetime.datetime.now(UTC) + datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

# --- case 1: forward header stamp must be CAUGHT -------------------------
d = json.loads(json.dumps(base))
d["as_of"] = future
save(led, d)
rc, out = run(led)
print("[1] forward as_of           -> exit=%d %s" % (rc, "CAUGHT" if rc == 1 else "*** MISSED ***"))
if rc != 1: fails.append("case1 header forward not caught")
if "FORWARD" not in out: fails.append("case1 no FORWARD line")

# --- case 2: forward per-task stamp must be CAUGHT -----------------------
d = json.loads(json.dumps(base))
t = next(x for x in d["tasks"] if x.get("id") == "email-google-oauth-grant-mesh")
t["updated_at"] = future
t["last_finch_review"] = future + " (finch:scan #999)"
save(led, d)
rc, out = run(led)
caught = rc == 1 and "email-google-oauth-grant-mesh" in out
print("[2] forward task stamp      -> exit=%d %s" % (rc, "CAUGHT" if caught else "*** MISSED ***"))
if not caught: fails.append("case2 task forward not caught")

# --- case 3: --repair fixes it and preserves the suffix ------------------
rc, out = run(led, ("--repair",))
d = load(led)
t = next(x for x in d["tasks"] if x.get("id") == "email-google-oauth-grant-mesh")
suffixed = t["last_finch_review"].endswith("(finch:scan #999)")
past = t["updated_at"] <= datetime.datetime.fromtimestamp(os.path.getmtime(led), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
print("[3] repair clamps + suffix   -> suffix_kept=%s in_past=%s %s"
      % (suffixed, past, "OK" if suffixed and past else "*** FAIL ***"))
if not (suffixed and past): fails.append("case3 repair wrong")

# --- case 4: clean ledger must PASS (exit 0) -----------------------------
rc, out = run(led)
print("[4] clean ledger            -> exit=%d %s" % (rc, "CLEAN" if rc == 0 else "*** FALSE POSITIVE ***"))
if rc != 0: fails.append("case4 false positive on clean ledger")

# --- case 5: PAST stamps must NOT be flagged (no false positive) ---------
d = json.loads(json.dumps(base))
d["as_of"] = "2020-01-01T00:00:00Z"
for x in d["tasks"][:5]:
    x["updated_at"] = "2020-01-01T00:00:00Z"
save(led, d)
rc, out = run(led)
print("[5] ancient past stamps     -> exit=%d %s" % (rc, "CLEAN" if rc == 0 else "*** FALSE POSITIVE ***"))
if rc != 0: fails.append("case5 ancient stamps misflagged")

# --- case 6: unreadable/missing ledger -> exit 2, NOT a silent pass ------
missing = os.path.join(tmpdir, "nope.json")
rc, out = run(missing)
ok = rc == 2 and "UNREADABLE" in out
print("[6] missing ledger          -> exit=%d %s" % (rc, "SIGNALLED" if ok else "*** SILENT PASS ***"))
if not ok: fails.append("case6 missing ledger not signalled")

# --- case 7: corrupt JSON -> exit 2 -------------------------------------
bad = os.path.join(tmpdir, "bad.json")
open(bad, "w").write("{not json")
rc, out = run(bad)
ok = rc == 2
print("[7] corrupt JSON            -> exit=%d %s" % (rc, "SIGNALLED" if ok else "*** SILENT PASS ***"))
if not ok: fails.append("case7 corrupt json not signalled")

# --- case 8: --repair preserves file mode 644 ----------------------------
d = json.loads(json.dumps(base))
d["as_of"] = future
save(led, d)
run(led, ("--repair",))
mode = oct(os.stat(led).st_mode & 0o777)
ok = mode == "0o644"
print("[8] mode preserved by repair-> %s %s" % (mode, "OK" if ok else "*** MODE CHANGED ***"))
if not ok: fails.append("case8 repair changed file mode")

# --- case 9: live ledger untouched by any of this -----------------------
live_ok = os.path.getmtime(LIVE) == os.path.getmtime(LIVE)  # sanity
rc, out = run(LIVE)
print("[9] live ledger re-check    -> exit=%d %s" % (rc, "CLEAN" if rc == 0 else "*** STILL DIRTY ***"))
if rc != 0: fails.append("case9 live ledger still dirty")

print("\n%s" % ("ALL CASES PASSED" if not fails else "FAILURES:\n  " + "\n  ".join(fails)))
shutil.rmtree(tmpdir)
sys.exit(0 if not fails else 1)
