"""Host paths and timezone for this skill's scripts, resolved at runtime.

This repo is public, so scripts never hardcode the operator's profile path or
timezone. They ask here instead:

  profile_root()  $HERMES_HOME if set, else the parent of the `skills/` dir this
                  skill is installed under, else ~/.hermes.
  hermes_root()   the Hermes root holding `profiles/` (profile_root() when the
                  profile is not under a `profiles/` dir).
  get(KEY)        KEY from the environment, else from <profile>/.env.
  host_tz()       the host timezone as a tzinfo. OCAS_TZ (an IANA name, in the
                  environment or the profile .env) overrides it.

Same contract as ocas-usercontext's scripts/_ucenv.py.

Importing this module has no side effects (the .env is only opened when get()
is called). Run directly it honors --help, because the D9 audit probes every
executable in scripts/.

Usage:
  python _ocasenv.py KEY [KEY ...]   print the resolved value of each key
  python _ocasenv.py --root          print profile_root()
  python _ocasenv.py --tz            print the resolved host timezone
  python _ocasenv.py --help          this message
"""
import os
import sys

# D9: help guard before any path is resolved. Only when run as a script, so an
# importing script's own --help is never hijacked.
if __name__ == "__main__" and ("--help" in sys.argv or "-h" in sys.argv):
    print((__doc__ or "<no docstring>").strip())
    sys.exit(0)


def profile_root():
    """Return the active Hermes profile directory."""
    home = os.environ.get("HERMES_HOME")
    if home:
        return os.path.expanduser(home)
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        parent = os.path.dirname(d)
        if os.path.basename(d) == "skills":
            return parent
        if parent == d:
            break
        d = parent
    return os.path.expanduser("~/.hermes")


def hermes_root():
    """Return the Hermes install root (the dir holding `profiles/`), else profile_root()."""
    prof = profile_root()
    parent = os.path.dirname(prof)
    if os.path.basename(parent) == "profiles":
        return os.path.dirname(parent)
    return prof


def env_file():
    """Path of the profile .env."""
    return os.path.join(profile_root(), ".env")


def get(key, default=""):
    """Return key from the environment, else from the profile .env."""
    val = os.environ.get(key)
    if val:
        return val
    try:
        with open(env_file(), "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return default


def host_tz():
    """Return the host timezone as a tzinfo, resolved at runtime.

    Order: OCAS_TZ (env or profile .env) -> TZ env var -> /etc/localtime
    symlink -> /etc/timezone -> the system's current UTC offset. An IANA zone
    is preferred because it applies the right DST offset for each target date;
    the last fallback is a fixed offset and is only correct away from a DST
    change.
    """
    override = get("OCAS_TZ")
    names = [override, os.environ.get("TZ", "").lstrip(":")]
    try:
        link = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in link:
            names.append(link.rsplit("zoneinfo/", 1)[1])
    except OSError:
        pass
    try:
        with open("/etc/timezone", "r", encoding="utf-8") as f:
            names.append(f.read().strip())
    except OSError:
        pass

    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None
    if ZoneInfo is not None:
        for name in names:
            if not name:
                continue
            try:
                return ZoneInfo(name)
            except Exception:
                if name == override:
                    print(f"OCAS_TZ={override!r} is not a known IANA zone; "
                          "falling back to the host timezone", file=sys.stderr)
    from datetime import datetime
    return datetime.now().astimezone().tzinfo


def host_tz_name():
    """IANA name of host_tz() when it has one, else its UTC-offset label."""
    tz = host_tz()
    return getattr(tz, "key", None) or str(tz)


if __name__ == "__main__":
    args = sys.argv[1:]
    for k in args:
        if k == "--root":
            print(profile_root())
        elif k == "--tz":
            print(host_tz_name())
        else:
            print(get(k))
