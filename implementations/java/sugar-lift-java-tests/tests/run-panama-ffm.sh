#!/usr/bin/env bash
# Unit tests for JavaPanamaFfmRpc (P5b: Panama FFM bridge lifter).
#
# Verifies:
#   1. Panama callsite fixture: emits 1 call-edge with correct targetSymbol,
#      sourceContractCid, targetContractCid, callSiteLocus.
#   2. Non-bridge fixture (no downcallHandle): emits 0 call-edges.
#   3. Missing-binding: emits named diagnostic, no call-edge.
#   4. Shutdown RPC: handles "shutdown" method gracefully.
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BUILD="$ROOT/target/panama-test-classes"
WORK="$ROOT/target/panama-test-workspace"
WORK2="$ROOT/target/panama-non-bridge-workspace"

rm -rf "$BUILD" "$WORK" "$WORK2"
mkdir -p "$BUILD" "$WORK/.sugar/imports" "$WORK2/.sugar/imports"

echo "== build JavaPanamaFfmRpc =="
javac \
  --add-exports jdk.compiler/com.sun.source.tree=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.source.util=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED \
  -source 21 -target 21 \
  -d "$BUILD" \
  "$ROOT/src/JavaPanamaFfmRpc.java" 2>&1 | grep -v '^Note:' || true

JAVA_FLAGS="--add-exports jdk.compiler/com.sun.source.tree=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.source.util=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED"

rpc() {
  printf '%s\n' "$1" | java $JAVA_FLAGS -cp "$BUILD" JavaPanamaFfmRpc
}

# ── Fixture 1: Panama bridge callsite ────────────────────────────────────────
cat > "$WORK/PanamaConsumer.java" << 'EOF'
package demo;

import static org.junit.jupiter.api.Assertions.assertEquals;
import java.lang.foreign.Arena;
import java.lang.foreign.FunctionDescriptor;
import java.lang.foreign.Linker;
import java.lang.foreign.SymbolLookup;
import java.lang.foreign.ValueLayout;
import java.lang.invoke.MethodHandle;
import org.junit.jupiter.api.Test;

final class PanamaConsumer {
    private static final Arena ARENA = Arena.ofAuto();
    private static final SymbolLookup LOOKUP =
            SymbolLookup.libraryLookup("libbase64_panama_demo.so", ARENA);
    private static final Linker LINKER = Linker.nativeLinker();
    private static final MethodHandle DECODED_LEN_ESTIMATE = LINKER.downcallHandle(
            LOOKUP.find("decoded_len_estimate").orElseThrow(),
            FunctionDescriptor.of(ValueLayout.JAVA_LONG, ValueLayout.JAVA_LONG));

    static int decoded_len_estimate(int n) throws Throwable {
        return Math.toIntExact((long) DECODED_LEN_ESTIMATE.invokeExact((long) n));
    }

    @Test
    void bridgeTest() throws Throwable {
        assertEquals(3, decoded_len_estimate(4));
    }
}
EOF

EUF="decoded_len_estimate#euf#c:callresult_decoded_len_estimate_a1(i:4)::assertion"
REQ="{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"lift\",\"params\":{\"workspace_root\":\"$WORK\",\"source_paths\":[\".\"],\"contract_bindings\":[{\"name\":\"$EUF\",\"contract_cid\":\"blake3-512:java-source-cid\"},{\"name\":\"$EUF\",\"contract_cid\":\"blake3-512:rust-target-cid\",\"target_proof_cid\":\"blake3-512:rust-proof-cid\"}]}}"

RESPONSE="$(rpc "$REQ")"

python3 - "$RESPONSE" "$WORK/java-panama-ffm.call-edges.json" "$EUF" <<'PY'
import json, sys

response_text, sidecar_path, euf = sys.argv[1:4]
response = json.loads(response_text)
result = response["result"]
edges = result["callEdges"]
assert len(edges) == 1, f"expected 1 edge, got {len(edges)}: {edges}"
edge = edges[0]

# Verify targetSymbol
expected_sym = "rust-kit:" + euf
assert edge["targetSymbol"] == expected_sym, f"wrong targetSymbol: {edge['targetSymbol']!r}"
print(f"   targetSymbol: {edge['targetSymbol']}")

