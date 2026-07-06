#!/usr/bin/env bash
# run-e2e.sh: the slice A receipt driver (#3774).
#
# Resolves the sugar-linkerd binary through the ONE published door (bin/sugarbin
# builds+publishes it if the shelf misses), compiles the TypeScript client, and
# runs the headless wire-protocol test that asserts red -> green -> red through
# the production daemon. No cargo is invoked directly.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
EXT_DIR="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$EXT_DIR/../.." && pwd)"

echo "== resolve sugar-linkerd via sugarbin =="
SUGAR_LINKERD_BIN="$("$REPO/bin/sugarbin" --profile release --bin sugar-linkerd)"
export SUGAR_LINKERD_BIN
echo "   $SUGAR_LINKERD_BIN"

echo "== compile the TypeScript client =="
cd "$EXT_DIR"
if [ ! -d node_modules ]; then
  npm install --silent
fi
npm run --silent compile

echo "== run the headless red -> green -> red receipt =="
node ./test/e2e.test.js
