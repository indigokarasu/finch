#!/usr/bin/env bash
# test_rr_git_sync_retired_remote.sh — directions for the retired-remote guard.
#
# WHY THIS EXISTS: on 2026-10-01 the sync job had failure_streak=8 with
# fail=26, and every one of those 26 was a 404 on a repository that had been
# deleted on GitHub when the util-* skills were consolidated into the
# indigokarasu/utilities monorepo. The 2026-09-28 repair made fail>0 exit
# non-zero so a refused commit could raise an alert -- and a permanent,
# unfixable 404 then guaranteed that alert fired forever. The guard added
# distinguishes the two by asking whether the local repo has anything
# unpublished.
#
# Two directions, and the second is the one that keeps the first honest:
#   4. retired remote, nothing unpublished -> NOT a failure, exit 0
#   5. retired remote WITH unpublished work -> STILL a failure, fail>0
#
# A guard that only has direction 4 is a mute button. Direction 5 is what
# makes it a distinction instead of a suppression.
#
# Uses a nonexistent LOCAL path as the remote so the fixture is hermetic: git
# emits "Could not read from remote repository" for a missing local path, which
# is the same fingerprint class the script classifies as a retired remote, and
# no network is touched.
#
# EXIT 0 all pass / 1 a direction failed / 3 could not set up a fixture.
set -u
# Default to the running profile's copy, discovered rather than written out:
# the pre-commit PII gate (host_path / profile_name / denylist) refuses a
# literal host path and a concrete profile name, and a denylisted name in this
# repo's .pii-denylist. The path is the only thing that has to be generic --
# the fixture itself is hermetic and needs nothing from the host.
SCRIPT="${1:-$(ls -d "$HOME"/.hermes/profiles/*/scripts/rr_git_sync.sh 2>/dev/null | head -1)}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAILURES=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1  -- $2"; FAILURES=$((FAILURES+1)); }

[ -f "$SCRIPT" ] || { echo "SETUP FAIL: $SCRIPT not found" >&2; exit 3; }
git config --global user.email >/dev/null 2>&1 || git config --global user.email t@t
git config --global user.name  >/dev/null 2>&1 || git config --global user.name t

run_sync() { # roots_dir -> "rc|summary|verdict"
  local roots="$1"
  local out rc summary verdict
  out=$(RR_SKILL_SYNC_DIR="$WORK/no-such-skill-sync.sh" \
        RR_GIT_SYNC_ROOTS="$roots" \
        RR_GIT_SYNC_LOG="$WORK/sync.log" \
        bash "$SCRIPT" 2>&1)
  rc=$?
  summary=$(printf '%s\n' "$out" | grep -o 'clean=[0-9]* conflict=[0-9]* fail=[0-9]* retired=[0-9]*' | tail -1)
  [ -z "$summary" ] && summary=$(printf '%s\n' "$out" | grep -o 'clean=[0-9]* conflict=[0-9]* fail=[0-9]*' | tail -1)
  verdict=$(printf '%s\n' "$out" | grep -o 'VERDICT: .*' | tail -1)
  echo "$rc|${summary}|${verdict}"
}
split3() { IFS='|' read -r RC_ SUMMARY_ VERDICT_ <<< "$1"; }

# A repo whose origin does not exist, with upstream tracking and a
# remote-tracking ref that matches HEAD (so ahead=0, behind=0).
mkrepo_dead() { # name -> path
  local name="$1"
  local path="$WORK/repo-$name"
  rm -rf "$path"
  git init -q "$path"
  (
    cd "$path" || exit 1
    git config user.email t@t
    git config user.name t
    echo "$name" > f.txt
    git add -A
    git commit -q -m init
    git branch -q -M main
    git remote add origin "$WORK/gone-$name.git"   # never created
    # Upstream + a remote-tracking ref equal to HEAD, WITHOUT a successful
    # fetch. Without the ref, @{u} does not resolve and the guard would read
    # ahead=0 for the wrong reason.
    git update-ref refs/remotes/origin/main HEAD
    git config branch.main.remote origin
    git config branch.main.merge refs/heads/main
  ) >/dev/null 2>&1
  printf '%s' "$path"
}

echo "--- direction 4: a RETIRED remote with nothing unpublished is not a failure ---"
D4="$WORK/roots_retired"; mkdir -p "$D4"
p4="$(mkrepo_dead retired)"
cp -a "$p4" "$D4/"
# Precondition: the fixture really is a dead remote, and really is unpublished-
# nothing. Asserted here rather than assumed -- the first version of this test
# passed for the wrong reason because @{u} did not resolve and ahead defaulted
# to 0 on a repo that had never been pushed.
if ! git -C "$D4/repo-retired" fetch origin >/dev/null 2>&1; then
  pass "fixture precondition: origin is unreachable (retired)"
