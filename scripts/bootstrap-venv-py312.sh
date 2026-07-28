#!/usr/bin/env bash
# Authenticated local inner loop: CPython 3.12.13 venv + declared corpus pins.
#
# A venv does NOT install its own interpreter. It only inherits the executable
# it was created from. Therefore:
#
#   python3 -m venv .venv-py312
#
# on a machine whose `python3` is 3.14.4 produces another 3.14.4 environment,
# regardless of the directory name. That is the environment-layer placeholder
# pattern: a label that does not name the runtime it carries.
#
# Declared pins (sugar-build.toml + sugar-lift-py-tests[test] on main):
#   python 3.12.13, numpy 2.5.1, pandas 3.0.3, pyarrow 22.0.0, pytest 9.1.1
#
# Usage (from any checkout of this repository — the script must be IN the tree):
#   bash scripts/bootstrap-venv-py312.sh
#   .venv-py312/bin/python -m pytest …
#
# Environment:
#   PYTHON312   exact 3.12.13 executable (default: search Homebrew / PATH)
#   VENV_DIR    destination (default: <repo>/.venv-py312)
#   BOOTSTRAP_CHECK_ONLY=1
#               validate the interpreter only; do not create a venv or pip install
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$repo_root"

die() {
  echo "bootstrap-venv-py312: $*" >&2
  exit 2
}

require_exact_cpython_31213() {
  local exe="$1"
  [[ -n "$exe" && -x "$exe" ]] || die "need an executable CPython 3.12.13 path"
  local ver
  ver="$("$exe" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
  # Exact triple — not 3.12.x, not a prefix. 3.12.0 and 3.12.30 both fail.
  if [[ "$ver" != "3.12.13" ]]; then
    die "required exact CPython 3.12.13; observed $ver at $exe"
  fi
}

py312="${PYTHON312:-}"
if [[ -z "$py312" ]]; then
  for candidate in \
    /usr/local/opt/python@3.12/bin/python3.12 \
    /usr/local/bin/python3.12 \
    /opt/homebrew/bin/python3.12 \
    "$(command -v python3.12 2>/dev/null || true)"
  do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      py312="$candidate"
      break
    fi
  done
fi
[[ -n "$py312" && -x "$py312" ]] || die \
  "need CPython 3.12.13 (local authority often /usr/local/opt/python@3.12/bin/python3.12); refuse bare python3"

require_exact_cpython_31213 "$py312"

if [[ "${BOOTSTRAP_CHECK_ONLY:-0}" == "1" ]]; then
  echo "bootstrap-venv-py312: check-only OK ($py312 is CPython 3.12.13)"
  exit 0
fi

venv_dir="${VENV_DIR:-$repo_root/.venv-py312}"

# The post-install discrimination, hoisted into one function. Used by BOTH the
# reuse fast path and the full run, so reuse can never authenticate an
# environment the full run would reject.
verify_pins() {
  "$1/bin/python" - <<'PY'
"""Post-install discrimination: version AND load path inside this venv."""
from __future__ import annotations

import importlib.metadata as md
import pathlib
import sys
import sysconfig

import numpy
import pandas
import pyarrow

assert sys.version_info[:3] == (3, 12, 13), sys.version
assert numpy.__version__ == "2.5.1", numpy.__version__
assert pandas.__version__ == "3.0.3", pandas.__version__
assert pyarrow.__version__ == "22.0.0", pyarrow.__version__
purelib = pathlib.Path(sysconfig.get_paths()["purelib"]).resolve()
assert purelib in pathlib.Path(numpy.__file__).resolve().parents, numpy.__file__
assert purelib in pathlib.Path(pandas.__file__).resolve().parents, pandas.__file__
assert purelib in pathlib.Path(pyarrow.__file__).resolve().parents, pyarrow.__file__
print("interpreter", sys.version.split()[0], sys.executable)
print("numpy", numpy.__version__, pathlib.Path(numpy.__file__).resolve())
print("pandas", pandas.__version__, pathlib.Path(pandas.__file__).resolve())
print("pyarrow", pyarrow.__version__, pathlib.Path(pyarrow.__file__).resolve())
print("pytest", md.version("pytest"))
print("PINS_OK")
PY
}

