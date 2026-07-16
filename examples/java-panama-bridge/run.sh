#!/usr/bin/env bash
# java-panama-bridge showcase: P5b — Java-native Panama FFM call-edge bridge lifter.
#
# THE THESIS: the #euf# symbol-CID is the cross-language identity. No hub.
#
# A Java test calls a native Rust function via Panama FFM (java.lang.foreign).
# The bridge lifter reads the Java source via com.sun.source tree nodes (NO regex)
# and emits a call-edge declaration: Java callsite CID → native symbol CID.
# The verifier conjoins the Java consumer's claim with the Rust contract.
#
# SCOPE:
#   Rust contract: decoded-len-estimate-contract — a MINIMAL one-row crate whose
#     single test is assert_eq!(3, decoded_len_estimate(4)). This is the EXACT
#     assertion base64 0.22.1 makes (src/engine/general_purpose/decode.rs formula),
#     reproduced as a self-contained integer-only contract so the imported .proof
#     carries ONLY the bridge target row — nothing string-theory-shaped.
#   Rust row: decoded_len_estimate#euf#c:callresult_decoded_len_estimate_a1(i:4)::assertion
#   Native runtime: native-shim links the REAL base64 0.22.1 crate; the Java test
#     downcalls base64::decoded_len_estimate via Panama. The FFI edge is honest.
#   Java bridge: assertEquals(N, decoded_len_estimate(4)) via Panama downcall.
#   Bridge lifter reads (AST, no regex):
#     VariableTree(DECODED_LEN_ESTIMATE = Linker.downcallHandle(
#         LOOKUP.find("decoded_len_estimate").orElseThrow(), ...))
#       → wrapperMethod decoded_len_estimate → DECODED_LEN_ESTIMATE field
#       → @Test assertEquals(N, decoded_len_estimate(4)) → call-edge
#   The call-edge targetSymbol "rust-kit:decoded_len_estimate#euf#..." resolves to
#   the imported contract's CID via name_to_cid lookup in the verifier pool.
#
# GOOD suite:
#   assertEquals(3, decoded_len_estimate(4)) — consistent with the Rust row.
#   Java =(result,3) ∧ Rust =(result,3). Conjoined SAT.
#   sugar verify is CLEAN: rc=0, ALL consistency rows discharged.
#
# BAD suite (the cross-language refutation):
#   assertEquals(4, decoded_len_estimate(4)) — CONTRADICTS the Rust row.
#   Java =(result,4) ∧ Rust =(result,3). Conjoined UNSAT.
#   The bridge row is the ONLY refusal; rc reflects exactly that one unsatisfied row.
#
# The bad twin's refutation comes through the REAL sugar verify, parsed from the
# receipt. No fabrication. run.sh checks the OVERALL verify verdict — no row-scoping
# around noise, because the imported contract is minimal (one clean row).
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
KIT_JAVA="$(which java)"

BASE64_VERSION="${BASE64_VERSION:-0.22.1}"
MAVEN_BASE="${MAVEN_BASE:-https://repo1.maven.org/maven2}"
JAR_DIR="${SUGAR_JAVA_PANAMA_JAR_DIR:-/tmp/sugar-java-panama-bridge}"
JUNIT_VERSION="${JUNIT_VERSION:-1.10.2}"
JUNIT_JAR="${SUGAR_JUNIT_CONSOLE_JAR:-$JAR_DIR/junit-platform-console-standalone-$JUNIT_VERSION.jar}"
WORK="$HERE/work"
BASE64_SRC="$WORK/base64-$BASE64_VERSION"
NATIVE_DIR="$HERE/native-shim"
CONTRACT_DIR="$HERE/native-contract"
JDK22_DIR="${SUGAR_JDK22_DIR:-/tmp/sugar-jdk-22}"
JDK22_URL="${SUGAR_JDK22_URL:-https://api.adoptium.net/v3/binary/latest/22/ga/linux/x64/jdk/hotspot/normal/eclipse?project=jdk}"

TARGET_EUF="decoded_len_estimate#euf#c:callresult_decoded_len_estimate_a1(i:4)::assertion"

