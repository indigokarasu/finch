#!/usr/bin/env python3
"""Single-shot writer: append one work_log entry + update signal/notes on a task.

One process, read-modify-write, atomic replace, then json.load() to confirm.
Parallel patches on task-list.json interleave and corrupt it, and a read_file
after the fact is not validation -- so the whole update and its confirmation
happen in this single process, under an exclusive lock.
"""
import fcntl
import json
import os
import sys
import tempfile

TASKLIST = "/root/.hermes/commons/data/ocas-finch/task-list.json"
LOCK = TASKLIST + ".lock"


def main():
    payload_path = sys.argv[1]
    with open(payload_path) as fh:
        payload = json.load(fh)

    task_id = payload["id"]
    with open(LOCK, "a") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        with open(TASKLIST) as fh:
            data = json.load(fh)

        tasks = data["tasks"] if isinstance(data, dict) and "tasks" in data else data
        matches = [t for t in tasks if t.get("id") == task_id]
        if len(matches) != 1:
            raise SystemExit(f"ABORT: {len(matches)} tasks match id={task_id!r}, expected exactly 1")

        t = matches[0]
        before_status = t.get("status")
        before_log = len(t.get("work_log") or [])

        t["signal"] = payload["signal"]
        t["notes"] = payload["notes"]
        t["work_log"] = [payload["work_log"]] + (t.get("work_log") or [])
        t["last_finch_review"] = payload["last_finch_review"]
        t["updated_at"] = payload["updated_at"]
        for k, v in payload.get("set", {}).items():
            t[k] = v

        out = json.dumps(data, indent=1, sort_keys=True) + "\n"
        json.loads(out)  # refuse to write a file we cannot read back
        d = os.path.dirname(TASKLIST)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(out)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, TASKLIST)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # Confirmation is a fresh read of the file on disk, not the in-memory copy.
    with open(TASKLIST) as fh:
        final = json.load(fh)
    ftasks = final["tasks"] if isinstance(final, dict) and "tasks" in final else final
    hit = [t for t in ftasks if t.get("id") == task_id]
    assert len(hit) == 1, f"post-write read found {len(hit)} matches"
    ft = hit[0]
    checks = {
        "json.loads ok": True,
        "work_log +1": len(ft.get("work_log") or []) == before_log + 1,
        "signal updated": ft.get("signal") == payload["signal"],
        "updated_at": ft.get("updated_at") == payload["updated_at"],
        "not a literal @file": not str(ft.get("signal", "")).startswith("@"),
        "entry is new first": (ft.get("work_log") or [None])[0] == payload["work_log"],
    }
    bad = [k for k, v in checks.items() if not v]
    print(f"WROTE {TASKLIST}")
    print(f"  id={task_id} status {before_status} -> {ft.get('status')} (unchanged)"
          if before_status == ft.get("status") else f"  id={task_id} status {before_status} -> {ft.get('status')}")
    print(f"  work_log {before_log} -> {len(ft.get('work_log') or [])}")
    print(f"  bytes={os.path.getsize(TASKLIST)}  total_tasks={len(ftasks)}")
    for k in checks:
        print(("  ok   " if checks[k] else "  FAIL ") + k)
    if bad:
        print("POST-WRITE VERIFICATION FAILED: " + ", ".join(bad))
        sys.exit(1)
    print("VERIFIED CLEAN")


if __name__ == "__main__":
    main()
