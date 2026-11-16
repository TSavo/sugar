#!/usr/bin/env bash
# The board measures after the fast lane (#8416).
#
# main-scorecard.yml (suite, twins, federation, rust) is the measurement that
# gates work; main-scorecard-board.yml (the pandas board, ~20 minutes on one
# runner) is not. Both run on the same three self-hosted runners, and the
# board often took a runner first, so the suite shards queued behind it. The
# board run now waits here, on a GitHub-hosted runner, until no run of
# main-scorecard.yml on this commit is queued or measuring, and only then
# asks for a self-hosted runner.
#
# measure=false when every fast-lane run on this commit was cancelled: main
# moved past this commit and the board run on the newer commit supersedes
# this one (tools/main_scorecard_supersede.sh). Otherwise measure=true,
# including when no fast-lane run on this commit appears within the grace
# period or the wait reaches its cap (the board then measures: a contended
# row, never a lost one).
#
# Usage: main_scorecard_wait_fast_lane.sh
# Env: GH_REPO, GH_TOKEN, GITHUB_SHA, GITHUB_OUTPUT.
set -uo pipefail

sha="$GITHUB_SHA"
fast="main-scorecard.yml"
grace_s="${FAST_LANE_GRACE_S:-180}"
cap_s="${FAST_LANE_WAIT_CAP_S:-7200}"
poll_s="${FAST_LANE_POLL_S:-30}"
t0=$(date +%s)

decide() {
  echo "measure=$1" >> "$GITHUB_OUTPUT"
  echo "fast-lane wait: measure=$1 (${sha:0:9}: $2; waited $(( $(date +%s) - t0 ))s)"
  exit 0
}

while :; do
  waited=$(( $(date +%s) - t0 ))
  runs="$(gh run list --repo "$GH_REPO" --workflow "$fast" --commit "$sha" \
    --limit 50 --json databaseId,status,conclusion \
    --jq '.[] | "\(.databaseId) \(.status) \(.conclusion)"')" || runs="__error__"
  if [ "$runs" = "__error__" ]; then
    echo "fast-lane wait: gh run list failed (${waited}s)"
  elif [ -z "$runs" ]; then
    if [ "$waited" -ge "$grace_s" ]; then
      decide true "no run of $fast on this commit"
    fi
  else
    active="$(printf '%s\n' "$runs" | awk '$2 != "completed" { print $1 }' | paste -sd, -)"
    if [ -z "$active" ]; then
      if printf '%s\n' "$runs" | awk '$3 != "cancelled" { found = 1 } END { exit !found }'; then
        decide true "the fast lane on this commit finished"
      fi
      decide false "every run of $fast on this commit was cancelled (superseded)"
    fi
    [ $(( waited % 300 )) -lt "$poll_s" ] && echo "fast-lane wait: run $active still measuring (${waited}s)"
  fi
  if [ "$waited" -ge "$cap_s" ]; then
    decide true "the wait reached its cap"
  fi
  sleep "$poll_s"
done
