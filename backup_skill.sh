#!/usr/bin/env bash
# Backup SKILL.md
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cp "$HERE/SKILL.md" "$HERE/SKILL.md.backup-$(date +%s)"