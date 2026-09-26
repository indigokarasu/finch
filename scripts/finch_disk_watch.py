#!/usr/bin/env python3
"""
finch_disk_watch.py — non-destructive disk-growth attribution for the
`system-disk-rising` finch task.

Read-only. Prints the two gate inputs (usage% and MB/24h) plus the
attribution of what's consuming the space, so a finch:work pass can
decide whether a trigger is MET without re-deriving the analysis.

Gates (from task re_verify_trigger):
  * usage%            >= 80                -> genie --assess + attribute
  * unexplained growth >= +5 GB / 24h      -> genie --assess + attribute

Usage:  python3 finch_disk_watch.py [--json]
"""
import argparse
import glob
import json
import math
import os
import sqlite3
import subprocess
import time

TRIGGER_PCT = 80.0
TRIGGER_GROWTH_MB_24H = 5 * 1024  # 5 GB

# A growth rate extrapolated from a near-zero interval is pure noise: two
# samples seconds apart differ by whatever unrelated I/O happened in between
# (a du walk, a test suite churning deleted-open files), and dividing that by
# ~0h produces an absurd MB/24h. Observed 2026-09-26: baseline 0.0h old
# reported +87911 MB/24h and flipped the gate to "TRIGGER MET" on pure noise.
# Below this age, report growth as unknown rather than guessing.
MIN_BASELINE_AGE_H = 1.0

HOME_DIR = os.path.expanduser("~")
PROFILE = os.environ.get("HERMES_PROFILE", "")


def _db_target(rel):
    """Resolve a DB path under this host's Hermes profile root.

    Generic by construction: the profile name and home directory come from the
    environment, so this file carries no host-specific path and works on any
    machine that sets $HERMES_PROFILE. Skips targets when unset."""
    if not PROFILE:
        return None
    return os.path.join(HOME_DIR, ".hermes", "profiles", PROFILE, rel)


DB_TARGETS = [
    (name, path) for name, path in (
        ("chronicle.db", _db_target("commons/db/chronicle/chronicle.db")),
        ("state.db", _db_target("state.db")),
        ("rally.db", _db_target("commons/data/ocas-rally/rally.db")),
    ) if path
]


def fs_usage():
    """Return (used_MB, total_MB, pct) for the root filesystem."""
    st = os.statvfs("/")
    total = st.f_blocks * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    free = st.f_bfree * st.f_frsize
    used = total - free
    return used / 1048576.0, total / 1048576.0, (used / total * 100.0 if total else 0.0)


def load_baseline(path=None):
    """Read the previous sample so growth/24h can be computed."""
    path = path or os.path.join(os.path.dirname(__file__), "disk_watch_baseline.json")
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_baseline(used_mb, pct, path=None):
    path = path or os.path.join(os.path.dirname(__file__), "disk_watch_baseline.json")
    payload = {
        "used_mb": round(used_mb, 1),
        "pct": round(pct, 1),
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)
    return payload


