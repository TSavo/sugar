#!/usr/bin/env bash
# The package suite, the solver twins, the source-tree tests and the
# sugar-lift-python-source tests of the main scorecard (#8416).
#
#   main_scorecard_suite.sh plan        every file, packed into bins (the shards)
#   main_scorecard_suite.sh run <w>     worker w: its lanes claim bins until none is left
#   main_scorecard_suite.sh post        post the suite, twins, tree and source numbers
#
# WORKERS CLAIM BINS FROM ONE QUEUE (#8416, run 43946664351: wall 1919s)
#
# The fast lane has three runners on one 32-thread host. Eight fixed shards
# (~420s each, four pytests in a row, one process at a time) ran in three
# waves behind the rust and federation jobs, so the row waited for
# 8 x 420s / 3 runners plus whatever went wrong on the last shard of the
# slowest runner: shard 5 lost 320s to a fault-signal rerun of its whole
# suite pytest, shard 2 waited 208s for the release binary federation was
# building, and one runner finished 8 minutes before the other. Now the plan
# cuts the files into population-pure bins of about SUITE_BIN_SECONDS of
# measured cost (one pytest each, longest first, <plan>/queue.txt), and each
# worker job runs SUITE_LANES lanes in parallel; a lane claims the next
# unclaimed bin (an atomic mkdir under <plan>/claims/attempt-<n>, in the cache
# directory every runner shares) and runs it, until the queue is empty. A
# slow bin or a fault rerun costs only its own lane one bin; the runners
# finish within about one bin of each other; and every runner does its
# checkout, environment and binary resolution once, not once per shard.
#
# A bin's results are <results>/<population>/shard-<ii>.json and .exit, as a
# shard's were, so `post` and main_scorecard_shard_plan.py check are the same:
# a bin no lane ran, or whose pytest did not run its tests, makes its
# population `incomplete:`. The worker that ran such a bin fails, and "re-run
# failed jobs" starts a new attempt whose claims are fresh: it runs every bin
# without a measured result (exit 0, 1 or 5 and a summary) and nothing else.
#
# Lanes share the worker's checkout; each has its own TMPDIR (/tmp/sc-lane-<n>), and each bin
# its own log (scorecard-logs/bin-<ii>.<population>.log) and twin evidence
# directory (twin-evidence/bin-<ii>).
#
# THE SOURCE TREE'S TESTS ARE THEIR OWN NUMBER
#
# The 183 test files under implementations/python/sugar-source-tree/tests ran
# in no CI job, so a stale test there was invisible. They are the `tree`
# population: packed by measured cost into their own bins on the same queue
# as the suite (no serial job), each bin its own pytest, and posted as
# `tree=P/T`, so `suite=` keeps counting exactly the
# files it always counted. The tree runs under its own package config
# (-c sugar-source-tree/pyproject.toml: its pythonpath, prepend import mode,
# so its sibling helper modules import), not implementations/python/pytest.ini
# (importlib mode), with the rootdir kept at implementations/python.
# Each tree bin's pytest has a wall budget (TREE_SHARD_BUDGET_SECONDS,
# default 900): a hung tree test is interrupted (SIGINT, so pytest prints
# where it was) and the tree is marked incomplete, while every other bin's
# results still count.
#
# THE LIFTER PACKAGE'S TESTS ARE THEIR OWN NUMBER TOO
#
# The 114 test files under implementations/python/sugar-lift-python-source/tests
# ran only under `make test-python`, which no workflow calls. They are the
# `source` population, the same way as the tree: packed by measured cost into
# their own bins on the same queue, each bin's pytest under
# SOURCE_SHARD_BUDGET_SECONDS (default 900), posted as `source=P/T`. The
# package has no pytest table of its own, so `make test-python`'s pytest in
# the package directory resolves implementations/python/pytest.ini (importlib
# mode, rootdir implementations/python); the shard names that same config
# (-c pytest.ini). Its tests/conftest.py pins the package's src, its sibling
# srcs and its tests directory on sys.path (tests/checkout_resolution.py), so
# its helper modules import. The two twin files in that package are counted
# from the source results (<plan>/twins-in-source.txt), not run twice.
#
# WHY ONE POOL
#
# The twins were a separate 20-minute job (564 tests in one pytest) that
# re-ran the 50 twin files the suite shards had already run, and the suite's
# 8 shards were cut by equal file counts (2 to 17 minutes each). Now:
#
# * The twins number is the suite's own results for the twin files in the
#   suite tree (scorecard_carry.py summarize --filtered/--only-files), plus
#   the twin files outside the suite tree, which run once, as `twins`, in
#   their own bins.
# * The plan packs every file into bins of SUITE_BIN_SECONDS by measured
#   cost (tools/main_scorecard_shard_plan.py on the LPT prior in
#   $SCORECARD_CACHE/lpt-file-costs and the path-keyed seconds in the
#   ledger, which every pytest here refreshes); see WORKERS CLAIM BINS above.
#
# NOTHING IS CARRIED (#8416): every file of the plan runs on every run. The
# carry recorder (sys.monitoring re-instrumenting live bytecode per test)
# carried nothing and was the prime suspect for the shards' segfaults; it is
# deleted (tools/scorecard_carry.py).
#
# Every shard reads the plan from $SCORECARD_CACHE/runs/plan-$GITHUB_RUN_ID
# (the cache directory every runner shares), so a re-run shard reads the
# same plan, and writes its pytest summaries (and pytest's exit status) under
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
#
# A FAULT SIGNAL IS RUN ONCE MORE (run 43881434709, #8416)
#
# Five SIGSEGVs in these lanes (runs 43832361876, 43841836171, 43881434709
# and two canonical-suite shards) hit five unrelated sites: pathlib's
# _parse_path under a 1,421-path sort, inspect.getfile while pytest formats
# a failure, a pure-Python string loop in a process whose only native module
# was _cffi_backend, nodes._child_edges, spans.line_col. Every faulthandler
# stack is whole and shallow (46-55 frames, none elided): no recursion was
# under way, the recursion limit is never raised in these processes, and the
# one other thread (engine_log's watchdog) was asleep in time.sleep each
# time. That is the signature #5932 measured and traced to this host's
# CPU (the i9-13900K's boost instability, which a 53x clock cap stopped), not
# a code path, and no change to the code under test can prevent it. What
# the lane can guarantee is that one fault never leaves the shard's other
# tests unmeasured: a pytest killed by SIGILL, SIGBUS or SIGSEGV runs once
# more in a fresh process, its crash log kept as <label>.crash.log and
# uploaded. The crashed process wrote no summary, so nothing is merged; a
# second fault leaves the shard incomplete as before, so a crash the code
# does cause (it recurs) is never hidden. A timeout or a kill is not rerun.
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
  rm -rf "$results" "$plan/claims"
  mkdir -p "$results/suite" "$results/twins" "$results/tree" "$results/source" "$plan"
  rm -f "$plan"/shard-*.txt "$plan/shards.json" "$plan/queue.txt"
  cd "$py"
  python "$repo/tools/python_package_suite_shards.py" \
    --repo-root "$repo" --shard-count 1 --shard-index 0 \
    --emit-paths-for-cwd > "$plan/suite-paths.txt"
  python "$repo/tools/python_package_suite_shards.py" \
    --repo-root "$repo" --tests-rel implementations/python/sugar-source-tree/tests \
    --shard-count 1 --shard-index 0 \
    --emit-paths-for-cwd > "$plan/tree-paths.txt"
  python "$repo/tools/python_package_suite_shards.py" \
    --repo-root "$repo" --tests-rel implementations/python/sugar-lift-python-source/tests \
    --shard-count 1 --shard-index 0 \
    --emit-paths-for-cwd > "$plan/source-paths.txt"
  # Every test file that drives a source through the real solver. A twin in
  # the suite, the source tree or the lifter package is counted from that
  # population's results; only the twins outside all three run as `twins`.
  git grep -l run_source_through_real_solver -- '*/tests/test_*.py' \
    > "$plan/twins-paths.txt" || true
  grep -Fxf "$plan/suite-paths.txt" "$plan/twins-paths.txt" > "$plan/twins-in-suite.txt" || true
  grep -Fxf "$plan/tree-paths.txt" "$plan/twins-paths.txt" > "$plan/twins-in-tree.txt" || true
  grep -Fxf "$plan/source-paths.txt" "$plan/twins-paths.txt" > "$plan/twins-in-source.txt" || true
  cat "$plan/twins-in-suite.txt" "$plan/twins-in-tree.txt" "$plan/twins-in-source.txt" \
    > "$plan/twins-counted.txt"
  grep -Fvxf "$plan/twins-counted.txt" "$plan/twins-paths.txt" > "$plan/twins-extra.txt" || true
  echo "suite files: $(count_lines "$plan/suite-paths.txt");" \
    "tree files: $(count_lines "$plan/tree-paths.txt");" \
    "source files: $(count_lines "$plan/source-paths.txt");" \
    "twin files: $(count_lines "$plan/twins-paths.txt")" \
    "($(count_lines "$plan/twins-in-suite.txt") counted from the suite's results," \
    "$(count_lines "$plan/twins-in-tree.txt") from the tree's," \
    "$(count_lines "$plan/twins-in-source.txt") from the source's," \
    "$(count_lines "$plan/twins-extra.txt") outside all three)"
  python "$repo/tools/main_scorecard_shard_plan.py" pack --cwd "$py" \
    --suite "$plan/suite-paths.txt" --twins "$plan/twins-extra.txt" \
    --tree "$plan/tree-paths.txt" --source "$plan/source-paths.txt" \
    --bin-seconds "${SUITE_BIN_SECONDS:-150}" --out "$plan" --ledger "$ledger"
  echo "files to run: $(( $(count_lines "$plan/suite-paths.txt") + $(count_lines "$plan/twins-extra.txt") + $(count_lines "$plan/tree-paths.txt") + $(count_lines "$plan/source-paths.txt") ))" \
    "in $(count_lines "$plan/queue.txt") bins"
}