# SERIALIZE MACHINE-WIDE, not per venv.
#
# A per-venv lock does not help: every agent worktree has its OWN venv_dir, so
# N worktrees bootstrap concurrently and every one of them holds a different
# lock legally. That is how a shared workstation reached load 200, and then 467
# once the fleet grew. The contended resource is the MACHINE (CPU, disk, and
# the pip download path), not one directory.
#
# So the lock is global by default. BOOTSTRAP_LOCK_DIR overrides it for an
# isolated host (CI, a container) where parallel bootstraps are actually fine.
lock_dir="${BOOTSTRAP_LOCK_DIR:-${TMPDIR:-/tmp}/sugar-bootstrap-venv-py312.lock}"
lock_waited=0
lock_timeout="${BOOTSTRAP_LOCK_TIMEOUT:-1800}"
while ! mkdir "$lock_dir" 2>/dev/null; do
  # A holder killed by SIGKILL cannot run its EXIT trap, so it leaves the lock
  # behind. Reclaim it only when the recorded pid is genuinely gone — never on
  # age alone, which would race a slow but healthy install.
  if [[ -f "$lock_dir/pid" ]]; then
    holder="$(cat "$lock_dir/pid" 2>/dev/null || true)"
    if [[ -n "$holder" ]] && ! kill -0 "$holder" 2>/dev/null; then
      echo "bootstrap-venv-py312: reclaiming lock from dead pid $holder" >&2
      rm -rf "$lock_dir"
      continue
    fi
  fi
  if (( lock_waited == 0 )); then
    echo "bootstrap-venv-py312: another bootstrap holds $lock_dir; waiting" >&2
  fi
  if (( lock_waited >= lock_timeout )); then
    die "timed out after ${lock_timeout}s waiting for $lock_dir (if no bootstrap is running: rm -rf $lock_dir)"
  fi
  sleep 5
  lock_waited=$(( lock_waited + 5 ))
done
echo "$$" > "$lock_dir/pid"
trap 'rm -rf "$lock_dir" 2>/dev/null || true' EXIT

# Already authenticated? Then there is nothing to do. Recreating the venv and
# reinstalling numpy+pandas on every invocation is what made this heavy.
if [[ -x "$venv_dir/bin/python" ]] && verify_pins "$venv_dir" 2>/dev/null; then
  echo
  echo "$venv_dir already authenticates the declared pins; reusing it."
  echo "Use:  $venv_dir/bin/python -m pytest …"
  exit 0
fi

echo "Creating $venv_dir from $py312 (3.12.13)"
"$py312" -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install -U pip setuptools wheel

# Editable Sugar packages always come from THIS checkout.
"$venv_dir/bin/python" -m pip install \
  -e "$repo_root/implementations/python/sugar-source-tree" \
  -e "$repo_root/implementations/python/sugar-lift-python-source" \
  -e "$repo_root/implementations/python/sugar-lift-py-tests[test]" \
  "pytest==9.1.1"

# AFTER the editable install: float was measured when extras resolved pandas
# 3.0.5 while ledgers key to 3.0.3. Re-pin exactly, then verify load path.
"$venv_dir/bin/python" -m pip install "numpy==2.5.1" "pandas==3.0.3"

verify_pins "$venv_dir"

echo
echo "Use:  $venv_dir/bin/python -m pytest …"
echo "Feature worktree: reinstall its editable packages, then re-pin"
echo "  numpy==2.5.1 pandas==3.0.3 (the post-editable step is load-bearing)."
echo "Note: macOS cannot consume Battleaxe Linux Sugar binary cells."
