#!/usr/bin/env bash
# Extract Workflow section to references/finch-workflow.md
# Extract Manual run section to references/finch-manual-run.md
# Extract Cron-worker shell blocks to references/finch-tirith.md
# Extract Storage & behavioral directives to references/finch-storage-directives.md

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$HERE"

# Create references directory if it doesn't exist
mkdir -p references

# Extract Workflow — the core loop
awk '/^## Workflow — the core loop$/,/^## [A-Z]/ {if (!/^## [A-Z]/ || /^## Workflow — the core loop$/) print}' SKILL.md > references/finch-workflow.md
echo "Extracted Workflow section"

# Extract Manual run, commands, recovery
awk '/^## Manual run, commands, recovery$/,/^## [A-Z]/ {if (!/^## [A-Z]/ || /^## Manual run, commands, recovery$/) print}' SKILL.md > references/finch-manual-run.md
echo "Extracted Manual run section"

# Extract Cron-worker shell blocks (Tirith) — adapt, do not retry
awk '/^## Cron-worker shell blocks \(Tirith\) — adapt, do not retry$/,/^## [A-Z]/ {if (!/^## [A-Z]/ || /^## Cron-worker shell blocks \(Tirith\) — adapt, do not retry$/) print}' SKILL.md > references/finch-tirith.md
echo "Extracted Tirith section"

# Extract Storage & behavioral directives
awk '/^## Storage & behavioral directives$/,/^## [A-Z]/ {if (!/^## [A-Z]/ || /^## Storage & behavioral directives$/) print}' SKILL.md > references/finch-storage-directives.md
echo "Extracted Storage directives section"

# Show sizes
wc -l references/finch-*.md