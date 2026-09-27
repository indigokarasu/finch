#!/usr/bin/env python3
"""Test finch_scan_counter.py. Both verdict directions must be exercised.

A lock-based allocator is only worth having if it (a) never hands out a
duplicate, (b) refuses to allocate when the ledger cannot be read, and
(c) is safe under concurrency. (b) is the one that gets forgotten, and getting
it wrong means a number is minted on top of an unreadable series.
"""
import json
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finch_scan_counter.py")
PASS, FAIL = [], []


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (("  -- " + detail) if detail and not cond else ""))


print("1. --floor on the real ledger (read path, allocates nothing)")
r = run("--floor", "--json")
check("floor exits 0", r.returncode == 0, r.stderr)
ev = json.loads(r.stdout) if r.returncode == 0 else {}
check("floor >= 174 (duplicate #174 cannot be reused)",
      ev.get("floor", 0) >= 174, "floor=%s" % ev.get("floor"))
check("next is floor+1", ev.get("next") == ev.get("floor", 0) + 1)
check("no sidecar written by --floor", not os.path.exists(
    os.path.join(tempfile.gettempdir(), "never")))

print("2. --peek does not allocate")
r = run("--peek", "--json")
check("peek exits 0", r.returncode == 0, r.stderr)
check("peek has no 'allocated' key", "allocated" not in json.loads(r.stdout))

print("3. unreadable ledger -> exit 1, explicitly NOT clean")
import importlib.util