# Verify source/target CIDs
assert edge["sourceContractCid"] == "blake3-512:java-source-cid", edge
assert edge["targetContractCid"] == "blake3-512:rust-target-cid", edge
print(f"   sourceContractCid: {edge['sourceContractCid']}")
print(f"   targetContractCid: {edge['targetContractCid']}")

# Verify callSiteLocus has line/column > 0 (from SourcePositions API)
locus = edge["callSiteLocus"]
assert locus["line"] > 0, f"expected line > 0, got {locus}"
assert locus["column"] > 0, f"expected column > 0, got {locus}"
print(f"   callSiteLocus: {locus}")

# Verify kind and schemaVersion
assert edge["kind"] == "call-edge", edge
assert edge["schemaVersion"] == "1", edge
print(f"   kind=call-edge schemaVersion=1")

# Verify sidecar file
sidecar = json.load(open(sidecar_path, encoding="utf-8"))
assert sidecar["edges"] == edges, f"sidecar mismatch: {sidecar}"
print(f"   sidecar edges match response")

# Verify evidenceTerm
ev = edge["evidenceTerm"]
assert ev["kind"] == "atomic", ev
assert ev["name"] == "call-site-obligation", ev
print(f"   evidenceTerm: {ev}")

print("TEST 1 PASS: Panama callsite → call-edge with correct shape")
PY

# ── Fixture 2: Non-bridge file → 0 edges ─────────────────────────────────────
cat > "$WORK2/RegularTest.java" << 'EOF'
import static org.junit.jupiter.api.Assertions.assertEquals;
import org.junit.jupiter.api.Test;
class RegularTest {
    @Test void simple() { assertEquals(3, 1 + 2); }
}
EOF

REQ2="{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"lift\",\"params\":{\"workspace_root\":\"$WORK2\",\"source_paths\":[\".\"],\"contract_bindings\":[]}}"
RESPONSE2="$(rpc "$REQ2")"

python3 - "$RESPONSE2" <<'PY'
import json, sys
r = json.loads(sys.argv[1])["result"]
assert r["callEdges"] == [], f"expected no edges for non-bridge file, got {r['callEdges']}"
assert r["diagnostics"] == [], f"expected no diagnostics, got {r['diagnostics']}"
print("TEST 2 PASS: non-bridge file → 0 edges, 0 diagnostics")
PY

# ── Fixture 3: Missing binding → named diagnostic ─────────────────────────────
REQ3="{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"lift\",\"params\":{\"workspace_root\":\"$WORK\",\"source_paths\":[\".\"],\"contract_bindings\":[]}}"
RESPONSE3="$(rpc "$REQ3")"

python3 - "$RESPONSE3" "$EUF" <<'PY'
import json, sys
r = json.loads(sys.argv[1])["result"]
euf = sys.argv[2]
assert r["callEdges"] == [], f"expected no edges for missing binding, got {r['callEdges']}"
diags = r["diagnostics"]
assert len(diags) >= 1, f"expected at least 1 diagnostic, got {diags}"
# Must be a named refusal with the euf name
reasons = [d["reason"] for d in diags]
assert any(euf in reason for reason in reasons), \
    f"euf name not in any diagnostic reason: {reasons}"
print(f"   diagnostic reason: {diags[0]['reason']}")
print("TEST 3 PASS: missing binding → named diagnostic with euf name")
PY

# ── Test 4: shutdown method ───────────────────────────────────────────────────
REQ4='{"jsonrpc":"2.0","id":4,"method":"shutdown","params":{}}'
RESPONSE4="$(rpc "$REQ4")"

python3 - "$RESPONSE4" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
assert r["result"] == None or r["result"] is None or r["result"] == "null", r
print(f"TEST 4 PASS: shutdown → ok")
PY

# ── Test 5: initialize method ─────────────────────────────────────────────────
REQ5='{"jsonrpc":"2.0","id":5,"method":"initialize","params":{}}'
RESPONSE5="$(rpc "$REQ5")"

python3 - "$RESPONSE5" <<'PY'
import json, sys
r = json.loads(sys.argv[1])["result"]
assert r["name"] == "sugar-lift-java-panama-ffm", r
assert "java-panama-ffm" in r["capabilities"]["authoring_surfaces"], r
print(f"TEST 5 PASS: initialize → name={r['name']} surface=java-panama-ffm")
PY

echo
echo "all JavaPanamaFfmRpc unit tests passed"
