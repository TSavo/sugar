#!/usr/bin/env bash
# PYTHONPATH = the kit lifter sources + the showcase venv (for the walker's
# find_spec resolution of itsdangerous' INSTALLED source -- read, never run).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
VENV="${ITSDANGEROUS_LOGO_VENV:-/tmp/itsdangerous-logo-venv}"
SITE="$("$VENV/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
export PYTHONPATH="$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src:$SITE"
exec "$VENV/bin/python" -m sugar_lift_py_tests.lift_rpc --rpc
