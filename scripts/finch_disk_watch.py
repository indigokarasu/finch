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
import struct
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
# Roots the weight walk covers. A constant, not an inline tuple, so a test can
# point the walk at a temp tree instead of inheriting whatever /opt happens to
# hold -- a fixture that reads the real host asserts nothing about the code.
RECLAIM_ROOTS = (HOME_DIR, "/opt", "/usr/local", "/usr/share")
PROFILE = os.environ.get("HERMES_PROFILE", "").strip()
# The platform's default data dir carries an optional suffix, so the default
# home is not always literally ~/.hermes. Mirrors hermes_constants'
# _get_platform_default_hermes_home() rather than hardcoding a path.
_DATA_SUFFIX = os.environ.get("HERMES_DATA_DIR_SUFFIX", "")


def _default_hermes_home():
    return os.path.join(HOME_DIR, ".hermes" + _DATA_SUFFIX)


def _profile_dir_ok(cand):
    """True if `cand` names a real profile directory under the default home."""
    if not cand or cand in (".", "..") or os.sep in cand:
        return False
    return os.path.isdir(os.path.join(_default_hermes_home(), "profiles", cand))


def _resolve_profile():
    """Find this host's profile name, preferring the environment.

    Order: $HERMES_PROFILE, then $HERMES_HOME's own basename, then the default
    home's `active_profile` marker, then the profile this script lives under.
    Every rule is derived from the environment or from this script's own
    location -- no host value is baked in, so the same code works anywhere.

    Why the two middle rules exist (measured 2026-09-30, four passes after
    clause (d) recorded the symptom): `self_path` can only fire when the script
    physically sits under .../profiles/<name>/..., which is true of the copy
    installed inside a profile's skill dir and FALSE of a repo checkout under
    ~/projects/... -- so the check that was supposed to prevent an empty DB
    section could never fire on a repo copy, and the section rendered EMPTY,
    which reads as "no bloat" when it actually means "not measured". That is a
    false negative in the safe direction, i.e. the worst kind here.

    $HERMES_HOME points AT a profile directory when a profile is active, and
    the platform's own resolution (hermes_constants.get_hermes_home) honours
    that env var ahead of the default home, so reading it here matches the
    agent's own rule instead of adding a fourth, private one.
    """
    if PROFILE:
        return PROFILE, "env"

    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        cand = os.path.basename(os.path.normpath(hermes_home))
        if _profile_dir_ok(cand):
            return cand, "hermes_home"

    try:
        with open(os.path.join(_default_hermes_home(), "active_profile")) as fh:
            cand = fh.read().strip()
    except OSError:
        cand = ""
    if _profile_dir_ok(cand):
        return cand, "active_profile"

    here = os.path.abspath(__file__)
    parts = here.split(os.sep)
    for i, p in enumerate(parts):
        if p == "profiles" and i + 1 < len(parts):
            cand = parts[i + 1]
            if _profile_dir_ok(cand):
                return cand, "self_path"
    return "", "unresolved"


PROFILE, PROFILE_SOURCE = _resolve_profile()


def _profile_root():
    """This host's data dir for the resolved profile, or None if unresolved.

    Generic by construction: the profile name comes from _resolve_profile() and
    the home from the environment, so this file carries no host-specific path.

    `_default_hermes_home()` is used rather than a literal `~/.hermes` because
    _profile_dir_ok() already honours HERMES_DATA_DIR_SUFFIX -- if the two
    disagreed, a suffixed install would validate the profile against one tree
    and then look for its DBs in another, and every DB path would resolve to
    None and the section would read as "no bloat" (the empty-means-not-measured
    false negative clause (d) was closed to fix).
    """
    if not PROFILE:
        return None
    return os.path.join(_default_hermes_home(), "profiles", PROFILE)


def _db_target(rel):
    """Resolve a DB path under this host's Hermes profile root."""
    root = _profile_root()
    return None if root is None else os.path.join(root, rel)


