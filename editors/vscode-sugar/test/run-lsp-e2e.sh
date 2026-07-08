#!/usr/bin/env bash
# run-lsp-e2e.sh: the-flip's extension-side receipt.
#
# Drives `sugar-lsp --in-process` over REAL LSP stdio (Content-Length framed
# JSON-RPC, the exact wire vscode-languageclient's LanguageClient speaks) --
# the same server, wire, and construction the extension's `activate()` hands
# a LanguageClient to. Uses the REAL demo fixtures
# (examples/python-base64-federation: native Python + a staged vendor
# .proof, NO annotations, no mock lifter) and asserts T's flip:
#
#   didOpen consumer-bad's buffer     -> RED  publishDiagnostics @ the assert line
#   didChange to consumer-good's text -> diagnostics clear
#   didChange back to the bad text    -> the diagnostic reappears
#
# `sugar-lsp` and `sugar` are both resolved through the ONE published door
# (bin/sugarbin); no cargo is invoked directly. Python env mirrors the demo's
# run.sh / run-prove-e2e.sh.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
EXT_DIR="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$EXT_DIR/../.." && pwd)"

echo "== resolve sugar + sugar-lsp via sugarbin =="
# NOTE: bin/sugarbin honors a `SUGAR_BIN` env override UNCONDITIONALLY (it
# short-circuits before even looking at --bin), so `sugar-lsp` MUST be
# resolved before `SUGAR_BIN` is exported -- otherwise the second call
# silently echoes back the `sugar` path instead of building/resolving
# sugar-lsp.
SUGAR_LSP_BIN="$("$REPO/bin/sugarbin" --profile release --bin sugar-lsp)"
export SUGAR_LSP_BIN
echo "   sugar-lsp: $SUGAR_LSP_BIN"
SUGAR_BIN="$("$REPO/bin/sugarbin" --profile release)"
export SUGAR_BIN
echo "   sugar:     $SUGAR_BIN"
echo "== ensure the bundled SMT compiler is resolvable =="
# Same SUGAR_BIN-override gotcha as above: scope it out of this call's env
# so sugar-ir-smt-lib is actually resolved/built, not just handed back the
# already-exported `sugar` path.
env -u SUGAR_BIN -u SUGAR_LSP_BIN "$REPO/bin/sugarbin" --profile release --bin sugar-ir-smt-lib >/dev/null
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

echo "== run the headless LSP-path red -> green -> red receipt =="
node ./test/lsp-e2e.test.js
