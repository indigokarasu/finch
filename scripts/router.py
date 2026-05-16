#!/usr/bin/env python3
"""
Finch — Recommendation Router (OCAS-compliant)

Takes findings from the session miner and produces a targeted action plan.
Each finding is routed to the modification target that will have the most
behavioral impact. Emits DecisionRecords per spec-ocas-shared-schemas.md.

Routing logic:
  - corrections + directives ("Always/Never") → MEMORY.md (highest impact)
  - course_changes → MEMORY.md + skill patch if skill-related
  - breakthroughs → MEMORY.md (reinforce what works)
  - methodologies → skill patch or new skill (encode the process)
  - stop signals → MEMORY.md (record what not to do)

MEMORY.md size awareness:
  - Hard limit: 2,200 characters (from config.yaml memory_char_limit)
  - Before generating plan, check current MEMORY.md size
  - If approaching limit: prioritize directives > corrections > breakthroughs
  - Overflow: route to skill files instead

Usage:
    python3 router.py --input <miner_output.json>
    python3 router.py --input <miner_output.json> --dry-run
    python3 router.py --input <miner_output.json> --json
    python3 router.py --input <miner_output.json> --emit-decisions
"""

import json
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
MEMORY_FILE = HERMES_HOME / "MEMORY.md"
SKILLS_DIR = HERMES_HOME / "skills"
CONFIG_FILE = HERMES_HOME / "config.yaml"
OCAS_DATA_DIR = HERMES_HOME / "commons" / "data" / "ocas-finch"

# MEMORY.md hard limit (chars)
MEMORY_CHAR_LIMIT = 2200


def _get_memory_usage() -> tuple[int, int]:
    """Return (current_chars, remaining_chars) for MEMORY.md."""
    if not MEMORY_FILE.exists():
        return 0, MEMORY_CHAR_LIMIT
    content = MEMORY_FILE.read_text(encoding="utf-8")
    used = len(content)
    return used, MEMORY_CHAR_LIMIT - used


def route_findings(findings: list[dict]) -> list[dict]:
    """Route each finding to the optimal modification target."""
    routed = []

    for f in findings:
        signal_type = f.get("signal_type", "unknown")
        content = f.get("content", "")
        confidence = f.get("confidence", 0.5)

        # ── Corrections → MEMORY.md ──
        if signal_type == "correction":
            routed.append({
                "finding": f,
                "action": "memory_add",
                "target": "MEMORY.md",
                "section": "User Corrections",
                "priority": 1,
                "rationale": "User corrected behavior → persist in memory for all future sessions",
                "suggested_entry": _extract_correction(content),
            })

        # ── Directives (Always/Never) → MEMORY.md (highest priority) ──
        elif signal_type in ("directive_always", "directive_never", "directive"):
            section = "Behavioral Directives"
            if "always" in signal_type:
                section = "Always Rules"
            elif "never" in signal_type:
                section = "Never Rules"

            routed.append({
                "finding": f,
                "action": "memory_add",
                "target": "MEMORY.md",
                "section": section,
                "priority": 0,  # Highest — directives are explicit behavioral rules
                "rationale": f"User directive ({signal_type}) → must persist across all sessions",
                "suggested_entry": _extract_directive(content),
            })

        # ── Course changes → MEMORY.md ──
        elif signal_type == "course_change":
            routed.append({
                "finding": f,
                "action": "memory_add",
                "target": "MEMORY.md",
                "section": "Course Changes",
                "priority": 1,
                "rationale": "User redirected interpretation → record the correct understanding",
                "suggested_entry": _extract_course_change(content),
            })

        # ── Breakthroughs → MEMORY.md (reinforce) ──
        elif signal_type == "breakthrough":
            routed.append({
                "finding": f,
                "action": "memory_add",
                "target": "MEMORY.md",
                "section": "What Works",
                "priority": 2,
                "rationale": "User confirmed something works → reinforce this pattern",
                "suggested_entry": _extract_breakthrough(content, f.get("context", [])),
            })

        # ── Methodologies → skill patch or MEMORY.md ──
        elif signal_type == "methodology":
            skill_name = _find_related_skill(content)
            if skill_name:
                routed.append({
                    "finding": f,
                    "action": "skill_patch",
                    "target": f"~/.hermes/skills/{skill_name}/SKILL.md",
                    "priority": 2,
                    "rationale": "Reproducible methodology → encode in relevant skill",
                    "suggested_entry": _extract_methodology(content),
                })
            else:
                routed.append({
                    "finding": f,
                    "action": "memory_add",
                    "target": "MEMORY.md",
                    "section": "Methodologies",
                    "priority": 2,
                    "rationale": "Reproducible methodology → record in memory",
                    "suggested_entry": _extract_methodology(content),
                })

        # ── Stop signals → MEMORY.md (negative reinforcement) ──
        elif signal_type == "stop":
            routed.append({
                "finding": f,
                "action": "memory_add",
                "target": "MEMORY.md",
                "section": "Stop Signals",
                "priority": 1,
                "rationale": "User stopped task → record what triggered the stop",
                "suggested_entry": _extract_stop(content, f.get("context", [])),
            })

        # ── Unknown → flag for review ──
        else:
            routed.append({
                "finding": f,
                "action": "review",
                "target": "manual",
                "priority": 3,
                "rationale": f"Unknown signal type: {signal_type}",
                "suggested_entry": content[:200],
            })

    # Sort by priority
    routed.sort(key=lambda r: r["priority"])
    return routed


