#!/usr/bin/env bash
# The package suite and the solver twins of the main scorecard (#8416).
#
#   main_scorecard_suite.sh plan        which files run, packed onto shards
#   main_scorecard_suite.sh run <i>     run shard i's files
#   main_scorecard_suite.sh post        post the suite and twins numbers
#
# WHY ONE POOL
#
# The twins were a separate 20-minute job (564 tests in one pytest) that
# re-ran the 50 twin files the suite shards had already run, and the suite's
# 8 shards were cut by equal file counts (2 to 17 minutes each). Now:
#
# * The twins number is the suite's own results for the twin files in the
#   suite tree (scorecard_carry.py summarize --filtered/--only-files), plus
#   the twin files outside the suite tree, which run once, as `twins`, on
#   whichever shard the plan puts them.
# * The plan packs every file that must run onto the shards by measured cost
#   (tools/main_scorecard_shard_plan.py on the LPT prior in
#   $SCORECARD_CACHE/lpt-file-costs, which every pytest here refreshes).
#
# Every shard reads the plan from $SCORECARD_CACHE/runs/plan-$GITHUB_RUN_ID
# (the cache directory every runner shares), so a re-run shard reads the
# same plan. `set +e` where pytest may exit nonzero on purpose (#8293).
set -uo pipefail

repo="$GITHUB_WORKSPACE"
py="$repo/implementations/python"
plan="$SCORECARD_CACHE/runs/plan-$GITHUB_RUN_ID"
export SUGAR_LPT_PRIOR_DIR="${SUGAR_LPT_PRIOR_DIR:-$SCORECARD_CACHE/lpt-file-costs}"

count_lines() {
  local n
  n="$(grep -c . "$1" 2>/dev/null)" || true
  echo "${n:-0}"
}

cmd_plan() {
  set -e
  mkdir -p "$SCORECARD_RUNS/suite" "$SCORECARD_RUNS/twins" "$plan"
  rm -f "$plan"/shard-*.txt
  cd "$py"
  python "$repo/tools/python_package_suite_shards.py" \
    --repo-root "$repo" --shard-count 1 --shard-index 0 \
    --emit-paths-for-cwd > "$plan/suite-paths.txt"
  # Every test file that drives a source through the real solver.
  git grep -l run_source_through_real_solver -- '*/tests/test_*.py' \
    > "$plan/twins-paths.txt" || true
  grep -Fxf "$plan/suite-paths.txt" "$plan/twins-paths.txt" > "$plan/twins-in-suite.txt" || true
  grep -Fvxf "$plan/suite-paths.txt" "$plan/twins-paths.txt" > "$plan/twins-extra.txt" || true
  echo "suite files: $(count_lines "$plan/suite-paths.txt");" \
    "twin files: $(count_lines "$plan/twins-paths.txt")" \
    "($(count_lines "$plan/twins-in-suite.txt") counted from the suite's results," \
    "$(count_lines "$plan/twins-extra.txt") outside the suite tree)"
  python "$repo/tools/scorecard_carry.py" suite-plan \
    --store "$SCORECARD_STORE" --label suite \
    --paths-file "$plan/suite-paths.txt" \
    --summary "$SCORECARD_RUNS/suite/plan.json" \
    --rerun-paths "$plan/suite-rerun.txt"
  python "$repo/tools/scorecard_carry.py" suite-plan \
    --store "$SCORECARD_STORE" --label twins \
    --paths-file "$plan/twins-extra.txt" \
    --summary "$SCORECARD_RUNS/twins/plan.json" \
    --rerun-paths "$plan/twins-rerun.txt"
  local n fanout shards
  n=$(( $(count_lines "$plan/suite-rerun.txt") + $(count_lines "$plan/twins-rerun.txt") ))
  if [ "$n" -gt "$SUITE_INLINE_MAX_FILES" ]; then fanout=true; shards="$SUITE_SHARD_COUNT"; else fanout=false; shards=1; fi
  python "$repo/tools/main_scorecard_shard_plan.py" --cwd "$py" \
    --suite "$plan/suite-rerun.txt" --twins "$plan/twins-rerun.txt" \
    --shard-count "$shards" --out "$plan"
  echo "rerun=$n" >> "$GITHUB_OUTPUT"
  echo "fanout=$fanout" >> "$GITHUB_OUTPUT"
  echo "files to run: $n (fan out over $shards shard(s): $fanout)"
}

