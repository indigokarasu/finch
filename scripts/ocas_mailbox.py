#!/usr/bin/env python3
"""Resolve the operator's mailbox account WITHOUT requiring an env var.

WHY THIS EXISTS
---------------
Every direct-API watcher in this skill resolves its credential file by
BUILDING THE FILENAME FROM AN EMAIL ADDRESS*:

    CRED_DIR / ("%s.json" % acct)

so `acct` must be known before the token file can even be located. They took
it from ``OCAS_OPERATOR_EMAIL``. That variable is declared in SKILL.md's
config block with an EMPTY default, and it lives in the profile ``.env`` --
but the cron worker does not export it. Measured 2026-09-27 (finch:work #225):
the ``finch:work`` job carries ``env={}``, and a bare
``hoorii_verify_watch.py`` died with EXIT 2 / "FATAL: pass --acct <email>".
So the named authority for a task was UNRUNNABLE from the very worker whose
job is to run it.

THE FAILURE DIRECTION IS THE DANGEROUS ONE
------------------------------------------
EXIT 2 is loud, which is good -- but the caller that skips a script it cannot
configure and moves on to the next task has no way to tell "the watcher said
nothing" from "the watcher never ran". That is a false negative in the safe
direction, the same class the NOT-MEASURED guards exist to prevent.

THE FIX, AND WHY IT IS NOT A HARDCODE
-------------------------------------
The credential directory ALREADY carries the answer, as a symlink:

    operator_email.json -> <operator-address>.json

The code never used it: it derived the account from the symlink's own name
rather than from the symlink's TARGET. So the resolution is to follow the
link and read the account off the realpath. Nothing here names an address --
it is discovered at runtime, so it stays correct across profiles and adds no
PII to the repo (``check_no_pii.py`` must keep passing).

PRECEDENCE, narrowest-to-broadest:
  1. ``OCAS_OPERATOR_EMAIL`` if set        (explicit always wins)
  2. ``$OCAS_GOOGLE_CRED_DIR/operator_email.json`` realpath basename
  3. any single non-agent ``*.json`` token in the cred dir (last resort)

Returns "" when it cannot resolve -- callers keep their own EXISTING
not-configured exit code. This module never raises on a missing directory,
because a watcher that crashes on import is worse than one that exits 2 with
a message.
"""
import os
from pathlib import Path

# The agent's own mailbox is a symlink INTO this directory, so it must never
# be auto-selected as "the operator" -- picking it would silently point a
# watcher at the wrong human's mail, which is a far worse failure than
# exiting 2. Matched structurally on the local part, never on a literal
# address. The "mx." prefix is what actually catches this profile's agent
# mailbox; "agent" catches the generic convention.
_AGENT_LOCAL_PARTS = ("mx.", "agent")
_NON_ACCOUNT_TOKENS = ("oauth_states", "operator_email")


def _cred_dir() -> Path:
    return Path(os.path.expanduser(
        os.environ.get("OCAS_GOOGLE_CRED_DIR", "~/.google_workspace_mcp/credentials")))


def _account_from_credfile(p: Path) -> str:
    """Account name = the token file's basename with .json stripped."""
    return p.name[:-len(".json")] if p.name.endswith(".json") else ""


def _is_agent(acct: str) -> bool:
    low = acct.lower()
    return any(low.startswith(p) or f".{p}." in low or low == p
               for p in _AGENT_LOCAL_PARTS)


def resolve_account() -> str:
    """Best-effort operator account. Empty string means UNRESOLVED."""
    env = (os.environ.get("OCAS_OPERATOR_EMAIL") or "").strip()
    if env:
        return env

    d = _cred_dir()

    # (2) the symlink the credential dir already maintains
    link = d / "operator_email.json"
    try:
        if link.is_symlink():
            real = Path(os.path.realpath(link))
            # realpath() does NOT follow a DANGLING link -- it returns the link
            # itself, so _account_from_credfile() would yield the literal
            # string "operator_email" and the caller would then build
            # CRED_DIR/"operator_email.json" and read... the symlink again,
            # i.e. resolve to nothing while reporting SUCCESS. is_file() is
            # False for a broken symlink, so this rejects it. Deliberately do
            # NOT also compare parent directories: the real target normally
            # lives in this very directory, so that test rejects valid input.
            if not real.is_file():
                return ""
            acct = _account_from_credfile(real)
            if acct and not _is_agent(acct):
                return acct
    except OSError:
        pass

    # (3) last resort: exactly one non-agent token file
    try:
        cands = [_account_from_credfile(p) for p in d.glob("*.json")]
        cands = [c for c in cands
                 if c and not _is_agent(c)
                 and not any(c.startswith(n) or c == n for n in _NON_ACCOUNT_TOKENS)
                 and not (d / (c + ".json")).is_symlink()]
        if len(cands) == 1:
            return cands[0]
    except OSError:
        pass
    return ""


if __name__ == "__main__":
    acct = resolve_account()
    print(acct or "UNRESOLVED (set $OCAS_OPERATOR_EMAIL)")
