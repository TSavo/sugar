#!/usr/bin/env bash
# Gate: real python/pandas kit through sugar-lsp --in-process.
#
# Same battleaxe family as the witness corpus (bcargo/brun + remote kit env).
# Arms SUGAR_REAL_KIT_LSP_REQUIRED so a skip is RED, never silent green.
# Asserts the receipt line `real-kit LSP: RAN` is present in the log.
set -euo pipefail

# brun's remote scratch is a rsync tree (often no .git). Prefer git when
# present; otherwise walk up from this script / $PWD looking for the sugar
# root markers the gate needs.
resolve_repo_root() {
  local start candidate
  if start="$(git rev-parse --show-toplevel 2>/dev/null)" && [[ -n "$start" ]]; then
    printf '%s\n' "$start"
    return 0
  fi
  candidate="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
  if [[ -f "$candidate/implementations/rust/Cargo.toml" \
     && -f "$candidate/implementations/rust/sugar-lsp/tests/real_python_kit_prove.rs" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi
  candidate="$(pwd -P)"
  if [[ -f "$candidate/implementations/rust/Cargo.toml" \
     && -f "$candidate/implementations/rust/sugar-lsp/tests/real_python_kit_prove.rs" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi
  return 1
}

repo_root="$(resolve_repo_root || true)"
if [[ -z "$repo_root" ]]; then
  echo "test-real-python-kit-lsp: cannot locate sugar repo root (need implementations/rust/Cargo.toml)" >&2
  exit 2
fi
cd "$repo_root"

log="${REAL_PYTHON_KIT_LSP_LOG:-/tmp/real-python-kit-lsp-gate.log}"

assert_ran_receipt() {
  local path="$1"
  if ! grep -q 'real-kit LSP: RAN' "$path"; then
    echo "test-real-python-kit-lsp FAIL: no 'real-kit LSP: RAN' receipt (skip is red on the gate)" >&2
    exit 1
  fi
  if grep -q 'real-kit LSP: SKIPPED' "$path"; then
    echo "test-real-python-kit-lsp FAIL: gate box emitted SKIPPED (must RUN)" >&2
    exit 1
  fi
}

# Hop to battleaxe from a Mac (same pattern as make test-showcases / witness bpytest).
if [[ "${REAL_PYTHON_KIT_LSP_ON_REMOTE:-0}" != "1" ]] \
  && [[ "$(uname -s)" != "Linux" ]] \
  && [[ "${USE_BCARGO:-1}" != "0" ]]; then
  echo "==== test-real-python-kit-lsp on battleaxe via brun ===="
  echo "battleaxe log: $log"
  set +e
  SUGAR_REAL_KIT_LSP_REQUIRED=1 bin/brun --env SUGAR_REAL_KIT_LSP_REQUIRED -- \
    env SUGAR_REAL_KIT_LSP_REQUIRED=1 REAL_PYTHON_KIT_LSP_ON_REMOTE=1 USE_BCARGO=0 \
    bash scripts/test-real-python-kit-lsp.sh \
    2>&1 | tee "$log"
  status=${PIPESTATUS[0]}
  set -e
  assert_ran_receipt "$log"
  exit "$status"
fi

export SUGAR_REAL_KIT_LSP_REQUIRED=1
echo "==== test-real-python-kit-lsp (SUGAR_REAL_KIT_LSP_REQUIRED=1) ===="

# Ensure pandas is importable on the interpreter PATH will use.
# brun/bcargo provision /tmp/sugar-bcargo-python-kit-env with pandas (Makefile).
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

# Clear make-exported -D warnings for this focused gate (unrelated dead_code
# in other crates must not block the PyCon demo path receipt).
export RUSTFLAGS="${REAL_PYTHON_KIT_LSP_RUSTFLAGS-}"

set +e
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-lsp --test real_python_kit_prove \
  -- --nocapture --test-threads=1 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
set -e

assert_ran_receipt "$log"
if [[ "$status" -ne 0 ]]; then
  exit "$status"
fi
echo "==== test-real-python-kit-lsp: PASS (RAN, not skipped) ===="
exit 0
