#!/usr/bin/env python3
"""
Finch — MEMORY.md Compaction Engine (OCAS-compliant)

Runs on every finch cycle (before applying new findings).
Keeps MEMORY.md within the 2,200 char limit without meaning loss.

Emits DecisionRecords per spec-ocas-shared-schemas.md.

Operations (in order):
  1. Deduplicate — merge entries that say the same thing
  2. Contradiction check — flag/resolve conflicting entries
  3. Re-rank — reorder sections and entries by priority
  4. Evict — drop lowest-priority entries if still over limit
  5. Compress — rewrite entries compactly (only when >80% = 1,760 chars)

Usage:
    python3 compact.py                          # dry-run, show plan
    python3 compact.py --apply                  # apply changes
    python3 compact.py --json                   # output plan as JSON
    python3 compact.py --apply --json           # apply + JSON log
    python3 compact.py --apply --emit-decisions # apply + DecisionRecords
"""

import json
import os
import re
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
MEMORY_FILE = HERMES_HOME / "MEMORY.md"
OCAS_DATA_DIR = HERMES_HOME / "commons" / "data" / "ocas-finch"
ARCHIVE_FILE = OCAS_DATA_DIR / "memory_archive.md"
MEMORY_CHAR_LIMIT = 2200
COMPRESS_THRESHOLD = int(MEMORY_CHAR_LIMIT * 0.80)  # 1760 chars

# Section priority (lower = more important, kept first)
SECTION_PRIORITY = {
    "Behavioral Directives": 0,
    "Always Rules": 0,
    "Never Rules": 0,
    "Identity Rules": 1,
    "Who I Am": 1,
    "Who the User Is": 1,
    "User Corrections": 2,
    "Course Changes": 2,
    "Key Infrastructure": 3,
    "Tool Quirks": 3,
    "What Works": 4,
    "Stop Signals": 5,
    "Methodologies": 6,
}

# Entry-level priority keywords (lower = more important)
HIGH_PRIORITY_KEYWORDS = ["always", "never", "must", "critical", "important", "do not", "don't"]
LOW_PRIORITY_KEYWORDS = ["nice to know", "optionally", "might", "could", "sometimes"]


def load_memory() -> str:
    if not MEMORY_FILE.exists():
        return ""
    return MEMORY_FILE.read_text(encoding="utf-8")


def parse_sections(content: str) -> list[dict]:
    """Parse MEMORY.md into sections with entries."""
    sections = []
    top_header = ""
    current_section = {"header": "", "entries": [], "raw": ""}
    current_entries_block = []

    for line in content.splitlines():
        # Capture the top-level # header (not ##)
        if line.startswith("# ") and not top_header:
            top_header = line.strip()
            continue
        if line.startswith("## "):
            if current_section["header"] or current_section["entries"]:
                current_section["raw"] = "\n".join(current_entries_block)
                sections.append(current_section)
            current_section = {"header": line.strip(), "entries": [], "raw": ""}
            current_entries_block = [line]
        elif line.startswith("- "):
            current_section["entries"].append(line.strip())
            current_entries_block.append(line)
        else:
            current_entries_block.append(line)

    if current_section["header"] or current_section["entries"]:
        current_section["raw"] = "\n".join(current_entries_block)
        sections.append(current_section)

    return sections


def entry_priority(entry: str) -> int:
    """Score an entry's priority (lower = more important)."""
    text = entry.lower()
    for kw in HIGH_PRIORITY_KEYWORDS:
        if kw in text:
            return 0
    for kw in LOW_PRIORITY_KEYWORDS:
        if kw in text:
            return 2
    return 1


def section_priority(header: str) -> int:
    """Get section priority from the ranking table."""
    for key, val in SECTION_PRIORITY.items():
        if key.lower() in header.lower():
            return val
    return 5  # unknown sections = low priority


# ─── 1. Deduplicate ──────────────────────────────────────────────────────────

