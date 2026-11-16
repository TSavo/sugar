#!/usr/bin/env bash
# Superseded scorecard runs are cancelled (#8416).
#
# main-scorecard.yml and main-scorecard-board.yml measure the tip of main.
# With one concurrency group and cancel-in-progress false, the run on the
# FIRST commit of a merge burst kept measuring after main had moved, holding
# the self-hosted runners while the run on the head sat pending (25 minutes
# lost on 2026-11-16). Each workflow's concurrency group is now per commit,
# so a newer run is never stuck behind an older one, and every run starts
# with this script: it cancels each older run of the same workflow on main
# whose head commit is not this run's commit. A run is never cancelled by a
# run on its own commit, and never by an older run (run ids only grow).
#
# Usage: main_scorecard_supersede.sh <workflow file name>
# Env: GH_REPO, GH_TOKEN (actions: write), GITHUB_SHA, GITHUB_RUN_ID.
# Exits 0 even when gh fails: a run left uncancelled costs runner time,
# never a row.
set -uo pipefail

workflow="$1"
sha="$GITHUB_SHA"
me="$GITHUB_RUN_ID"

older="$(gh run list --repo "$GH_REPO" --workflow "$workflow" --branch main \
  --limit 100 --json databaseId,headSha,status \
  --jq ".[] | select(.status != \"completed\" and .databaseId < $me and .headSha != \"$sha\")
             | \"\(.databaseId) \(.headSha[0:9]) \(.status)\"")" || {
  echo "supersede: gh run list failed; nothing cancelled"
  exit 0
}
if [ -z "$older" ]; then
  echo "supersede: no older run of $workflow on another commit is queued or measuring"
  exit 0
fi
while read -r id head status; do
  [ -n "$id" ] || continue
  if gh run cancel "$id" --repo "$GH_REPO" >/dev/null 2>&1; then
    echo "supersede: cancelled run $id ($head, $status): main moved to ${sha:0:9}"
  else
    echo "supersede: could not cancel run $id ($head, $status); it may have just finished"
  fi
done <<< "$older"
exit 0