else
  fail "fixture precondition" "origin is reachable; this is not a retired-remote fixture"
fi
if [ -n "$(git -C "$D4/repo-retired" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)" ] \
   && [ "$(git -C "$D4/repo-retired" rev-list --count '@{u}'..HEAD 2>/dev/null)" = "0" ] \
   && [ "$(git -C "$D4/repo-retired" status --porcelain | wc -l)" = "0" ]; then
  pass "fixture precondition: upstream resolves, ahead=0, tree clean"
else
  fail "fixture precondition" "upstream does not resolve or the tree is not clean; direction 4 would pass for the wrong reason"
fi
split3 "$(run_sync "$D4")"
if [ "$RC_" = "0" ] && printf '%s' "$SUMMARY_" | grep -q 'fail=0' \
   && printf '%s' "$SUMMARY_" | grep -q 'retired=1'; then
  pass "retired remote -> exit 0, fail=0, retired=1   [$SUMMARY_] ${VERDICT_:-<no verdict line>}"
else
  fail "retired remote must not raise a failure" "rc=$RC_ summary='$SUMMARY_' verdict='$VERDICT_'"
fi

echo
echo "--- direction 5: a retired remote WITH unpublished work is STILL a failure ---"
D5="$WORK/roots_retired_dirty"; mkdir -p "$D5"
p5="$(mkrepo_dead stranded)"
cp -a "$p5" "$D5/"
# One unpushed commit. This is work that can never reach the remote, so the
# guard must not swallow it.
( cd "$D5/repo-stranded" && echo more >> f.txt && git add -A && git commit -q -m unpushed )
a5="$(git -C "$D5/repo-stranded" rev-list --count '@{u}'..HEAD 2>/dev/null || echo 0)"
if [ "$a5" -ge 1 ]; then
  pass "fixture precondition: 1 unpushed commit stranded on a dead remote (ahead=$a5)"
else
  fail "fixture precondition" "expected ahead>=1, got '$a5'; direction 5 cannot test anything"
fi
split3 "$(run_sync "$D5")"
if [ "$RC_" != "0" ] && printf '%s' "$SUMMARY_" | grep -q 'fail=[1-9]' \
   && printf '%s' "$SUMMARY_" | grep -q 'retired=0'; then
  pass "retired remote + unpublished work -> non-zero exit AND fail>0   rc=$RC_ [$SUMMARY_] ${VERDICT_:-}"
else
  fail "unpublished work on a dead remote must still fail" "rc=$RC_ summary='$SUMMARY_' verdict='$VERDICT_'"
fi

echo
echo "--- guard is not a mute button: the real fault still alerts alongside a retired repo ---"
D6="$WORK/roots_mixed"; mkdir -p "$D6"
cp -a "$(mkrepo_dead mixed-retired)" "$D6/retired"
# A live repo whose commit is refused, the 2026-09-28 real cause.
bare6="$WORK/rem-live.git"; rm -rf "$bare6" "$WORK/src6"
git init -q --bare "$bare6"
git clone -q "$bare6" "$WORK/src6" 2>/dev/null
( cd "$WORK/src6" && git config user.email t@t && git config user.name t \
  && echo base > f.txt && git add -A && git commit -q -m base \
  && git branch -q -M main && git push -q -u origin main 2>/dev/null )
cp -a "$WORK/src6" "$D6/live"
mkdir -p "$D6/live/.githooks"
printf '#!/bin/sh\necho "pre-commit: refusing" >&2\nexit 1\n' > "$D6/live/.githooks/pre-commit"
chmod +x "$D6/live/.githooks/pre-commit"
git -C "$D6/live" config core.hooksPath .githooks
echo changed >> "$D6/live/f.txt"
split3 "$(run_sync "$D6")"
if [ "$RC_" != "0" ] && printf '%s' "$SUMMARY_" | grep -q 'fail=[1-9]' \
   && printf '%s' "$SUMMARY_" | grep -q 'retired=1'; then
  pass "retired repo + refused commit -> fail>0 AND retired counted separately   rc=$RC_ [$SUMMARY_]"
else
  fail "mixed run must count the real fault and separate the retired repo" "rc=$RC_ summary='$SUMMARY_' verdict='$VERDICT_'"
fi

echo
if [ "$FAILURES" -eq 0 ]; then echo "ALL DIRECTIONS PASS"; exit 0; fi
echo "$FAILURES direction(s) failed"; exit 1
