#!/usr/bin/env python3
"""
Finch — Session Miner (OCAS-compliant)

Reads session JSONL files directly (no Dojo/state.db dependency).
Extracts learning signals: corrections, breakthroughs, methodologies,
course-changes, and behavioral directives.

Emits Action Journal entries per spec-ocas-journal.md and
DecisionRecord entries per spec-ocas-shared-schemas.md.

Usage:
    python3 miner.py                          # Mine all recent sessions
    python3 miner.py --days 7                 # Mine last N days
    python3 miner.py --sessions-dir ~/.hermes/sessions
    python3 miner.py --json                   # Output as JSON
    python3 miner.py --min-confidence 0.7     # Filter by confidence
    python3 miner.py --journal-dir /path      # Custom journal output dir
"""

import json
import os
import re
import sys
import glob
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

SESSIONS_DIR = Path(os.getenv("SESSIONS_DIR", Path.home() / ".hermes" / "sessions"))

# OCAS storage paths
HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
OCAS_DATA_DIR = HERMES_HOME / "commons" / "data" / "ocas-finch"
OCAS_JOURNAL_DIR = HERMES_HOME / "commons" / "journals" / "ocas-finch"

# ─── Signal Patterns ─────────────────────────────────────────────────────────

# Corrections: user says no/wrong/stop and gives alternate direction
CORRECTION_PATTERNS = [
    {"pattern": r"(?i)^no[,.\\s]", "type": "correction", "confidence": 0.9},
    {"pattern": r"(?i)^wrong", "type": "correction", "confidence": 0.9},
    {"pattern": r"(?i)^stop\\b", "type": "correction", "confidence": 0.8},
    {"pattern": r"(?i)^don'?t\\b", "type": "correction", "confidence": 0.8},
    {"pattern": r"(?i)^never\\b", "type": "correction", "confidence": 0.9},
    {"pattern": r"(?i)\\bI meant\\b", "type": "correction", "confidence": 0.95},
    {"pattern": r"(?i)\\bnot what I\\b", "type": "correction", "confidence": 0.9},
    {"pattern": r"(?i)\\bthat'?s not\\b", "type": "correction", "confidence": 0.85},
    {"pattern": r"(?i)\\byou (should|shouldn'?t|need to|have to)\\b", "type": "correction", "confidence": 0.8},
    {"pattern": r"(?i)\\bplease (don'?t|stop|fix|change)\\b", "type": "correction", "confidence": 0.85},
    {"pattern": r"(?i)\\bactually[,.\\s]", "type": "correction", "confidence": 0.7},
    {"pattern": r"(?i)\\binstead[,.\\s]", "type": "correction", "confidence": 0.7},
    {"pattern": r"(?i)\\bwhat I'?m (saying|trying) is\\b", "type": "course_change", "confidence": 0.95},
    {"pattern": r"(?i)\\bthat'?s not what I (asked|want|need|meant)\\b", "type": "correction", "confidence": 0.95},
    {"pattern": r"(?i)\\byou (misunderstood|misread|got that wrong)\\b", "type": "correction", "confidence": 0.95},
    {"pattern": r"(?i)\\bI didn'?t (ask|say|mean)\\b", "type": "correction", "confidence": 0.9},
]

# Behavioral directives: Always/Never rules
DIRECTIVE_PATTERNS = [
    {"pattern": r"(?i)\\balways\\b", "type": "directive_always", "confidence": 0.8},
    {"pattern": r"(?i)\\bnever\\b", "type": "directive_never", "confidence": 0.8},
    {"pattern": r"(?i)\\bmust (always|never)\\b", "type": "directive", "confidence": 0.9},
    {"pattern": r"(?i)\\bdo not\\b", "type": "directive_never", "confidence": 0.7},
    {"pattern": r"(?i)\\bdon'?t ever\\b", "type": "directive_never", "confidence": 0.9},
    {"pattern": r"(?i)\\b(make sure|ensure) (to|you|that|we)\\b", "type": "directive", "confidence": 0.7},
    {"pattern": r"(?i)\\bremember to\\b", "type": "directive", "confidence": 0.8},
    {"pattern": r"(?i)\\bfrom now on\\b", "type": "directive", "confidence": 0.9},
    {"pattern": r"(?i)\\bgoing forward\\b", "type": "directive", "confidence": 0.9},
]