run_pytest() {
  # run_pytest <label (the population)> <list> <summary> <log> <budget seconds, 0 = none> [pytest args...];
  # returns 1 when pytest did not run its tests (exit other than 0 passed,
  # 1 failed, 5 no tests collected).
  local label="$1" name="$1${BIN_TAG:+ bin $BIN_TAG}" list="$2" summary="$3" log="$4" budget="$5" rc
  shift 5
  local -a paths=() limit=()
  [ -f "$list" ] && mapfile -t paths < "$list"
  echo "$name files to run: ${#paths[@]}"
  [ "${#paths[@]}" -gt 0 ] || return 0
  # Over budget: SIGINT, so pytest reports where it was and writes its
  # summary (exit 2); KILL a minute later if it does not stop. timeout exits 124.
  if [ "$budget" -gt 0 ]; then limit=(timeout -s INT -k 60 "$budget"); fi
  # A test file that fails to import is one failing file, never a lost shard:
  # without --continue-on-collection-errors one ImportError stops pytest
  # before any test runs ("Interrupted: 1 error during collection", exit 2),
  # and the shard's every other file goes unmeasured (main 3ff7cff91 lost
  # source shards 0, 3, 5 and 7 that way). With it pytest runs the rest and
  # exits 1; the summary names the file under collectionErrors, and
  # scorecard_carry.py summarize counts each one as a failing test.
  local attempt
  for attempt in 1 2; do
    PYTHONFAULTHANDLER=1 PYTHONPATH="$repo/tools:$PYTHONPATH" \
      "${limit[@]}" python -m pytest "${paths[@]}" -v \
      --continue-on-collection-errors \
      -p no:cacheprovider -p no:randomly \
      -p scorecard_carry_pytest \
      --carry-label "$label" --carry-summary "$summary" \
      "$@" \
      > "$log" 2>&1
    rc=$?
    # A fault signal (SIGILL 132, SIGBUS 135, SIGSEGV 139) at a site no
    # code path explains is run once more in a fresh process (see A FAULT
    # SIGNAL IS RUN ONCE MORE above): the crashed process wrote no summary,
    # so nothing is merged or carried. Its log is kept beside the rerun's.
    # A second fault leaves the shard incomplete below, never retried again.
    case "$rc" in
      132 | 135 | 139) ;;
      *) break ;;
    esac
    [ "$attempt" -eq 1 ] || break
    mv "$log" "${log%.log}.crash.log"
    echo "::warning::$name pytest killed by signal $((rc - 128)) in: $(grep -a -m1 'Fatal Python error' "${log%.log}.crash.log" || echo '(no faulthandler dump in the log)'); running it once more in a fresh process (crash log: $(basename "${log%.log}.crash.log"))"
    awk '/^Current thread/ { on = 1 } on && /^$/ { exit } on' "${log%.log}.crash.log"
  done
  echo "$rc" > "${summary%.json}.exit"
  echo "$name pytest exit $rc"
  grep -a 'SCORECARD CARRY' "$log"
  case "$rc" in
    0 | 1 | 5) return 0 ;;
  esac
  if [ "$rc" -eq 124 ]; then
    echo "::error::$name pytest ran past its ${budget}s wall budget and was interrupted; the last -v line before KeyboardInterrupt in $(basename "$log") is the test it was running"
  fi
  if [ "$rc" -gt 128 ]; then
    # Killed by a signal: the test it was running is the -v line the
    # faulthandler dump interrupts; the crashing thread's stack follows.
    echo "::error::$name pytest killed by signal $((rc - 128)) in: $(grep -a -m1 'Fatal Python error' "$log" || echo '(no faulthandler dump in the log)')"
    awk '/^Current thread/ { on = 1 } on && /^$/ { exit } on' "$log"
  fi
  echo "::error::$name pytest exit $rc: this bin's tests did not run (full log in the uploaded $(basename "$log")); the row marks $label incomplete"
  return 1
}

