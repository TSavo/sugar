#!/usr/bin/env bash
# java-witness-recompute showcase:
# GOOD suite — both tests pass; witness package discharges and verifies.
# BAD  suite — one test fails; bundle still reproduces honestly, but the
#              verifier REFUSES because not all outcomes are "passed".
#              The LYING-DISCHARGE twin: a resolver that returns bytes claiming
#              all tests passed; the verifier REFUSES because blake3 of those
#              tampered bytes ≠ pinned package_cid.
#
# Runs: sugar mint -> sugar prove -> sugar verify; parses real JSON receipts.
# JDK skip-guard: exits 0 with SKIP if no JDK on PATH.
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"
KIT_JAVA="$(which java)"

echo "SCOPE: P5a — Java-native JUnit witness kit."
echo "SCOPE: GOOD: 2 passing tests -> witness package discharges + verifies."
echo "SCOPE: BAD:  1 passing + 1 failing -> bundle reproduces, verifier REFUSES."
echo "SCOPE: LYING-DISCHARGE: tampered bytes (all passed) -> blake3 mismatch -> REFUSED."

echo
echo "== build the sugar CLI =="
if [ "${JAVA_WITNESS_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
  cargo build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar >/dev/null
fi
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not at $SUGAR"; exit 1; }

echo
echo "== build the Java witness kit =="
bash "$KIT_DIR/build.sh" "$KIT_DIR/out" >/dev/null 2>&1
[ -f "$KIT_DIR/out/JavaJunitWitnessRpc.class" ] || {
  echo "FAIL: JavaJunitWitnessRpc.class not built"; exit 1; }

echo
echo "== prepare manifests and clean state =="
for suite in good bad; do
  mfin="$HERE/$suite/.sugar/lift/java-junit-witness/manifest.toml.in"
  mf="$HERE/$suite/.sugar/lift/java-junit-witness/manifest.toml"
  sed "s#@KIT_JAVA@#${KIT_JAVA}#g; s#@KIT_DIR@#${KIT_DIR}#g" "$mfin" > "$mf"
  # Clean old state (anchored: .sugar/runs, .sugar/witnesses, .proof files)
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" "$HERE/$suite/.sugar/witnesses" 2>/dev/null || true
  rm -f "$HERE/$suite"/.prove*.json "$HERE/$suite"/.verify*.json 2>/dev/null || true
done

pyget() { python3 -c "import sys,json; d=json.load(open(sys.argv[1])); print($2)" "$1"; }

# ── run GOOD suite ─────────────────────────────────────────────────────────────
echo
echo "==================== suite: good ===================="

echo "-- mint: run tests, emit witness-package contract --"
( cd "$HERE/good" && SUGAR_WITNESS_PROJECT_DIR="$(pwd)" "$SUGAR" mint --out . ) >/dev/null 2>&1

have_proof=0
for p in "$HERE/good"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
[ "$have_proof" = 1 ] || { echo "FAIL[good]: mint produced no .proof"; exit 1; }

echo "-- prove: witness-package row --"
prove_json="$HERE/good/.prove.json"
( cd "$HERE/good" && SUGAR_WITNESS_PROJECT_DIR="$(pwd)" "$SUGAR" prove . --json \
  2>/dev/null ) > "$prove_json" || true

witness_status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows', []) if 'witness-package' in (r.get('property', '') or '')), 'MISSING')
")"
echo "   prove witness-package status: $witness_status"
[ "$witness_status" = "discharged" ] || {
  echo "FAIL[good]: expected witness discharge, got $witness_status"; exit 1; }

echo "-- verify: durable witness dimension --"
verify_json="$HERE/good/.verify.json"
( cd "$HERE/good" && SUGAR_WITNESS_PROJECT_DIR="$(pwd)" \
  PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json \
  2>/dev/null ) > "$verify_json" || true

python3 - "good" "$verify_json" <<'PY'
import json, sys
suite, path = sys.argv[1], sys.argv[2]
receipt = json.load(open(path, encoding="utf-8"))
rows = receipt.get("rows", [])
witness = [r.get("status") for r in rows
           if "witness-package" in (r.get("property") or "")]
if witness != ["discharged"]:
    raise SystemExit(f"FAIL[{suite}]: durable witness statuses {witness}")
verified = any(
    w.get("verdict") == "verified"
    for w in receipt.get("witnessDimension", {}).get("witnesses", [])
)
if not verified:
    raise SystemExit(f"FAIL[{suite}]: witness dimension did not verify")
print(f"   durable witness status:    {','.join(witness)}")
print(f"   durable witness dimension: verified")
PY

echo "== good: PASS =="

# ── run BAD suite ──────────────────────────────────────────────────────────────
echo
echo "==================== suite: bad ===================="

echo "-- mint: run tests (one fails), emit honest witness-package contract --"
( cd "$HERE/bad" && SUGAR_WITNESS_PROJECT_DIR="$(pwd)" "$SUGAR" mint --out . ) >/dev/null 2>&1

have_proof=0
for p in "$HERE/bad"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
[ "$have_proof" = 1 ] || { echo "FAIL[bad]: mint produced no .proof"; exit 1; }

echo "-- prove: honest run -> witness-package should be REFUSED (1 test failed) --"
prove_json="$HERE/bad/.prove.json"
( cd "$HERE/bad" && SUGAR_WITNESS_PROJECT_DIR="$(pwd)" "$SUGAR" prove . --json \
  2>/dev/null ) > "$prove_json" || true

witness_status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows', []) if 'witness-package' in (r.get('property', '') or '')), 'MISSING')
")"
echo "   prove witness-package status: $witness_status"
if [ "$witness_status" = "discharged" ]; then
  echo "FAIL[bad]: expected witness refusal, got discharged"; exit 1
fi

echo "-- verify: honest run -> witness dimension should be refused/unsatisfied --"
verify_json="$HERE/bad/.verify.json"
( cd "$HERE/bad" && SUGAR_WITNESS_PROJECT_DIR="$(pwd)" \
  PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json \
  2>/dev/null ) > "$verify_json" || true

python3 - "bad" "$verify_json" <<'PY'
import json, sys
suite, path = sys.argv[1], sys.argv[2]
receipt = json.load(open(path, encoding="utf-8"))
rows = receipt.get("rows", [])
witness = [r.get("status") for r in rows
           if "witness-package" in (r.get("property") or "")]
if witness == ["discharged"] or not witness:
    raise SystemExit(f"FAIL[{suite}]: expected refusal, got {witness}")
print(f"   durable witness status: {','.join(witness)}")
print(f"   durable: REFUSED (one test failed — correct)")
PY

# ── LYING DISCHARGE: tampered bytes claim all passed ───────────────────────────
echo
echo "-- lying-discharge: resolver returns tampered bytes (all 'passed') --"
echo "   The verifier recomputes blake3 of those bytes itself."
echo "   If blake3(tampered_bytes) != pinned package_cid -> REFUSED."

# Build a lying resolver: a Java wrapper that intercepts resolve_witness and
# returns tampered bundle bytes (all outcomes = "passed").
# The tampered bytes have a different blake3 than the real bundle_cid.
LYING_DIR="$HERE/bad/.sugar/lying-resolver"
mkdir -p "$LYING_DIR"

cat > "$LYING_DIR/LyingResolver.java" << 'JEOF'
// A lying witness resolver: intercepts resolve_witness and returns bytes
// where all test outcomes are "passed" — regardless of what actually ran.
// This tests that the rust verifier's recompute guard catches the lie.
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

public class LyingResolver {
    public static void main(String[] args) throws Exception {
        BufferedReader in  = new BufferedReader(
            new InputStreamReader(System.in, StandardCharsets.UTF_8));
        PrintWriter    out = new PrintWriter(
            new OutputStreamWriter(System.out, StandardCharsets.UTF_8), true);
        String line;
        while ((line = in.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty()) continue;
            String id     = extractId(line);
            String method = jsonString(line, "method");
            String reply;
            if ("initialize".equals(method)) {
                reply = ok(id, "{\"name\":\"lying-resolver\",\"version\":\"0.0.0\","
                    + "\"protocol_version\":\"pep/1.7.0\","
                    + "\"capabilities\":{\"authoring_surfaces\":[\"java-junit-witness\"],"
                    + "\"ir_version\":\"v1.1.0\",\"emits_signed_mementos\":false}}");
            } else if ("sugar.plugin.kit_declaration".equals(method)) {
                reply = ok(id, "{\"kit\":{\"id\":\"lying-resolver\",\"language\":\"java\","
                    + "\"version\":\"0.0.0\"},"
                    + "\"rpc\":{\"methods\":[{\"name\":\"initialize\",\"required\":true},"
                    + "{\"name\":\"sugar.plugin.kit_declaration\",\"required\":true},"
                    + "{\"name\":\"sugar.plugin.resolve_witness\",\"required\":false},"
                    + "{\"name\":\"shutdown\",\"required\":false}]},"
                    + "\"proofResolution\":{\"strategy\":\"junit\"},"
                    + "\"effectKinds\":[],\"effectLeaves\":[],\"guardPredicates\":[],"
                    + "\"controlCarriers\":[],\"residueCategories\":[]}");
            } else if ("sugar.plugin.resolve_witness".equals(method)) {
                // Return tampered bytes: claim all tests passed.
                // This body has "outcome":"passed" for all tests but the
                // blake3 of these bytes != the real pinned package_cid.
                String fakeBody =
                    "{\"codeCid\":\"blake3-512:000000\","
                    + "\"codeFiles\":\"src/WitnessTest.java\","
                    + "\"kind\":\"junit-test-witness\","
                    + "\"outcome\":\"passed\","
                    + "\"runtimeCid\":\"blake3-512:000000\","
                    + "\"test\":\"WitnessTest::testGFails\"}\n"
                    + "{\"codeCid\":\"blake3-512:000000\","
                    + "\"codeFiles\":\"src/WitnessTest.java\","
                    + "\"kind\":\"junit-test-witness\","
                    + "\"outcome\":\"passed\","
                    + "\"runtimeCid\":\"blake3-512:000000\","
                    + "\"test\":\"WitnessTest::testGReturnsOne\"}\n";
                String b64 = Base64.getEncoder().encodeToString(
                    fakeBody.getBytes(StandardCharsets.UTF_8));
                // We need the real witness_cid to fill in, but we're lying so we
                // return the b64 of tampered bytes; the verifier will recompute
                // blake3(bytes) and find it != pinned package_cid -> REFUSED.
                String witnessId = jsonString(line, "witness_cid");
                reply = ok(id, "{\"witness_cid\":" + jsl(witnessId)
                    + ",\"body_b64\":" + jsl(b64)
                    + ",\"resolved_by\":\"lying-recompute\"}");
            } else if ("shutdown".equals(method)) {
                out.println("{\"jsonrpc\":\"2.0\",\"id\":" + id + ",\"result\":null}");
                out.flush();
                break;
            } else {
                reply = ok(id, "null");
            }
            out.println(reply);
            out.flush();
        }
    }
    static String ok(String id, String res) {
        return "{\"jsonrpc\":\"2.0\",\"id\":" + id + ",\"result\":" + res + "}";
    }
    static String jsl(String s) {
        if (s == null) return "null";
        StringBuilder sb = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if      (c == '"')  sb.append("\\\"");
            else if (c == '\\') sb.append("\\\\");
            else if (c < 0x20)  sb.append(String.format("\\u%04x",(int)c));
            else                sb.append(c);
        }
        return sb.append('"').toString();
    }
    static String extractId(String json) {
        int i = json.indexOf("\"id\""); if (i<0) return "null";
        int c = json.indexOf(':', i+4); if (c<0) return "null";
        int s = c+1; while (s<json.length() && json.charAt(s)==' ') s++;
        if (s>=json.length()) return "null";
        if (json.charAt(s)=='"') { int e=json.indexOf('"',s+1); return e<0?"null":json.substring(s,e+1); }
        int e=s; while (e<json.length()&&",}] ".indexOf(json.charAt(e))<0) e++;
        return json.substring(s,e).trim();
    }
    static String jsonString(String json, String key) {
        String n = "\"" + key + "\""; int i = json.indexOf(n); if (i<0) return "";
        int c = json.indexOf(':',i+n.length()); if (c<0) return "";
        int s=c+1; while (s<json.length()&&json.charAt(s)==' ') s++;
        if (s>=json.length()||json.charAt(s)!='"') return "";
        StringBuilder sb = new StringBuilder(); int j=s+1;
        while (j<json.length()) {
            char ch=json.charAt(j);
            if (ch=='\\'&&j+1<json.length()){char nx=json.charAt(j+1);sb.append(nx);j+=2;}
            else if (ch=='"') break;
            else {sb.append(ch);j++;}
        }
        return sb.toString();
    }
}
JEOF

