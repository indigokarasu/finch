#!/usr/bin/env python3
import os
"""finch_scan_tasklist_rerank.py - safe re-rank + validate for ocas-finch task-list.json.

WHY: finch:scan must NEVER hand-edit task-list.json with parallel `patch` calls
(the parallel-patch / prefix-corruption trap breaks the file). All mutations
(append new tasks + re-rank + validate) happen in ONE python3 process.

USAGE (indigo cron profile - execute_code is BLOCKED, use terminal python3):
  terminal python3 scripts/finch_scan_tasklist_rerank.py
  terminal python3 scripts/finch_scan_tasklist_rerank.py /path/to/task-list.json
  terminal python3 scripts/finch_scan_tasklist_rerank.py --merge new_tasks.json
  terminal python3 scripts/finch_scan_tasklist_rerank.py --dry

--merge appends tasks from a sidecar JSON (a list, or {"tasks":[...]}) whose
ids are not already present, then re-ranks everything.
"""
import json, sys, os, tempfile, argparse, datetime

PRIO = {'P1': 1, 'P2': 2, 'P3': 3, 'P4': 4}
DEFAULT = os.path.expanduser("~/.hermes/commons/data/ocas-finch/task-list.json")


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

    if args.dry:
        print(f'DRY: {before} -> {len(tasks)} tasks; would write {args.path}')
        return

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(args.path)))
    with os.fdopen(fd, 'w') as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, args.path)
    json.load(open(args.path))  # validate-after-write
    print(f'OK: {before} -> {len(tasks)} tasks written + validated at {args.path}')


if __name__ == '__main__':
    main()
