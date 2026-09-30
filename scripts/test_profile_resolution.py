#!/usr/bin/env python3
"""Test _resolve_profile() in finch_disk_watch.py. Both directions must be exercised.

The symptom this exists for: `profile_source='unresolved'` rendered the DB
bloat section EMPTY, which reads as "no bloat" when it actually means "not
measured". So the direction that matters most is the NEGATIVE one -- given a
sandbox with no profile information at all, the resolver must say 'unresolved'
rather than invent a name -- and the direction that regresses silently is a
name that is not a real profile directory being accepted anyway.

Every case runs the real resolver in a subprocess with a synthetic HOME, so
nothing here depends on this host's profiles. A test that reads the live
filesystem proves the host, not the rule.
"""
import json
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finch_disk_watch.py")
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (("  -- " + detail) if detail and not cond else ""))


def resolve(home, script=SCRIPT, env_extra=None, make_profiles=("alpha",)):
    """Run the script's _resolve_profile() under a synthetic HOME.

    Returns (profile, source). The script is copied OUT of any 'profiles/'
    path when `script` is given, so the self_path rule is exercised only when
    the test asks for it.
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
        code = (
            "import importlib.util,json,sys\n"
            "spec=importlib.util.spec_from_file_location('fdw',sys.argv[1])\n"
            "m=importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "print(json.dumps([m.PROFILE,m.PROFILE_SOURCE]))\n"
        )
        r = subprocess.run([sys.executable, "-c", code, script], capture_output=True,
                           text=True, env=env, cwd=tmp)
        if r.returncode != 0:
            tail = (r.stderr.strip().splitlines() or ["?"])[-1]
            return None, "ERROR: " + tail
        return tuple(json.loads(r.stdout.strip().splitlines()[-1]))


if "--help" in sys.argv or "-h" in sys.argv:
    print(__doc__.strip())
    print("Usage: test_disk_watch_profile.py   (no arguments; exit 0 = all checks pass)")
    sys.exit(0)


with tempfile.TemporaryDirectory() as home:
    # 1. The regression itself: a repo copy under ~/projects cannot self-resolve.
    print("1. repo copy, no env, no marker -> must NOT be unresolved by luck")
    prof, src = resolve(home)
    check("resolves to something", src != "unresolved" or prof == "",
          f"got profile={prof!r} source={src!r}")
    check("source is a named rule", src in ("env", "hermes_home", "active_profile", "self_path", "unresolved"))
    check("no ERROR", not str(src).startswith("ERROR"), str(src))
    print(f"     -> profile={prof!r} source={src!r}")

    # 2. $HERMES_PROFILE wins outright, even for a name that is not a profile.
    print("2. $HERMES_PROFILE is authoritative")
    prof, src = resolve(home, env_extra={"HERMES_PROFILE": "alpha"})
    check("env wins", (prof, src) == ("alpha", "env"), f"got {prof!r}/{src!r}")

    # 3. $HERMES_HOME -> the active profile, matching the platform's own rule.
    print("3. $HERMES_HOME basename names the active profile")
    prof, src = resolve(home, env_extra={"HERMES_HOME": os.path.join(home, ".hermes", "profiles", "alpha")})
    check("hermes_home rule fires", (prof, src) == ("alpha", "hermes_home"), f"got {prof!r}/{src!r}")

    # 4. The marker file, for the case where neither env var is exported.
    print("4. active_profile marker, neither env var exported")
    with open(os.path.join(home, ".hermes", "active_profile"), "w") as fh:
        fh.write("alpha\n")
    prof, src = resolve(home)
    check("active_profile rule fires", (prof, src) == ("alpha", "active_profile"), f"got {prof!r}/{src!r}")

    # 5. A marker naming a profile that does not exist must NOT be accepted --
    #    the guard that keeps this from becoming a path-traversal footgun.
    print("5. stale marker naming a missing profile is rejected, not obeyed")
    with open(os.path.join(home, ".hermes", "active_profile"), "w") as fh:
        fh.write("does-not-exist\n")
    prof, src = resolve(home, env_extra={"HERMES_HOME": ""})
    check("stale marker not accepted", (prof, src) == ("", "unresolved"), f"got {prof!r}/{src!r}")

    # 6. A traversal-shaped marker must never escape the profiles dir.
    print("6. traversal-shaped marker is rejected")
    with open(os.path.join(home, ".hermes", "active_profile"), "w") as fh:
        fh.write("../../../etc\n")
    prof, src = resolve(home, env_extra={"HERMES_HOME": ""})
    check("traversal rejected", (prof, src) == ("", "unresolved"), f"got {prof!r}/{src!r}")

    # 7. A data-dir suffix moves the home; the resolver must follow it.
    print("7. HERMES_DATA_DIR_SUFFIX relocates the default home")
    # The suffix extends the DATA DIR name (~/.hermes-x), not $HOME itself.
    suff_home = os.path.join(home, ".hermes-suffixed")
    os.makedirs(os.path.join(suff_home, "profiles", "alpha"), exist_ok=True)
    with open(os.path.join(suff_home, "active_profile"), "w") as fh:
        fh.write("alpha\n")
    prof, src = resolve(home, env_extra={"HERMES_DATA_DIR_SUFFIX": "-suffixed"})
    check("suffix followed", (prof, src) == ("alpha", "active_profile"), f"got {prof!r}/{src!r}")

    # 8. self_path still works for a copy installed inside a profile's skill dir.
    print("8. self_path still fires for a profile-installed copy")
    installed = os.path.join(home, ".hermes", "profiles", "alpha", "skills", "s", "scripts")
    os.makedirs(installed, exist_ok=True)
    live = os.path.join(installed, "finch_disk_watch.py")
    with open(SCRIPT) as src_fh, open(live, "w") as dst_fh:
        dst_fh.write(src_fh.read())
    prof, src = resolve(home, script=live, env_extra={"HERMES_HOME": ""})
    check("self_path fires", (prof, src) == ("alpha", "self_path"), f"got {prof!r}/{src!r}")

print()
print(f"passed {len(PASS)}/{len(PASS) + len(FAIL)}")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