# Compile the lying resolver
javac --release 21 -d "$LYING_DIR" "$LYING_DIR/LyingResolver.java" 2>/dev/null || {
  echo "SKIP: could not compile LyingResolver.java (non-fatal)"; }

if [ -f "$LYING_DIR/LyingResolver.class" ]; then
  # Write a lying manifest that uses LyingResolver instead of JavaJunitWitnessRpc
  lying_mf="$HERE/bad/.sugar/lift/java-junit-witness/manifest_lie.toml"
  cat > "$lying_mf" << TOML
name = "java-junit-witness-lift"
version = "0.1.0"
protocol_version = "pep/1.7.0"
kind = "lift"
command = ["${KIT_JAVA}", "-cp", "${KIT_DIR}/out", "JavaJunitWitnessRpc"]
resolve_witness_command = ["${KIT_JAVA}", "-cp", "${LYING_DIR}", "LyingResolver"]
resolve_witness_method = "sugar.plugin.resolve_witness"
working_dir = "."

[capabilities]
authoring_surfaces = ["java-junit-witness"]
ir_version = "v1.1.0"
emits_signed_mementos = false
TOML

  # Swap in lying manifest temporarily
  real_mf="$HERE/bad/.sugar/lift/java-junit-witness/manifest.toml"
  cp "$real_mf" "${real_mf}.bak"
  cp "$lying_mf" "$real_mf"

  lie_verify_json="$HERE/bad/.verify_lie.json"
  ( cd "$HERE/bad" && SUGAR_WITNESS_PROJECT_DIR="$(pwd)" \
    PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json \
    2>/dev/null ) > "$lie_verify_json" 2>/dev/null || true

  # Restore real manifest
  cp "${real_mf}.bak" "$real_mf"
  rm -f "${real_mf}.bak"

  python3 - "lying-discharge" "$lie_verify_json" <<'PY'
import json, sys
suite, path = sys.argv[1], sys.argv[2]
try:
    receipt = json.load(open(path, encoding="utf-8"))
except Exception as e:
    raise SystemExit(f"FAIL[{suite}]: could not read verify receipt: {e}")
rows = receipt.get("rows", [])
witness = [r.get("status") for r in rows
           if "witness-package" in (r.get("property") or "")]
reasons = [r.get("reason", "") for r in rows
           if "witness-package" in (r.get("property") or "")]
if witness == ["discharged"]:
    raise SystemExit(f"FAIL[{suite}]: lying resolver was ACCEPTED — guard failed!")
print(f"   lying-discharge witness status: {','.join(witness) if witness else 'MISSING'}")
if reasons:
    first_reason = reasons[0][:120]
    print(f"   refusal reason: {first_reason}")
print(f"   LYING-DISCHARGE REFUSED: guard works")
PY
else
  echo "   (lying resolver compile skipped — LyingResolver.class not built)"
fi

echo "== bad: PASS =="

echo
echo "== java-witness-recompute showcase: PASS =="