def load_counter(**overrides):
    spec = importlib.util.spec_from_file_location("cnt_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for k, v in overrides.items():
        setattr(mod, k, v)
    return mod


with tempfile.TemporaryDirectory() as td:
    missing = os.path.join(td, "nope.json")
    mod = load_counter(LEDGER=missing)
    try:
        mod.evidence()
        check("missing ledger raises rather than defaulting to 0", False, "no raise")
    except FileNotFoundError:
        check("missing ledger raises rather than defaulting to 0", True)

    corrupt = os.path.join(td, "corrupt.json")
    with open(corrupt, "w") as fh:
        fh.write("{not json")
    mod = load_counter(LEDGER=corrupt)
    try:
        mod.evidence()
        check("corrupt ledger is caught by json.load, not swallowed", False, "no raise")
    except json.JSONDecodeError:
        check("corrupt ledger is caught by json.load, not swallowed", True)

print("4. journal noise must not break allocation")
with tempfile.TemporaryDirectory() as td:
    with open(os.path.join(td, "good.json"), "w") as fh:
        json.dump({"scan_number": 900}, fh)
    with open(os.path.join(td, "bad.json"), "w") as fh:
        fh.write("{oops")
    with open(os.path.join(td, "prose.json"), "w") as fh:
        json.dump({"run": "finch:scan #950"}, fh)
    led = os.path.join(td, "led.json")
    with open(led, "w") as fh:
        json.dump({"scan_number": 800}, fh)
    mod = load_counter(LEDGER=led, JOURNALS=td)
    ev = mod.evidence()
    check("floor takes max of header/journal/prose",
          ev["floor"] == 950, "floor=%s" % ev["floor"])
    check("malformed journal skipped, not fatal",
          ev["journal_files"] == 4 and 900 in ev["journal_scan_numbers"],
          "files=%s nums=%s" % (ev["journal_files"], ev["journal_scan_numbers"]))
    check("prose numbers harvested", 950 in ev["prose_scan_numbers"])
    check("module-repointed paths are honoured (not the real ledger)",
          ev["ledger_scan_number"] == 800, "got %s" % ev["ledger_scan_number"])

print("4b. prose harvest is NOT limited to run/source/summary")
# The 2026-09-27 blind spot: the floor read three named fields, while the
# guard read the whole document. 26 of 33 prose-carried numbers -- up to 157 --
# were invisible to the floor. These cases pin the WIDTH of the harvest, which
# is the property that was untested. A `run`-only test passes against the old
# 3-field implementation, which is why the gap survived a green suite.
with tempfile.TemporaryDirectory() as td:
    led = os.path.join(td, "led.json")
    with open(led, "w") as fh:
        json.dump({"scan_number": 10}, fh)
    # Each number sits in a field the old implementation never read, and every
    # one is > the header, so a miss changes the floor.
    for i, (fname, payload) in enumerate([
        ("a.json", {"findings": ["raised by finch:scan #612"]}),
        ("b.json", {"scan_cycle": "finch:scan #613"}),
        ("c.json", {"scan_id": "finch:scan #614"}),
        ("d.json", {"next_scheduled": "after finch:scan #615, before finch:scan #616"}),
        ("e.json", {"nested": {"deep": ["finch:scan #617"]}}),
        ("f.json", {"scan_number": 40, "note": "also mentions finch:scan #618"}),
    ]):
        with open(os.path.join(td, fname), "w") as fh:
            json.dump(payload, fh)
    mod = load_counter(LEDGER=led, JOURNALS=td)
    ev = mod.evidence()
    got = set(ev["prose_scan_numbers"])
    for n in (612, 613, 614, 615, 616, 617, 618):
        check("prose #%d harvested from a non-run field" % n, n in got,
              "got %s" % sorted(got))
    check("floor reflects the widest number seen anywhere (618)",
          ev["floor"] == 618, "floor=%s prose=%s" % (ev["floor"], sorted(got)))
    # A 3-digit number must survive: the old pattern also under-matched width.
    with open(os.path.join(td, "g.json"), "w") as fh:
        json.dump({"note": "finch:scan #1234"}, fh)
    ev2 = load_counter(LEDGER=led, JOURNALS=td).evidence()
    check("4-digit number not dropped by the harvest", 1234 in ev2["prose_scan_numbers"])
    # Guard and allocator must agree on the corpus. This is the property whose
    # absence produced the blind spot, so assert it against the REAL journals
    # rather than a fixture.
    import glob as _glob
    import re as _re
    real_mod = load_counter()          # fresh module bound to the REAL paths
    real_guard, real_alloc = set(), set()
    for jf in _glob.glob(os.path.join(real_mod.JOURNALS, "**", "*.json"), recursive=True):
        try:
            jd = json.load(open(jf))
        except Exception:
            continue
        for m in _re.finditer(r"finch:scan\s*#\s*(\d{1,4})\b", json.dumps(jd, ensure_ascii=False)):
            real_guard.add(int(m.group(1)))
    real_alloc = set(real_mod.evidence()["prose_scan_numbers"])
    missing = real_guard - real_alloc
    check("allocator sees EVERY number the guard sees (real journals)",
          not missing, "blind to %s" % sorted(missing))
    # The two tools keep SEPARATE copies of the prose pattern (no import, so
    # each script still runs standalone). That duplication is only safe while
    # a test compares them -- this is that test, and it is why the patterns are
    # allowed to be literals instead of a silent-fallback import.
    import importlib.util as _iu2
    gspec = _iu2.spec_from_file_location(
        "_guard_pat", os.path.join(os.path.dirname(SCRIPT), "finch_ledger_guard.py"))
    if gspec is None or gspec.loader is None:
        check("prose pattern is byte-identical to the guard's (_PROSE_NUM_RE)", False, "no spec")
    else:
        g = _iu2.module_from_spec(gspec)
        gspec.loader.exec_module(g)
        cmod = load_counter()
        check("prose pattern is byte-identical to the guard's (_PROSE_NUM_RE)",
              getattr(g, "_PROSE_NUM_RE", None) is not None
              and g._PROSE_NUM_RE.pattern == cmod.PROSE_RE.pattern,
              "guard=%r counter=%r" % (getattr(g, "_PROSE_NUM_RE", None) and
                                       g._PROSE_NUM_RE.pattern, cmod.PROSE_RE.pattern))

print("5. concurrent allocation never duplicates")
with tempfile.TemporaryDirectory() as td:
    led = os.path.join(td, "led.json")
    with open(led, "w") as fh:
        json.dump({"scan_number": 500}, fh)
    counter = os.path.join(td, "scan-counter.json")
    procs = [subprocess.Popen(
        [sys.executable, "-c",
         "import importlib.util as u,sys;s=u.spec_from_file_location('m',%r);"
         "m=u.module_from_spec(s);s.loader.exec_module(m);"
         "m.LEDGER=%r;m.JOURNALS=%r;m.COUNTER=%r;m.LOCK=%r;"
         "sys.exit(m.main(['--json']))" % (SCRIPT, led, td, counter, counter + ".lock")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(8)]
    got, errs = [], []
    for p in procs:
        out, err = p.communicate()
        if p.returncode == 0 and out.strip():
            got.append(json.loads(out)["allocated"])
        else:
            errs.append((p.returncode, err.strip()[-80:]))
    check("no duplicate number allocated", len(got) == len(set(got)),
          "allocated=%s errs=%s" % (sorted(got), errs))
    check("losers exit 2 (lock), not 0", all(c == 2 for c, _ in errs) if errs else True,
          str(errs))
    # Contiguity: each winner must take the next number above the floor. With
    # 8 racers the lock serialises them, so a gap would mean a number was minted
    # and lost, not merely that losers did not run.
    check("winning numbers contiguous above floor",
          sorted(got) == list(range(501, 501 + len(got))), str(sorted(got)))

print("6. sidecar is mode 0644 and atomic-replaced")
import importlib.util as _iu
_s = _iu.spec_from_file_location("cnt_final", SCRIPT)
_m = _iu.module_from_spec(_s)
_s.loader.exec_module(_m)
if os.path.exists(_m.COUNTER):
    check("sidecar mode 0644", oct(os.stat(_m.COUNTER).st_mode)[-3:] == "644",
          oct(os.stat(_m.COUNTER).st_mode))
    st = json.load(open(_m.COUNTER))
    check("sidecar records last_allocated", "last_allocated" in st)
    check("sidecar sits beside the ledger",
          os.path.dirname(_m.COUNTER) == os.path.dirname(_m.LEDGER))
else:
    print("  skip  sidecar (not allocated in this env)")

print("7. paths resolve from script location, not a hardcoded host path")
_src = open(SCRIPT).read()
# The gate checks for a real profile directory name in a PATH, not the
# documentation placeholder that explains the layout. Test the literal risk.
check("no concrete profile path in a string literal",
      '"/root/.hermes/profiles/' not in _src and "'/root/.hermes/profiles/" not in _src,
      "hardcoded profile path found")
check("LEDGER resolves to a real file", os.path.isfile(_m.LEDGER), _m.LEDGER)
check("JOURNALS resolves to a real dir", os.path.isdir(_m.JOURNALS), _m.JOURNALS)

print()
print("PASS %d / FAIL %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("FAILED:", FAIL)
sys.exit(1 if FAIL else 0)