def deduplicate(sections: list[dict]) -> tuple[list[dict], list[str]]:
    """Remove duplicate or near-duplicate entries within and across sections."""
    removed = []
    seen = {}  # normalized text -> first section header

    for section in sections:
        kept = []
        for entry in section["entries"]:
            # Normalize: lowercase, strip bullets, collapse whitespace
            norm = re.sub(r"\s+", " ", entry.lower().strip().lstrip("- ")).strip()

            # Check for exact or near-duplicate (>80% overlap)
            is_dup = False
            for seen_norm, seen_section in seen.items():
                if _similarity(norm, seen_norm) > 0.8:
                    removed.append(f"Dedup: '{entry[:80]}' (duplicate of entry in {seen_section})")
                    is_dup = True
                    break

            if not is_dup:
                seen[norm] = section["header"]
                kept.append(entry)

        section["entries"] = kept

    return sections, removed


def _similarity(a: str, b: str) -> float:
    """Simple Jaccard similarity of word sets."""
    if not a or not b:
        return 0.0
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


# ─── 2. Contradiction check ──────────────────────────────────────────────────

def check_contradictions(sections: list[dict]) -> list[dict]:
    """Find entries that contradict each other."""
    contradictions = []

    # Collect all entries
    all_entries = []
    for section in sections:
        for entry in section["entries"]:
            all_entries.append({"entry": entry, "section": section["header"]})

    # Check pairs for contradiction patterns
    contradiction_patterns = [
        (r"\balways\b", r"\bnever\b"),
        (r"\bdon'?t\b", r"\bdo\b"),
        (r"\bmust\b", r"\bmust not\b"),
        (r"\buse\b", r"\bdon'?t use\b"),
        (r"\brequired\b", r"\boptional\b"),
    ]

    for i, a in enumerate(all_entries):
        for j, b in enumerate(all_entries):
            if i >= j:
                continue
            text_a = a["entry"].lower()
            text_b = b["entry"].lower()

            # Check if entries are about the same topic (share significant words)
            sim = _similarity(text_a, text_b)
            if sim < 0.3:
                continue  # not about the same thing

            # Check for contradiction patterns
            for pos_pat, neg_pat in contradiction_patterns:
                a_has_pos = bool(re.search(pos_pat, text_a))
                a_has_neg = bool(re.search(neg_pat, text_a))
                b_has_pos = bool(re.search(pos_pat, text_b))
                b_has_neg = bool(re.search(neg_pat, text_b))

                if (a_has_pos and b_has_neg) or (a_has_neg and b_has_pos):
                    contradictions.append({
                        "entry_a": a["entry"],
                        "section_a": a["section"],
                        "entry_b": b["entry"],
                        "section_b": b["section"],
                        "similarity": sim,
                    })
                    break

    return contradictions


# ─── 3. Re-rank ──────────────────────────────────────────────────────────────

def rerank(sections: list[dict]) -> list[dict]:
    """Reorder sections by priority, and entries within sections by priority."""
    # Sort sections
    sections.sort(key=lambda s: section_priority(s["header"]))

    # Sort entries within each section
    for section in sections:
        section["entries"].sort(key=lambda e: entry_priority(e))

    return sections


# ─── 4. Evict ────────────────────────────────────────────────────────────────

def evict(sections: list[dict], target_chars: int) -> tuple[list[dict], list[str]]:
    """Remove lowest-priority entries until under target_chars."""
    evicted = []
    current_size = _render_size(sections)

    if current_size <= target_chars:
        return sections, evicted

    # Build a flat list of all entries with their priority
    all_entries = []
    for section in sections:
        for entry in section["entries"]:
            all_entries.append({
                "entry": entry,
                "section": section["header"],
                "priority": section_priority(section["header"]) * 10 + entry_priority(entry),
            })

    # Sort by priority (highest number = least important = evict first)
    all_entries.sort(key=lambda e: -e["priority"])

    # Evict until under limit
    evicted_texts = set()
    for item in all_entries:
        if current_size <= target_chars:
            break
        evicted_texts.add(item["entry"])
        evicted.append(f"Evicted ({item['priority']}): '{item['entry'][:80]}'")
        current_size -= len(item["entry"]) + 2  # +2 for "- " and newline

    # Rebuild sections without evicted entries
    for section in sections:
        section["entries"] = [e for e in section["entries"] if e not in evicted_texts]

    # Remove empty sections (but keep header-only sections that had content before)
    sections = [s for s in sections if s["entries"] or s["header"].startswith("# ") and not s["header"].startswith("## ")]

    return sections, evicted


# ─── 5. Compress ─────────────────────────────────────────────────────────────

def should_compress(sections: list[dict]) -> bool:
    return _render_size(sections) > COMPRESS_THRESHOLD


