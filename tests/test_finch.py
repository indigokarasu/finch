#!/usr/bin/env python3
"""Regression tests for ocas-finch.

Locks the two data-loss / silent-failure bugs found in the v2.15.3 review:

  1. self_update.py must NEVER discard local work (it used to run
     `git reset --hard` + `git clean -fd` unconditionally).
  2. memory_state.route_entry must target the REAL MEMORY.md and must not
     report OK when it removed nothing (it used to point at a
     non-existent <profile>/MEMORY.md and silently no-op).

Run:  python3 -m unittest discover -s tests -v
"""
import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, text=True,
                          capture_output=True, check=False)


class SelfUpdateSafety(unittest.TestCase):
    """self_update.py must preserve uncommitted work."""

    def test_source_contains_no_destructive_commands(self):
        """No destructive git subcommand may appear as an actual argument list.

        Parse the AST rather than grepping: prose like "what a hard reset would
        eat" is fine, an executed ["git", "reset", "--hard"] is not.
        """
        import ast
        tree = ast.parse((SCRIPTS / "self_update.py").read_text(encoding="utf-8"))
        banned = {("reset",), ("clean",), ("checkout",)}
        found = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple)):
                items = [el.value for el in node.elts
                         if isinstance(el, ast.Constant) and isinstance(el.value, str)]
                if items and items[0] == "git":
                    for sub in banned:
                        if sub[0] in items:
                            found.append(items)
        self.assertEqual(found, [],
                         f"destructive git commands present in code: {found}")

    def test_refuses_to_run_on_dirty_tree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            (repo / "scripts").mkdir(parents=True)
            _git(["init", "-q"], repo)
            _git(["config", "user.email", "t@t"], repo)
            _git(["config", "user.name", "t"], repo)
            (repo / "seed.txt").write_text("seed\n")
            _git(["add", "-A"], repo)
            _git(["commit", "-qm", "init"], repo)

            # copy the real script in and dirty the tree
            (repo / "scripts" / "self_update.py").write_text(
                (SCRIPTS / "self_update.py").read_text(encoding="utf-8"), encoding="utf-8")
            precious = repo / "precious.txt"
            precious.write_text("DO NOT DELETE\n", encoding="utf-8")
            (repo / "seed.txt").write_text("locally modified\n", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(repo / "scripts" / "self_update.py")],
                cwd=repo, text=True, capture_output=True, check=False)

            self.assertEqual(proc.returncode, 2, "dirty tree should exit 2")
            self.assertIn("Refusing to update", proc.stdout + proc.stderr)
            # The whole point: local work survived.
            self.assertTrue(precious.exists(), "untracked file was destroyed!")
            self.assertEqual(precious.read_text(), "DO NOT DELETE\n")
            self.assertEqual((repo / "seed.txt").read_text(), "locally modified\n")

    def test_help_works(self):
        proc = subprocess.run([sys.executable, str(SCRIPTS / "self_update.py"), "--help"],
                              text=True, capture_output=True, check=False)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage", proc.stdout.lower())


class MemoryRouting(unittest.TestCase):
    """route_entry must really move the entry, or fail loudly."""

    def _load(self, mem_path, home):
        os.environ["FINCH_MEMORY_FILE"] = str(mem_path)
        os.environ["HERMES_HOME"] = str(home)
        import memory_state
        return importlib.reload(memory_state)

    def test_resolves_real_memory_file_not_profile_root(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / "memories").mkdir()
            real = home / "memories" / "MEMORY.md"
            real.write_text("- x\n", encoding="utf-8")
            os.environ.pop("FINCH_MEMORY_FILE", None)
            os.environ["HERMES_HOME"] = str(home)
            import memory_state
            m = importlib.reload(memory_state)
            self.assertEqual(m.MEMORY_FILE, real,
                             "must prefer memories/MEMORY.md over profile root")

    def test_route_actually_removes_and_writes(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = home / "MEMORY.md"
            dest = home / "tier2.md"
            entry = "route-me-please"
            mem.write_text(f"- keep a\n- {entry}\n- keep b\n", encoding="utf-8")
            m = self._load(mem, home)

            res = m.route_entry(entry, to_tier=2, dest_path=str(dest))

            self.assertEqual(res["status"], "OK")
            self.assertTrue(res["removed_from_memory"])
            after = mem.read_text(encoding="utf-8")
            self.assertNotIn(entry, after, "entry not removed from source")
            self.assertIn(entry, dest.read_text(encoding="utf-8"))
            self.assertIn("keep a", after)
            self.assertIn("keep b", after)

    def test_missing_source_fails_loudly(self):
        """The core regression: used to return OK while doing nothing."""
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            m = self._load(home / "nope.md", home)
            res = m.route_entry("anything", to_tier=2, dest_path=str(home / "t2.md"))
            self.assertEqual(res["status"], "FAILED")
            self.assertIn("not found", res["error"].lower())

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            mem = home / "MEMORY.md"
            dest = home / "tier2.md"
            entry = "dry-entry"
            mem.write_text(f"- {entry}\n", encoding="utf-8")
            m = self._load(mem, home)
            m.route_entry(entry, to_tier=2, dest_path=str(dest), dry_run=True)
            self.assertIn(entry, mem.read_text(encoding="utf-8"))
            self.assertFalse(dest.exists())


    def test_empty_profile_does_not_double_the_path(self):
        """Regression: an unset HERMES_PROFILE must not resolve to <home>/profiles.

        Path(x) / "profiles" / "" collapses to x/profiles, which can exist as a
        path-doubling artifact; joining it silently produced
        <home>/profiles/memories/MEMORY.md instead of the correct path.  # pii-allow
        """
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / "memories").mkdir()
            (home / "memories" / "MEMORY.md").write_text("- x\n", encoding="utf-8")
            (home / "profiles").mkdir()  # the artifact that triggered it  # pii-allow
            os.environ.pop("FINCH_MEMORY_FILE", None)
            os.environ.pop("HERMES_PROFILE", None)
            os.environ["HERMES_HOME"] = str(home)
            import memory_state
            m = importlib.reload(memory_state)
            self.assertEqual(m.MEMORY_FILE, home / "memories" / "MEMORY.md")
            self.assertNotIn("profiles", str(m.MEMORY_FILE))


class ScriptsExposeHelp(unittest.TestCase):
    """Every script must answer --help without optional deps installed."""

    def test_all_scripts_help(self):
        failures = []
        for script in sorted(SCRIPTS.glob("*.py")):
            proc = subprocess.run([sys.executable, str(script), "--help"],
                                  text=True, capture_output=True, check=False, timeout=60)
            if proc.returncode != 0:
                failures.append(f"{script.name}: rc={proc.returncode} {proc.stderr[:80]}")
        self.assertEqual(failures, [], "scripts failing --help:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main(verbosity=2)
