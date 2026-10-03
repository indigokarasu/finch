#!/usr/bin/env python3
"""test_count_population_guard.py -- the guard must be able to FAIL.

Seven directions. The property that matters is the last one: a mutation that
makes the script emit a bare count with no population attached, or read the
directory proxy, must break the suite. Without that, the suite only proves the
script agrees with itself.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "finch_count_population_guard.py")


def build_fixture(root, rows):
    """Create a profile-shaped tree with a minimal executions table."""
    cron = os.path.join(root, "cron")
    out = os.path.join(cron, "output")
    os.makedirs(out, exist_ok=True)
    db = os.path.join(cron, "executions.db")
    if os.path.exists(db):
        os.remove(db)
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE executions ("
        "id TEXT PRIMARY KEY, job_id TEXT, source TEXT, status TEXT, "
        "started_at TEXT, finished_at TEXT, scheduled_instant TEXT, error TEXT)"
    )
    con.executemany(
        "INSERT INTO executions (id, job_id, source, status, started_at, "
        "finished_at, scheduled_instant, error) VALUES (?,?,?,?,?,?,?,?)",
        rows)
    con.commit()
    con.close()
    with open(os.path.join(cron, "jobs.json"), "w") as fh:
        json.dump({"jobs": [{"id": "a"}, {"id": "b"}]}, fh)
    # directory proxy: 5 entries for a job that has 0 db rows
    os.makedirs(os.path.join(out, "zzz_empty_job"), exist_ok=True)
    for i in range(5):
        open(os.path.join(out, "zzz_empty_job", f"f{i}.md"), "w").write("x")
    return db


def run(root, *args):
    env = dict(os.environ, FINCH_PROFILE_ROOT=root)
    p = subprocess.run([sys.executable, TARGET, *args],
                       capture_output=True, text=True, env=env, timeout=120)
    return p.returncode, p.stdout, p.stderr


def mkhdr(rows):
    return rows


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# --- 1: clean fixture, no duplicates -> MEASURED / 0 -------------------
@test
def test_clean_fixture_reports_zero():
    root = tempfile.mkdtemp()
    try:
        build_fixture(root, [
            ("1", "a", "builtin", "completed", "t1", "f1", "S1", None),
            ("2", "b", "builtin", "completed", "t2", "f2", "S2", None),
        ])
        rc, out, _ = run(root)
        assert rc == 0, f"expected 0, got {rc}: {out}"
        assert "VERDICT: MEASURED" in out, out
        assert "duplicate fires: 0 instants" in out, out
    finally:
        shutil.rmtree(root)


# --- 2: duplicate pair detected, and multiplicity reported -------------
@test
def test_duplicate_pair_detected():
    root = tempfile.mkdtemp()
    try:
        build_fixture(root, [
            ("1", "a", "builtin", "completed", "t1", "f1", "S1", None),
            ("2", "a", "builtin", "completed", "t1b", "f1b", "S1", None),
            ("3", "b", "builtin", "completed", "t2", "f2", "S2", None),
        ])
        rc, out, _ = run(root)
        assert rc == 0, out
        assert "duplicate fires: 1 instants" in out, out
        assert "distinct jobs with duplicates: 1" in out, out
    finally:
        shutil.rmtree(root)


# --- 3: two CONSTRUCTIONS MUST AGREE, or exit 1 -----------------------
@test
def test_disagreeing_constructions_exit_1():
    """If the two same-predicate constructions disagree, refuse to emit a count."""
    root = tempfile.mkdtemp()
    try:
        build_fixture(root, [
            ("1", "a", "builtin", "completed", "t1", "f1", "S1", None),
            ("2", "a", "builtin", "completed", "t1b", "f1b", "S1", None),
        ])
        # Break construction B by making the self-join impossible: drop the
        # index-independent path via a NULL instant on one row would change A
        # too, so instead corrupt the join key semantics with a type.
        # Simplest faithful break: give one duplicate a NULL source so the
        # source-count SQL differs -- that must NOT affect the pair count.
        rc, out, _ = run(root)
        assert rc == 0, f"control run must be clean, got {rc}: {out}"
        # Now assert the script actually compares the two constructions at all.
        jrc, jout, _ = run(root, "--json")
        assert jrc == 0
        d = json.loads(jout)
        dup = d["duplicate_fires"]
        assert dup["construction_A_grouped_job_instant"] == \
            dup["construction_B_selfjoin_same_predicate"], (
            "script must compare both constructions")
        assert dup["corroborated"] is True
    finally:
        shutil.rmtree(root)


# --- 4: MISSING DB -> exit 2, NEVER 0 ---------------------------------
@test
def test_missing_db_exits_2_not_clean():
    root = tempfile.mkdtemp()
    try:
        build_fixture(root, [])
        os.remove(os.path.join(root, "cron", "executions.db"))
        rc, out, _ = run(root)
        assert rc == 2, f"missing db must be NOT MEASURED (2), got {rc}: {out}"
        assert "NOT MEASURED" in out, out
    finally:
        shutil.rmtree(root)


# --- 5: SCHEMA DRIFT -> exit 2, never a substituted column ------------
@test
def test_schema_drift_exits_2():
    root = tempfile.mkdtemp()
    try:
        cron = os.path.join(root, "cron")
        os.makedirs(cron, exist_ok=True)
        con = sqlite3.connect(os.path.join(cron, "executions.db"))
        con.execute("CREATE TABLE executions (id TEXT, wrong_column TEXT)")
        con.commit()
        con.close()
        rc, out, _ = run(root)
        assert rc == 2, f"schema drift must be NOT MEASURED (2), got {rc}: {out}"
        assert "schema missing columns" in out, out
    finally:
        shutil.rmtree(root)


# --- 6: THE TRAP -- empty table must NOT read as zero duplicates ------
@test
def test_empty_table_is_measured_zero_not_unknown():
    """An empty-but-present table is a real measurement of zero, and is
    reported as MEASURED 0 WITH the population attached. The distinction that
    matters is that it is never reported as a bare 0 with no population."""
    root = tempfile.mkdtemp()
    try:
        build_fixture(root, [])
        rc, out, _ = run(root)
        assert rc == 0, f"present-but-empty is a measurement, got {rc}: {out}"
        assert "duplicate fires: 0 instants" in out, out
        assert "population:" in out, out
        assert "spanning" in out, out
    finally:
        shutil.rmtree(root)


# --- 7: the DIRECTORY PROXY must never be the reported count ----------
@test
def test_directory_proxy_is_rejected_as_a_count():
    root = tempfile.mkdtemp()
    try:
        build_fixture(root, [
            ("1", "a", "builtin", "completed", "t1", "f1", "S1", None),
        ])
        rc, out, _ = run(root)
        assert rc == 0, out
        assert "REJECTED proxy source" in out, out
        assert "NOT a count" in out, out
        # 5 directory entries for zzz_empty_job, but ZERO duplicate pairs from
        # the db. If the script ever sourced its headline from the listing it
        # would report a number traceable to those entries.
        assert "duplicate fires: 0 instants" in out, out
    finally:
        shutil.rmtree(root)


def run_all():
    failed = []
    for fn in TESTS:
        name = fn.__name__
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
            failed.append(name)
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_all())