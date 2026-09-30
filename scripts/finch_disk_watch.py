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


def _resolve_profile():
    """Find this host's profile name, preferring the environment.

    Order: $HERMES_PROFILE, then the profile this script itself lives under.
    A script at .../profiles/<name>/skills/<skill>/scripts/ is inside <name> by
    construction, so that is a general rule derived from our own path, not a
    baked-in host value. Needed because cron sessions do not always export
    HERMES_PROFILE -- when they do not, the DB section below used to render
    EMPTY, which reads as "no bloat" when it actually means "not measured".
    That is a false negative in the safe direction, i.e. the worst kind here.
    """
    if PROFILE:
        return PROFILE, "env"
    here = os.path.abspath(__file__)
    parts = here.split(os.sep)
    for i, p in enumerate(parts):
        if p == "profiles" and i + 1 < len(parts):
            cand = parts[i + 1]
            if os.path.isdir(os.path.join(HOME_DIR, ".hermes", "profiles", cand)):
                return cand, "self_path"
    return "", "unresolved"


PROFILE, PROFILE_SOURCE = _resolve_profile()


def _db_target(rel):
    """Resolve a DB path under this host's Hermes profile root.

    Generic by construction: the profile name comes from $HERMES_PROFILE or from
    this script's own location, and the home directory from the environment, so
    this file carries no host-specific path and works on any machine."""
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


def reclaim_candidates():
    """Large model-weight files, sized by (inode, nlink) instead of by du.

    ``du`` counts a hardlinked file once per name it finds, so a weight that is
    both served from a service directory and present in a content-addressed
    blob store is double-counted. Deleting one name then reclaims ZERO bytes
    while every du-based figure promises otherwise -- a 4.2 GB over-estimate on
    the moondream2 set alone. Size by inode: a file whose ``nlink > 1`` shares
    its bytes with another name, so only the LAST name is worth deleting. This
    is a general rule (any hardlink), not a host value.
    """
    seen_inodes = {}
    out = []
    for base in (HOME_DIR, "/opt", "/usr/local", "/usr/share"):
        for dirpath, _dirnames, filenames in os.walk(base):
            # A blob store's own names are the OTHER links; keep them out of the
            # walk so the reported candidate is the copy a service can drop.
            if "/blobs/" in dirpath or dirpath.endswith("/.git"):
                continue
            for n in filenames:
                if not n.endswith((".gguf", ".safetensors", ".bin", ".pt", ".onnx")):
                    continue
                p = os.path.join(dirpath, n)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if st.st_size < 200 * 1024 * 1024:
                    continue
                key = st.st_ino
                if key in seen_inodes:
                    seen_inodes[key][1] += 1
                    continue
                seen_inodes[key] = [p, 1, st.st_size, st.st_nlink]
    for p, links, size, nlink in seen_inodes.values():
        reclaimable = links == 1 and nlink == 1
        out.append({
            "path": p,
            "size_mb": round(size / 1048576, 1),
            "nlink": nlink,
            "other_links": links - 1,
            "du_would_report_mb": round(size / 1048576, 1),
            "truly_reclaimable_mb": round(size / 1048576, 1) if reclaimable else 0.0,
        })
    out.sort(key=lambda r: -r["size_mb"])
    return out[:12]


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
    reclaim = reclaim_candidates()

    pct_met = pct >= TRIGGER_PCT
    growth_met = growth_mb_24h is not None and growth_mb_24h >= TRIGGER_GROWTH_MB_24H
    if pct_met or growth_met:
        verdict = "TRIGGER MET - run genie --assess + attribute"
    else:
        verdict = "gate unmet - no preemptive destructive cleanup"

    # Do not let a run younger than the extrapolation guard overwrite the
    # baseline. finch:scan and finch:work both run more often than
    # MIN_BASELINE_AGE_H, so writing on every run pins the baseline at ~0h and
    # the growth leg of the gate can then never be evaluated at all -- it
    # reports "unknown" forever. That is a false negative in the safe
    # direction: the one trigger that catches a real leak is the one that
    # never fires. Keeping the older sample makes every ~3rd run measurable
    # instead, and still refreshes once the sample has aged past the guard.
    baseline_written = False
    if not args.no_baseline_write:
        if base is None or (age_h is not None and age_h >= MIN_BASELINE_AGE_H):
            save_baseline(used_mb, pct)
            baseline_written = True

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
        "growth_measured": growth_mb_24h is not None,
        "baseline_written": baseline_written,
        "deleted_open_leaks": leaks,
        "reclaim_candidates": reclaim,
        "reclaim_total_true_mb": round(sum(r["truly_reclaimable_mb"] for r in reclaim), 1),
        "reclaim_du_overreport_mb": round(
            sum(r["du_would_report_mb"] - r["truly_reclaimable_mb"] for r in reclaim), 1
        ),
        "db_bloat": dbs,
        "db_bloat_measured": bool(dbs) or PROFILE_SOURCE != "unresolved",
        "profile": PROFILE,
        "profile_source": PROFILE_SOURCE,
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

    print("\n=== LARGE MODEL WEIGHTS (sized by inode, NOT du) ===")
    if not reclaim:
        print(f"  none >= 200 MB found under {HOME_DIR}, /opt, /usr/local, /usr/share")
    for r in reclaim:
        flag = "" if r["truly_reclaimable_mb"] else "  <-- HARDFLINKED: du counts it, deleting it frees 0 B"
        print(f"  {r['size_mb']:>7.0f} MB  nlink={r['nlink']} other_links={r['other_links']}  "
              f"reclaim {r['truly_reclaimable_mb']:>7.0f} MB  {r['path']}{flag}")
    print(f"  TOTAL truly reclaimable {sum(r['truly_reclaimable_mb'] for r in reclaim):.0f} MB; "
          f"du would over-report by {sum(r['du_would_report_mb'] - r['truly_reclaimable_mb'] for r in reclaim):.0f} MB")

    print("\n=== DB BLOAT (free-list is reclaimable; used is real data) ===")
    if not dbs:
        # Distinguish "measured, nothing to reclaim" from "could not measure".
        # An empty list used to print as a blank section, which a reader takes
        # for "no bloat" -- the safe-looking reading -- when it can also mean the
        # profile never resolved. Say which one it is.
        if PROFILE_SOURCE == "unresolved":
            print("  NOT MEASURED - could not resolve a Hermes profile name "
                  "(set $HERMES_PROFILE). This is NOT 'no bloat'.")
        else:
            print(f"  none found under profiles/{PROFILE} (profile={PROFILE}, "
                  f"source={PROFILE_SOURCE}) - measured, nothing to report")
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
