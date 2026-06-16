#!/usr/bin/env python3
"""
memory_guard.py - deterministic safety wrapper for MEMORY.md compaction (ocas-finch).

The LLM compaction procedure (references/forgetting_curve.md) decides WHAT to keep,
route, and consolidate. This guard provides the GUARANTEES that procedure cannot:

  - hard char-cap enforcement (deterministic eviction of lowest-priority NON-directive lines)
  - directive protection (Always/Never/Must lines are never auto-evicted)
  - anti-pattern stripping (no "see references/..." pointers - the documented regrowth cause)
  - atomic, locked, backed-up writes (OOM-safe; race-safe vs the live `memory` tool)
  - idempotency (no-op when already compliant - prevents churn/erosion)
  - integrity verification + audit (DecisionRecords)

It is LINE-PRESERVING: it never rewrites or reorders entry text (that is the LLM's job).
It only REMOVES lines (stripped pointers + over-cap evictions), and archives what it removes.

Intended call site: the FINAL write step of finch.compact. The LLM produces the proposed
MEMORY.md; this guard validates + enforces + writes it safely. Can also run standalone as a
deterministic floor.

Usage:
  python3 memory_guard.py                 # dry-run report against MEMORY.md
  python3 memory_guard.py --apply         # enforce + safe-write
  python3 memory_guard.py --json
  python3 memory_guard.py --file PATH ...  # override target (testing)
"""
import argparse
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
DEFAULT_MEMORY = HERMES_HOME / "MEMORY.md"
HARD_CAP = int(os.getenv("HERMES_MEMORY_CHAR_LIMIT", "2200"))
SOFT_TARGET = int(os.getenv("HERMES_MEMORY_SOFT_TARGET", "500"))
ARCHIVE = HERMES_HOME / "commons" / "data" / "ocas-finch" / "memory_archive.md"
DECISIONS = HERMES_HOME / "commons" / "data" / "ocas-finch" / "decisions.jsonl"
BACKUP_KEEP = 10

DIRECTIVE_RE = re.compile(r"\b(always|never|must not|must|do not|don'?t)\b", re.I)
POINTER_RE = re.compile(r"\bsee\b.*(references?/|\bskill\b|SKILL\.md|\.md\b)", re.I)
LOW_PRIORITY_RE = re.compile(r"\b(nice to know|optionally|might|maybe|sometimes|fyi)\b", re.I)


def is_directive(line):
    return bool(DIRECTIVE_RE.search(line))


def is_pointer(line):
    return bool(POINTER_RE.search(line)) and not is_directive(line)


def acquire_lock(lock_path, ttl=3600):
    """PID-aware lock (stale detection per references/cleanup-and-health.md)."""
    if lock_path.exists():
        try:
            data = json.loads(lock_path.read_text() or "{}")
            pid = data.get("pid")
            age = time.time() - lock_path.stat().st_mtime
            if pid and Path("/proc/%s" % pid).exists() and age < ttl:
                return False  # held by a live process
        except Exception:
            pass
    lock_path.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}))
    return True


def release_lock(lock_path):
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def backup(memory_file):
    bdir = memory_file.parent / ".backups"
    bdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = bdir / ("%s.%s" % (memory_file.name, ts))
    shutil.copy2(memory_file, dest)
    for old in sorted(bdir.glob("%s.*" % memory_file.name))[:-BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


def atomic_write(memory_file, content):
    tmp = memory_file.with_name(memory_file.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, memory_file)


def archive_lines(lines, reason):
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVE, "a", encoding="utf-8") as f:
        f.write("\n--- memory_guard %s %s ---\n" % (reason, datetime.now(timezone.utc).isoformat()))
        for ln in lines:
            f.write(ln + "\n")


