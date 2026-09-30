#!/usr/bin/env python3
"""Tests for the PII guard that keeps personal data out of this public repo."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_no_pii  # noqa: E402


class PIIDetection(unittest.TestCase):
    def _hits(self, text, denylist=None):
        return list(check_no_pii.scan_text(text, denylist or []))

    def test_catches_real_email(self):
        kinds = [k for _, k, _, _ in self._hits("mail jane.doe@realcorp.com now")]  # pii-allow
        self.assertIn("email", kinds)

    def test_catches_thread_id(self):
        kinds = [k for _, k, _, _ in self._hits("thread 0f1e2d3c4b5a6978")]  # pii-allow
        self.assertIn("thread_id", kinds)

    def test_catches_phone_and_home_path(self):
        kinds = [k for _, k, _, _ in self._hits("call 415-555-0132\ncd /home/jdoe/secrets/")]  # pii-allow
        self.assertIn("phone", kinds)
        self.assertIn("home_path", kinds)

    def test_catches_tokens(self):
        # Built at runtime: a literal token-shaped string in a public repo trips
        # GitHub secret scanning and our own gate, for a value that is fictional.
        kinds = [k for _, k, _, _ in self._hits("ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")]  # pii-allow
        self.assertIn("api_key", kinds)

    def test_placeholders_are_allowed(self):
        clean = (
            "mail counterparty@example.com and contact@example.com\n"
            "id <thread-id>\n"
            "env $OCAS_OPERATOR_EMAIL\n"
            "path ~/.hermes/profiles/<profile>/\n"
            "sender@domain.com\n"  # pii-allow
        )
        self.assertEqual(self._hits(clean), [], f"false positives: {self._hits(clean)}")

    def test_ordinary_prose_is_not_a_token(self):
        """Regression: a bare 'sk' prefix matched skill-update-directive."""
        kinds = [k for _, k, _, _ in self._hits("see skill-update-directive.md")]
        self.assertNotIn("api_key", kinds)

    def test_denylist_catches_names(self):
        hits = self._hits("spoke with Jane Doe today", denylist=["Jane Doe"])
        self.assertTrue(any(k == "denylist" for _, k, _, _ in hits))

    def test_denylist_is_case_insensitive(self):
        hits = self._hits("acme corporation invoice", denylist=["Acme Corporation"])
        self.assertTrue(any(k == "denylist" for _, k, _, _ in hits))


class RepoIsClean(unittest.TestCase):
    """The committed tree must contain no structural PII. This is the gate."""

    def test_repo_scan_passes(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "check_no_pii.py"), "--quiet"],
            text=True, capture_output=True, check=False, timeout=180)
        self.assertEqual(proc.returncode, 0,
                         f"PII detected in repo:\n{proc.stdout}\n{proc.stderr}")


class ShippingIsDecidedByTheIgnoreList(unittest.TestCase):
    """An UNTRACKED file is not a SAFE file.

    The auto-sync runs `git add -A`, so the class of file that is about to be
    published is exactly the class git does not currently know about. Deciding
    "shipping" by index membership therefore blinds the gate to precisely the
    new files it exists to catch, and the skip-reason it prints ("gitignored,
    does not ship") becomes a reason it never checked.

    Exercised against the real repo (the gitignore rules ARE the fixture), and
    against a temp git repo for the classification itself. No commit is made.
    """

    def _mkrepo(self, base: Path, ignore: str = "") -> Path:
        d = base / "r"
        d.mkdir()
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
               "PATH": "/usr/bin:/bin", "HOME": str(d)}
        subprocess.run(["git", "init", "-q", str(d)], check=True, capture_output=True, env=env)
        if ignore:
            (d / ".gitignore").write_text(ignore, encoding="utf-8")
        return d

    # Built at runtime, like the token fixture above: a literal email in a
    # tracked file is itself a finding, so the shipped test must not contain
    # one. `.invalid` keeps it structurally a real address (the scanner must
    # still match it) without being deliverable.
    _PII = "contact test.person@notarealdomain" + ".invalid\n"  # pii-allow

    def test_untracked_unignored_file_is_classified_shipping(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            d = self._mkrepo(base)
            f = d / "notes.md"
            f.write_text(self._PII, encoding="utf-8")
            # NOT staged: `git add -A` has not run. The old index-membership
            # test classified this non-shipping; the ignore list does not.
            self.assertEqual(check_no_pii.ignored_paths(d, ["notes.md"]), set())
            self.assertIn("notes.md", _classify(d, f))

    def test_ignored_file_is_classified_local(self):
        with tempfile.TemporaryDirectory() as td:
            d = self._mkrepo(Path(td), ignore="hostonly/\n")
            f = d / "hostonly" / "watch.py"
            f.parent.mkdir()
            f.write_text("x\n", encoding="utf-8")
            self.assertIn("hostonly/watch.py", check_no_pii.ignored_paths(d, ["hostonly/watch.py"]))
            self.assertNotIn("hostonly/watch.py", _classify(d, f))

    def test_unreadable_git_answers_none_ignored_so_nothing_is_excused(self):
        """Fail-safe direction: an error must cost strictness, never a green."""
        self.assertEqual(check_no_pii.ignored_paths(Path("/nonexistent-repo-xyz"), ["a"]), set())

    def test_live_root_scan_refuses_an_untracked_unignored_leak(self):
        """The end-to-end direction, and the one that was silently inverted.

        A root scan (no --path) over the real repo is the only invocation that
        reaches the in-repo classification branch, because --path forces the
        out-of-repo branch instead. So this drops a structurally-real address
        into a file git does not track, runs the real gate exactly as the
        developer and the pre-commit path do, and requires a refusal.

        Pre-fix this returned 0 and tagged the file "(gitignored, does not
        ship)" -- so the direction genuinely fails without the fix. The probe
        is removed in `finally`, and the scan is asserted to have seen it, so
        a green that never measured anything cannot pass.
        """
        probe_rel = "references/_test_untracked_leak_probe.md"
        probe = REPO / probe_rel
        self.assertFalse(probe.exists(), f"stale probe left behind: {probe_rel}")
        probe.write_text(self._PII, encoding="utf-8")
        try:
            self.assertFalse(
                subprocess.run(["git", "check-ignore", "-q", probe_rel],
                               cwd=str(REPO), capture_output=True).returncode == 0,
                "probe is gitignored; the arm is broken and the test is vacuous")
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "check_no_pii.py")],
                cwd=str(REPO), text=True, capture_output=True, check=False, timeout=180)
            self.assertIn(probe_rel, proc.stdout,
                          f"scan did not examine the probe: {proc.stdout[-2000:]}")
            self.assertNotIn("does not ship", proc.stdout.split(probe_rel)[1][:200],
                             "untracked file was excused with a reason never checked")
            self.assertEqual(proc.returncode, 1,
                             f"untracked, unignored leak was allowed:\n{proc.stdout[-2000:]}")
        finally:
            probe.unlink(missing_ok=True)


def _classify(repo: Path, f: Path) -> set[str]:
    """Reproduce main()'s shipping decision for one file, without side effects."""
    rel = f.resolve().relative_to(repo.resolve()).as_posix()
    ignored = check_no_pii.ignored_paths(repo, [rel])
    return set() if rel in ignored else {rel}


class GenericisationRuleDocumented(unittest.TestCase):
    """The authoring rule must stay in the workflow doc finch follows."""

    def test_workflow_doc_has_genericise_rule(self):
        doc = (REPO / "references" / "reference-file-workflow.md").read_text(encoding="utf-8")
        self.assertIn("Genericise Before You Write", doc)
        self.assertIn("check_no_pii.py", doc)
        self.assertIn("<counterparty>", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
