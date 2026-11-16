#!/usr/bin/env bash
# The hourly scheduled scorecard run measures only a head nothing else
# measured (#8416).
#
# main-scorecard.yml and main-scorecard-board.yml run on every push to main
# and once an hour. The hour measured the head of main again even when the
# push run for that head was still waiting in the concurrency group (and,
# sharing the group, replaced it: 0c85193a5, 41f6d6298) or had already posted
# its row. The scheduled run now goes through this gate first: it measures
# (measure=true) only when no other run of the same workflow on the head is
# queued or measuring and no run of it on the head posted a row on the
# scorecard issue. Push and workflow_dispatch runs never call it.
#
# Usage: main_scorecard_schedule_gate.sh <workflow file name>
# Env: GH_REPO, GH_TOKEN, GITHUB_SHA, GITHUB_RUN_ID, GITHUB_OUTPUT,
#      SCORECARD_ISSUE_TITLE.
# Writes measure=true|false to GITHUB_OUTPUT. Exits nonzero only when gh
# fails; the workflow then measures (a duplicate row, never a lost one).
set -euo pipefail

workflow="$1"
sha="$GITHUB_SHA"
me="$GITHUB_RUN_ID"

decide() {
  echo "measure=$1" >> "$GITHUB_OUTPUT"
  echo "schedule gate: measure=$1 (${sha:0:9}: $2)"
}

# Every other run of this workflow on this head, and the ones not finished.
others="$(gh run list --repo "$GH_REPO" --workflow "$workflow" --commit "$sha" \
  --limit 100 --json databaseId,status \
  --jq ".[] | select(.databaseId != $me) | \"\(.databaseId) \(.status)\"")"
active="$(printf '%s\n' "$others" | awk 'NF == 2 && $2 != "completed" { print $1 }' | paste -sd, -)"
if [ -n "$active" ]; then
  decide false "run $active of $workflow is queued or measuring this head"
  exit 0
fi
ids="$(printf '%s\n' "$others" | awk 'NF == 2 { print $1 }')"
if [ -z "$ids" ]; then
  decide true "no other run of $workflow on this head"
  exit 0
fi

# A row is the comment line `sha=<head> prev=... run=<id> ...` written by
# tools/main_scorecard_post.py; only rows of this workflow's own runs count,
# since the other scorecard workflow posts on the same issue.
issue="$(gh issue list --repo "$GH_REPO" --state open \
  --search "\"$SCORECARD_ISSUE_TITLE\" in:title" --json number,title \
  --jq "map(select(.title == \"$SCORECARD_ISSUE_TITLE\")) | .[0].number // empty")"
if [ -z "$issue" ]; then
  decide true "no open \"$SCORECARD_ISSUE_TITLE\" issue"
  exit 0
fi
since="$(gh api "repos/$GH_REPO/commits/$sha" --jq '.commit.committer.date')"
rows="$(gh api --paginate "repos/$GH_REPO/issues/$issue/comments?per_page=100&since=$since" \
  --jq '.[].body' | tr -d '\r' | grep -E "^[[:space:]]*sha=$sha " || true)"
for id in $ids; do
  if printf '%s\n' "$rows" | grep -qE "(^|[[:space:]])run=$id([[:space:]]|$)"; then
    decide false "run $id of $workflow already posted its row on #$issue"
    exit 0
  fi
done
decide true "no run of $workflow posted a row for this head on #$issue"
