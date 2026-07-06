#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../../../.." && pwd)"
VENV="${PYTHON_URLSAFE_SEAM_VENV:-/tmp/python-urlsafe-seam-venv}"
PYTHON="${PYTHON_URLSAFE_SEAM_PYTHON:-$VENV/bin/python}"

export PYTHONPATH="$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" "$REPO/implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py" "$@"
