#!/usr/bin/env bash
# Build the Java-native lifters. Requires JDK 21+ (com.sun.source tree API).
# Output: out/ directory with:
#   - JavaTestAssertionsRpc.class  (contract: assertions, vocab, universes)
#   - JavaPanamaFfmRpc.class       (P5b: Panama FFM call-edge bridge lifter)
#   - JavaJunitWitnessRpc.class    (P5a: JUnit witness resolve/recompute)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$HERE/out}"

if [ -z "$OUT" ] || [ "$OUT" = "/" ]; then
  echo "Refusing unsafe Java kit output directory: ${OUT:-<empty>}" >&2
  exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT"

# JavaJunitWitnessRpc: JDK-only, pure Java. Uses --release 21.
javac \
  -encoding UTF-8 \
  --release 21 \
  -proc:none \
  -d "$OUT" \
  "$HERE/src/JavaDependencyProofResolver.java" \
  "$HERE/src/JavaJunitWitnessRpc.java"

# JavaTestAssertionsRpc and JavaSourceOracle use com.sun.source (jdk.compiler
# module). We compile without --release because --add-exports is incompatible
# with --release for system modules. Written to JDK 21 language level.
javac \
  -encoding UTF-8 \
  --add-exports jdk.compiler/com.sun.source.tree=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.source.util=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED \
  -source 21 -target 21 \
  -cp "$OUT" \
  -d "$OUT" \
  "$HERE/src/JavaDependencyProofResolver.java" \
  "$HERE/src/JavaTestAssertionsRpc.java" \
  "$HERE/src/JavaPanamaFfmRpc.java" \
  "$HERE/src/JavaSourceOracle.java"

echo "Built to $OUT"