# Breakthroughs: user confirms something works or expresses satisfaction
BREAKTHROUGH_PATTERNS = [
    {"pattern": r"(?i)\\bthat'?s (exactly|perfect|right|correct|it)\\b", "type": "breakthrough", "confidence": 0.9},
    {"pattern": r"(?i)\\bthat works\\b", "type": "breakthrough", "confidence": 0.8},
    {"pattern": r"(?i)\\bgreat (job|work|idea)\\b", "type": "breakthrough", "confidence": 0.8},
    {"pattern": r"(?i)\\bexactly what I (wanted|needed|was looking for)\\b", "type": "breakthrough", "confidence": 0.95},
    {"pattern": r"(?i)\\byou (nailed|got) it\\b", "type": "breakthrough", "confidence": 0.9},
    {"pattern": r"(?i)\\bthis is (great|perfect|exactly right)\\b", "type": "breakthrough", "confidence": 0.85},
    {"pattern": r"(?i)\\blove (it|this|that)\\b", "type": "breakthrough", "confidence": 0.8},
    {"pattern": r"(?i)\\bwell done\\b", "type": "breakthrough", "confidence": 0.8},
]

# Reproducible methodologies: user describes a process that worked
METHODOLOGY_PATTERNS = [
    {"pattern": r"(?i)\\bthe (way|method|process|approach|trick) (is|that works)\\b", "type": "methodology", "confidence": 0.8},
    {"pattern": r"(?i)\\bwhat works (is|for me|best)\\b", "type": "methodology", "confidence": 0.85},
    {"pattern": r"(?i)\\bthe (key|secret|trick|hack) is\\b", "type": "methodology", "confidence": 0.9},
    {"pattern": r"(?i)\\bthis is how (you|we|I) (should|do|can)\\b", "type": "methodology", "confidence": 0.8},
    {"pattern": r"(?i)\\bthe pattern (is|here)\\b", "type": "methodology", "confidence": 0.8},
    {"pattern": r"(?i)\\bstep\\s*\\d+\\b.*\\bstep\\s*\\d+\\b", "type": "methodology", "confidence": 0.7},
    {"pattern": r"(?i)\\bfirst\\b.*\\bthen\\b.*\\bfinally\\b", "type": "methodology", "confidence": 0.7},
]

# Stop/interrupt signals: user stopped the agent mid-task
STOP_PATTERNS = [
    {"pattern": r"(?i)^stop$", "type": "stop", "confidence": 0.95},
    {"pattern": r"(?i)^stop\\b.*", "type": "stop", "confidence": 0.9},
    {"pattern": r"(?i)^cancel\\b", "type": "stop", "confidence": 0.9},
    {"pattern": r"(?i)^abort\\b", "type": "stop", "confidence": 0.9},
    {"pattern": r"(?i)^never mind\\b", "type": "stop", "confidence": 0.85},
    {"pattern": r"(?i)^forget (it|that|this)\\b", "type": "stop", "confidence": 0.85},
    {"pattern": r"(?i)^not worth (it|the effort|continuing)\\b", "type": "stop", "confidence": 0.9},
]


def load_session(path: str) -> list[dict]:
    """Load messages from a session JSONL file."""
    messages = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    messages.append(obj)
                except json.JSONDecodeError:
                    continue
    except (IOError, OSError):
        pass
    return messages


def get_session_meta(messages: list[dict]) -> dict:
    """Extract metadata from session_meta message."""
    for msg in messages:
        if msg.get("role") == "session_meta":
            return {
                "platform": msg.get("platform", "unknown"),
                "model": msg.get("model", "unknown"),
                "timestamp": msg.get("timestamp", ""),
                "tools_count": len(msg.get("tools", [])),
            }
    return {"platform": "unknown", "model": "unknown", "timestamp": "", "tools_count": 0}


def is_real_user_message(msg: dict, meta: dict, session_has_meta: bool) -> bool:
    """Filter out system-generated messages (cron, system notes, compaction, etc.)."""
    if msg.get("role") != "user":
        return False

    content = msg.get("content", "")
    if not content or not content.strip():
        return False

    # Skip system-generated messages
    system_prefixes = [
        "[System note:",
        "[SYSTEM",
        "[CRON",
        "[IMPORTANT:",
        "[context",
        "[session",
        "Your previous turn",
        "Your active task list",
        "[Your active",
        "[CONTEXT COMPACTION",
        "Your active task list was preserved",
    ]
    for prefix in system_prefixes:
        if content.startswith(prefix):
            return False

    # Skip cron sessions (explicitly marked)
    if meta.get("platform") == "cron":
        return False

    # Skip very short messages (likely artifacts)
    if len(content.strip()) < 3:
        return False

    return True


def extract_signals(content: str) -> list[dict]:
    """Extract learning signals from a user message."""
    signals = []

    all_patterns = (
        CORRECTION_PATTERNS
        + DIRECTIVE_PATTERNS
        + BREAKTHROUGH_PATTERNS
        + METHODOLOGY_PATTERNS
        + STOP_PATTERNS
    )

    for pat_def in all_patterns:
        pattern = pat_def["pattern"]
        if re.search(pattern, content):
            signals.append({
                "type": pat_def["type"],
                "confidence": pat_def["confidence"],
                "matched_pattern": pattern,
                "matched_text": content[:300],
            })

    return signals


