#!/usr/bin/env python3
"""
finch_write_verify.py -- prove that an `applied` claim names artefacts that exist.

WHY THIS EXISTS
---------------
Measured 2026-10-03: the 2026-09-30 daily journaled two skill edits under
`applied` -- a rewrite of `ocas-finch/SKILL.md` § Storage & behavioral
directives, and a new dated trap in `references/scanning-traps.md`. Neither was
on disk. Both `write_file` calls had returned success.

The journal already carried the rule ("after any write, re-read and grep a
unique substring per intended block") and the 09-30 pass skipped it on the very
pass that should have applied it. A rule written in prose is not a control
surface: `finch_journal_write.py` gave the JOURNAL a clamp choke point for the
same reason -- detection lost. This is the choke point for the WRITE side.

THE CONTRACT
------------
An `applied` entry is a list of claims about files. Each claim must be checkable
against the filesystem, so every claim needs:

    {"path": "...", "expect_any": ["substring", ...], "expect_gone": ["..."]}

  expect_any   -- at least one substring must be present in the file
  expect_gone  -- NONE of these substrings may be present (use for the text a
                  claim says it replaced; this is what catches a no-op write
                  that "succeeded")

A claim with no `expect_any` is only an existence check -- legal, but it proves
nothing about content, and the output says so.

EXIT CODES
----------
  0  every claim verified
  1  at least one claim FAILED (missing file, absent substring, lingering text)
  2  the claim document itself is malformed -- NOT MEASURED, never a pass

That third outcome is deliberate and load-bearing: this skill's ledger is full
of checks whose only path is a zero, and a checker that cannot distinguish "all
good" from "never ran" reports clean in both cases.

    python3 finch_write_verify.py --claims claims.json
    python3 finch_write_verify.py --doc journal.json      # read journal['applied']
    python3 finch_write_verify.py --doc journal.json --key applied
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _norm(s):
    """Collapse whitespace so a claim can quote a sentence that a markdown
    formatter reflowed. Without this a correct write reads as a failure."""
    return ' '.join(str(s).split())


def _extract(obj, key):
    """Pull the claim list out of whatever shape the caller handed us."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        # A dict of claims keyed by filename.
        out = []
        for k, v in obj.items():
            if isinstance(v, str):
                out.append({'path': k, 'expect_any': [v]})
            elif isinstance(v, dict):
                c = dict(v)
                c.setdefault('path', k)
                out.append(c)
        return out
    return None


def verify_one(claim):
    """Return (ok, detail) for a single claim."""
    if not isinstance(claim, dict) or 'path' in claim and not isinstance(claim.get('path'), str):
        return False, 'claim is not an object with a string `path`'

    path = claim['path']
    if not os.path.isabs(path):
        # Default to the skill root so claims can be written relative to it.
        path = os.path.join(ROOT, path)

    if not os.path.isfile(path):
        return False, f'FILE MISSING: {path}'

    try:
        with open(path, 'r', errors='replace') as fh:
            body = _norm(fh.read())
    except OSError as e:
        return False, f'UNREADABLE: {e}'

    expect_gone = claim.get('expect_gone') or []
    lingering = [s for s in expect_gone if _norm(s) in body]
    if lingering:
        return False, (f'TEXT THE CLAIM SAID IT REPLACED IS STILL PRESENT: '
                      f'{lingering[0][:80]!r}')

    expect_any = claim.get('expect_any') or []
    if not expect_any:
        return True, 'exists (no content asserted -- proves presence only)'

    if not any(_norm(s) in body for s in expect_any):
        return False, ('NONE of the expected substrings present; the write may '
                       f'have succeeded but written nothing. tried: '
                       f'{[s[:60] for s in expect_any]}')

    return True, 'verified'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--claims', help='JSON file holding a claim list')
    ap.add_argument('--doc', help='journal JSON; read the claim list from it')
    ap.add_argument('--key', default='applied', help='key inside --doc (default applied)')
    ap.add_argument('--json', action='store_true', help='machine-readable result')
    a = ap.parse_args()

    if bool(a.claims) == bool(a.doc):
        print('REFUSED: give exactly one of --claims / --doc', file=sys.stderr)
        return 2

    src = a.claims or a.doc
    if not os.path.isfile(src):
        print(f'REFUSED: claim document not found: {src}', file=sys.stderr)
        return 2

    try:
        with open(src) as fh:
            obj = json.load(fh)
    except json.JSONDecodeError as e:
        print(f'REFUSED: claim document is not valid JSON ({e})', file=sys.stderr)
        return 2

    claims = _extract(obj, a.key)
    if claims is None:
        print(f'REFUSED: no claim list found at key {a.key!r}', file=sys.stderr)
        return 2
    if not isinstance(claims, list):
        print(f'REFUSED: claims at {a.key!r} is not a list', file=sys.stderr)
        return 2
    if not claims:
        print('NOT MEASURED: claim list is empty -- that is a pass with no checks')
        return 2

    results = []
    for c in claims:
        ok, detail = verify_one(c)
        results.append({'claim': c, 'ok': ok, 'detail': detail})

    failed = [r for r in results if not r['ok']]

    if a.json:
        print(json.dumps({
            'checked': len(results),
            'failed': len(failed),
            'verdict': 'VERIFIED' if not failed else 'FAILED',
            'results': [{'path': r['claim'].get('path'), 'ok': r['ok'],
                         'detail': r['detail']} for r in results],
        }, indent=2))
    else:
        for r in results:
            mark = 'PASS' if r['ok'] else 'FAIL'
            print(f'[{mark}] {r["claim"].get("path")} -- {r["detail"]}')
        print(f'\nVERDICT: {"VERIFIED" if not failed else "FAILED"} -- '
              f'{len(results) - len(failed)}/{len(results)} claims verified')

    if failed:
        print('\nDO NOT journal these as `applied`. A write that returns success '
              'is not a write that landed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())