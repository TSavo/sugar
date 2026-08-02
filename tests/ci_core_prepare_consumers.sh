#!/usr/bin/env bash
# R_ci_prepare_dead_edge: after #7019 (light core unhooked), the remaining
# defect is the prepare JOB itself and dead warms (coretests_sweep).
# Live consumers self-warm via bin/sugarbin + single-flight.
set -euo pipefail

repo="${1:?usage: ci_core_prepare_consumers.sh REPO_ROOT}"
ci="$repo/.github/workflows/ci.yml"
[[ -f "$ci" ]] || { echo "missing $ci" >&2; exit 1; }

fail() { echo "FAIL: $*" >&2; exit 1; }

# Strip comments so narrative about the deleted edge does not fail the tooth.
live="$(grep -vE '^\s*#' "$ci" || true)"

# Dead warm: coretests_sweep only serves Makefile coretests-invariants.
if grep -Eq 'coretests_sweep' <<<"$live"; then
  fail 'ci.yml still warms or references coretests_sweep on the live path'
fi

# Shared prepare job and needs: edges must stay gone.
if grep -Eq '^[[:space:]]+name: shared Rust build[[:space:]]*$' <<<"$live"; then
  fail 'ci.yml reintroduced shared Rust prepare job'
fi
if grep -Eq '^[[:space:]]+needs:[[:space:]]*prepare[[:space:]]*$|^[[:space:]]+needs:[[:space:]]*\[prepare' <<<"$live"; then
  fail 'ci.yml reintroduced needs: prepare serialization'
fi

# Light instruments still present and independent.
for target in check-lift-refusal-vocabulary check-fleet-claim-contract \
  test-python-format test-claim-mass-tripwires; do
  grep -Fq "$target" "$ci" || fail "core matrix missing $target"
done

# Shelf consumers self-warm (no prepare gate).
grep -Fq 'self-attest' "$ci" || fail 'self-attest missing'
grep -Fq 'test-showcases' "$ci" || fail 'showcases missing'
grep -Fq 'core-shelf' "$ci" || fail 'core-shelf job missing'

echo 'PASS: R_ci_prepare_dead_edge — no prepare job, no dead warm, no needs:prepare'
