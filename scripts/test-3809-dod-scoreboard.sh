#!/usr/bin/env bash
# Consolidated #3809 DoD scoreboard — ONE gated, recomputable receipt.
#
# Epic DoD (issue #3809) + LSP acceptance arc:
#   (A)-(C) retired 2026-11-13: they scored prove's kit fold (`prove_from_kit`),
#           which is deleted; `sugar prove` reads `.proof` files only (step 9).
#   (D) real-kit LSP RAN: lying→UNSAT, truthful→clear
#   (E) golden NDJSON conversation byte-identical replay
#
# Extends (does not replace) the existing pieces:
#   - scripts/test-real-python-kit-lsp.sh pieces             (#3934/#3936)
#   - real_python_kit_conversation_golden                   (#3938)
#
# On battleaxe (or Linux with USE_BCARGO=0), skip is RED for the real-kit legs.
# Hop from a Mac via bin/brun (same family as witness bpytest).
set -euo pipefail

resolve_repo_root() {
  local start candidate
  if start="$(git rev-parse --show-toplevel 2>/dev/null)" && [[ -n "$start" ]]; then
    printf '%s\n' "$start"
    return 0
  fi
  candidate="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
  if [[ -f "$candidate/implementations/rust/Cargo.toml" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi
  candidate="$(pwd -P)"
  if [[ -f "$candidate/implementations/rust/Cargo.toml" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi
  return 1
}

repo_root="$(resolve_repo_root || true)"
if [[ -z "$repo_root" ]]; then
  echo "test-3809-dod-scoreboard: cannot locate sugar repo root" >&2
  exit 2
fi
cd "$repo_root"

log="${DOD_3809_SCOREBOARD_LOG:-/tmp/dod-3809-scoreboard.log}"

assert_receipts() {
  local path="$1"
  local fail=0

  # (D) real-kit LSP — must RAN, never SKIPPED on the gate
  if ! grep -q 'real-kit LSP: RAN' "$path"; then
    echo "FAIL (D): no 'real-kit LSP: RAN' (skip is red on the gate)" >&2
    fail=1
  fi
  if grep -q 'real-kit LSP: SKIPPED' "$path"; then
    echo "FAIL (D): gate emitted SKIPPED (must RUN)" >&2
    fail=1
  fi
  if ! grep -q 'UNSAT' "$path"; then
    echo "FAIL (D): no lying-twin UNSAT receipt" >&2
    fail=1
  fi
  if ! grep -qE 'truthful twin -> clear|didChange truthful diagnostics \(n=0\)' "$path"; then
    echo "FAIL (D): no truthful-twin clear receipt" >&2
    fail=1
  fi

  # (E) golden NDJSON
  if ! grep -q 'BYTE-IDENTICAL' "$path"; then
    echo "FAIL (E): no BYTE-IDENTICAL golden conversation receipt" >&2
    fail=1
  fi

  if [[ "$fail" -ne 0 ]]; then
    echo "==== #3809 consolidated DoD scoreboard: FAIL (see $path) ====" >&2
    exit 1
  fi
}

# Hop to battleaxe from a Mac (same pattern as test-real-python-kit-lsp).
if [[ "${DOD_3809_ON_REMOTE:-0}" != "1" ]] \
  && [[ "$(uname -s)" != "Linux" ]] \
  && [[ "${USE_BCARGO:-1}" != "0" ]]; then
  echo "==== test-3809-dod-scoreboard on battleaxe via brun ===="
  echo "battleaxe log: $log"
  set +e
  SUGAR_REAL_KIT_LSP_REQUIRED=1 bin/brun --env SUGAR_REAL_KIT_LSP_REQUIRED -- \
    env SUGAR_REAL_KIT_LSP_REQUIRED=1 DOD_3809_ON_REMOTE=1 USE_BCARGO=0 \
    bash scripts/test-3809-dod-scoreboard.sh \
    2>&1 | tee "$log"
  status=${PIPESTATUS[0]}
  set -e
  assert_receipts "$log"
  exit "$status"
fi

export SUGAR_REAL_KIT_LSP_REQUIRED=1
# Clear make-exported -D warnings for focused gates (unrelated dead_code).
export RUSTFLAGS="${DOD_3809_RUSTFLAGS-}"

echo "==== #3809 CONSOLIDATED DoD SCOREBOARD (SUGAR_REAL_KIT_LSP_REQUIRED=1) ===="
echo "log: $log"
echo "host: $(uname -s) $(hostname 2>/dev/null || true)"
echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# Ensure pandas for real kit + scoreboard.
if [[ -n "${BCARGO_PYTHON_VENV:-}" && -x "${BCARGO_PYTHON_VENV}/bin/python" ]]; then
  "${BCARGO_PYTHON_VENV}/bin/python" -c 'import pandas' 2>/dev/null \
    || "${BCARGO_PYTHON_VENV}/bin/python" -m pip install --quiet pandas
elif [[ -n "${PYTHON:-}" && -x "${PYTHON}" ]]; then
  "$PYTHON" -c 'import pandas' 2>/dev/null \
    || "$PYTHON" -m pip install --quiet pandas
else
  python3 -c 'import pandas' 2>/dev/null \
    || python3 -m pip install --quiet --user pandas || true
fi

set +e
{
  echo "------------------------------------------------------------"
  echo "=== (D) real-kit LSP acceptance — RAN, lie→UNSAT, truth→clear ==="
  echo "    cargo test -p sugar-lsp --test real_python_kit_prove"
  echo "------------------------------------------------------------"
  cargo test --manifest-path implementations/rust/Cargo.toml \
    -p sugar-lsp --test real_python_kit_prove \
    -- --nocapture --test-threads=1
  status_lsp=$?

  echo ""
  echo "------------------------------------------------------------"
  echo "=== (E) golden NDJSON conversation — byte-identical replay ==="
  echo "    cargo test -p sugar-lsp --test real_python_kit_conversation_golden --ignored --exact"
  echo "------------------------------------------------------------"
  cargo test --manifest-path implementations/rust/Cargo.toml \
    -p sugar-lsp --test real_python_kit_conversation_golden \
    real_python_kit_conversation_is_byte_identical_to_golden_ndjson \
    -- --ignored --exact --nocapture --test-threads=1
  status_golden=$?

  echo ""
  echo "------------------------------------------------------------"
  echo "component exit codes: lsp=$status_lsp golden=$status_golden"
  echo "------------------------------------------------------------"
} 2>&1 | tee "$log"
# PIPESTATUS of the braced group is not available after tee; re-run status from greps + last cargo via log
set -e

# Derive failure from test result lines if any component failed.
if grep -qE 'test result:.*[1-9][0-9]* failed' "$log"; then
  echo "FAIL: at least one cargo test reported failures" >&2
  assert_receipts "$log" || true
  exit 1
fi
if grep -qE '^error:|could not compile' "$log"; then
  echo "FAIL: compile error in scoreboard run" >&2
  exit 1
fi

assert_receipts "$log"

echo ""
echo "==== #3809 CONSOLIDATED DoD SCOREBOARD: PASS ===="
echo "  (D) real-kit LSP RAN — lie→UNSAT, truth→clear"
echo "  (E) golden NDJSON conversation BYTE-IDENTICAL"
echo "  full log: $log"
echo "================================================="
exit 0