def get_context_window(messages: list[dict], user_idx: int, window: int = 3) -> list[str]:
    """Get surrounding messages for context."""
    start = max(0, user_idx - window)
    end = min(len(messages), user_idx + window + 1)
    context = []
    for i in range(start, end):
        msg = messages[i]
        role = msg.get("role", "?")
        content = msg.get("content", "")[:200]
        if content:
            context.append(f"[{role}] {content}")
    return context


def mine_session(path: str) -> list[dict]:
    """Mine a single session file for learning signals."""
    messages = load_session(path)
    if not messages:
        return []

    meta = get_session_meta(messages)
    session_has_meta = meta.get("platform") != "unknown"
    findings = []

    for i, msg in enumerate(messages):
        if not is_real_user_message(msg, meta, session_has_meta):
            continue

        content = msg.get("content", "")
        signals = extract_signals(content)

        for signal in signals:
            context = get_context_window(messages, i)
            findings.append({
                "signal_type": signal["type"],
                "confidence": signal["confidence"],
                "content": content[:500],
                "context": context,
                "timestamp": msg.get("timestamp", ""),
                "platform": meta.get("platform", "unknown"),
                "model": meta.get("model", "unknown"),
                "session_file": os.path.basename(path),
                "matched_pattern": signal["matched_pattern"],
            })

    return findings


def get_session_files(days: int = None, sessions_dir: Path = None) -> list[str]:
    """Get session files, optionally filtered by recency."""
    sessions_dir = sessions_dir or SESSIONS_DIR
    pattern = str(sessions_dir / "*.jsonl")
    files = sorted(glob.glob(pattern))

    if days is None:
        return files

    cutoff = datetime.now() - timedelta(days=days)
    filtered = []
    for f in files:
        try:
            # Parse timestamp from filename: YYYYMMDD_HHMMSS_*.jsonl
            basename = os.path.basename(f)
            date_str = basename[:8]  # YYYYMMDD
            file_date = datetime.strptime(date_str, "%Y%m%d")
            if file_date >= cutoff:
                filtered.append(f)
        except (ValueError, IndexError):
            filtered.append(f)  # Include if we can't parse

    return filtered


def mine_all(days: int = None, sessions_dir: Path = None, min_confidence: float = 0.0) -> dict:
    """Mine all session files for learning signals."""
    files = get_session_files(days=days, sessions_dir=sessions_dir)

    all_findings = []
    sessions_scanned = 0
    sessions_with_findings = 0

    for f in files:
        findings = mine_session(f)
        sessions_scanned += 1
        if findings:
            sessions_with_findings += 1
            all_findings.extend(findings)

    # Filter by confidence
    if min_confidence > 0:
        all_findings = [f for f in all_findings if f["confidence"] >= min_confidence]

    # Sort by confidence descending
    all_findings.sort(key=lambda x: x["confidence"], reverse=True)

    # Group by signal type
    by_type = {}
    for f in all_findings:
        t = f["signal_type"]
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(f)

    return {
        "meta": {
            "sessions_scanned": sessions_scanned,
            "sessions_with_findings": sessions_with_findings,
            "total_findings": len(all_findings),
            "days_filter": days,
            "min_confidence": min_confidence,
        },
        "by_type": {k: len(v) for k, v in by_type.items()},
        "findings": all_findings,
    }


# ─── OCAS Journal Emission ───────────────────────────────────────────────────