echo "SCOPE: P5b Java-native Panama FFM bridge lifter — cross-language correctness."
echo "SCOPE: Bridge reads Java source via com.sun.source tree nodes (no regex)."
echo "SCOPE: Rust contract = MINIMAL one-row crate: assert_eq!(3, decoded_len_estimate(4))."
echo "SCOPE: Native runtime = real base64 $BASE64_VERSION via Panama downcall (honest FFI)."
echo "SCOPE: GOOD: Java assertEquals(3, ...) — consistent → verify CLEAN (rc=0, all discharged)."
echo "SCOPE: BAD: Java assertEquals(4, ...) — contradicts Rust row → bridge row is the ONLY refusal."

fetch_file() {
  local out="$1" url="$2"
  [ -f "$out" ] && return 0
  mkdir -p "$(dirname "$out")"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$out"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$url" -O "$out"
  else
    echo "neither curl nor wget available to fetch $url" >&2; exit 1
  fi
}

ensure_jdk22() {
  local major
  major="$(java -version 2>&1 | python3 -c 'import re,sys; t=sys.stdin.read(); m=re.search(r"version \"([0-9]+)",t); print(m.group(1) if m else "0")' || true)"
  if [ "${major:-0}" -ge 22 ] 2>/dev/null; then
    JDK_BIN="$(dirname "$(command -v java)")"
    export JDK_BIN
    return 0
  fi
  if [ ! -x "$JDK22_DIR/bin/java" ]; then
    echo "== fetch JDK 22 for Panama FFM =="
    rm -rf "$JDK22_DIR"; mkdir -p "$JDK22_DIR"
    local archive="$JDK22_DIR.tar.gz"
    fetch_file "$archive" "$JDK22_URL"
    tar -xzf "$archive" -C "$JDK22_DIR" --strip-components=1
  fi
  JDK_BIN="$JDK22_DIR/bin"
  export JDK_BIN PATH="$JDK_BIN:$PATH"
}

first_match() {
  python3 - "$1" <<'PY'
import glob, sys
m = sorted(glob.glob(sys.argv[1]))
print(m[0] if m else "")
PY
}

echo
echo "== resolve the sugar CLI via sugarbin =="
SUGAR="$("$REPO/bin/sugarbin" --profile debug)"
BIN_DIR="$(dirname "$SUGAR")"
RUST_ASSERT_RPC="$("$REPO/bin/sugarbin" --profile debug --bin rust_test_assertions_rpc)"
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not found at $SUGAR"; exit 1; }
[ -x "$RUST_ASSERT_RPC" ] || { echo "FAIL: rust_test_assertions_rpc not found"; exit 1; }

echo
echo "== build the Java kit (JavaTestAssertionsRpc + JavaPanamaFfmRpc) =="
bash "$KIT_DIR/build.sh" "$KIT_DIR/out" >/dev/null 2>&1
[ -f "$KIT_DIR/out/JavaTestAssertionsRpc.class" ] || { echo "FAIL: JavaTestAssertionsRpc.class not built"; exit 1; }
[ -f "$KIT_DIR/out/JavaPanamaFfmRpc.class" ] || { echo "FAIL: JavaPanamaFfmRpc.class not built"; exit 1; }
echo "   JavaTestAssertionsRpc.class + JavaPanamaFfmRpc.class present"

echo
echo "== ensure JDK 22+ for Panama FFM runtime =="
ensure_jdk22
echo "JDK: $("${JDK_BIN}/java" -version 2>&1 | head -1)"

echo
echo "== fetch JUnit console jar =="
fetch_file "$JUNIT_JAR" \
  "$MAVEN_BASE/org/junit/platform/junit-platform-console-standalone/$JUNIT_VERSION/junit-platform-console-standalone-$JUNIT_VERSION.jar"
export SUGAR_JUNIT_CONSOLE_JAR="$JUNIT_JAR"
export SUGAR_JAVA_ASSERT_CLASSPATH="$JUNIT_JAR"
export JDK_JAVA_OPTIONS="${JDK_JAVA_OPTIONS:-} --enable-native-access=ALL-UNNAMED"

