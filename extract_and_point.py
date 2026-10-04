#!/usr/bin/env python3
import re
import sys
from pathlib import Path

skill_dir = Path(__file__).resolve().parent
skill_md = skill_dir / "SKILL.md"

# Read the file
content = skill_md.read_text(encoding="utf-8")
lines = content.splitlines(keepends=True)

# Find the frontmatter (between the first two '---' lines)
fm_start = None
fm_end = None
for i, line in enumerate(lines):
    if line.strip() == "---":
        if fm_start is None:
            fm_start = i
        else:
            fm_end = i
            break
if fm_start is None or fm_end is None:
    print("Could not find frontmatter boundaries", file=sys.stderr)
    sys.exit(1)

frontmatter = lines[:fm_end+1]
body = lines[fm_end+1:]

# We'll split the body by top-level headings (lines that start with '## ')
# We want to extract specific sections and replace them with a pointer.
# The sections we want to extract are:
sections_to_extract = [
    "Workflow — the core loop",
    "Manual run, commands, recovery",
    "Cron-worker shell blocks (Tirith) — adapt, do not retry",
    "Storage & behavioral directives",
]

# We'll build a new body and a list of extracted sections
new_body = []
extracted = {}

i = 0
while i < len(body):
    line = body[i]
    # Check if this line is a top-level heading
    if line.startswith("## "):
        heading = line[3:].rstrip()
        if heading in sections_to_extract:
            # We found a section to extract
            # Collect the entire section until the next top-level heading or end of file
            section_lines = [line]
            j = i + 1
            while j < len(body) and not body[j].startswith("## "):
                section_lines.append(body[j])
                j += 1
            # Now we have the section from i to j-1
            section_content = "".join(section_lines)
            # Store the extracted content
            extracted[heading] = section_content
            # In the new body, we add a pointer line
            # Convert heading to a filename: lowercase, replace spaces and em-dash with underscores, remove punctuation
            fname = heading.lower()
            fname = re.sub(r'[^\w\s-]', '', fname)  # remove punctuation
            fname = re.sub(r'[-\s]+', '_', fname)   # collapse spaces and hyphens to underscore
            fname = fname.strip('_')
            # Ensure it's not empty
            if not fname:
                fname = "extracted_section"
            # Add a pointer line
            new_body.append(f"See references/{fname}.md for details.\n")
            # Skip the lines we've processed
            i = j
        else:
            # This is a heading we keep
            new_body.append(line)
            i += 1
    else:
        new_body.append(line)
        i += 1

# Write the extracted sections to references/
refs_dir = skill_dir / "references"
refs_dir.mkdir(exist_ok=True)
for heading, content in extracted.items():
    fname = heading.lower()
    fname = re.sub(r'[^\w\s-]', '', fname)
    fname = re.sub(r'[-\s]+', '_', fname)
    fname = fname.strip('_')
    if not fname:
        fname = "extracted_section"
    ref_file = refs_dir / f"{fname}.md"
    ref_file.write_text(content, encoding="utf-8")
    print(f"Extracted '{heading}' to {ref_file}")

# Write the new SKILL.md
new_content = "".join(frontmatter + new_body)
skill_md.write_text(new_content, encoding="utf-8")
print(f"Rewritten {skill_md}")

# Now update the support file map
support_map = refs_dir / "finch-support-map.md"
# We'll append new entries for each extracted section
with open(support_map, "a", encoding="utf-8") as f:
    f.write("\n")
    for heading in sections_to_extract:
        fname = heading.lower()
        fname = re.sub(r'[^\w\s-]', '', fname)
        fname = re.sub(r'[-\s]+', '_', fname)
        fname = fname.strip('_')
        if not fname:
            fname = "extracted_section"
        # Determine a reasonable "When to read" based on the section
        when = ""
        if heading == "Workflow — the core loop":
            when = "Before writing a `degraded:`/\"absent\"/\"0 errors\" verdict, or any count you will report as complete"
        elif heading == "Manual run, commands, recovery":
            when = "Before executing any finch:work task, and before honouring a prescribed fix"
        elif heading == "Cron-worker shell blocks (Tirith) — adapt, do not retry":
            when = "During finch:scan when evaluating cron job commands"
        elif heading == "Storage & behavioral directives":
            when = "When inspecting data directories or skill package structure"
        else:
            when = "For details on this section"
        f.write(f"|| `references/{fname}.md` | {when} |\n")
print(f"Updated {support_map}")