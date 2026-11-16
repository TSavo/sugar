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
# same plan, and writes its carry summaries (and pytest's exit status) under
# $plan/results, which every attempt of the run shares: a shard re-run after
# a failure completes the same row. `set +e` where pytest may exit nonzero on
# purpose (#8293).
#
# A LOST SHARD IS NEVER A SMALLER TOTAL (run 43832361876)
#
# The plan writes shards.json: how many shards, and per shard how many files
# and about how many tests (the ledger of each file's last measured count).
# `post` checks every planned shard left its results
# (main_scorecard_shard_plan.py check); a shard that did not -- the job died
# before pytest, or pytest died or was interrupted -- makes the measure
# unmeasured with an `incomplete:` note, never a smaller total. A shard whose
# pytest did not run its tests fails its job, so "re-run failed jobs" redoes it.
#
# A CRASHED PYTEST NAMES ITSELF (runs 43832361876, 43841836171: exit 139)
#
# pytest runs with PYTHONFAULTHANDLER=1, so a fatal signal from interpreter
# start onward (not only after pytest's own faulthandler plugin is configured)
# dumps every thread's Python stack into the shard log, and with -v, so the
# log names each test as it starts (pytest writes and flushes the node ID
# before the test body runs): the line the crash interrupts is the test that
# was running, and the lines above it are every test the process ran first.
# A pytest killed by a signal prints that test and the crashing thread's
# stack into the job log as well; the full log is the uploaded artifact
# (`if: always()`).
set -uo pipefail

repo="$GITHUB_WORKSPACE"
py="$repo/implementations/python"
plan="$SCORECARD_CACHE/runs/plan-$GITHUB_RUN_ID"
results="$plan/results"
ledger="$SCORECARD_CACHE/file-test-counts.json"
export SUGAR_LPT_PRIOR_DIR="${SUGAR_LPT_PRIOR_DIR:-$SCORECARD_CACHE/lpt-file-costs}"

count_lines() {
  local n
  n="$(grep -c . "$1" 2>/dev/null)" || true
  echo "${n:-0}"
}

cmd_plan() {
  set -e
  rm -rf "$results"
  mkdir -p "$results/suite" "$results/twins" "$plan"
  rm -f "$plan"/shard-*.txt "$plan/shards.json"
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
    --summary "$results/suite/plan.json" \
    --rerun-paths "$plan/suite-rerun.txt"
  python "$repo/tools/scorecard_carry.py" suite-plan \
    --store "$SCORECARD_STORE" --label twins \
    --paths-file "$plan/twins-extra.txt" \
    --summary "$results/twins/plan.json" \
    --rerun-paths "$plan/twins-rerun.txt"
  local n fanout shards
  n=$(( $(count_lines "$plan/suite-rerun.txt") + $(count_lines "$plan/twins-rerun.txt") ))
  if [ "$n" -gt "$SUITE_INLINE_MAX_FILES" ]; then fanout=true; shards="$SUITE_SHARD_COUNT"; else fanout=false; shards=1; fi
  python "$repo/tools/main_scorecard_shard_plan.py" pack --cwd "$py" \
    --suite "$plan/suite-rerun.txt" --twins "$plan/twins-rerun.txt" \
    --shard-count "$shards" --out "$plan" --ledger "$ledger"
  echo "rerun=$n" >> "$GITHUB_OUTPUT"
  echo "fanout=$fanout" >> "$GITHUB_OUTPUT"
  echo "files to run: $n (fan out over $shards shard(s): $fanout)"
}

run_pytest() {
  # run_pytest <label> <list> <summary> <log>; returns 1 when pytest did not
  # run its tests (exit other than 0 passed, 1 failed, 5 nothing left to run).
  local label="$1" list="$2" summary="$3" log="$4" rc
  local -a paths=()
  [ -f "$list" ] && mapfile -t paths < "$list"
  echo "$label files to run: ${#paths[@]}"
  [ "${#paths[@]}" -gt 0 ] || return 0
  PYTHONFAULTHANDLER=1 PYTHONPATH="$repo/tools:$PYTHONPATH" \
    python -m pytest "${paths[@]}" -v \
    -p no:cacheprovider -p no:randomly \
    -p scorecard_carry_pytest \
    --carry-store "$SCORECARD_STORE" --carry-label "$label" \
    --carry-summary "$summary" \
    > "$log" 2>&1
  rc=$?
  echo "$rc" > "${summary%.json}.exit"
  echo "$label pytest exit $rc"
  grep -a 'SCORECARD CARRY' "$log"
  case "$rc" in
    0 | 1 | 5) return 0 ;;
  esac
  if [ "$rc" -gt 128 ]; then
    # Killed by a signal: the test it was running is the -v line the
    # faulthandler dump interrupts; the crashing thread's stack follows.
    echo "::error::$label pytest killed by signal $((rc - 128)) in: $(grep -a -m1 'Fatal Python error' "$log" || echo '(no faulthandler dump in the log)')"
    awk '/^Current thread/ { on = 1 } on && /^$/ { exit } on' "$log"
  fi
  echo "::error::$label pytest exit $rc: this shard's tests did not run (full log in the uploaded $(basename "$log")); the row marks $label incomplete"
  return 1
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
  mkdir -p "$results/suite" "$results/twins"
  # This shard's results from an earlier attempt are replaced, never kept.
  rm -f "$results"/suite/shard-"$tag".* "$results"/twins/shard-"$tag".*
  cd "$py"
  if [ -s "$suite_list" ] || [ -s "$twins_list" ]; then
    SUGAR_BIN="$("$repo/bin/sugarbin" --profile release)"
    export SUGAR_BIN
  fi
  # Each twin keeps its source, lift doc and prove doc here; uploaded with
  # the logs so a failing twin is diagnosed from CI's artifact.
  rm -rf "$repo/twin-evidence"
  export SUGAR_WITNESS_EVIDENCE_DIR="$repo/twin-evidence"
  local status=0
  run_pytest suite "$suite_list" "$results/suite/shard-$tag.json" "$repo/suite.log" || status=1
  run_pytest twins "$twins_list" "$results/twins/shard-$tag.json" "$repo/twins.log" || status=1
  return "$status"
}

cmd_post() {
  cd "$repo"
  local -a filtered=()
  local f
  for f in "$results"/suite/*.json; do
    [ -f "$f" ] && filtered+=(--filtered "$f")
  done
  python3 tools/scorecard_carry.py summarize --label suite \
    --out "$RUNNER_TEMP/suite-totals.json" \
    --result "$RUNNER_TEMP/suite-result.json" \
    "$results"/suite/*.json
  python3 tools/scorecard_carry.py summarize --label twins \
    --out "$RUNNER_TEMP/twins-totals.json" \
    --result "$RUNNER_TEMP/twins-result.json" \
    --only-files "$plan/twins-in-suite.txt" "${filtered[@]}" \
    "$results"/twins/*.json
  # A planned shard that left no results makes its measure unmeasured.
  python3 tools/main_scorecard_shard_plan.py check --plan "$plan" --results "$results" \
    --result "suite=$RUNNER_TEMP/suite-result.json" \
    --result "twins=$RUNNER_TEMP/twins-result.json" \
    --ledger "$ledger"
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
