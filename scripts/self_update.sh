#!/bin/bash
# self_update.py — OCAS self-update via gh CLI
# Checks GitHub for newer version and pulls if available.
#
# Called by ocas-finch self-update mechanism.
# Usage: python3 scripts/self_update.py

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTMATTER="$SKILL_DIR/SKILL.md"

# Extract source URL and local version from frontmatter
SOURCE_URL=$(grep "^source:" "$FRONTMATTER" | sed 's/source: *//')
LOCAL_VERSION=$(grep "^version:" "$FRONTMATTER" | sed 's/version: *"//' | sed 's/"//')

# Extract owner/repo from URL
OWNER_REPO=$(echo "$SOURCE_URL" | sed 's|https://github.com/||' | sed 's|.*github.com/||' | sed 's/\.git$//')

# Fetch remote version
REMOTE_VERSION=$(gh api "repos/$OWNER_REPO/contents/SKILL.md" --jq '.content' 2>/dev/null | base64 -d | grep '^version:' | head -1 | sed 's/version: *"//' | sed 's/"//')

if [ -z "$REMOTE_VERSION" ]; then
    echo "Could not fetch remote version"
    exit 1
fi

if [ "$REMOTE_VERSION" = "$LOCAL_VERSION" ]; then
    echo "Up to date (v$LOCAL_VERSION)"
    exit 0
fi

echo "Updating ocas-finch from v$LOCAL_VERSION to v$REMOTE_VERSION"

TMPDIR=$(mktemp -d)
gh api "repos/$OWNER_REPO/tarball/main" > "$TMPDIR/archive.tar.gz"
mkdir "$TMPDIR/extracted"
tar xzf "$TMPDIR/archive.tar.gz" -C "$TMPDIR/extracted" --strip-components=1

# Preserve archive/ and data/
cp -R "$SKILL_DIR/archive" "$TMPDIR/extracted/" 2>/dev/null || true
for d in commons/journals/ocas-finch commons/data/ocas-finch; do
    if [ -d "$HOME/.hermes/$d" ]; then
        cp -R "$HOME/.hermes/$d" "$TMPDIR/extracted/$d" 2>/dev/null || true
    fi
done

# Install (overwrite everything except git history)
rsync -a --exclude='.git' "$TMPDIR/extracted/" "$SKILL_DIR/"
rm -rf "$TMPDIR"

echo "I updated ocas-finch from version $LOCAL_VERSION to $REMOTE_VERSION"
