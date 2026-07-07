#!/usr/bin/env bash
# run-prove-e2e.sh: the IDE PROVE-path receipt (#3774 / #3779).
#
# Drives the SAME code the VS Code extension runs -- `proveClient.proveProject`,
# which shells `sugar prove --json` on a consumer PROJECT and maps `unsatisfied`
# rows to diagnostics at the assertion's source locus. It uses the REAL demo
# fixtures (examples/python-base64-federation: native Python + a staged vendor
# .proof, NO annotations) and asserts T's flip:
#
#   consumer-bad  (assert encodeBase64("xyz") == "AAAA")  -> RED  diagnostic @ the assert line
#   consumer-good (assert encodeBase64("xyz") == "eHl6")  -> no diagnostic
#   flip the literal both ways -> the diagnostic appears / clears.
#
# The `sugar` binary is resolved through the ONE published door (bin/sugarbin);
# no cargo is invoked directly. Python env mirrors the example's run.sh.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
EXT_DIR="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$EXT_DIR/../.." && pwd)"

echo "== resolve sugar via sugarbin =="
SUGAR_BIN="$("$REPO/bin/sugarbin" --profile release)"
export SUGAR_BIN
echo "   $SUGAR_BIN"
echo "== ensure the bundled SMT compiler is resolvable =="
"$REPO/bin/sugarbin" --profile release --bin sugar-ir-smt-lib >/dev/null
command -v z3 >/dev/null 2>&1 || { echo "FAIL: z3 is required"; exit 1; }

PYTHON_SRC="$REPO/implementations/python/sugar-lift-py-pytest-witness/src:$REPO/implementations/python/sugar-lift-py-tests/src:$REPO/implementations/python/sugar-lift-python-source/src"
VENV="${PYTHON_LITERAL_BASE64_VENV:-/tmp/python-literal-base64-venv}"
SYSTEM_PYTHON="${PYTHON_LITERAL_BASE64_PYTHON:-$(command -v python3)}"
PYTHON="$SYSTEM_PYTHON"
if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import blake3, cbor2, nacl, pytest
PY
then
  PYTHON="$VENV/bin/python"
  [ -x "$PYTHON" ] || "$SYSTEM_PYTHON" -m venv "$VENV"
  "$PYTHON" -m pip install -q blake3 cbor2 pynacl pytest
fi
PYTHON_BIN_DIR="$(cd "$(dirname "$PYTHON")" && pwd)"

export SUGAR_PROVE_PATH="$PYTHON_BIN_DIR:$PATH"
export SUGAR_PROVE_PYTHONPATH_SUFFIX="$PYTHON_SRC"
export SUGAR_EXAMPLE_DIR="$REPO/examples/python-base64-federation"

echo "== compile the TypeScript client =="
cd "$EXT_DIR"
if [ ! -d node_modules ]; then
  npm install --silent
fi
npm run --silent compile

echo "== run the headless PROVE-path red -> green -> red receipt =="
node ./test/prove-e2e.test.js