def emit_decision(report):
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "decision_id": "dec_%s" % uuid.uuid4().hex[:12],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill_id": "ocas-finch",
        "component": "memory_guard",
        "decision_type": "memory_enforce",
        "description": "MEMORY.md guard %d->%d chars; stripped %d pointer(s); evicted %d line(s)" % (
            report["original_size"], report["final_size"],
            len(report["pointers_stripped"]), len(report["evicted"])),
        "outcome": "applied" if report["applied"] else "dry_run",
        "over_cap_after": report["final_size"] > HARD_CAP,
        "confidence": "high",
    }
    with open(DECISIONS, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _size(lines):
    return len("\n".join(lines))


def enforce(content):
    report = {"original_size": len(content), "pointers_stripped": [], "evicted": [],
              "warnings": [], "actions": [], "applied": False, "final_size": len(content)}
    lines = content.split("\n")

    # 1. strip pointer lines (the documented "grows back" anti-pattern)
    kept = []
    for ln in lines:
        if ln.strip() and is_pointer(ln):
            report["pointers_stripped"].append(ln.strip())
        else:
            kept.append(ln)
    if report["pointers_stripped"]:
        report["actions"].append("stripped %d pointer line(s)" % len(report["pointers_stripped"]))

    # 2. enforce hard cap by evicting lowest-priority NON-directive content lines
    if _size(kept) > HARD_CAP:
        evictable = sorted(
            [i for i, ln in enumerate(kept) if ln.strip() and not is_directive(ln)],
            key=lambda i: (0 if LOW_PRIORITY_RE.search(kept[i]) else 1, -i),
        )
        evicted_idx = set()
        for i in evictable:
            if _size([l for j, l in enumerate(kept) if j not in evicted_idx]) <= HARD_CAP:
                break
            evicted_idx.add(i)
            report["evicted"].append(kept[i].strip())
        kept = [l for j, l in enumerate(kept) if j not in evicted_idx]
        if report["evicted"]:
            report["actions"].append("evicted %d non-directive line(s) to meet cap" % len(report["evicted"]))

    new_content = "\n".join(kept)
    report["final_size"] = len(new_content)

    # 3. integrity: every directive present before must still be present
    orig_dir = {l.strip() for l in content.split("\n") if l.strip() and is_directive(l)}
    new_dir = {l.strip() for l in kept if l.strip() and is_directive(l)}
    if orig_dir - new_dir:
        report["warnings"].append("INTEGRITY: %d directive(s) would be lost - REFUSING" % len(orig_dir - new_dir))
    if report["final_size"] > HARD_CAP:
        report["warnings"].append(
            "STILL OVER CAP after evicting all non-directives (%d>%d); directives alone exceed cap "
            "- needs LLM consolidation / human review" % (report["final_size"], HARD_CAP))
    return new_content, report


def run(memory_file, apply=False, emit=False):
    if not memory_file.exists():
        return {"error": "%s not found" % memory_file}
    content = memory_file.read_text(encoding="utf-8")
    new_content, report = enforce(content)
    report["memory_file"] = str(memory_file)
    report["hard_cap"] = HARD_CAP
    report["soft_target"] = SOFT_TARGET
    report["idempotent_noop"] = (new_content == content and report["final_size"] <= HARD_CAP)
    integrity_ok = not any(w.startswith("INTEGRITY") for w in report["warnings"])

    if apply and new_content != content and integrity_ok:
        lock = memory_file.with_name(memory_file.name + ".lock")
        if not acquire_lock(lock):
            report["error"] = "MEMORY.md locked by a live process - deferring"
            return report
        try:
            backup(memory_file)
            if report["evicted"]:
                archive_lines(report["evicted"], "evicted")
            if report["pointers_stripped"]:
                archive_lines(report["pointers_stripped"], "pointers_stripped")
            atomic_write(memory_file, new_content)
            verify = memory_file.read_text(encoding="utf-8")
            if verify != new_content:
                report["warnings"].append("POST-WRITE mismatch")
            report["applied"] = True
        finally:
            release_lock(lock)
    elif apply and not integrity_ok:
        report["error"] = "refused to apply: directive integrity violation"

    if emit:
        emit_decision(report)
    return report


def main():
    ap = argparse.ArgumentParser(description="memory_guard - deterministic MEMORY.md safety enforcement")
    ap.add_argument("--apply", action="store_true", help="enforce + write (default: dry-run)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--emit-decision", action="store_true")
    ap.add_argument("--file", default=str(DEFAULT_MEMORY))
    args = ap.parse_args()
    report = run(Path(args.file), apply=args.apply, emit=args.emit_decision)
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print("memory_guard:", report.get("memory_file", args.file))
    if "error" in report:
        print("  ERROR:", report["error"])
        return
    print("  size: %d -> %d  (hard_cap %d, soft_target %d)" % (
        report["original_size"], report["final_size"], report["hard_cap"], report["soft_target"]))
    print("  pointers stripped: %d | evicted: %d | idempotent no-op: %s" % (
        len(report["pointers_stripped"]), len(report["evicted"]), report["idempotent_noop"]))
    for a in report["actions"]:
        print("   -", a)
    for w in report["warnings"]:
        print("   ! ", w)
    print("  APPLIED" if report.get("applied") else "  dry-run (use --apply to write)")


if __name__ == "__main__":
    main()