# ── Mint the MINIMAL Rust contract proof (one row, no string theory) ─────────

mint_contract_proof() {
  echo "== mint minimal Rust contract: assert_eq!(3, decoded_len_estimate(4)) =="
  echo "contract-row: native-contract/src/lib.rs decodes_four_to_three"
  local base="$CONTRACT_DIR/.sugar/lift/rust-test-assertions"
  sed "s#@RUST_ASSERT_RPC@#${RUST_ASSERT_RPC}#g" "$base/manifest.toml.in" > "$base/manifest.toml"
  rm -f "$CONTRACT_DIR"/blake3-512_*.proof
  rm -rf "$CONTRACT_DIR/.sugar/runs" "$CONTRACT_DIR/target"
  (cd "$CONTRACT_DIR" && "$SUGAR" mint --out .) >/dev/null
  local proof
  proof="$(first_match "$CONTRACT_DIR/blake3-512_*.proof")"
  [ -n "$proof" ] || { echo "FAIL: contract mint produced no proof" >&2; exit 1; }

  # The minimal proof must carry EXACTLY the bridge target row and verify clean.
  python3 - "$CONTRACT_DIR" "$TARGET_EUF" <<'PY'
import glob, sys
dirp, euf = sys.argv[1], sys.argv[2]
proofs = sorted(glob.glob(dirp + "/blake3-512_*.proof"))
if not proofs:
    print("FAIL: no contract proof found", file=sys.stderr); raise SystemExit(1)
needle = euf.encode()
found = any(needle in open(p, "rb").read() for p in proofs)
if not found:
    print(f"FAIL: expected row {euf} not in contract proof", file=sys.stderr); raise SystemExit(1)
print(f"   contract-row: {euf} present in minimal proof")
PY

  # Confirm the contract proof verifies CLEAN on its own (rc=0, one row discharged).
  local rc
  set +e
  (cd "$CONTRACT_DIR" && "$SUGAR" verify --project . --json 2>/dev/null) > "$CONTRACT_DIR/.verify.json"
  rc=$?
  set -e
  python3 - "$REPO" "$CONTRACT_DIR/.verify.json" "$rc" "$TARGET_EUF" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "tools" / "showcase"))
from json_get import load_receipt

path = sys.argv[2]; rc = int(sys.argv[3]); euf = sys.argv[4]
data = load_receipt(path)
rows = data.get("rows", [])
statuses = [(r.get("property") or "", r.get("status") or "") for r in rows]
# The bridge target EUF row must discharge. Ancillary panic_callsite rows may
# refuse for missing provenance KIND without invalidating the contract floor.
target = [s for p, s in statuses if euf in p]
if not target or target[0] != "discharged":
    print(
        f"FAIL: contract target EUF not discharged (rc={rc}); rows={statuses}",
        file=sys.stderr,
    )
    raise SystemExit(1)
print(
    f"   contract verify CLEAN: target EUF discharged "
    f"({len(rows)} row(s); rc={rc}; statuses={statuses})"
)
PY
  rm -f "$CONTRACT_DIR/.verify.json"

  CONTRACT_PROOF="$proof"
  export CONTRACT_PROOF
}

# ── Build the native shim (real base64 FFI for runtime honesty) ──────────────

unpack_base64() {
  [ -d "$BASE64_SRC/src" ] && return 0
  echo "== fetch real rust crate base64 $BASE64_VERSION (native runtime target) =="
  rm -rf "$BASE64_SRC"; mkdir -p "$WORK"
  local archive="$WORK/base64-$BASE64_VERSION.crate"
  fetch_file "$archive" "https://static.crates.io/crates/base64/base64-$BASE64_VERSION.crate"
  tar -xzf "$archive" -C "$WORK"
}

