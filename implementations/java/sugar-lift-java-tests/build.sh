#!/usr/bin/env bash
# Build the Java-native lifters. Requires JDK 21+ (com.sun.source tree API).
# Output: out/ directory with:
#   - JavaTestAssertionsRpc.class  (contract: assertions, vocab, universes)
#   - JavaPanamaFfmRpc.class       (P5b: Panama FFM call-edge bridge lifter)
#   - JavaJunitWitnessRpc.class    (P5a: JUnit witness resolve/recompute)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-$HERE/out}"
STAMP_NAME=".sugar-java-kit-build"

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1"
  else
    shasum -a 256 "$1"
  fi
}

sha256_stream() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum
  else
    shasum -a 256
  fi
}

if [ -z "$OUT" ] || [ "$OUT" = "/" ]; then
  echo "Refusing unsafe Java kit output directory: ${OUT:-<empty>}" >&2
  exit 1
fi

fingerprint="$({
  printf '%s\n' 'sugar-java-kit-build-v1'
  javac -version 2>&1
  sha256_file "$HERE/build.sh"
  find "$HERE/src" -type f -name '*.java' -print | LC_ALL=C sort | while IFS= read -r source; do
    sha256_file "$source"
  done
} | sha256_stream | awk '{print $1}')"

kit_is_current() {
  [ -f "$OUT/$STAMP_NAME" ] &&
    [ "$(cat "$OUT/$STAMP_NAME")" = "$fingerprint" ] &&
    [ -f "$OUT/JavaTestAssertionsRpc.class" ] &&
    [ -f "$OUT/JavaJunitWitnessRpc.class" ] &&
    [ -f "$OUT/JavaPanamaFfmRpc.class" ] &&
    [ -f "$OUT/JavaSourceOracle.class" ]
}

if kit_is_current; then
  echo "Reused content-addressed Java kit at $OUT"
  exit 0
fi

# Cargo tests and showcases can reach this script concurrently. Serialize the
# one cache miss; every waiter rechecks the content stamp after acquiring it.
if command -v flock >/dev/null 2>&1; then
  mkdir -p "$(dirname "$OUT")"
  exec 9>"$OUT.lock"
  flock 9
  if kit_is_current; then
    echo "Reused content-addressed Java kit at $OUT"
    exit 0
  fi
fi

TMP_OUT="$OUT.tmp.$$"
rm -rf "$TMP_OUT"
mkdir -p "$TMP_OUT"
trap 'rm -rf "$TMP_OUT"' EXIT

# JavaJunitWitnessRpc: JDK-only, pure Java. Uses --release 21.
javac \
  -encoding UTF-8 \
  --release 21 \
  -proc:none \
  -d "$TMP_OUT" \
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
  -cp "$TMP_OUT" \
  -d "$TMP_OUT" \
  "$HERE/src/JavaDependencyProofResolver.java" \
  "$HERE/src/JavaTestAssertionsRpc.java" \
  "$HERE/src/JavaPanamaFfmRpc.java" \
  "$HERE/src/JavaSourceOracle.java"

printf '%s' "$fingerprint" > "$TMP_OUT/$STAMP_NAME"
rm -rf "$OUT"
mv "$TMP_OUT" "$OUT"
trap - EXIT
echo "Built content-addressed Java kit at $OUT"
