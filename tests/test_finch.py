#!/usr/bin/env python3
"""Regression tests for ocas-finch.

Locks the data-loss / silent-failure bug found in the v2.15.3 review:

  memory_state.route_entry must target the REAL MEMORY.md and must not
  report OK when it removed nothing (it used to point at a
  non-existent <profile>/MEMORY.md and silently no-op).

Run:  python3 -m unittest discover -s tests -v
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


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
            # The regression is about a 'profiles' component introduced INSIDE
            # the HERMES_HOME resolution. The temp dir the test runs in may
            # itself sit under a profiles/ subtree (TMPDIR), so assert on the
            # path RELATIVE to home, not the absolute string.  # pii-allow
            self.assertNotIn("profiles", m.MEMORY_FILE.relative_to(home).parts)


class FinchHooksPluginTests(unittest.TestCase):
    """Tests for finch_hooks_plugin.py."""

    def test_extracts_realtime_directives(self):
        import finch_hooks_plugin
        text = (
            "Hello agent.\n"
            "Always run unit tests before submitting changes.\n"
            "Never write to MEMORY.md directly.\n"
            "Don't skip verification steps.\n"
        )
        signals = finch_hooks_plugin.extract_realtime_signals(text)
        self.assertEqual(len(signals), 3)
        phrases = [s["phrase"] for s in signals]
        self.assertIn("Always run unit tests before submitting changes.", phrases)
        self.assertIn("Never write to MEMORY.md directly.", phrases)
        self.assertIn("Don't skip verification steps.", phrases)

    def test_blocks_built_in_memory_tool(self):
        import finch_hooks_plugin
        blocked = finch_hooks_plugin.check_memory_tool_call("memory", {"content": "test"})
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["action"], "block")
        self.assertIn("restricted", blocked["message"])

        allowed = finch_hooks_plugin.check_memory_tool_call("terminal", {"command": "ls"})
        self.assertIsNone(allowed)

    def test_registers_hooks_and_system_prompt_section(self):
        import finch_hooks_plugin

        class MockCtx:
            def __init__(self):
                self.hooks = {}
                self.sections = {}

            def register_hook(self, name, handler):
                self.hooks[name] = handler

            def register_system_prompt_section(self, section_id, content_fn, position, max_chars):
                self.sections[section_id] = {
                    "content_fn": content_fn,
                    "position": position,
                    "max_chars": max_chars,
                }

        ctx = MockCtx()
        finch_hooks_plugin.register(ctx)
        self.assertIn("pre_tool_call", ctx.hooks)
        self.assertIn("post_llm_call", ctx.hooks)
        self.assertIn("subagent_start", ctx.hooks)
        self.assertIn("subagent_stop", ctx.hooks)
        self.assertIn("on_session_reset", ctx.hooks)
        self.assertIn("finch.memory-rules", ctx.sections)

        section = ctx.sections["finch.memory-rules"]
        rendered = section["content_fn"]({})
        self.assertIn("Finch Memory & Learning Rules", rendered)

    def test_subagent_failure_buffering_with_file_lock(self):
        import finch_hooks_plugin
        with tempfile.TemporaryDirectory() as td:
            os.environ["HERMES_HOME"] = td
            finch_hooks_plugin.on_subagent_stop(
                parent_session_id="parent_123",
                child_role="worker",
                child_summary="Task failed due to timeout",
                child_status="failed",
                duration_ms=1500,
            )
            failure_file = Path(td) / "commons" / "data" / "ocas-finch" / "subagent_failures.jsonl"
            self.assertTrue(failure_file.exists())
            lines = failure_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            data = json.loads(lines[0])
            self.assertEqual(data["parent_session_id"], "parent_123")
            self.assertEqual(data["child_status"], "failed")


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
