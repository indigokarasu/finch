"""rmtree_confined.py — the one sanctioned fixture-deletion helper.

A test that deletes real data is a worse defect than a test that fails, so every
removal in a finch suite goes through this module rather than a bare
``shutil.rmtree``.

WHY REGISTER-AT-CREATION, NOT "LIVES UNDER /tmp"
-----------------------------------------------
Two suites here deliberately build their fixture tree OUTSIDE /tmp (a
profile-scoped scratch dir, a synthetic $HOME) so that path resolution is
exercised against the real host layout rather than a convenient one. A
/tmp-only allowlist would therefore refuse the suites' own directories, turning
passing tests red for a reason that has nothing to do with the world. The
invariant is "THIS PROCESS created it", which rejects the dangerous shape (a
path assembled from an env var, a glob, or a fixture string) without
constraining where the suite may work.

This module exists because the helper was duplicated across two suites and a
third needed it: three copies of a safety check are three things to keep in
agreement, and the copy that drifts is the copy that deletes something. It was
extracted on 2026-10-03 while closing the unguarded-``rmtree`` D8 finding on
ocas-finch, which the rubric scores as a -2 correctness penalty.

USAGE
  import rmtree_confined as rc
  d = rc.mkfixture(prefix="my_suite_")      # tempfile.mkdtemp, registered
  try:
      ...
  finally:
      rc.rmtree(d)                          # refuses anything unregistered

  # Already have a path from mkdtemp()/TemporaryDirectory? Register it:
  d = rc.new_root(tempfile.mkdtemp())
  rc.rmtree(d)

EXIT / BEHAVIOUR
  Raises RuntimeError when asked to delete a path this process never created.
  That is a test bug, and failing loudly is the intended outcome -- silently
  skipping the delete would leave the next run inheriting a stale tree and
  report a green suite over a contaminated fixture.
"""
from __future__ import annotations

import os
import shutil
import tempfile

# Every directory this process created and may therefore delete.
_CREATED = set()


def new_root(path):
    """Register an existing path as deletable, and return it unchanged.

    Use this when the directory came from somewhere other than mkfixture() --
    tempfile.mkdtemp(), a NamedTemporaryFile parent, or a suite that builds its
    own tree -- so the deletion still goes through the structural check.
    """
    real = os.path.realpath(path)
    _CREATED.add(real)
    return path


def _register(path):
    _CREATED.add(os.path.realpath(path))
    return path


def mkfixture(*args, **kwargs):
    """tempfile.mkdtemp that remembers what it made."""
    return _register(tempfile.mkdtemp(*args, **kwargs))


def rmtree_confined(path, *, allow_missing=True):
    """Delete `path` only if this process created it. Refuse otherwise.

    A registered root OR anything beneath it counts: fixtures legitimately
    build sub-trees (a launder/ dir inside a ledger temp dir), and deleting one
    of those individually is still deleting only what this suite made.
    """
    real = os.path.realpath(path)
    if not any(real == r or real.startswith(r + os.sep) for r in _CREATED):
        raise RuntimeError(
            "refusing to delete %s: not created by this suite. A test fixture "
            "must never name a path it did not make -- that shape is how a "
            "suite deletes live state." % real)
    if real in _CREATED:
        _CREATED.discard(real)
    if not os.path.exists(real):
        if allow_missing:
            return
        raise FileNotFoundError(real)
    shutil.rmtree(real, ignore_errors=True)
