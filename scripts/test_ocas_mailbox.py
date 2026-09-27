#!/usr/bin/env python3
"""Tests for ocas_mailbox.resolve_account().

Fixtures build REAL temp directories with REAL symlinks -- the resolution
reads os.path.realpath, so a mock would prove nothing about the branch it is
meant to exercise. A symlink that is never created, or created pointing at a
missing file, is the case that must NOT resolve; those are the false-safe
directions worth pinning.

Run: python3 test_ocas_mailbox.py     EXIT 0 = all pass
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocas_mailbox as om  # noqa: E402

PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print("  ok   %-52s %r" % (name, got))
    else:
        FAIL += 1
        print("  FAIL %-52s got %r want %r" % (name, got, want))


def with_cred_dir(fn):
    d = Path(tempfile.mkdtemp())
    try:
        return fn(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def clear_env():
    os.environ.pop("OCAS_OPERATOR_EMAIL", None)
    os.environ.pop("OCAS_GOOGLE_CRED_DIR", None)


print("test_ocas_mailbox")


def t_env_wins():
    clear_env()
    os.environ["OCAS_OPERATOR_EMAIL"] = "explicit@example.com"
    check("env var wins outright", om.resolve_account(), "explicit@example.com")
    clear_env()


def t_symlink():
    def body(d):
        clear_env()
        os.environ["OCAS_GOOGLE_CRED_DIR"] = str(d)
        real = d / "real.person@example.com.json"
        real.write_text("{}")
        (d / "operator_email.json").symlink_to(real)
        check("operator_email.json symlink -> realpath basename",
              om.resolve_account(), "real.person@example.com")
    with_cred_dir(body)


def t_dangling_symlink_falls_through():
    def body(d):
        clear_env()
        os.environ["OCAS_GOOGLE_CRED_DIR"] = str(d)
        (d / "operator_email.json").symlink_to(d / "gone@example.com.json")
        check("dangling symlink resolves to UNRESOLVED (no false pick)",
              om.resolve_account(), "")
    with_cred_dir(body)


def t_regular_file_named_operator_email():
    """A REAL (non-link) file named operator_email.json must NOT resolve.

    The name is an ALIAS, not an account address. Returning it would make the
    caller build CRED_DIR/"operator_email.json.json" and fail, or -- worse --
    read the alias file as if it were a token. Refusing is the honest answer.
    """
    def body(d):
        clear_env()
        os.environ["OCAS_GOOGLE_CRED_DIR"] = str(d)
        (d / "operator_email.json").write_text("{}")
        check("plain alias file is not mistaken for an account",
              om.resolve_account(), "")
    with_cred_dir(body)


def t_never_picks_agent():
    """The agent's own mailbox is a symlink INTO the dir; it must be skipped."""
    def body(d):
        clear_env()
        os.environ["OCAS_GOOGLE_CRED_DIR"] = str(d)
        agent = d / "mx.agent.mailbox@example.com.json"
        agent.write_text("{}")
        (d / "operator_email.json").symlink_to(agent)
        check("refuses an agent mailbox even if operator_email points at it",
              om.resolve_account(), "")
    with_cred_dir(body)


def t_lone_token_last_resort():
    def body(d):
        clear_env()
        os.environ["OCAS_GOOGLE_CRED_DIR"] = str(d)
        (d / "solo.person@example.com.json").write_text("{}")
        (d / "oauth_states.json").write_text("{}")
        check("lone non-agent token is the last resort",
              om.resolve_account(), "solo.person@example.com")
    with_cred_dir(body)


def t_ambiguous_refuses():
    def body(d):
        clear_env()
        os.environ["OCAS_GOOGLE_CRED_DIR"] = str(d)
        (d / "a@example.com.json").write_text("{}")
        (d / "b@example.com.json").write_text("{}")
        check("two candidates -> UNRESOLVED, not a coin flip", om.resolve_account(), "")
    with_cred_dir(body)


def t_missing_dir_no_crash():
    clear_env()
    os.environ["OCAS_GOOGLE_CRED_DIR"] = "/nonexistent/creds/nowhere"
    check("missing cred dir returns UNRESOLVED, does not raise",
          om.resolve_account(), "")
    clear_env()


def t_env_cred_dir_end_to_end():
    def body(d):
        clear_env()
        real = d / "someone@example.com.json"
        real.write_text("{}")
        (d / "operator_email.json").symlink_to(real)
        os.environ["OCAS_OPERATOR_EMAIL"] = "someone@example.com"
        check("env var and cred dir agree", om.resolve_account(), "someone@example.com")
        clear_env()
    with_cred_dir(body)


for t in (t_env_wins, t_symlink, t_dangling_symlink_falls_through,
          t_regular_file_named_operator_email, t_never_picks_agent,
          t_lone_token_last_resort, t_ambiguous_refuses, t_missing_dir_no_crash,
          t_env_cred_dir_end_to_end):
    t()

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