bin_population() {
  # The population of bin <tag>: the one list the plan wrote for it.
  local p
  for p in suite twins tree source; do
    if [ -s "$plan/shard-$1.$p.txt" ]; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

bin_measured() {
  # bin_measured <tag> <population>: an earlier attempt left a summary and an
  # exit status after which its tests ran (0 passed, 1 failed, 5 none collected).
  [ -f "$results/$2/shard-$1.json" ] && grep -qxE '0|1|5' "$results/$2/shard-$1.exit" 2>/dev/null
}

run_bin() {
  # run_bin <tag> <population>: one pytest over the bin's files.
  local tag="$1" pop="$2" budget=0 t0=$SECONDS rc=0
  local -a config=()
  case "$pop" in
    # The source tree under its own package config, with a wall budget. The
    # rootdir stays implementations/python (the cwd) so node IDs are
    # sugar-source-tree/tests/... like the plan's paths (the ledger, the cost
    # prior and the twins' file filter key on them); the config's pythonpath
    # entries resolve against the config file's own directory.
    tree)
      budget="${TREE_SHARD_BUDGET_SECONDS:-900}"
      config=(-c sugar-source-tree/pyproject.toml --rootdir .)
      ;;
    # The lifter package's tests, under the config `make test-python`
    # resolves for them (implementations/python/pytest.ini: the package has
    # no pytest table), with their own wall budget; node IDs are
    # sugar-lift-python-source/tests/... like the plan's paths.
    source)
      budget="${SOURCE_SHARD_BUDGET_SECONDS:-900}"
      config=(-c pytest.ini --rootdir .)
      ;;
  esac
  # This bin's results from an earlier attempt are replaced, never kept.
  rm -f "$results/$pop/shard-$tag".*
  # Each twin keeps its source, lift doc and prove doc here; uploaded with
  # the logs so a failing twin is diagnosed from CI's artifact.
  export SUGAR_WITNESS_EVIDENCE_DIR="$repo/twin-evidence/bin-$tag"
  BIN_TAG="$tag"
  run_pytest "$pop" "$plan/shard-$tag.$pop.txt" "$results/$pop/shard-$tag.json" \
    "$repo/scorecard-logs/bin-$tag.$pop.log" "$budget" "${config[@]}" || rc=1
  echo "SCORECARD BIN shard=$tag population=$pop wall_s=$((SECONDS - t0)) lane=$LANE rc=$rc"
  return "$rc"
}