run_pytest() {
  # run_pytest <label> <list> <summary> <log>
  local label="$1" list="$2" summary="$3" log="$4"
  local -a paths=()
  [ -f "$list" ] && mapfile -t paths < "$list"
  echo "$label files to run: ${#paths[@]}"
  [ "${#paths[@]}" -gt 0 ] || return 0
  PYTHONPATH="$repo/tools:$PYTHONPATH" python -m pytest "${paths[@]}" -q \
    -p no:cacheprovider -p no:randomly \
    -p scorecard_carry_pytest \
    --carry-store "$SCORECARD_STORE" --carry-label "$label" \
    --carry-summary "$summary" \
    > "$log" 2>&1
  echo "$label pytest exit $? (evidence only)"
  grep -a 'SCORECARD CARRY' "$log"
}

cmd_run() {
  local tag suite_list twins_list
  tag="$(printf '%02d' "$1")"
  suite_list="$plan/shard-$tag.suite.txt"
  twins_list="$plan/shard-$tag.twins.txt"
  if [ ! -f "$suite_list" ] || [ ! -f "$twins_list" ]; then
    echo "::error::no plan for shard $tag in $plan"
    exit 1
  fi
  mkdir -p "$SCORECARD_RUNS/suite" "$SCORECARD_RUNS/twins"
  cd "$py"
  if [ -s "$suite_list" ] || [ -s "$twins_list" ]; then
    SUGAR_BIN="$("$repo/bin/sugarbin" --profile release)"
    export SUGAR_BIN
  fi
  # Each twin keeps its source, lift doc and prove doc here; uploaded with
  # the logs so a failing twin is diagnosed from CI's artifact.
  rm -rf "$repo/twin-evidence"
  export SUGAR_WITNESS_EVIDENCE_DIR="$repo/twin-evidence"
  run_pytest suite "$suite_list" "$SCORECARD_RUNS/suite/shard-$tag.json" "$repo/suite.log"
  run_pytest twins "$twins_list" "$SCORECARD_RUNS/twins/shard-$tag.json" "$repo/twins.log"
  return 0
}

cmd_post() {
  cd "$repo"
  local -a filtered=()
  local f
  for f in "$SCORECARD_RUNS"/suite/*.json; do
    [ -f "$f" ] && filtered+=(--filtered "$f")
  done
  python3 tools/scorecard_carry.py summarize --label suite \
    --out "$RUNNER_TEMP/suite-totals.json" \
    --result "$RUNNER_TEMP/suite-result.json" \
    "$SCORECARD_RUNS"/suite/*.json
  python3 tools/scorecard_carry.py summarize --label twins \
    --out "$RUNNER_TEMP/twins-totals.json" \
    --result "$RUNNER_TEMP/twins-result.json" \
    --only-files "$plan/twins-in-suite.txt" "${filtered[@]}" \
    "$SCORECARD_RUNS"/twins/*.json
  python3 tools/main_scorecard_post.py --runs "$SCORECARD_RUNS" \
    --put "suite=$RUNNER_TEMP/suite-result.json" \
    --put "twins=$RUNNER_TEMP/twins-result.json"
}

case "${1:-}" in
  plan) cmd_plan ;;
  run) cmd_run "${2:?shard index}" ;;
  post) cmd_post ;;
  *) echo "usage: $0 plan | run <i> | post" >&2; exit 2 ;;
esac
