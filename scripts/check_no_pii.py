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
  python3 scripts/check_no_pii.py --list-patterns

Exit 0 = clean, 1 = findings, 2 = bad invocation.
"""
from __future__ import annotations

import argparse
import re
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
    r"|^(you|user|someone|operator|counterparty|noreply|no-reply|name|email|sender|contact)@",
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


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        name = p.name
        if any(s in name for s in SKIP_SUFFIX_PARTS):
            continue
        if p.name == DENYLIST_FILE.name:
            continue
        yield p


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
    for f in iter_files(root):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for lineno, kind, hit, hint in scan_text(text, denylist):
            findings += 1
            shown = hit if kind == "denylist" else (
                hit[:4] + "…" + hit[-6:] if len(hit) > 14 else hit)
            rel = f.relative_to(root) if str(f).startswith(str(root)) else f
            print(f"  {rel}:{lineno}: [{kind}] {shown}  -> {hint}")

    if findings:
        print(f"\nFAIL: {findings} potential PII finding(s).")
        print("Genericise before committing — see references/reference-file-workflow.md")
        return 1
    if not args.quiet:
        print("\nOK: no PII patterns detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