run_lane() {
  # run_lane <lane>: claim the next unclaimed bin of the queue (longest
  # first) and run it, until every bin is claimed. Runs in its own subshell.
  LANE="$1"
  local claims="$plan/claims/attempt-${GITHUB_RUN_ATTEMPT:-1}" index tag pop status=0 ran=0
  local -a queue=()
  mapfile -t queue < "$plan/queue.txt"
  # Its own temp root (pytest's basetemp and every mkdtemp), kept short.
  export TMPDIR="/tmp/sc-lane-$LANE"
  rm -rf "$TMPDIR"
  mkdir -p "$TMPDIR"
  for index in "${queue[@]}"; do
    [ -n "$index" ] || continue
    tag="$(printf '%02d' "$index")"
    if ! pop="$(bin_population "$tag")"; then
      echo "::error::no file list for bin $tag in $plan"
      status=1
      continue
    fi
    # A re-run attempt runs only what no earlier attempt measured.
    bin_measured "$tag" "$pop" && continue
    mkdir "$claims/bin-$tag" 2>/dev/null || continue
    echo "${WORKER:-?}/$LANE" > "$claims/bin-$tag/by"
    run_bin "$tag" "$pop" || status=1
    ran=$((ran + 1))
  done
  echo "SCORECARD LANE worker=${WORKER:-?} lane=$LANE bins_run=$ran status=$status"
  return "$status"
}