def emit_action_journal(run_id: str, result: dict, journal_dir: Path = None) -> Path:
    """Emit an Action Journal entry per spec-ocas-journal.md."""
    journal_dir = journal_dir or OCAS_JOURNAL_DIR
    now = datetime.now(timezone.utc)
    date_dir = journal_dir / now.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    meta = result.get("meta", {})
    by_type = result.get("by_type", {})

    journal_entry = {
        "run_id": run_id,
        "run_identity": {
            "skill_id": "ocas-finch",
            "skill_version": "2.0.0",
            "run_id": run_id,
            "timestamp": now.isoformat(),
        },
        "runtime": {
            "script": "miner.py",
            "days_filter": meta.get("days_filter"),
            "min_confidence": meta.get("min_confidence"),
        },
        "input": {
            "sessions_scanned": meta.get("sessions_scanned", 0),
            "signal_types_targeted": [
                "correction", "directive_always", "directive_never",
                "breakthrough", "methodology", "stop", "course_change"
            ],
        },
        "decision": {
            "decision_type": "mine",
            "description": f"Mined {meta.get('sessions_scanned', 0)} sessions, found {meta.get('total_findings', 0)} signals",
        },
        "action": {
            "action_type": "session_mining",
            "sessions_scanned": meta.get("sessions_scanned", 0),
            "sessions_with_findings": meta.get("sessions_with_findings", 0),
            "total_findings": meta.get("total_findings", 0),
            "findings_by_type": by_type,
        },
        "metrics": {
            "sessions_scanned": meta.get("sessions_scanned", 0),
            "sessions_with_findings": meta.get("sessions_with_findings", 0),
            "total_findings": meta.get("total_findings", 0),
        },
        "okr_evaluation": {
            "coverage": meta.get("sessions_scanned", 0),
            "yield_rate": (
                meta.get("sessions_with_findings", 0) / max(meta.get("sessions_scanned", 1), 1)
            ),
        },
        "journal_type": "Action",
        "journal_spec_version": "1.2.3",
    }

    journal_path = date_dir / f"{run_id}.json"
    with open(journal_path, "w") as f:
        json.dump(journal_entry, f, indent=2, default=str)

    return journal_path


def emit_decision_record(run_id: str, result: dict, decisions_path: Path = None) -> Path:
    """Append a DecisionRecord per spec-ocas-shared-schemas.md."""
    decisions_path = decisions_path or (OCAS_DATA_DIR / "decisions.jsonl")
    OCAS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    meta = result.get("meta", {})

    record = {
        "decision_id": f"dec_{uuid.uuid4().hex[:12]}",
        "timestamp": now.isoformat(),
        "skill_id": "ocas-finch",
        "skill_version": "2.0.0",
        "decision_type": "mine",
        "description": (
            f"Session mining run {run_id}: scanned {meta.get('sessions_scanned', 0)} sessions, "
            f"found {meta.get('total_findings', 0)} signals across "
            f"{meta.get('sessions_with_findings', 0)} sessions"
        ),
        "evidence_refs": [f"journal:ocas-finch/{now.strftime('%Y-%m-%d')}/{run_id}.json"],
        "outcome": f"{meta.get('total_findings', 0)} findings routed for review",
        "confidence": "high" if meta.get("total_findings", 0) > 0 else "low",
        "side_effects": None,
    }

    with open(decisions_path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")

    return decisions_path


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Finch — Session Miner (OCAS)")
    parser.add_argument("--days", type=int, default=None, help="Only scan last N days")
    parser.add_argument("--sessions-dir", type=str, default=None, help="Sessions directory")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--min-confidence", type=float, default=0.0, help="Minimum confidence threshold")
    parser.add_argument("--journal-dir", type=str, default=None, help="Custom journal output directory")
    parser.add_argument("--no-journal", action="store_true", help="Skip OCAS journal emission")
    args = parser.parse_args()

    sessions_dir = Path(args.sessions_dir) if args.sessions_dir else None
    result = mine_all(
        days=args.days,
        sessions_dir=sessions_dir,
        min_confidence=args.min_confidence,
    )

    # Generate run ID
    run_id = f"fin_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    # Emit OCAS journal and decision record
    if not args.no_journal:
        journal_dir = Path(args.journal_dir) if args.journal_dir else None
        try:
            journal_path = emit_action_journal(run_id, result, journal_dir=journal_dir)
            decisions_path = emit_decision_record(run_id, result)
            result["meta"]["journal_path"] = str(journal_path)
            result["meta"]["decisions_path"] = str(decisions_path)
            result["meta"]["run_id"] = run_id
        except Exception as e:
            result["meta"]["journal_error"] = str(e)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        meta = result["meta"]
        print("=" * 60)
        print("  OCAS FINCH — SESSION MINER")
        print("=" * 60)
        print(f"  Run ID:            {run_id}")
        print(f"  Sessions scanned:  {meta['sessions_scanned']}")
        print(f"  Sessions w/ finds: {meta['sessions_with_findings']}")
        print(f"  Total findings:    {meta['total_findings']}")
        if meta.get("journal_path"):
            print(f"  Journal:           {meta['journal_path']}")
        print()

        if result["by_type"]:
            print("  FINDINGS BY TYPE:")
            for t, count in sorted(result["by_type"].items(), key=lambda x: -x[1]):
                print(f"    {t:25s} {count}")
            print()

        # Show top findings
        if result["findings"]:
            print("  TOP FINDINGS:")
            for f in result["findings"][:20]:
                print(f"    [{f['signal_type']}] (conf={f['confidence']:.1f}) {f['platform']}")
                print(f"      {f['content'][:120]}")
                print()


if __name__ == "__main__":
    main()
