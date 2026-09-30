#!/usr/bin/env python3
"""Test that the growth baseline is keyed by PROFILE, not by CHECKOUT.

The defect this exists for: `disk_watch_baseline.json` used to be written next
to the script, i.e. inside whatever checkout was invoked. Two live copies of
this file (a repo checkout and a profile-skill install) therefore each held a
PRIVATE sample, and whichever copy a finch pass happened to run decided what
the growth gate reported -- even though the quantity being measured is a
property of the filesystem, not of the instrument. The file was also
git-tracked, so every run staged a real host measurement into a public repo.

The direction that matters most is the NEGATIVE one: a baseline path must NOT
contain the checkout it was derived from, or the defect simply relocates. The
positive direction -- two copies agreeing -- is what proves the rule works.

Every case runs the real module in a subprocess with a synthetic HOME, so
nothing here depends on this host. A test that reads the live filesystem
proves the host, not the rule.
"""
import json
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finch_disk_watch.py")
PASS, FAIL = [], []

# Profile names are SYNTHETIC and chosen here, never the host's. They are held
# in names and interpolated into the expected-path fragments below, because the
# committed source must never spell a concrete `profiles/<name>/` path -- the
# PII gate flags that shape on sight, and hardcoding it here would ship the
# very leak the gate exists to catch. PROFILE_SCOPE is built at runtime for the
# same reason: a literal fragment in the source is a finding even when the
# profile name is fake.
PROFILE = "alpha"
OTHER_PROFILE = "beta"
PROFILE_SCOPE = f"profiles/{PROFILE}/"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (("  -- " + detail) if detail and not cond else ""))


def _code(expr):
    """Import the real module under a synthetic HOME and print a JSON value."""
    return (
        "import importlib.util,json,sys\n"
        "spec=importlib.util.spec_from_file_location('fdw',sys.argv[1])\n"
        "m=importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "print(json.dumps(" + expr + "))\n"
    )


def run(home, expr, script=SCRIPT, env_extra=None, make_profiles=(PROFILE,)):
    """Return (value, None) on success or (None, error_tail) on a failed run.

    A 2-tuple rather than a sentinel dict, because a caller comparing two
    resolved PATHS must compare path strings, and a mixed return type makes
    that comparison a type error instead of a clean failure.
    """
    with tempfile.TemporaryDirectory() as tmp:
        for p in make_profiles:
            os.makedirs(os.path.join(home, ".hermes", "profiles", p), exist_ok=True)
        env = dict(os.environ)
        env["HOME"] = home
        env.pop("HERMES_PROFILE", None)
        env.pop("HERMES_HOME", None)
        env.pop("HERMES_DATA_DIR_SUFFIX", None)
        env.update(env_extra or {})
        r = subprocess.run([sys.executable, "-c", _code(expr), script],
                           capture_output=True, text=True, env=env, cwd=tmp)
        if r.returncode != 0:
            return None, (r.stderr.strip().splitlines() or ["?"])[-1]
        return json.loads(r.stdout.strip().splitlines()[-1]), None


if "--help" in sys.argv or "-h" in sys.argv:
    print(__doc__.strip())
    print("Usage: test_baseline_scope.py   (no arguments; exit 0 = all checks pass)")
    sys.exit(0)