cmd_run() {
  WORKER="$1"
  local lanes="${SUITE_LANES:-2}" lane pid status=0
  local -a pids=()
  if [ ! -f "$plan/shards.json" ] || [ ! -f "$plan/queue.txt" ]; then
    echo "::error::no plan (shards.json, queue.txt) in $plan"
    exit 1
  fi
  mkdir -p "$results/suite" "$results/twins" "$results/tree" "$results/source" \
    "$plan/claims/attempt-${GITHUB_RUN_ATTEMPT:-1}"
  # Logs and twin evidence are this run's only (the self-hosted workspace persists).
  rm -rf "$repo/scorecard-logs" "$repo/twin-evidence"
  mkdir -p "$repo/scorecard-logs" "$repo/twin-evidence"
  cd "$py"
  if [ -s "$plan/queue.txt" ]; then
    SUGAR_BIN="$("$repo/bin/sugarbin" --profile release)"
    export SUGAR_BIN
  fi
  for ((lane = 0; lane < lanes; lane++)); do
    run_lane "$lane" &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do
    wait "$pid" || status=1
  done
  echo "SCORECARD WORKER worker=$WORKER lanes=$lanes status=$status"
  return "$status"
}

cmd_post() {
  cd "$repo"
  local -a filtered=()
  local f
  for f in "$results"/suite/*.json "$results"/tree/*.json "$results"/source/*.json; do
    [ -f "$f" ] && filtered+=(--filtered "$f")
  done
  python3 tools/scorecard_carry.py summarize --label suite \
    --out "$RUNNER_TEMP/suite-totals.json" \
    --result "$RUNNER_TEMP/suite-result.json" \
    "$results"/suite/*.json
  python3 tools/scorecard_carry.py summarize --label tree \
    --out "$RUNNER_TEMP/tree-totals.json" \
    --result "$RUNNER_TEMP/tree-result.json" \
    "$results"/tree/*.json
  python3 tools/scorecard_carry.py summarize --label source \
    --out "$RUNNER_TEMP/source-totals.json" \
    --result "$RUNNER_TEMP/source-result.json" \
    "$results"/source/*.json
  python3 tools/scorecard_carry.py summarize --label twins \
    --out "$RUNNER_TEMP/twins-totals.json" \
    --result "$RUNNER_TEMP/twins-result.json" \
    --only-files "$plan/twins-counted.txt" "${filtered[@]}" \
    "$results"/twins/*.json
  # A planned shard that left no results makes its measure unmeasured.
  python3 tools/main_scorecard_shard_plan.py check --plan "$plan" --results "$results" \
    --result "suite=$RUNNER_TEMP/suite-result.json" \
    --result "twins=$RUNNER_TEMP/twins-result.json" \
    --result "tree=$RUNNER_TEMP/tree-result.json" \
    --result "source=$RUNNER_TEMP/source-result.json" \
    --ledger "$ledger"
  python3 tools/main_scorecard_post.py --runs "$SCORECARD_RUNS" \
    --put "suite=$RUNNER_TEMP/suite-result.json" \
    --put "twins=$RUNNER_TEMP/twins-result.json" \
    --put "tree=$RUNNER_TEMP/tree-result.json" \
    --put "source=$RUNNER_TEMP/source-result.json"
}

case "${1:-}" in
  plan) cmd_plan ;;
  run) cmd_run "${2:?shard index}" ;;
  post) cmd_post ;;
  *) echo "usage: $0 plan | run <i> | post" >&2; exit 2 ;;
esac