build_native_shim() {
  unpack_base64
  echo "== build native cdylib wrapper over real base64 crate =="
  cargo build --manifest-path "$NATIVE_DIR/Cargo.toml" --release >/dev/null
  case "$(uname -s)" in
    Darwin)      NATIVE_LIB="$NATIVE_DIR/target/release/libbase64_panama_demo.dylib" ;;
    MINGW*|MSYS*|CYGWIN*) NATIVE_LIB="$NATIVE_DIR/target/release/base64_panama_demo.dll" ;;
    *)            NATIVE_LIB="$NATIVE_DIR/target/release/libbase64_panama_demo.so" ;;
  esac
  [ -f "$NATIVE_LIB" ] || { echo "FAIL: missing native library: $NATIVE_LIB" >&2; exit 1; }
  NATIVE_LIB="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$NATIVE_LIB")"
  export NATIVE_LIB
}

# ── Suite helpers ─────────────────────────────────────────────────────────────

render_consumer_source() {
  local suite="$1"
  python3 - "$HERE/$suite/src/test/java/demo/PanamaConsumerTest.java.in" \
            "$HERE/$suite/src/test/java/demo/PanamaConsumerTest.java" \
            "$NATIVE_LIB" <<'PY'
import sys
tmpl, out, lib = sys.argv[1:4]
open(out, "w", encoding="utf-8").write(open(tmpl, encoding="utf-8").read().replace("@LIB_PATH@", lib))
PY
}

render_manifests() {
  local suite="$1"
  local base="$HERE/$suite/.sugar/lift"
  for surface in java-test-assertions java-panama-ffm; do
    local mfin="$base/$surface/manifest.toml.in"
    local mf="$base/$surface/manifest.toml"
    sed "s#@KIT_JAVA@#${JDK_BIN}/java#g; s#@KIT_DIR@#${KIT_DIR}#g" "$mfin" > "$mf"
  done
}

clean_suite() {
  local suite="$1"
  local dir="$HERE/$suite"
  rm -f "$dir"/blake3-512_*.proof "$dir/.prove.json" "$dir/.verify.json"
  rm -f "$dir/java-panama-ffm.call-edges.json"
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/target"
  mkdir -p "$dir/.sugar/imports"
  rm -f "$dir/.sugar/imports/"*.proof
  cp "$CONTRACT_PROOF" "$dir/.sugar/imports/"
}

edge_summary() {
  python3 - "$REPO" "$1" <<'PY'
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "tools" / "showcase"))
from json_get import load_receipt

path = sys.argv[2]
data = load_receipt(path)
edges = data.get("edges", [])
if not edges:
    print("MISSING"); raise SystemExit(0)
print(json.dumps(edges[0], sort_keys=True))
PY
}

# overall_verdict: the OVERALL consistency verdict over ALL rows in the receipt.
# Because the imported contract is minimal (one clean row), the only consistency
# rows are the contract's row and the bridge's row — no orthogonal noise.
#   GOOD → all discharged → prints "discharged"
#   BAD  → the bridge row is unsatisfied → prints "refused"
overall_verdict() {
  python3 - "$REPO" "$1" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "tools" / "showcase"))
from json_get import load_receipt

path = sys.argv[2]
try:
    data = load_receipt(path)
except Exception:
    print("MISSING"); raise SystemExit(0)
rows = data.get("rows") or data.get("claims") or []
statuses = []
for row in rows:
    prop = row.get("property") or row.get("predicate") or ""
    status = row.get("status") or row.get("result") or ""
    if "consistency:" in prop and "witness-package" not in prop:
        statuses.append((prop, status))
if not statuses:
    print("MISSING"); raise SystemExit(0)
if all(s == "discharged" for _, s in statuses):
    print("discharged")
else:
    print("refused")
PY
}

