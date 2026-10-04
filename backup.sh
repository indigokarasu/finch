#!/usr/bin/env bash
# Backup current state
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cp "$HERE/SKILL.md" "$HERE/SKILL.md.pre-grind-backup"