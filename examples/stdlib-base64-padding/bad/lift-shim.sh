#!/usr/bin/env bash
# PYTHONPATH = the kit lifter sources. stdlib base64 needs no vendor site-packages.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
VENV="${STDLIB_BASE64_PADDING_LOGO_VENV:-${ITSDANGEROUS_LOGO_VENV:-/tmp/stdlib-base64-padding-logo-venv}}"
if [ -x "$VENV/bin/python" ]; then
  PYTHON="$VENV/bin/python"
else
  PYTHON="${STDLIB_BASE64_PADDING_LOGO_PYTHON:-python3}"
fi
export PYTHONPATH="$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m sugar_lift_py_tests.lift_rpc --rpc
