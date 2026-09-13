#!/usr/bin/env python3
"""Hermes Agent Hooks Plugin for Finch.

This module provides Hermes hook handlers that enable real-time learning signal
capture, memory tool interception, subagent delegation tracking, and cache-safe
system prompt section registration for Finch.

Can be loaded as a Hermes plugin via register(ctx) or executed via CLI.
"""

import argparse
import fcntl
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("finch.hooks")

# Regex patterns for detecting explicit behavioral corrections and learning signals
DIRECTIVE_PATTERNS = [
    re.compile(r"\b(always|never)\s+(?:do|use|run|check|write|call|patch|edit|skip|delete|remove|clear|modify)\b", re.IGNORECASE),
    re.compile(r"\b(?:don't|do not|stop|avoid)\s+(?:do|use|run|check|write|call|patch|edit|skip|delete|remove|clear|modify)\b", re.IGNORECASE),
    re.compile(r"\b(?:you should have|you ought to|next time|from now on)\b", re.IGNORECASE),
]


def _get_finch_buffer_dir() -> Path:
    base = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    buffer_dir = base / "commons" / "data" / "ocas-finch"
    buffer_dir.mkdir(parents=True, exist_ok=True)
    return buffer_dir


def _append_jsonl_with_lock(filepath: Path, record: dict) -> None:
    """Atomically append a record to a JSONL file using fcntl advisory locking."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(record) + "\n")
            f.flush()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def extract_realtime_signals(user_message: str) -> list[dict]:
    """Extract potential learning signals from user input in real-time.

    Returns a list of extracted signal dicts.
    """
    if not user_message or not isinstance(user_message, str):
        return []

    signals = []
    lines = user_message.splitlines()
    for line in lines:
        clean = line.strip()
        if not clean:
            continue

        for pattern in DIRECTIVE_PATTERNS:
            if pattern.search(clean):
                signals.append({
                    "type": "correction_directive",
                    "phrase": clean[:300],
                    "pattern": pattern.pattern,
                })
                break

    return signals


def check_memory_tool_call(tool_name: str, args: dict) -> dict | None:
    """Intercept built-in 'memory' tool calls and redirect to Finch memory guard.

    Returns directive dict with action 'block' if tool_name is 'memory', else None.
    """
    if tool_name == "memory":
        return {
            "action": "block",
            "message": (
                "Direct edits via built-in 'memory' tool are restricted in Finch profiles. "
                "Finch maintains MEMORY.md deterministically via scripts/memory_guard.py. "
                "Use 'finch.compact' or run 'python3 scripts/memory_guard.py --file ...' instead."
            ),
        }
    return None


def on_pre_tool_call(tool_name: str, args: dict, task_id: str = "", **kwargs) -> dict | None:
    """Hermes pre_tool_call hook handler."""
    return check_memory_tool_call(tool_name, args)


def on_post_llm_call(
    session_id: str,
    user_message: str,
    assistant_response: str,
    model: str = "",
    platform: str = "",
    **kwargs,
) -> None:
    """Hermes post_llm_call hook handler.

    Scans user messages for immediate behavioral directives / corrections.
    """
    signals = extract_realtime_signals(user_message)
    if not signals:
        return

    logger.info("Finch hook captured %d real-time learning signal(s) in session %s", len(signals), session_id)
    buffer_file = _get_finch_buffer_dir() / "realtime_signals.jsonl"

    try:
        for sig in signals:
            entry = {
                "session_id": session_id,
                "model": model,
                "platform": platform,
                "signal": sig,
            }
            _append_jsonl_with_lock(buffer_file, entry)
    except Exception as e:
        logger.warning("Failed to write real-time signal buffer: %s", e)


def on_subagent_start(
    parent_session_id: str | None = None,
    parent_turn_id: str = "",
    child_session_id: str | None = None,
    child_subagent_id: str = "",
    child_role: str = "",
    child_goal: str = "",
    **kwargs,
) -> None:
    """Hermes subagent_start hook handler.

    Observes subagent instantiation and records context for subagent lifecycle tracking.
    """
    logger.info(
        "Subagent delegation started: parent=%s child_session=%s role=%s subagent_id=%s",
        parent_session_id,
        child_session_id,
        child_role,
        child_subagent_id,
    )


def on_subagent_stop(
    parent_session_id: str = "",
    child_role: str | None = None,
    child_summary: str | None = None,
    child_status: str = "completed",
    duration_ms: int = 0,
    **kwargs,
) -> None:
    """Hermes subagent_stop hook handler.

    Tracks subagent delegation execution and persists non-completed executions for mining.
    """
    if child_status != "completed":
        logger.warning(
            "Subagent delegation non-completion: parent=%s role=%s status=%s duration=%dms",
            parent_session_id,
            child_role,
            child_status,
            duration_ms,
        )
        buffer_file = _get_finch_buffer_dir() / "subagent_failures.jsonl"
        record = {
            "parent_session_id": parent_session_id,
            "child_role": child_role,
            "child_status": child_status,
            "child_summary": (child_summary or "")[:500],
            "duration_ms": duration_ms,
        }
        try:
            _append_jsonl_with_lock(buffer_file, record)
        except Exception as e:
            logger.warning("Failed to write subagent failure buffer: %s", e)


def on_session_reset(session_id: str, platform: str = "", **kwargs) -> None:
    """Hermes on_session_reset hook handler.

    Fires on session reset boundaries to trigger memory compaction if MEMORY.md is near cap.
    """
    logger.info("Session reset event observed for session %s (platform=%s)", session_id, platform)


def render_finch_system_prompt_section(session_info: dict) -> str:
    """Render cache-safe Finch memory rules for Hermes system prompt."""
    return (
        "## Finch Memory & Learning Rules\n"
        "- Behavioral directives marked ALWAYS or NEVER take priority 0.\n"
        "- Do not manually perform memory surgery on MEMORY.md; Finch handles compaction.\n"
        "- Route procedures to skill or reference files rather than expanding MEMORY.md."
    )


def register(ctx) -> None:
    """Register Finch hooks with Hermes PluginContext."""
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_llm_call", on_post_llm_call)
    ctx.register_hook("subagent_start", on_subagent_start)
    ctx.register_hook("subagent_stop", on_subagent_stop)
    ctx.register_hook("on_session_reset", on_session_reset)

    if hasattr(ctx, "register_system_prompt_section"):
        ctx.register_system_prompt_section(
            section_id="finch.memory-rules",
            content_fn=render_finch_system_prompt_section,
            position="after_memory",
            max_chars=2000,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Finch Hermes Hooks Plugin & Helper. Registers real-time signal hooks and memory tool guards."
    )
    parser.add_argument("--extract-signals", type=str, help="Extract learning signals from a text string.")
    parser.add_argument("--check-tool", type=str, help="Check if tool call should be intercepted.")
    args = parser.parse_args()

    if args.extract_signals:
        signals = extract_realtime_signals(args.extract_signals)
        print(json.dumps(signals, indent=2))
        return

    if args.check_tool:
        result = check_memory_tool_call(args.check_tool, {})
        print(json.dumps(result or {"status": "allowed"}, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
