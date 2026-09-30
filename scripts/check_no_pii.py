#!/usr/bin/env python3
"""check_no_pii.py — block personally-identifying data from entering the repo.

ocas-finch writes reference files distilled from REAL operational runs. Without
a guard, live values leak straight into a public repo — which is exactly how a
counterparty's work email, their name, an employer, and real Gmail thread ids
ended up published.

Two layers:

  1. STRUCTURAL patterns (built in, always on, safe to commit): real-looking
     email addresses, Gmail/message thread ids, phone numbers, API keys and
     bearer tokens, and absolute home paths that expose a username.

  2. NAMED ENTITIES (local only): people, employers, project code names. These
     cannot live in a committed denylist — the denylist would republish the very
     strings it protects. Put them one-per-line in `.pii-denylist` at the repo
     root, which .gitignore excludes. CI runs layer 1; your machine runs both.

USAGE:
  python3 scripts/check_no_pii.py                # scan repo, exit 1 on findings
  python3 scripts/check_no_pii.py --path references/
  python3 scripts/check_no_pii.py --path references/one.md   # single file
  python3 scripts/check_no_pii.py --list-patterns

Exit 0 = clean (and at least one file was actually read), 1 = findings,
2 = bad invocation, 3 = NOT MEASURED (0 files scanned -- bad path, or
everything under it was skipped). Never read exit 0 as a pass unless a
file count was printed alongside it.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SKIP_DIRS = {".git", "archive", ".archive", "__pycache__", "node_modules", ".venv"}
SKIP_SUFFIX_PARTS = (".bak", ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".svg")
DENYLIST_FILE = REPO / ".pii-denylist"

#: Put this on a line to exempt it (deliberate bad-examples, test fixtures).
ALLOW_MARKER = "pii-allow"

#: The author/org identity is meant to be published (LICENSE, repo URL);
#: a denylist term inside one of these is not a leak.
DENY_ALLOW = re.compile(r"Indigo Karasu|indigokarasu", re.IGNORECASE)

# Domains/addresses that are documentation placeholders, not real people.
ALLOWED_EMAIL = re.compile(
    r"@(example\.(com|org|net)|domain\.com|test\.invalid|localhost)$"
    r"|^(you|user|someone|operator|counterparty|noreply|no-reply|name|email|sender|contact)@"
    # Service no-reply senders are not people: noreply-accounts@google.com is a
    # Google account-data notice, not a counterparty. Match the role prefix
    # rather than the bare word so no-reply-anything@ is covered too.
    r"|^(?:no[-_.]?reply|donotreply|mailer-daemon|postmaster|notifications?|alerts?)"
    r"[-_.][A-Za-z0-9._-]*@",
    re.IGNORECASE,
)

# Strings that look like secrets but are placeholders.
PLACEHOLDER = re.compile(
    r"<[a-z0-9._-]+>|\{\{.*?\}\}|\$\{?[A-Z_][A-Z0-9_]*\}?|xxx+|\.\.\.|"
    r"your[-_]?|placeholder|redacted|example|dummy|sample",
    re.IGNORECASE,
)

PATTERNS = [
    ("email",
     re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
     "real-looking email address — use counterparty@example.com"),
    ("thread_id",
     re.compile(r"\b[0-9a-f]{16}\b"),
     "Gmail/message thread id — use <thread-id>"),
    ("phone",
     re.compile(r"(?<!\d)(?:\+?1[-. ])?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?!\d)"),
     "phone number — use <phone>"),
    # Real key shapes only: a prefix + separator + a high-entropy blob.
    # (A bare "sk" prefix matched ordinary words like skill-update-directive.)
    ("api_key",
     re.compile(r"\b(?:sk|pk)-[A-Za-z0-9]{20,}\b"
                r"|\bgh[pousr]_[A-Za-z0-9]{30,}\b"
                r"|\bxox[baprs]-[A-Za-z0-9-]{12,}\b"
                r"|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
     "API key / token — move to an env var"),
    ("bearer",
     re.compile(r"\bbearer\s+[A-Za-z0-9._\-]{20,}\b", re.IGNORECASE),
     "bearer token — move to an env var"),
    ("home_path",
     re.compile(r"/(?:home|Users)/(?!user\b|you\b|username\b|<)[A-Za-z0-9_-][A-Za-z0-9._-]*/"),
     "absolute home path exposing a username — use ~ or <fs-root>"),
    # Host identity: this repo is public, so a concrete profile name or an
    # absolute root path is a leak AND useless to anyone else's machine.
    ("host_path",
     re.compile(r"/root/(?!\s)"),  # pii-allow
     "absolute host path — use ~/ or <fs-root>/"),
    ("profile_name",
     re.compile(r"profiles/(?!<)[a-z0-9_-]+/"),
     "concrete profile name — use profiles/<profile>/"),
]


def load_denylist() -> list[str]:
    if not DENYLIST_FILE.exists():
        return []
    terms = []
    for line in DENYLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def tracked_files(root: Path) -> set[str] | None:
    """Repo-relative paths git would actually publish, or None if not a repo.

    The scan answers "is the PUBLIC REPO clean", so the file set that matters
    is the one a clone receives -- not every file on this disk. A host-only
    watcher in a gitignored path cannot leak by being present locally, and
    counting it makes the real leak invisible behind noise it can never fix.
    """
    if not (root / ".git").exists() and not (root.parent / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root,
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return {p for p in out.stdout.split("\0") if p}


def ignored_paths(root: Path, rels: list[str]) -> set[str]:
    """Repo-relative paths the ignore list excludes, in ONE git call.

    This is the other half of "would a clone of this repo leak?", and it is
    the half `tracked_files` cannot answer. `git ls-files` reports the index --
    what is published RIGHT NOW. The daily auto-sync runs `git add -A`, so an
    untracked-but-unignored file is published at the next sync: it is exactly
    the class `git add -A` exists to pick up.

    FAIL-SAFE BY CONSTRUCTION: every error path returns the EMPTY set, which
    marks nothing as ignored and therefore classifies every finding as
    shipping. An unreadable ignore list must cost strictness, never a green.
    (exit 1 = "none are ignored" and is a valid answer, not a failure.)
    """
    if not rels:
        return set()
    try:
        out = subprocess.run(["git", "check-ignore", "--stdin", "-z"], cwd=root,
                             input="\0".join(rels) + "\0",
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode not in (0, 1):
        return set()
    return {p for p in out.stdout.split("\0") if p}


def tracked_but_ignored(tracked: set[str], root: Path) -> list[str]:
    """Tracked files that a .gitignore pattern claims to exclude.

    .gitignore governs only untracked files. A pattern added after a file was
    committed never applies to it, so the ignore list can look exhaustive and
    correct while the file it was written for is still shipping. That is not a
    hypothetical here: `scripts/*_watch.py` had covered the host-only watchers
    since 2026-09-26, and one committed on 2026-09-27 kept publishing another
    profile's name because the pattern could not reach it. An ignore rule a
    tracked file has already escaped is decoration, so the gate reports the
    contradiction instead of trusting the list.
    """
    if not tracked:
        return []
    try:
        proc = subprocess.run(["git", "check-ignore", "--stdin"], cwd=root,
                              input="\n".join(sorted(tracked)) + "\n",
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted(p for p in proc.stdout.split("\n") if p.strip())


def iter_files(root: Path):
    # Optimize traversal: use os.walk to prune skipped directories (e.g., node_modules, .git, .venv)
    # before recursing into them, and use tuple str.endswith for suffix filtering.
    #
    # A FILE root must yield that file. os.walk() on a non-directory path
    # yields NOTHING at all, so passing `--path some/file.py` scanned zero
    # files and reported "OK: no PII patterns detected" -- a safe-direction
    # false negative on a file that held 35 real findings. Every
    # single-file measurement this repo documents (SKILL.md's own guidance to
    # "measure a single file with --path <file>") was silently vacuous until
    # this was fixed. An empty scan must never be able to read as a pass, so
    # the file case is handled explicitly and a zero-file scan is an error.
    if root.is_file():
        if root.name.endswith(SKIP_SUFFIX_PARTS) or root.name == DENYLIST_FILE.name:
            return
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name.endswith(SKIP_SUFFIX_PARTS):
                continue
            if name == DENYLIST_FILE.name:
                continue
            yield Path(dirpath) / name


def scan_text(text: str, denylist: list[str]):
    """Yield (lineno, kind, match, hint)."""
    for i, line in enumerate(text.splitlines(), 1):
        # Inline escape hatch for deliberate examples (docs showing what NOT to
        # write, test fixtures). Visible in review, unlike a silent deletion.
        if ALLOW_MARKER in line:
            continue
        for kind, rx, hint in PATTERNS:
            for m in rx.finditer(line):
                hit = m.group(0)
                if kind == "email" and ALLOWED_EMAIL.search(hit):
                    continue
                if PLACEHOLDER.search(hit):
                    continue
                yield i, kind, hit, hint
        low = line.lower()
        for term in denylist:
            if term.lower() in low:
                # skip when the hit is only part of the author/org identity
                stripped = DENY_ALLOW.sub("", line).lower()
                if term.lower() not in stripped:
                    continue
                yield i, "denylist", term, "named entity from .pii-denylist"


def main() -> int:
    ap = argparse.ArgumentParser(description="Fail if PII would be committed.")
    ap.add_argument("--path", default=None, help="limit scan to this path")
    ap.add_argument("--list-patterns", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="only print findings")
    args = ap.parse_args()

    if args.list_patterns:
        for kind, rx, hint in PATTERNS:
            print(f"  {kind:10s} {hint}\n             {rx.pattern}")
        return 0

    root = Path(args.path).resolve() if args.path else REPO
    if not root.exists():
        print(f"No such path: {root}", file=sys.stderr)
        return 2

    denylist = load_denylist()
    if not args.quiet:
        print(f"Scanning {root}")
        print(f"  structural patterns: {len(PATTERNS)}")
        print(f"  local denylist terms: {len(denylist)}"
              + ("" if denylist else f"  (create {DENYLIST_FILE.name} to add names)"))

    findings = 0
    scanned = 0
    # Shippable vs host-local. The question this gate exists to answer is
    # "would a clone of this repo leak?", so a finding in a gitignored
    # host-only file is not this gate's business -- and burying the real leak
    # under 85 findings that cannot ship is how 54 real ones stayed invisible
    # long enough to be counted as "pre-existing". Both numbers are printed:
    # the second is context, never a substitute for the first.
    #
    # "SHIPPING" MUST BE DECIDED BY THE IGNORE LIST, NOT BY INDEX MEMBERSHIP.
    # Testing "is this in the index" is a claim about the PAST -- it answers
    # "was it committed", not "will it be". The daily auto-sync runs
    # `git add -A`, so an untracked-but-unignored file -- precisely what a new
    # file written moments ago is -- is classified non-shipping, then published
    # on the next sync. Measured 2026-09-30 on this tree: 5 untracked,
    # unignored files were each tagged "(gitignored, does not ship)", a tag
    # that is doubly false (not ignored, and shipping) while the scan still
    # exits 0. A gate that reports the reason it skipped a finding must not
    # be able to state a reason it never checked.
    #
    # The one thing that IS checked is the ignore list. Anything not excluded
    # by it is shipping, whether or not git currently knows about the file.
    tracked = tracked_files(REPO)
    ship = 0
    local = 0
    pending_rels: list[str] = []
    pending_files: list[Path] = []
    pending_hits: list[list] = []
    for f in iter_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        scanned += 1
        try:
            rel_repo = f.resolve().relative_to(REPO).as_posix()
        except ValueError:
            # A --path scan of a temp tree (the pre-commit hook's staged
            # snapshot) lives OUTSIDE REPO, so relative_to raises for EVERY
            # file. That is not "this file is host-local": it is "I cannot
            # place this file in the repo at all". Classifying it as
            # not-shipping made the pre-commit hook structurally incapable of
            # firing, and CI -- which runs the same gate but only AFTER the
            # push -- was the sole thing standing between a staged leak and a
            # PUBLIC repo. A file whose location is unknown is the one case
            # that must be treated as shipping.
            ships = True
            rel_repo = str(f)
        else:
            # In-repo: queue the ignore-list decision for the single batched
            # git call below rather than asking git per file.
            pending_rels.append(rel_repo)
            pending_files.append(f)
            ships = None  # decided in bulk below
        hits = list(scan_text(text, denylist))
        if ships is None:
            pending_hits.append(hits)
            continue
        for lineno, kind, hit, hint in hits:
            findings += 1
            if ships:
                ship += 1
            else:
                local += 1
            shown = hit if kind == "denylist" else (
                hit[:4] + "…" + hit[-6:] if len(hit) > 14 else hit)
            rel = f.relative_to(root) if str(f).startswith(str(root)) else f
            tag = "" if ships else "  (gitignored, does not ship)"
            print(f"  {rel}:{lineno}: [{kind}] {shown}  -> {hint}{tag}")

    # One batched `git check-ignore` for every in-repo file, then render. This
    # replaces N subprocess calls with one, and -- more to the point -- it is
    # the only place the shipping verdict is decided, so there is exactly one
    # classification code path to test.
    if pending_rels:
        ignored = ignored_paths(REPO, pending_rels)
        for f, hits in zip(pending_files, pending_hits):
            ships = f.resolve().relative_to(REPO).as_posix() not in ignored
            for lineno, kind, hit, hint in hits:
                findings += 1
                if ships:
                    ship += 1
                else:
                    local += 1
                shown = hit if kind == "denylist" else (
                    hit[:4] + "…" + hit[-6:] if len(hit) > 14 else hit)
                rel = f.relative_to(root) if str(f).startswith(str(root)) else f
                tag = "" if ships else "  (gitignored, does not ship)"
                print(f"  {rel}:{lineno}: [{kind}] {shown}  -> {hint}{tag}")

    # A scan that examined zero files is NOT a clean scan. Reporting OK here
    # would make "I pointed the gate at the wrong path" and "the repo is clean"
    # the same output -- the same conflation that let the file-root bug above
    # hide 35 findings behind a green result. Distinct exit code so a caller
    # can never mistake an empty measurement for a pass.
    if scanned == 0:
        print(f"\nNOT MEASURED: 0 files scanned under {root} "
              f"(bad path, or everything here was skipped).", file=sys.stderr)
        return 3

    # The .gitignore/index contradiction is a finding in its own right: a file
    # the ignore list claims to exclude is still in the commit, so the list is
    # not the safety net it appears to be.
    escapes = tracked_but_ignored(tracked, REPO) if tracked else []
    if escapes:
        print(f"\nFAIL: {len(escapes)} tracked file(s) are matched by .gitignore but "
              f"still committed — the ignore rule cannot reach them:")
        for p in escapes:
            print(f"  {p}   -> git rm --cached '{p}'")

    if ship:
        print(f"\nFAIL: {ship} PII finding(s) that WOULD SHIP "
              f"({local} more in gitignored host-only files), "
              f"across {scanned} scanned file(s).")
        print("Genericise before committing — see references/reference-file-workflow.md")
        return 1
    if escapes:
        return 1
    if local and not args.quiet:
        print(f"\nOK: no PII in any file that ships ({scanned} scanned; "
              f"{local} finding(s) confined to gitignored host-only files).")
    elif not args.quiet:
        print(f"\nOK: no PII patterns detected in {scanned} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