def compress_entry(entry: str) -> str:
    """Compress a single entry without losing meaning."""
    text = entry.lstrip("- ").strip()

    # Remove filler phrases
    fillers = [
        r"\b(it is|it's) (important|notable|worth noting) that\b",
        r"\b(please )?note that\b",
        r"\b(as )?(mentioned|noted|stated) (above|earlier|before)\b",
        r"\b(in order )?to\b",
        r"\b(make sure|ensure) (that )?\b",
        r"\b(also,? )?(remember|keep in mind) (that )?\b",
    ]
    for pat in fillers:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Truncate if still very long (keep first 200 chars + "...")
    if len(text) > 200:
        text = text[:197] + "..."

    return f"- {text}"


def compress_sections(sections: list[dict]) -> tuple[list[dict], int]:
    """Compress all entries. Returns (sections, chars_saved)."""
    original_size = _render_size(sections)
    for section in sections:
        section["entries"] = [compress_entry(e) for e in section["entries"]]
    new_size = _render_size(sections)
    return sections, original_size - new_size


# ─── Render ──────────────────────────────────────────────────────────────────

def _render_size(sections: list[dict]) -> int:
    """Calculate the char size of the rendered output (excluding top header)."""
    return len(_render(sections, top_header=""))


def _render(sections: list[dict], top_header: str = "") -> str:
    """Render sections back to markdown."""
    parts = []
    if top_header:
        parts.append(top_header)
        parts.append("")
    for i, section in enumerate(sections):
        parts.append(section["header"])
        for entry in section["entries"]:
            parts.append(entry)
        if i < len(sections) - 1:
            parts.append("")  # blank line between sections
    return "\n".join(parts)


# ─── Archive ─────────────────────────────────────────────────────────────────

def archive_evicted(evicted: list[str], contradictions: list[dict]):
    """Write evicted entries and contradictions to the archive file."""
    OCAS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n--- Compaction run ---\n")
        if evicted:
            f.write("Evicted entries:\n")
            for e in evicted:
                f.write(f"  {e}\n")
        if contradictions:
            f.write("Contradictions found:\n")
            for c in contradictions:
                f.write(f"  [{c['section_a']}] {c['entry_a'][:80]}\n")
                f.write(f"  [{c['section_b']}] {c['entry_b'][:80]}\n")
                f.write(f"  Similarity: {c['similarity']:.2f}\n\n")


# ─── OCAS DecisionRecord Emission ────────────────────────────────────────────

def emit_compact_decisions(report: dict, decisions_path: Path = None) -> Path:
    """Emit DecisionRecords for compaction operations."""
    decisions_path = decisions_path or (OCAS_DATA_DIR / "decisions.jsonl")
    OCAS_DATA_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    records = []

    # Decision: compaction run
    records.append({
        "decision_id": f"dec_{uuid.uuid4().hex[:12]}",
        "timestamp": now.isoformat(),
        "skill_id": "ocas-finch",
        "skill_version": "2.0.0",
        "decision_type": "compact",
        "description": (
            f"MEMORY.md compaction: {report['original_size']} → {report['final_size']} chars "
            f"(saved {report['original_size'] - report['final_size']})"
        ),
        "evidence_refs": [],
        "outcome": f"compacted: {len(report.get('evicted', []))} evicted, {len(report.get('contradictions', []))} contradictions",
        "confidence": "high",
        "side_effects": "MEMORY.md rewritten" if report.get("applied") else None,
    })

    # Decision: each eviction
    for evicted_item in report.get("evicted", []):
        records.append({
            "decision_id": f"dec_{uuid.uuid4().hex[:12]}",
            "timestamp": now.isoformat(),
            "skill_id": "ocas-finch",
            "skill_version": "2.0.0",
            "decision_type": "evict",
            "description": f"Evicted from MEMORY.md: {evicted_item[:100]}",
            "evidence_refs": [f"archive:ocas-finch/memory_archive.md"],
            "outcome": "evicted_to_archive",
            "confidence": "med",
            "side_effects": None,
        })

    with open(decisions_path, "a") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")

    return decisions_path


# ─── Main ────────────────────────────────────────────────────────────────────

