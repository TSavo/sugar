#!/usr/bin/env bash
# Prove the whole supply chain. Maven-driven, period.
#
#   mvn, give me all my sources.   ->  one goal, the full transitive closure.
#   sugar, prove everything.       ->  one proof per artifact, from its own
#                                       source + its own tests.
#
# This is not a plugin and not a framework. It is the loop. Point it at any
# Maven project and it mints a `.proof` for every dependency the pom resolves
# to -- and logs, by name, every artifact that lifts to the empty set: the
# perimeter, the shape of what no vendor ever swore to.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
# Use debug binary if release hasn't been built; caller can override via SUGAR=.
SUGAR="${SUGAR:-$("$REPO/bin/sugarbin" --profile release)}"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
# JUnit5 vendor source for assertion vocab derivation — identical to what the
# java-assertion-consistency showcase uses. Copied into each work dir so the
# kit can learn assertEquals=equality from the framework's own source.
JUNIT5_VENDOR="$KIT_DIR/tests/fixtures/vendor/junit5"
OUT="$HERE/proofs"; mkdir -p "$OUT"

command -v mvn >/dev/null 2>&1 || { echo "SKIP: no mvn on PATH"; exit 0; }
command -v javac >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }

cd "$HERE"

# Drop a minimal .sugar lift config + manifest onto a freshly-unpacked vendor
# source tree, pointing the java-test-assertions kit at it. Right by
# construction: the kit reads the unpacked .java through com.sun.source.
#
# assertion_source_dirs must point at the JUnit5 (or JUnit4) framework source
# so the kit can learn assertEquals=equality from the framework's own source
# (throw-locus derivation). Without it every assertion is refused as
# "no learned vocabulary" and the perimeter stays at 100%.
render_manifest() {
  local work="$1" kit="$2" java; java="$(command -v java)"
  # Copy JUnit5 vendor source into the work dir (under vendor/junit5/).
  # The kit reads assertion_source_dirs relative to the workspace root.
  mkdir -p "$work/vendor/junit5"
  cp "$JUNIT5_VENDOR"/*.java "$work/vendor/junit5/" 2>/dev/null || true
  mkdir -p "$work/.sugar/lift/java-test-assertions"
  cat > "$work/.sugar/config.toml" <<TOML
[[plugins]]
name = "java-test-assertions-lift"
kind = "lift"
surface = "java-test-assertions"
emit = "ir-document"

[solvers]
default = "z3"
[solvers.dispatch]
default = "z3"
[solvers.z3]
binary = "z3"

[java-test-assertions]
assertion_source_dirs = ["vendor/junit5"]
TOML
  cat > "$work/.sugar/lift/java-test-assertions/manifest.toml" <<TOML
name = "java-test-assertions-lift"
version = "0.1.0"
protocol_version = "pep/1.7.0"
kind = "lift"
command = ["$java", "--add-exports", "jdk.compiler/com.sun.source.tree=ALL-UNNAMED", "--add-exports", "jdk.compiler/com.sun.source.util=ALL-UNNAMED", "--add-exports", "jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED", "-cp", "$kit/out", "JavaTestAssertionsRpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["java-test-assertions"]
ir_version = "v1.1.0"
emits_signed_mementos = false
TOML
}

# 1. mvn, give me all my sources (and the vendor's own tests = the spec).
echo "== mvn: resolve every dependency's source + test-source =="
mvn -q -B dependency:copy-dependencies -Dclassifier=sources      -DoutputDirectory=target/srcjars
mvn -q -B dependency:copy-dependencies -Dclassifier=test-sources -DoutputDirectory=target/testjars -DfailOnMissingClassifierArtifact=false || true

# Count the contracts the kit lifts from a work dir — drive the kit's JSON-RPC
# `lift` directly (the SAME invocation sugar mint makes) and count the `ir`
# array. The .proof bundle itself is a binary content-addressed artifact, so we
# read the count from the lift response, not the bundle. This is the real
# per-artifact warranty surface — reported so the loop itself is the honest
# record, not an external tally.
count_lifted_contracts() {
  local work="$1" kit="$2" java; java="$(command -v java)"
  printf '%s\n%s\n%s\n' \
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
    "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"lift\",\"params\":{\"workspace_root\":\"$work\"}}" \
    '{"jsonrpc":"2.0","id":3,"method":"shutdown","params":{}}' \
  | "$java" --add-exports jdk.compiler/com.sun.source.tree=ALL-UNNAMED \
            --add-exports jdk.compiler/com.sun.source.util=ALL-UNNAMED \
            --add-exports jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED \
            -cp "$kit/out" JavaTestAssertionsRpc 2>/dev/null \
  | python3 -c '
import sys, json
n = 0
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try: obj = json.loads(line)
    except Exception: continue
    if obj.get("id") == 2 and "result" in obj:
        n = len(obj["result"].get("ir", []))
print(n)
' 2>/dev/null || echo "?"
}

# 2. sugar, prove everything: one .proof per artifact, from its own source.
echo "== sugar: mint a proof per artifact =="
proven=0; gaps=0
for jar in target/srcjars/*-sources.jar; do
  [ -e "$jar" ] || continue
  art="$(basename "$jar" -sources.jar)"
  work="$(mktemp -d)"
  unzip -qo "$jar" -d "$work" -x 'META-INF/*' >/dev/null 2>&1 || true
  tj="target/testjars/${art}-test-sources.jar"
  have_testjar=0
  if [ -e "$tj" ]; then
    have_testjar=1
    unzip -qo "$tj" -d "$work" -x 'META-INF/*' >/dev/null 2>&1 || true
  fi
  render_manifest "$work" "$KIT_DIR"   # drop a java-test-assertions lift manifest onto $work
  if ( cd "$work" && "$SUGAR" mint --out . ) >/dev/null 2>&1 && ls "$work"/blake3-512_*.proof >/dev/null 2>&1; then
    proof="$(ls "$work"/blake3-512_*.proof | head -1)"
    cp "$proof" "$OUT/$art.proof"
    nc="$(count_lifted_contracts "$work" "$KIT_DIR")"
    proven=$((proven+1)); printf "  PROOF  %-34s %s contracts\n" "$art" "$nc"
  else
    # Honest GAP reason: no test-source jar = nobody published a spec; vs a
    # test-source jar present but nothing liftable = a real perimeter inside
    # the vendor's own tests.
    if [ "$have_testjar" = 1 ]; then
      reason="test-sources present, 0 liftable assertions"
    else
      reason="no -test-sources.jar on Central (no published spec)"
    fi
    gaps=$((gaps+1));     printf "  GAP    %-34s -> []   (%s)\n" "$art" "$reason"
  fi
  rm -rf "$work"
done

echo
echo "== supply chain: $proven proven, $gaps on the perimeter =="
echo "   proofs in $OUT/ ; the GAP lines ARE the map of what nobody warranted."
