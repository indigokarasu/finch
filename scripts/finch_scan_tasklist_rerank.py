#!/usr/bin/env python3
import os
"""finch_scan_tasklist_rerank.py - safe re-rank + validate for ocas-finch task-list.json.

WHY: finch:scan must NEVER hand-edit task-list.json with parallel `patch` calls
(the parallel-patch / prefix-corruption trap breaks the file). All mutations
(append new tasks + re-rank + validate) happen in ONE python3 process.

USAGE (cron profile where execute_code is BLOCKED - use terminal python3):
  terminal python3 scripts/finch_scan_tasklist_rerank.py
  terminal python3 scripts/finch_scan_tasklist_rerank.py /path/to/task-list.json
  terminal python3 scripts/finch_scan_tasklist_rerank.py --merge new_tasks.json
  terminal python3 scripts/finch_scan_tasklist_rerank.py --dry

--merge appends tasks from a sidecar JSON (a list, or {"tasks":[...]}) whose
ids are not already present, then re-ranks everything.
"""
import importlib.util, json, os, sys, tempfile, argparse, datetime

PRIO = {'P1': 1, 'P2': 2, 'P3': 3, 'P4': 4}
DEFAULT = os.path.expanduser("~/.hermes/commons/data/ocas-finch/task-list.json")

_HERE = os.path.dirname(os.path.abspath(__file__))


def load_clamp():
    """Import finch_ledger_write.clamp by path -- NO silent fallback.

    This writer used to carry no clock logic at all, so a forward stamp planted
    on any row passed straight through it and the re-rank reported OK. Measured
    live 2026-10-01 on a byte copy of the real ledger: a +90min stamp on a
    third-party row survived this writer, and the guard still read 2 forward
    after it returned. The capability was already in the skill --
    finch_ledger_write.clamp reads its field lists from the guard rather than
    restating them, so it cannot drift from the detector -- and this writer was
    simply not calling it.

    Imported by path and raised on, never wrapped in try/except: a silent
    fallback to "no clamping" is the same false-clean the fix exists to remove,
    and it would read identically in the output.
    """
    path = os.path.join(_HERE, "finch_ledger_write.py")
    spec = importlib.util.spec_from_file_location("_finch_ledger_write", path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rank(t):
    return (PRIO.get(t.get('priority'), 9),
            1 if t.get('status') == 'done' else 0,
            t.get('added', ''),
            t.get('id', ''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', nargs='?', default=DEFAULT)
    ap.add_argument('--merge', help='sidecar JSON with new tasks to append')
    ap.add_argument('--dry', action='store_true', help='print plan, do not write')
    args = ap.parse_args()

    d = json.load(open(args.path))
    tasks = d.get('tasks', [])
    before = len(tasks)

    if args.merge:
        side = json.load(open(args.merge))
        new = side if isinstance(side, list) else side.get('tasks', [])
        existing = {t.get('id') for t in tasks}
        added = 0
        for nt in new:
            if nt.get('id') not in existing:
                tasks.append(nt)
                added += 1
        print(f'merged {added} new task(s) from {args.merge}')

    tasks.sort(key=rank)
    d['tasks'] = tasks
    d['updated_at'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Clamp BEFORE the write, and clamp the WHOLE document -- this writer is a
    # full-document rewrite, so it carries every other row's stamps through
    # unchanged. That is how a forward stamp authored by one pass keeps
    # surviving later passes: they all rewrite the file and none of them look
    # at what they are carrying. The guard's receipt channel calls the result
    # LAUNDERED when the same (id, field, value) is still present and was
    # flagged earlier, which is this writer's contribution to the defect.
    #
    # Order is load-bearing and is the reason clamp runs before the sort:
    # re-ranking cannot move a stamp, but writing first and clamping after
    # would be a second write. One write, one clamp.
    changes = load_clamp().clamp(d)

    if args.dry:
        print(f'DRY: {before} -> {len(tasks)} tasks; would write {args.path}')
        if changes:
            print(f'DRY: would clamp {len(changes)} forward stamp(s):')
            for c in changes:
                print('DRY:   %-6s %-44s %-20s %s -> %s'
                      % (c['scope'], c['id'], c['field'], c['from'], c['to']))
        return

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(args.path)))
    try:
        # mkstemp creates 0600 and os.replace keeps the TEMP file's mode, so a
        # writer that skips this silently narrows the ledger's permissions on
        # every pass. Measured 2026-10-01: this writer turned a 0644 ledger
        # into 0600. finch_ledger_write.write_atomic carries the same fchmod
        # and is the reference for it.
        os.fchmod(fd, os.stat(args.path).st_mode & 0o7777)
        with os.fdopen(fd, 'w') as f:
            json.dump(d, f, indent=1, sort_keys=True)
            f.write('\n')
        os.replace(tmp, args.path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    # Confirm on a FRESH read from disk. json.load() below is that read, but it
    # proves parseability only -- a write that carried a forward stamp through
    # would parse perfectly happily, which is exactly the failure this pass
    # measured. Re-measure with the guard's OWN check() so the verdict is a
    # fact about the bytes on disk and not about the object in memory.
    json.load(open(args.path))  # validate-after-write
    print(f'OK: {before} -> {len(tasks)} tasks written + validated at {args.path}')
    if changes:
        print(f'clamped: {len(changes)} forward stamp(s) carried on rows this '
              f'writer did not author:')
        for c in changes:
            print('   %-6s %-44s %-20s %s -> %s'
                  % (c['scope'], c['id'], c['field'], c['from'], c['to']))
    else:
        print('clamped: 0 (every stamp is at or before now)')

    rep = guard_check(args.path)
    if not rep["ledger_found"]:
        print('VERDICT: NOT MEASURED -- the guard could not read back %s (%s);'
              ' a write whose confirmation could not be measured is not a'
              ' clean write' % (args.path, rep.get("ledger_error")))
        return 2
    header_fwd = sum(1 for h in rep["header"] if h["forward"])
    print('re-read: mtime %s, sha %s, header %d checked / %d forward, '
          'task stamps %d forward, %d laundered'
          % (rep.get("mtime_utc"), (rep.get("sha256") or "")[:8],
             len(rep["header"]), header_fwd,
             rep.get("forward_count", 0), rep.get("laundered_count", 0)))
    if rep.get("forward_count") or rep.get("laundered_count"):
        print('VERDICT: NOT CLEAN -- a writer other than this function is'
              ' writing the ledger, or a carried stamp could not be clamped.'
              ' The write landed, so this needs a human, not a retry.')
        return 3
    print('VERDICT: WRITTEN CLEAN -- 0 forward, 0 laundered')
    return 0


def guard_check(path):
    """The guard's OWN check(), loaded by path so the two cannot drift.

    Raised on, never silently degraded to a no-op: this is the confirmation
    half of the writer's contract, and a fallback that quietly skips it would
    report success on an unverified write -- the same false-clean in a new
    place.
    """
    path_g = os.path.join(_HERE, "finch_ledger_guard.py")
    spec = importlib.util.spec_from_file_location("_finch_ledger_guard", path_g)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % path_g)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.check(path, None)


if __name__ == '__main__':
    sys.exit(main() or 0)