def compact(memory_content: str, apply: bool = False) -> dict:
    """Run the full compaction pipeline. Returns a report dict."""
    report = {
        "original_size": len(memory_content),
        "operations": [],
        "contradictions": [],
        "evicted": [],
        "compressed": False,
        "chars_saved": 0,
        "final_size": 0,
        "applied": False,
    }

    if not memory_content.strip():
        report["operations"].append("MEMORY.md is empty — nothing to compact")
        return report

    sections = parse_sections(memory_content)
    # Extract top-level # header from raw content
    top_header = ""
    for line in memory_content.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            top_header = line.strip()
            break

    # 1. Deduplicate
    sections, deduped = deduplicate(sections)
    if deduped:
        report["operations"].append(f"Dedup: removed {len(deduped)} duplicate(s)")
        report["evicted"].extend(deduped)

    # 2. Contradiction check
    contradictions = check_contradictions(sections)
    report["contradictions"] = contradictions
    if contradictions:
        report["operations"].append(f"Contradictions: found {len(contradictions)} pair(s) — flagged for review")

    # 3. Re-rank
    sections = rerank(sections)
    report["operations"].append("Re-ranked: sections and entries reordered by priority")

    # 4. Evict (target: leave room for new findings — aim for 70% = 1540 chars)
    target = int(MEMORY_CHAR_LIMIT * 0.70)
    sections, evicted = evict(sections, target)
    if evicted:
        report["operations"].append(f"Evicted: removed {len(evicted)} low-priority entry(ies)")
        report["evicted"].extend(evicted)

    # 5. Compress (only if still over 80%)
    if should_compress(sections):
        sections, saved = compress_sections(sections)
        report["compressed"] = True
        report["chars_saved"] = saved
        report["operations"].append(f"Compressed: saved {saved} chars")
    else:
        report["operations"].append(f"Skipped compression (under {COMPRESS_THRESHOLD} char threshold)")

    rendered = _render(sections, top_header)
    report["final_size"] = len(rendered)

    if apply:
        MEMORY_FILE.write_text(rendered + "\n", encoding="utf-8")
        report["applied"] = True
        if report["evicted"] or report["contradictions"]:
            archive_evicted(report["evicted"], report["contradictions"])

    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Finch — MEMORY.md Compaction Engine (OCAS)")
    parser.add_argument("--apply", action="store_true", help="Apply changes to MEMORY.md")
    parser.add_argument("--json", action="store_true", help="Output report as JSON")
    parser.add_argument("--emit-decisions", action="store_true", help="Emit DecisionRecords")
    args = parser.parse_args()

    content = load_memory()
    report = compact(content, apply=args.apply)

    # Emit DecisionRecords if requested
    if args.emit_decisions:
        decisions_path = emit_compact_decisions(report)
        report["decisions_path"] = str(decisions_path)

    if args.json:
        # Make contradictions JSON-serializable
        out = dict(report)
        out["contradictions"] = [
            {k: v for k, v in c.items()} for c in report["contradictions"]
        ]
        print(json.dumps(out, indent=2))
    else:
        print("=" * 60)
        print("  OCAS FINCH — MEMORY.md COMPACTION REPORT")
        print("=" * 60)
        print(f"  Original size:  {report['original_size']} chars")
        print(f"  Final size:     {report['final_size']} chars")
        print(f"  Compressed:     {'Yes' if report['compressed'] else 'No'}")
        if report['compressed']:
            print(f"  Chars saved:    {report['chars_saved']}")
        print(f"  Applied:        {'Yes' if report['applied'] else 'No (dry run)'}")
        if report.get("decisions_path"):
            print(f"  Decisions:      {report['decisions_path']}")
        print()

        if report["operations"]:
            print("  OPERATIONS:")
            for op in report["operations"]:
                print(f"    ✓ {op}")
            print()

        if report["contradictions"]:
            print("  CONTRADICTIONS (need human review):")
            for c in report["contradictions"]:
                print(f"    ⚠ [{c['section_a']}] {c['entry_a'][:80]}")
                print(f"      [{c['section_b']}] {c['entry_b'][:80]}")
                print(f"      Similarity: {c['similarity']:.2f}")
            print()

        if report["evicted"]:
            print("  EVICTED:")
            for e in report["evicted"]:
                print(f"    ✗ {e}")
            print()

        if not args.apply:
            print("  ⚠️  DRY RUN — no changes applied. Use --apply to write.")
        else:
            print("  ✅ Changes written to MEMORY.md")


if __name__ == "__main__":
    main()
