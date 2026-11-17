#!/usr/bin/env bash
# The board measures after the fast lane (#8416); the heavy lanes measure
# one at a time.
#
# main-scorecard.yml (suite, twins, federation, rust) is the measurement that
# gates work; main-scorecard-board.yml (the pandas board, ~10 minutes on one
# runner, then the pandas lift seat) is not. Both run on the same three
# self-hosted runners, and the board often took a runner first, so the suite
# shards queued behind it. The board run now waits here, on a GitHub-hosted
# runner, until no run of main-scorecard.yml on this commit is queued or
# measuring, and only then asks for a self-hosted runner.
#
# ONE HEAVY LANE AT A TIME. The three runners share one 32-thread, 48 GB
# host. On 9c4067da8 (runs 43996546635, 43996546638) the pandas board, the
# pandas lift seat (28 files at once) and the numpy lift (12 at once) all
# started at 01:49:22Z, the moment the fast lane finished, and all three
# were cancelled together at 02:28:15-32Z, with no row posted. AFTER_WORKFLOWS
# (space-separated workflow file names) extends the wait: once the fast lane
# finished, the wait also holds until no run of each named workflow on this
# commit is queued or measuring. main-scorecard-numpy.yml names
# main-scorecard-board.yml, so numpy measures after the board and the pandas
# lift seat, never beside them.
#
# measure=false when every fast-lane run on this commit was cancelled: main
# moved past this commit and the run on the newer commit supersedes this one
# (tools/main_scorecard_supersede.sh). Otherwise measure=true, including when
# no fast-lane run on this commit appears within the grace period, no run of
# an AFTER_WORKFLOWS workflow on this commit appears within the grace period,
# or the wait reaches its cap (the lane then measures: a contended row, never
# a lost one). A cancelled or failed AFTER_WORKFLOWS run is still finished:
# only the fast lane decides measure=false.
#
# Usage: main_scorecard_wait_fast_lane.sh
# Env: GH_REPO, GH_TOKEN, GITHUB_SHA, GITHUB_OUTPUT; optional AFTER_WORKFLOWS,
#      FAST_LANE_GRACE_S, FAST_LANE_WAIT_CAP_S, FAST_LANE_POLL_S.
set -uo pipefail

sha="$GITHUB_SHA"
fast="main-scorecard.yml"
after="${AFTER_WORKFLOWS:-}"
grace_s="${FAST_LANE_GRACE_S:-180}"
cap_s="${FAST_LANE_WAIT_CAP_S:-7200}"
poll_s="${FAST_LANE_POLL_S:-30}"
t0=$(date +%s)

decide() {
  echo "measure=$1" >> "$GITHUB_OUTPUT"
  echo "fast-lane wait: measure=$1 (${sha:0:9}: $2; waited $(( $(date +%s) - t0 ))s)"
  exit 0
}

# Prints the run ids of $1 on this commit, one "id status conclusion" a line,
# or __error__ when gh fails.
runs_of() {
  gh run list --repo "$GH_REPO" --workflow "$1" --commit "$sha" \
    --limit 50 --json databaseId,status,conclusion \
    --jq '.[] | "\(.databaseId) \(.status) \(.conclusion)"' || echo "__error__"
}

# Phase 1: the fast lane.
while :; do
  waited=$(( $(date +%s) - t0 ))
  runs="$(runs_of "$fast")"
  if [ "$runs" = "__error__" ]; then
    echo "fast-lane wait: gh run list failed (${waited}s)"
  elif [ -z "$runs" ]; then
    if [ "$waited" -ge "$grace_s" ]; then
      echo "fast-lane wait: no run of $fast on this commit (${waited}s)"
      break
    fi
  else
    active="$(printf '%s\n' "$runs" | awk '$2 != "completed" { print $1 }' | paste -sd, -)"
    if [ -z "$active" ]; then
      if printf '%s\n' "$runs" | awk '$3 != "cancelled" { found = 1 } END { exit !found }'; then
        echo "fast-lane wait: the fast lane on this commit finished (${waited}s)"
        break
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

# Phase 2: every AFTER_WORKFLOWS workflow on this commit, in order.
for wf in $after; do
  t1=$(date +%s)
  while :; do
    waited=$(( $(date +%s) - t0 ))
    runs="$(runs_of "$wf")"
    if [ "$runs" = "__error__" ]; then
      echo "fast-lane wait: gh run list failed for $wf (${waited}s)"
    elif [ -z "$runs" ]; then
      if [ $(( $(date +%s) - t1 )) -ge "$grace_s" ]; then
        echo "fast-lane wait: no run of $wf on this commit (${waited}s)"
        break
      fi
    else
      active="$(printf '%s\n' "$runs" | awk '$2 != "completed" { print $1 }' | paste -sd, -)"
      if [ -z "$active" ]; then
        echo "fast-lane wait: $wf on this commit finished (${waited}s)"
        break
      fi
      [ $(( waited % 300 )) -lt "$poll_s" ] && echo "fast-lane wait: run $active of $wf still measuring (${waited}s)"
    fi
    if [ "$waited" -ge "$cap_s" ]; then
      decide true "the wait reached its cap behind $wf"
    fi
    sleep "$poll_s"
  done
done

if [ -n "$after" ]; then
  decide true "the fast lane and $after on this commit finished"
fi
decide true "the fast lane on this commit finished"