def _baseline_path():
    """Where the growth baseline lives: per PROFILE, never per CHECKOUT.

    Measured 2026-09-30 (finch:work #1041). The baseline used to sit next to
    this file, i.e. inside the checkout, which had two consequences, both real:

    1. A growth RATE is only meaningful against a baseline for the same
       instrument on the same host. With the baseline in the checkout, the
       repo copy and the profile-skill copy each held a private sample, so
       whichever copy a pass happened to run decided what the growth gate
       said. The rate is a property of the FILESYSTEM; the sample is an
       input to measuring it and must not vary with which copy is invoked.

    2. The file is git-tracked (it has been committed on every 'chore: sync'
       since 2026-09-26), so every run dirtied the working tree with a real
       host measurement. That is the same class as the 2026-09-26/27 publish
       incident in .gitignore: host state staged by `git add -A` into a public
       repo. Keying the path by profile puts it beside the profile's own data,
       outside any checkout, so the class cannot recur from a later pass.

    Falls back to the in-checkout path only when no profile resolves, so a run
    with no profile information still measures something rather than crashing.
    """
    root = _profile_root()
    if root is None:
        return os.path.join(os.path.dirname(__file__), "disk_watch_baseline.json")
    return os.path.join(root, "state", "disk_watch_baseline.json")


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
    path = path or _baseline_path()
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_baseline(used_mb, pct, path=None):
    path = path or _baseline_path()
    payload = {
        "used_mb": round(used_mb, 1),
        "pct": round(pct, 1),
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
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


def _reclaim_candidates(in_use):
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
    for base in RECLAIM_ROOTS:
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
        hardlink_unique = links == 1 and nlink == 1
        # A file can be hardlink-unique AND live: the weight a service is
        # reading on every request is the only name of its inode, so the
        # hardlink rule alone calls it free. Subtract live use, not rename it.
        live = p in in_use
        reclaimable = hardlink_unique and not live
        size_mb = round(size / 1048576, 1)
        # Two DIFFERENT reasons a weight is not reclaimable, and they must not
        # be summed under one name: a hardlinked file is double-counted by du
        # (a real du artifact), while an in-use file is simply alive (a liveness
        # gap). The old total added them, so a field named for the du artifact
        # moved when a service merely started reading a weight.
        hardlink_overreport_mb = 0.0 if hardlink_unique else size_mb
        out.append({
            "path": p,
            "size_mb": size_mb,
            "nlink": nlink,
            "other_links": links - 1,
            "du_would_report_mb": size_mb,
            "in_use_by_running_process": live,
            "hardlink_overreport_mb": hardlink_overreport_mb,
            "truly_reclaimable_mb": size_mb if reclaimable else 0.0,
        })
    out.sort(key=lambda r: -r["size_mb"])
    return out[:12]


def in_use_paths():
    """Absolute paths named by a RUNNING process -- its argv, or a file it holds open.

    ``reclaim_candidates()`` is hardlink-correct but has no way to know that a
    path is an argument of a live service, so a weight the running daemon reads
    on every request is reported as free. Deleting it does not fail loudly -- it
    works until the next inference, which is the worst shape a reclaim bug can
    have. Three independent sources, because any one alone is incomplete:

      * argv  catches the ``-m /path/model.gguf`` case;
      * open FDs catch a service that inherited the fd from a parent, or loaded
        the file and kept the descriptor;
      * memory MAPS catch the case neither of the other two sees, measured
        2026-09-30: a file that is mmapped but named by no argv token and held
        by no open fd is invisible to both. Every mmap'd region names its
        backing file in field 6 of /proc/<pid>/maps, and a loader that opens a
        weight, maps it, and closes the descriptor (the normal way to read a
        multi-GB model without pinning an fd) leaves NO other trace. That is a
        live file reported as free, which is the one answer this section must
        never give.

    A path can also be in use while being genuinely reclaimable later, so this is
    reported as a set for the caller to subtract, never as a deletion decision.
    General rule (walk /proc), not a host value.
    """
    out = set()
    for piddir in glob.glob("/proc/[0-9]*"):
        # Each source is independent, so each is read in its own try. A single
        # `except OSError: continue` on the cmdline read used to abandon the
        # fd and maps walks for that pid: an unreadable argv (a process
        # vanished mid-walk, a hidepid mount, a kernel thread) silently
        # discarded two sources that might still have been readable. The
        # measurement was then "this file is free" when the truth was "I
        # stopped looking", which is the false negative in the dangerous
        # direction this function exists to prevent.
        try:
            with open(os.path.join(piddir, "cmdline"), "rb") as fh:
                for tok in fh.read().split(b"\0"):
                    if tok.startswith(b"/") and os.sep.encode() in tok[1:]:
                        out.add(os.fsdecode(tok.rstrip(b"/")))
        except OSError:
            pass
        try:
            with open(os.path.join(piddir, "maps")) as fh:
                for line in fh:
                    parts = line.split(maxsplit=5)
                    if len(parts) < 6:
                        continue
                    # Field 6 is the backing file, and it CARRIES THE LINE'S OWN
                    # TRAILING NEWLINE -- a real /proc/<pid>/maps line ends
                    # "/path/weight.gguf\n". Kept verbatim, the path never
                    # equals any candidate on disk, so every mapped file reads
                    # as unmapped while looking correct in the source.
                    backing = parts[5][:-1] if parts[5].endswith("\n") else parts[5]
                    # A mapped region whose file was unlinked reads
                    # "<path> (deleted)"; the path can no longer be a reclaim
                    # candidate, but it is still a file the kernel is using.
                    if backing.endswith(" (deleted)"):
                        backing = backing[: -len(" (deleted)")]
                    if backing.startswith("/"):
                        out.add(backing)
        except OSError:
            pass
        fddir = os.path.join(piddir, "fd")
        try:
            fds = os.listdir(fddir)
        except OSError:
            continue
        for fd in fds:
            try:
                out.add(os.path.realpath(os.path.join(fddir, fd)))
            except OSError:
                continue
    return out


def reclaim_candidates():
    """Public entry: hardlink-correct reclaim sizing, discounted by live process use."""
    return _reclaim_candidates(in_use=in_use_paths())


def deleted_open_leaks(threshold=50, top=8):
    """Find processes holding many deleted-but-open files (space held by no path).

    ``threshold`` is a *count of file descriptors*, not a size. The default of
    50 is high enough that a process leaking hundreds of small deleted files --
    the common shape for a browser or a rotating log -- falls under it and the
    report says ``[]``. That reads as "no invisible space", which is a false
    negative in the dangerous direction: this section exists precisely to rule
    out usage that no directory listing can see, so an empty list is the
    reading that most needs to be qualified. ``[]`` and "the biggest holder is
    under 50 fds" are different claims, and only the second is what was
    measured.

    Both are now reported: the thresholded list keeps its original meaning, and
    a new total over ALL holders, regardless of count, says how much space is
    held with no path. A reader wanting the old behaviour reads
    ``deleted_open_leaks``; a reader wanting the truth about invisible space
    reads ``deleted_open_total_mb``.
    """
    results = []
    all_rows = []
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
        if n:
            all_rows.append((total, n, pid))
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
    return results[:top], all_rows


def _wal_live_bytes(wal_path):
    """Bytes of a -wal file that are LIVE frames, not a stale high-water tail.

    A SQLite checkpoint copies committed frames into the database and resets
    the WAL header's salt, but does not shrink the file. The bytes past the new
    end are on disk, counted by du and by getsize, and belong to no
    transaction. Reading getsize() there reports a WAL that has been fully
    checkpointed as though a reader were pinning it, which is a false alarm
    that invites a pointless "fix" on a healthy database.

    The live region is the prefix of frame headers whose salt equals the salt
    in the current WAL header. The 32-byte header is always live and is
    counted, so a WAL with every frame live returns exactly the file size and a
    fully-checkpointed one returns 32. No PRAGMA, no write, no checkpoint
    triggered. Returns the file size unchanged if the header is not a WAL
    header at all.
    """
    try:
        with open(wal_path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return 0
    if len(raw) < 32:
        return len(raw)
    magic, _fmt, psize, _ckpt, salt1, salt2, _c1, _c2 = struct.unpack(">8I", raw[:32])
    if magic not in (0x377F0682, 0x377F0683) or psize <= 0:
        return len(raw)
    frame_bytes = 24 + psize
    frames = (len(raw) - 32) // frame_bytes
    live = 0
    for i in range(frames):
        off = 32 + i * frame_bytes
        _pg, _dbsize, fs1, fs2, _fc1, _fc2 = struct.unpack(">6I", raw[off:off + 24])
        if fs1 == salt1 and fs2 == salt2:
            live = i + 1
        else:
            break
    return 32 + live * frame_bytes


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
        row = {
            "db": name,
            "size_mb": round(size_mb, 1),
            "free_mb": round(free_mb, 1),
            "bloat_pct": round(free_mb / size_mb * 100.0, 1) if size_mb else 0.0,
            "used_mb": round((pcnt - free) * psz / 1048576.0, 1),
        }
        # A WAL-mode DB's sidecars are real bytes on the filesystem and are
        # invisible to getsize(db) and to page_count. state.db's -wal was 64 MB
        # against a 736 MB database -- 8% of the file's footprint reported by
        # no field in this section. Worse, a checkpoint resets the WAL's
        # contents in place and does NOT shrink the file, so file size measures
        # the high-water mark and not the live frame count: a 64 MB -wal that
        # looks stuck is usually a completed checkpoint that never truncated.
        # Read the header's salt against the frame headers to get live frames.
        wal = path + "-wal"
        if os.path.exists(wal):
            wal_bytes = os.path.getsize(wal)
            row["wal_file_mb"] = round(wal_bytes / 1048576.0, 1)
            row["wal_live_mb"] = round(_wal_live_bytes(wal) / 1048576.0, 1)
        out.append(row)
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

    leaks, leak_rows = deleted_open_leaks()
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
        "deleted_open_leaks_threshold_fds": 50,
        "deleted_open_total_mb": round(
            sum(t for t, _n, _p in leak_rows) / 1048576.0, 2
        ),
        "deleted_open_holders": len(leak_rows),
        "deleted_open_top_holder_mb": (
            round(max(leak_rows)[0] / 1048576.0, 2) if leak_rows else 0.0
        ),
        "reclaim_candidates": reclaim,
        "reclaim_total_true_mb": round(sum(r["truly_reclaimable_mb"] for r in reclaim), 1),
        "reclaim_in_use_mb": round(
            sum(r["size_mb"] for r in reclaim if r["in_use_by_running_process"]), 1
        ),
        "reclaim_du_overreport_mb": round(
            sum(r["hardlink_overreport_mb"] for r in reclaim), 1
        ),
        "reclaim_not_reclaimable_mb": round(
            sum(r["size_mb"] for r in reclaim if not r["truly_reclaimable_mb"]), 1
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
