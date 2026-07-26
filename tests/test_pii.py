#!/usr/bin/env python3
"""Tests for the PII guard that keeps personal data out of this public repo."""
import importlib
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
            "sender@domain.com\n"
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


class GenericisationRuleDocumented(unittest.TestCase):
    """The authoring rule must stay in the workflow doc finch follows."""

    def test_workflow_doc_has_genericise_rule(self):
        doc = (REPO / "references" / "reference-file-workflow.md").read_text(encoding="utf-8")
        self.assertIn("Genericise Before You Write", doc)
        self.assertIn("check_no_pii.py", doc)
        self.assertIn("<counterparty>", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