def top_dirs(paths=None, depth=2, limit=15):
    # Default to this host's home dir, not a literal /root — a committed path
    # that only works on one machine is a host leak and a portability bug.
    paths = paths or (HOME_DIR, "/var", "/usr", "/opt")
    out = []
    for base in paths:
        try:
            cp = subprocess.run(
                ["du", "-x", "-m", "-d", str(depth), base],
                capture_output=True, text=True, timeout=240,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        for line in cp.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            try:
                mb = int(parts[0].strip())
            except ValueError:
                continue
            out.append((mb, parts[1].strip()))
    out.sort(reverse=True)
    return out[:limit]


def deleted_open_leaks(threshold=50, top=8):
    """Find processes holding many deleted-but-open files (space held by no path)."""
    results = []
    for fddir in glob.glob("/proc/[0-9]*/fd"):
        pid = fddir.split("/")[2]
        n = 0
        total = 0
        newest_ok = True
        try:
            entries = os.listdir(fddir)
        except OSError:
            continue
        for fd in entries:
            try:
                if "(deleted)" not in os.readlink(os.path.join(fddir, fd)):
                    continue
                st = os.stat(os.path.join(fddir, fd))
            except OSError:
                continue
            n += 1
            total += st.st_size
        if n >= threshold:
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as fh:
                    cmd = fh.read().replace(b"\x00", b" ").decode(errors="replace").strip()
            except OSError:
                cmd = "?"
            results.append({
                "pid": int(pid), "fds": n, "mb": round(total / 1048576.0, 1),
                "cmd": cmd[:160], "readable": newest_ok,
            })
    results.sort(key=lambda r: r["mb"], reverse=True)
    return results[:top]


def db_bloat():
    """Separate real data from reclaimable free-list space per DB."""
    out = []
    for name, path in DB_TARGETS:
        if not os.path.exists(path):
            continue
        size_mb = os.path.getsize(path) / 1048576.0
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
            cur = con.cursor()
            cur.execute("PRAGMA page_size"); psz = cur.fetchone()[0]
            cur.execute("PRAGMA page_count"); pcnt = cur.fetchone()[0]
            cur.execute("PRAGMA freelist_count"); free = cur.fetchone()[0]
            con.close()
        except sqlite3.Error as e:
            out.append({"db": name, "size_mb": round(size_mb, 1), "error": str(e)})
            continue
        free_mb = free * psz / 1048576.0
        out.append({
            "db": name,
            "size_mb": round(size_mb, 1),
            "free_mb": round(free_mb, 1),
            "bloat_pct": round(free_mb / size_mb * 100.0, 1) if size_mb else 0.0,
            "used_mb": round((pcnt - free) * psz / 1048576.0, 1),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-baseline-write", action="store_true")
    args = ap.parse_args()

    used_mb, total_mb, pct = fs_usage()
    base = load_baseline()

    growth_mb_24h = None
    age_h = None
    growth_stale = False
    if base and "ts" in base:
        dt_h = max((time.time() - base["ts"]) / 3600.0, 0.01)
        age_h = dt_h
        if dt_h >= MIN_BASELINE_AGE_H:
            growth_mb_24h = (used_mb - base["used_mb"]) * (24.0 / dt_h)
        else:
            # Too recent to extrapolate from - report unknown, not a bogus rate.
            growth_stale = True

    leaks = deleted_open_leaks()
    dbs = db_bloat()
    dirs = top_dirs()

    pct_met = pct >= TRIGGER_PCT
    growth_met = growth_mb_24h is not None and growth_mb_24h >= TRIGGER_GROWTH_MB_24H
    if pct_met or growth_met:
        verdict = "TRIGGER MET - run genie --assess + attribute"
    else:
        verdict = "gate unmet - no preemptive destructive cleanup"

    if not args.no_baseline_write:
        save_baseline(used_mb, pct)

    report = {
        "used_mb": round(used_mb, 1),
        "total_mb": round(total_mb, 1),
        "pct": round(pct, 1),
        "pct_trigger": TRIGGER_PCT,
        "pct_met": pct_met,
        "growth_mb_24h": None if growth_mb_24h is None else round(growth_mb_24h, 1),
        "observed_delta_mb": None if not base else round(used_mb - base.get("used_mb", used_mb), 1),
        "baseline_used_mb": None if not base else base.get("used_mb"),
        "growth_trigger_mb_24h": TRIGGER_GROWTH_MB_24H,
        "growth_met": growth_met,
        "baseline_age_hours": None if age_h is None else round(age_h, 2),
        "growth_stale": growth_stale,
        "deleted_open_leaks": leaks,
        "db_bloat": dbs,
        "top_dirs_mb": [{"mb": mb, "path": p} for mb, p in dirs],
        "verdict": verdict,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print("=== DISK ===")
    print(f"used {used_mb/1024:.1f}GiB / {total_mb/1024:.1f}GiB  ({pct:.1f}%)  "
          f"pct_trigger={TRIGGER_PCT} -> {'MET' if pct_met else 'unmet'}")
    # READ THE GiB LINE, NOT df -h. df -h prints a CEILINGED whole number in
    # 1024-based units, so MB-level churn flips the display between adjacent
    # integers (71G <-> 72G) with zero bytes written. On 2026-09-26 that display
    # flap was logged as "+1G in 1.7h" and chased as a growth spike across
    # several scans; byte-exact sampling showed +7 MB over 150s and -36 MB
    # against the prior baseline. Never diff `df -h` output against an earlier
    # `df -h` value -- it is quantised. The GiB/decimal lines below are the
    # comparable ones, and observed_delta_mb is the only trustworthy delta.
    used_gb_dec = used_mb / 1000.0 * 1.048576
    print(f"     ({used_mb/1024:.2f} GiB = {used_gb_dec:.2f} GB decimal; "
          f"df -h would show {math.ceil(used_mb/1024.0)}G -- quantised, do not diff)")
    if growth_mb_24h is None:
        if growth_stale:
            print(f"growth: unknown - baseline only {age_h:.2f}h old "
                  f"(need >={MIN_BASELINE_AGE_H}h to extrapolate; re-run later)")
        else:
            print("growth: no baseline yet (first run)")
    else:
        # NOTE: this is a 24h-NORMALISED RATE, not a raw total. +2.6G over a
        # 6h sample normalises to +10.4G/24h and trips this gate, even though
        # only 2.6G of real growth occurred. Read it as "if this rate held for
        # a day". The task trigger wording ("+5G/24h") is a rate; the total
        # actually observed is base_used_mb delta, reported in the JSON below.
        print(f"growth: {growth_mb_24h:+.0f} MB/24h normalised (baseline {age_h:.1f}h old)  "
              f"trigger={TRIGGER_GROWTH_MB_24H} -> {'MET' if growth_met else 'unmet'}")
    print(f"\nVERDICT: {verdict}")

    print("\n=== DB BLOAT (free-list is reclaimable; used is real data) ===")
    for d in dbs:
        if "error" in d:
            print(f"  {d['db']:<14} ERROR {d['error']}")
        else:
            print(f"  {d['db']:<14} {d['size_mb']:>7.0f} MB  free {d['free_mb']:>6.0f} MB "
                  f"({d['bloat_pct']:>4.1f}%)  used {d['used_mb']:>7.0f} MB")

    print("\n=== DELETED-BUT-OPEN HOLDERS (space df counts, du cannot see) ===")
    if not leaks:
        print("  none (no process holds >50 deleted-open files)")
    for r in leaks:
        print(f"  pid {r['pid']:<8} {r['fds']:>6} fds  {r['mb']:>8.1f} MB  {r['cmd'][:90]}")

    print("\n=== TOP DIRS ===")
    for mb, p in dirs:
        print(f"  {mb:>7} MB  {p}")


if __name__ == "__main__":
    main()
