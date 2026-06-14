#!/usr/bin/env bash
# PYTHONPATH = the Python kit sources + the showcase venv site-packages so the
# source oracle resolves pandas' installed source files and never embeds them.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
VENV="${PANDAS_WITNESS_VENV:-/tmp/pandas-witness-venv}"
SITE="$("$VENV/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
export PYTHONPATH="$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src:$SITE"
export SUGAR_PY_PACKAGE_ACCOUNTING_MODE=structural
export SUGAR_PY_PACKAGE_ACCOUNTING_LOCI=summary
export SUGAR_PY_PACKAGE_ACCOUNTING_SAMPLE_LIMIT="${PANDAS_SOURCE_SAMPLE_LIMIT:-40}"
exec "$VENV/bin/python" -m sugar_lift_py_tests.lsp
