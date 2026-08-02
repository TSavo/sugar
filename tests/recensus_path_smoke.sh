#!/usr/bin/env bash
# Static teeth for recensus-path-smoke walls (no full measure — CI runs that).
set -euo pipefail
repo="${1:?usage: recensus_path_smoke.sh REPO_ROOT}"
script="$repo/implementations/python/sugar-lift-py-tests/scripts/recensus_path_smoke.py"
disc="$repo/implementations/python/sugar-lift-py-tests/scripts/recensus_path_smoke_discrimination.py"
wf="$repo/.github/workflows/recensus-path-smoke.yml"
fixtures="$repo/implementations/python/sugar-lift-py-tests/fixtures/recensus_path_smoke"
cm="$repo/tools/commit_measurement.py"

fail() { echo "FAIL: $*" >&2; exit 1; }

[[ -f "$script" ]] || fail "missing $script"
[[ -f "$disc" ]] || fail "missing discrimination runner $disc"
[[ -f "$wf" ]] || fail "missing workflow $wf"
[[ -d "$fixtures" ]] || fail "missing fixtures"

grep -Fq 'SCOREBOARD_AUTHORITY = False' "$script" || fail 'smoke must declare SCOREBOARD_AUTHORITY = False'
grep -Fq 'recensus-path-smoke' "$script" || fail 'smoke must enroll as recensus-path-smoke'
grep -Fq 'PATH_OK' "$script" || fail 'smoke must emit PATH_OK'
grep -Fq 'PATH_UNMEASURED' "$script" || fail 'smoke must treat crash as PATH_UNMEASURED'
grep -Fq 'R_construction_panics' "$script" || fail 'smoke must name forbidden product key to refuse it'
# Must not assign product panics field onto path body construction.
if grep -E '^\s*"R_construction_panics"\s*:' "$script"; then
  fail 'smoke script must not construct R_construction_panics product field'
fi

# Plantable lies — without these the negative arm cannot be re-run in CI.
grep -Fq 'RECENSUS_PATH_SMOKE_LIE' "$script" || fail 'smoke must accept RECENSUS_PATH_SMOKE_LIE for discrimination'
for lie in constructed_zero swallow_panic drop_opaque crash_mid; do
  grep -Fq "$lie" "$script" || fail "smoke must plant lie=$lie"
  grep -Fq "$lie" "$disc" || fail "discrimination runner must name arm=$lie"
done
grep -Fq 'known_constructed' "$disc" || fail 'disc must expect known_constructed tooth'
grep -Fq 'known_panic' "$disc" || fail 'disc must expect known_panic tooth'
grep -Fq 'unconstructed_residual' "$disc" || fail 'disc must expect unconstructed_residual tooth'
grep -Fq 'crash_not_green' "$disc" || fail 'disc must expect crash_not_green tooth'
grep -Fq 'PATH_UNMEASURED' "$disc" || fail 'disc must expect PATH_UNMEASURED for crash_mid'

# Fixtures (mr_blue plants + panic host)
for f in planted_constructed_with.py planted_opaque_with.py planted_clean.py planted_panic_host.py; do
  [[ -f "$fixtures/$f" ]] || fail "missing plant $f"
done

# Workflow honesty + enrollment + discrimination phase (every commit re-proves bite)
grep -Fq 'recensus-path-smoke' "$wf" || fail 'workflow must name recensus-path-smoke'
grep -Fq 'NOT measure Class B' "$wf" || grep -Fq 'Does NOT measure' "$wf" \
  || fail 'workflow header must state coverage honesty'
grep -Fq 'recensus_path_smoke_discrimination.py' "$wf" \
  || fail 'workflow must run discrimination runner (green-only teeth are decoration)'
grep -Fq 'control-effect-recensus' "$wf" || true  # may appear in prose as "not that"
# Live job name must not be bare control-effect-recensus
if grep -E 'name: control-effect recensus' "$wf"; then
  fail 'smoke workflow must not use control-effect recensus job name'
fi

# CommitMeasurement must refuse smoke as panics candidate
grep -Fq 'recensus-path-smoke' "$cm" || fail 'commit_measurement must know recensus-path-smoke'
grep -Fq 'recensus-path-smoke-verdict' "$cm" || fail 'commit_measurement must refuse smoke kind'

echo 'PASS: recensus-path-smoke walls (static + discrimination enrollment)'