def _extract_correction(content: str) -> str:
    """Extract the correction as a concise memory entry."""
    cleaned = content
    for prefix in ["No,", "No.", "No ", "Wrong,", "Wrong.", "Don't", "Stop"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    return f"Correction: {cleaned[:300]}"


def _extract_directive(content: str) -> str:
    """Extract Always/Never directive as a rule."""
    return f"Directive: {content[:300]}"


def _extract_course_change(content: str) -> str:
    """Extract course change as corrected understanding."""
    return f"Course change: {content[:300]}"


def _extract_breakthrough(content: str, context: list) -> str:
    """Extract what worked."""
    preceding = ""
    for msg in context:
        if msg.startswith("[assistant]"):
            preceding = msg[:200]
            break
    if preceding:
        return f"Works: {preceding} → User confirmed: {content[:200]}"
    return f"Works: {content[:300]}"


def _extract_methodology(content: str) -> str:
    """Extract reproducible methodology."""
    return f"Methodology: {content[:400]}"


def _extract_stop(content: str, context: list) -> str:
    """Extract what triggered a stop."""
    preceding = ""
    for msg in context:
        if msg.startswith("[assistant]"):
            preceding = msg[:200]
            break
    if preceding:
        return f"Stop trigger: Was doing '{preceding}' → User stopped: {content[:200]}"
    return f"Stop: {content[:300]}"


def _find_related_skill(content: str) -> str | None:
    """Try to find which skill is related to this methodology."""
    content_lower = content.lower()

    skill_keywords = {
        "github": "github",
        "git ": "github",
        "pr ": "github-pr-workflow",
        "pull request": "github-pr-workflow",
        "google": "google-workspace",
        "gmail": "google-workspace",
        "calendar": "google-workspace",
        "drive": "google-workspace",
        "linkedin": "linkedin",
        "telegram": "telegram",
        "browser": "stealth-browser",
        "search": "web_search",
        "memory": "hermes-agent",
        "skill": "hermes-agent",
        "cron": "hermes-agent",
        "config": "hermes-agent",
    }

    for keyword, skill in skill_keywords.items():
        if keyword in content_lower:
            # Check if skill exists (check both old and new naming)
            for prefix in ["ocas-", ""]:
                skill_path = SKILLS_DIR / f"{prefix}{skill}" / "SKILL.md"
                if skill_path.exists():
                    return f"{prefix}{skill}"

    return None


def generate_action_plan(routed: list[dict]) -> dict:
    """Generate a structured action plan from routed findings.

    MEMORY.md size-aware: when space is tight, low-priority findings
    are rerouted to skill files or flagged for manual review.
    """
    memory_used, memory_remaining = _get_memory_usage()

    plan = {
        "memory_additions": [],
        "skill_patches": [],
        "manual_review": [],
        "overflow_to_skills": [],
        "summary": {
            "total_findings": len(routed),
            "memory_entries": 0,
            "skill_patches": 0,
            "manual_review": 0,
            "overflowed": 0,
            "memory_used": memory_used,
            "memory_remaining": memory_remaining,
        },
    }

    # Estimate chars each memory entry will consume
    estimated_memory_cost = 0

    for r in routed:
        action = r["action"]
        entry_len = len(r.get("suggested_entry", "")) + 30  # overhead for formatting

        if action == "memory_add":
            # Check if we have room (reserve 100 chars buffer)
            if estimated_memory_cost + entry_len < memory_remaining - 100:
                entry = r["suggested_entry"]
                if not any(e["entry"][:100] == entry[:100] for e in plan["memory_additions"]):
                    plan["memory_additions"].append({
                        "section": r["section"],
                        "entry": entry,
                        "priority": r["priority"],
                    })
                    plan["summary"]["memory_entries"] += 1
                    estimated_memory_cost += entry_len
            else:
                # MEMORY.md full — overflow to skill file or manual review
                skill_name = _find_related_skill(r.get("suggested_entry", ""))
                if skill_name:
                    plan["overflow_to_skills"].append({
                        "target": f"~/.hermes/skills/{skill_name}/SKILL.md",
                        "entry": r["suggested_entry"],
                        "original_section": r.get("section", ""),
                        "reason": "MEMORY.md size limit — overflowed to skill file",
                    })
                    plan["summary"]["overflowed"] += 1
                else:
                    plan["manual_review"].append({
                        **r,
                        "overflow_reason": f"MEMORY.md near limit ({memory_used}/{MEMORY_CHAR_LIMIT} chars)",
                    })
                    plan["summary"]["manual_review"] += 1

        elif action == "skill_patch":
            target = r["target"]
            if not any(p["target"] == target for p in plan["skill_patches"]):
                plan["skill_patches"].append({
                    "target": target,
                    "entry": r["suggested_entry"],
                    "priority": r["priority"],
                })
                plan["summary"]["skill_patches"] += 1

        elif action == "review":
            plan["manual_review"].append(r)
            plan["summary"]["manual_review"] += 1

    return plan


# ─── OCAS DecisionRecord Emission ────────────────────────────────────────────

def emit_routing_decisions(plan: dict, run_id: str, decisions_path: Path = None) -> Path:
    """Emit DecisionRecords for each routing decision per spec-ocas-shared-schemas.md."""
    decisions_path = decisions_path or (OCAS_DATA_DIR / "decisions.jsonl")
    OCAS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    records = []

    # Decision: memory additions
    for entry in plan.get("memory_additions", []):
        record = {
            "decision_id": f"dec_{uuid.uuid4().hex[:12]}",
            "timestamp": now.isoformat(),
            "skill_id": "ocas-finch",
            "skill_version": "2.0.0",
            "decision_type": "route",
            "description": f"Route finding to MEMORY.md section '{entry['section']}': {entry['entry'][:80]}",
            "evidence_refs": [],
            "outcome": f"memory_add → {entry['section']}",
            "confidence": "high",
            "side_effects": None,
        }
        records.append(record)

    # Decision: skill patches
    for patch in plan.get("skill_patches", []):
        record = {
            "decision_id": f"dec_{uuid.uuid4().hex[:12]}",
            "timestamp": now.isoformat(),
            "skill_id": "ocas-finch",
            "skill_version": "2.0.0",
            "decision_type": "route",
            "description": f"Route finding to skill patch: {patch['target']}: {patch['entry'][:80]}",
            "evidence_refs": [],
            "outcome": f"skill_patch → {patch['target']}",
            "confidence": "high",
            "side_effects": None,
        }
        records.append(record)

    # Decision: manual review items
    for item in plan.get("manual_review", []):
        finding = item.get("finding", {})
        record = {
            "decision_id": f"dec_{uuid.uuid4().hex[:12]}",
            "timestamp": now.isoformat(),
            "skill_id": "ocas-finch",
            "skill_version": "2.0.0",
            "decision_type": "review",
            "description": f"Flagged for manual review: [{finding.get('signal_type', 'unknown')}] {finding.get('content', '')[:80]}",
            "evidence_refs": [],
            "outcome": "manual_review",
            "confidence": "med",
            "side_effects": None,
        }
        records.append(record)

    with open(decisions_path, "a") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")

    return decisions_path


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Finch — Recommendation Router (OCAS)")
    parser.add_argument("--input", required=True, help="Path to miner output JSON")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without applying")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--emit-decisions", action="store_true", help="Emit DecisionRecords")
    args = parser.parse_args()

    with open(args.input) as f:
        data = json.load(f)

    findings = data.get("findings", [])
    routed = route_findings(findings)
    plan = generate_action_plan(routed)

    # Emit DecisionRecords if requested
    if args.emit_decisions:
        run_id = data.get("meta", {}).get("run_id", f"route_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
        decisions_path = emit_routing_decisions(plan, run_id)
        plan["decisions_path"] = str(decisions_path)

    if args.json:
        print(json.dumps(plan, indent=2, default=str))
    else:
        print("=" * 60)
        print("  OCAS FINCH — ACTION PLAN")
        print("=" * 60)
        print(f"  Total findings:    {plan['summary']['total_findings']}")
        print(f"  Memory entries:    {plan['summary']['memory_entries']}")
        print(f"  Skill patches:     {plan['summary']['skill_patches']}")
        print(f"  Manual review:     {plan['summary']['manual_review']}")
        print(f"  Overflowed:        {plan['summary']['overflowed']}")
        mem_pct = plan['summary']['memory_used'] / MEMORY_CHAR_LIMIT * 100
        print(f"  MEMORY.md:         {plan['summary']['memory_used']}/{MEMORY_CHAR_LIMIT} chars ({mem_pct:.0f}%)")
        if plan.get("decisions_path"):
            print(f"  Decisions:         {plan['decisions_path']}")
        print()

        if plan["memory_additions"]:
            print("  MEMORY ADDITIONS (→ MEMORY.md):")
            for entry in plan["memory_additions"]:
                priority_label = "🔴" if entry["priority"] <= 0 else "🟡" if entry["priority"] <= 1 else "🟢"
                print(f"    {priority_label} [{entry['section']}]")
                print(f"       {entry['entry'][:120]}")
                print()

        if plan["skill_patches"]:
            print("  SKILL PATCHES:")
            for patch in plan["skill_patches"]:
                print(f"    🟡 {patch['target']}")
                print(f"       {patch['entry'][:120]}")
                print()

        if plan["overflow_to_skills"]:
            print("  OVERFLOW → SKILL FILES (MEMORY.md full):")
            for o in plan["overflow_to_skills"]:
                print(f"    🔵 {o['target']}")
                print(f"       {o['entry'][:120]}")
                print()

        if plan["manual_review"]:
            print("  MANUAL REVIEW:")
            for r in plan["manual_review"]:
                f = r["finding"]
                overflow = r.get("overflow_reason", "")
                tag = f" ⚠️ {overflow}" if overflow else ""
                print(f"    ⚪ [{f['signal_type']}] {f['content'][:100]}{tag}")
            print()

        if args.dry_run:
            print("  ⚠️  DRY RUN — no changes applied.")
        else:
            print("  ✅ Plan ready to apply.")

    return plan


if __name__ == "__main__":
    main()