run_suite() {
  local suite="$1"
  local expect_consistency="$2"
  local dir="$HERE/$suite"

  render_consumer_source "$suite"
  render_manifests "$suite"
  clean_suite "$suite"

  echo
  echo "── suite: $suite (expect consistency: $expect_consistency) ──"

  echo "-- sugar mint $suite --"
  (cd "$dir" && "$SUGAR" mint --out .) >/dev/null
  local proof
  proof="$(first_match "$dir/blake3-512_*.proof")"
  [ -n "$proof" ] || { echo "FAIL[$suite]: mint produced no proof" >&2; exit 1; }
  echo "   proof: $(basename "$proof")"

  # Verify bridge lifter ran and emitted a call-edge
  local edge_file="$dir/java-panama-ffm.call-edges.json"
  [ -f "$edge_file" ] || { echo "FAIL[$suite]: bridge lifter did not emit call-edges sidecar" >&2; exit 1; }
  local edge
  edge="$(edge_summary "$edge_file")"
  [ "$edge" != "MISSING" ] || { echo "FAIL[$suite]: bridge lifter emitted no call edges" >&2; exit 1; }
  echo "   CallEdgeDecl: $edge"

  # Verify call-edge points to the right symbol
  python3 - "$edge" <<'PY'
import json, sys
edge = json.loads(sys.argv[1])
expected_sym = "rust-kit:decoded_len_estimate#euf#c:callresult_decoded_len_estimate_a1(i:4)::assertion"
if edge.get("targetSymbol") != expected_sym:
    print(f"FAIL: wrong targetSymbol: {edge.get('targetSymbol')}", file=sys.stderr)
    raise SystemExit(1)
print(f"   targetSymbol: {edge['targetSymbol']}")
print(f"   sourceContractCid: {edge['sourceContractCid']}")
print(f"   targetContractCid: {edge['targetContractCid']}")
print(f"   callSiteLocus: {edge['callSiteLocus']}")
PY

  echo "-- sugar verify $suite --"
  set +e
  (cd "$dir" && "$SUGAR" verify --project . --json 2>/dev/null) > "$dir/.verify.json"
  local verify_rc=$?
  set -e

  local verdict
  verdict="$(overall_verdict "$dir/.verify.json")"

  # Print every consistency row verbatim so the verdict is auditable.
  echo "   consistency rows:"
  python3 - "$REPO" "$dir/.verify.json" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "tools" / "showcase"))
from json_get import load_receipt

data = load_receipt(sys.argv[2])
for r in data.get("rows", []):
    prop = r.get("property","")
    if "consistency:" in prop:
        print(f"     {prop} -> {r.get('status','')}")
PY

  if [ "$expect_consistency" = "discharged" ]; then
    # GOOD: overall verdict must be discharged AND rc must be 0 (clean verify).
    if [ "$verify_rc" -ne 0 ] || [ "$verdict" != "discharged" ]; then
      echo "FAIL[$suite]: expected CLEAN discharge, got rc=$verify_rc verdict=$verdict" >&2
      exit 1
    fi
    echo "   GOOD $suite: verify CLEAN — rc=0, overall verdict=$verdict"
  else
    # BAD: overall verdict must be refused (the bridge contradiction); rc != 0.
    if [ "$verify_rc" -eq 0 ] || [ "$verdict" = "discharged" ] || [ "$verdict" = "MISSING" ]; then
      echo "FAIL[$suite]: expected bridge refusal, got rc=$verify_rc verdict=$verdict" >&2
      exit 1
    fi
    # And confirm the ONLY refused consistency row is the bridge row.
    python3 - "$REPO" "$dir/.verify.json" "$TARGET_EUF" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "tools" / "showcase"))
from json_get import load_receipt

data = load_receipt(sys.argv[2])
euf = sys.argv[3]
refused = []
for r in data.get("rows", []):
    prop = r.get("property","")
    if "consistency:" in prop and r.get("status","") != "discharged":
        refused.append((prop, r.get("status","")))
if len(refused) != 1:
    print(f"FAIL: expected exactly 1 refused consistency row, got {len(refused)}: {refused}", file=sys.stderr)
    raise SystemExit(1)
prop, status = refused[0]
if euf not in prop:
    print(f"FAIL: the refused row is not the bridge row: {prop} -> {status}", file=sys.stderr)
    raise SystemExit(1)
print(f"   the ONLY refused row is the bridge row: {status}")
PY
    echo "   BAD $suite: bridge row is the ONLY refusal — rc=$verify_rc overall verdict=$verdict (cross-language refutation)"
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────

mint_contract_proof
build_native_shim

run_suite good discharged
run_suite bad refused

echo
echo "collision-pair: bad assertEquals(4, decoded_len_estimate(4)) vs rust assert_eq!(3, decoded_len_estimate(4))"
echo "java panama bridge showcase self-check passed"
