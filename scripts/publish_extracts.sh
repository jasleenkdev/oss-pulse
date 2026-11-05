#!/bin/sh
# Commit the refreshed dashboard extracts to the `data` branch.
# Usage: publish_extracts.sh <YYYY-MM-DD>
set -eu
DAY=$1
ROOT=$(pwd)
WORKTREE=$(mktemp -d)

if git fetch --quiet origin data; then
    git worktree add --quiet "$WORKTREE" -B data FETCH_HEAD
else
    git worktree add --quiet --detach "$WORKTREE"
    git -C "$WORKTREE" checkout --quiet --orphan data
    git -C "$WORKTREE" rm -rfq .
fi

mkdir -p "$WORKTREE/extracts"
cp "$ROOT"/dashboard/src/data/*.json "$WORKTREE/extracts/"
cd "$WORKTREE"
git add extracts
if git diff --cached --quiet; then
    echo "extracts unchanged, nothing to publish"
else
    git -c user.name="github-actions[bot]" \
        -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
        commit --quiet -m "data: refresh $DAY"
    git push --quiet origin HEAD:data
fi
cd "$ROOT"
git worktree remove --force "$WORKTREE"