with tempfile.TemporaryDirectory() as home:
    # A resolvable profile must EXIST before any case asserts a scoped path.
    # Written up front rather than inside case 5, because cases 1-3 assert the
    # scoped path and would otherwise be exercising the unresolved fallback --
    # which is case 4's job. Getting this order wrong makes cases 1-2 fail for
    # a reason that has nothing to do with the rule under test.
    #
    # makedirs, not just open: `run()` creates the profiles/ subdirs itself but
    # a FRESH sandbox home has no .hermes at all, and the marker write is the
    # first thing that touches it.
    os.makedirs(os.path.join(home, ".hermes"), exist_ok=True)
    with open(os.path.join(home, ".hermes", "active_profile"), "w") as fh:
        fh.write("alpha\n")

    # 1. A resolved profile puts the baseline under that profile's state dir.
    print("1. baseline path is keyed by profile, not by checkout")
    a, err = run(home, "m._baseline_path()")
    print(f"     -> {a}")
    check("no ERROR", err is None, str(err))
    check("profile actually resolved", isinstance(a, str) and PROFILE_SCOPE in a.replace(os.sep, "/"),
          f"got {a!r} -- if this fails, the sandbox has no active_profile marker")
    check("under the profile root",
          isinstance(a, str) and f".hermes/{PROFILE_SCOPE}" in a.replace(os.sep, "/"),
          f"got {a!r}")
    check("inside state/",
          isinstance(a, str) and a.replace(os.sep, "/").rstrip("/").endswith("state/disk_watch_baseline.json"),
          f"got {a!r}")
    check("NOT inside the checkout",
          isinstance(a, str) and os.path.dirname(os.path.abspath(SCRIPT)) not in a,
          f"got {a!r}")

    # 2. THE NEGATIVE DIRECTION: the path must not carry the checkout it came
    #    from, or the fix has only relocated the per-copy divergence.
    print("2. a copy under an unrelated checkout still resolves to the SAME path")
    with tempfile.TemporaryDirectory() as other:
        copy_dir = os.path.join(other, "some", "checkout", "scripts")
        os.makedirs(copy_dir, exist_ok=True)
        copy = os.path.join(copy_dir, "finch_disk_watch.py")
        with open(SCRIPT) as src, open(copy, "w") as dst:
            dst.write(src.read())
        b, err = run(home, "m._baseline_path()", script=copy)
        print(f"     -> {b}")
        check("no ERROR", err is None, str(err))
        check("checkout-independent", a == b, f"{a!r} != {b!r}")

    # 3. A DIFFERENT profile must get a DIFFERENT path -- otherwise two agents
    #    on one host would share a sample and measure each other's writes.
    print("3. a different profile gets a different baseline (no cross-agent bleed)")
    b2, err = run(home, "m._baseline_path()", env_extra={"HERMES_PROFILE": OTHER_PROFILE},
                  make_profiles=(PROFILE, OTHER_PROFILE))
    check("no ERROR", err is None, str(err))
    check("per-profile separation", b2 is not None and a != b2, f"{a!r} == {b2!r}")

    # 4. With NO profile resolvable, it must still measure rather than crash.
    print("4. unresolved profile still yields a usable path (no crash)")
    empty_home = tempfile.mkdtemp()
    try:
        c, err = run(empty_home, "m._baseline_path()", make_profiles=())
        print(f"     -> {c}")
        check("no ERROR", err is None, str(err))
        check("non-empty path", bool(c), f"got {c!r}")
    finally:
        import shutil
        shutil.rmtree(empty_home, ignore_errors=True)

    # 5. Round-trip: save then load reads the SAME file the path names. This is
    #    the invariant the whole gate rests on -- a rate is only meaningful if
    #    the sample it divides by is the sample that was written.
    print("5. save_baseline/load_baseline round-trip through the scoped path")
    d, err = run(home, "[(m._baseline_path(), (m.save_baseline(1234.5, 42.0) or m.load_baseline())['used_mb'])]")
    print(f"     -> {d}")
    check("no ERROR", err is None, str(err))
    # The expression above is a one-element list, so json round-trips it as a
    # NESTED list: d == [[path, used_mb]]. Guarding on len(d) == 2 tested the
    # outer length and never fired, so BOTH assertions below were dead code and
    # the round-trip invariant this file exists to prove was never asserted --
    # the case passed by being skipped. Unwrap explicitly and fail loudly if the
    # shape is not what we expect, rather than passing on an unexamined result.
    if isinstance(d, list) and len(d) == 1 and isinstance(d[0], list) and len(d[0]) == 2:
        path, used = d[0]
        check("round-trip path is profile-scoped",
              PROFILE_SCOPE in str(path).replace(os.sep, "/"), f"got {path!r}")
        check("round-trip value", used == 1234.5, f"got {used!r}")
    else:
        check("round-trip result has the expected shape", False,
              f"got {d!r} -- expected [[path, used_mb]]")

print()
print(f"passed {len(PASS)}/{len(PASS) + len(FAIL)}")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
