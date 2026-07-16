#!/usr/bin/env bash
# Stdlib zlib.crc32 logo: kit sources only (no showcase venv).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
export PYTHONPATH="$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m sugar_lift_py_tests.lift_rpc --rpc
