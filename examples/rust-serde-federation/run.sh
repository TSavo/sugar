#!/usr/bin/env bash
# rust-serde-federation: serde_json as a VENDOR, a separate rust CONSUMER,
# sat/unsat by conjoining the vendor's sworn fact with the consumer's OWN
# fact through the staged .proof -- the rust parity analog of
# examples/python-base64-federation, and the fixture
# editors/vscode-sugar/test/rust-prove-e2e.test.js drives.
#
#   VENDOR (vendor/src/lib.rs): a real serde_json 1.0.150 exact vendor row,
#           `serde_json::to_string(&true).unwrap() == "true"`
#           (tests/test.rs::test_write_bool via test_encode_ok). `sugar mint`
#           lifts the test assertion + packages it into a content-addressed
#           .proof.
#   CONSUMER stages the vendor .proof in .sugar/imports/ and writes its OWN
#           test asserting the SAME callsite.
#
#   GOOD consumer: asserts == "true" (agrees)    -> refused (stated cannot
#                  corroborate stated; matches the vendor showcase's own law).
#   BAD  consumer: asserts == "false" (lies)     -> UNSAT -> unsatisfied,
#                  anchored at the CONSUMER's OWN tests/consumer_test.rs line
#                  (see sugar-verifier/src/consistency.rs's PROJECT-LOCAL
#                  PREFERENCE: the consumer ships no `src/lib.rs`, so the
#                  vendor's own `src/lib.rs` locus never collides on disk).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
BIN="$("$REPO/bin/sugarbin" --profile release)"
BIN_DIR="$(dirname "$BIN")"

echo "== resolve the CLI + rust lifters via sugarbin =="
for b in rust_test_assertions_rpc witness_rpc discharge_cli sugar-ir-smt-lib sugar-walk-rpc; do
  "$REPO/bin/sugarbin" --profile release --bin "$b" >/dev/null || { echo "FAIL: $b build"; exit 1; }
done
command -v z3 >/dev/null 2>&1 || { echo "FAIL: z3 is required"; exit 1; }

for d in vendor consumer-good consumer-bad; do
  sed "s#@BIN_DIR@#$BIN_DIR#g" "$HERE/$d/.sugar/lift/rust-test-assertions/manifest.toml.in" \
    > "$HERE/$d/.sugar/lift/rust-test-assertions/manifest.toml"
  sed "s#@BIN_DIR@#$BIN_DIR#g" "$HERE/$d/.sugar/lift/rust-cargo-test-witness/manifest.toml.in" \
    > "$HERE/$d/.sugar/lift/rust-cargo-test-witness/manifest.toml"
done

# The rust-kit pre-flight ("Rust workspace detected ... no Sugar Rust kit
# component claimed it") queries the COMPONENT registry, not the project-local
# .sugar/lift/<surface>/manifest.toml above. The repo's own top-level
# `.sugar/components/` (discovered exe-relative regardless of cwd -- see
# component_plan.rs::exe_relative_component_roots) ships dev/debug-profile
# command paths; a LATER-discovered root by the same component name wins, so a
# hermetic SUGAR_COMPONENT_PATH registry with the REAL release paths overrides
# it and reliably claims the workspace.
COMPONENTS="$HERE/.sugar-components-runtime"
rm -rf "$COMPONENTS"
write_component() {
  local name="$1"; shift
  mkdir -p "$COMPONENTS/$name"
  local cmd=""
  for tok in "$@"; do cmd+="\"$tok\", "; done
  cmd="${cmd%, }"
  cat > "$COMPONENTS/$name/manifest.toml" <<TOML
name = "$name"
version = "0.1.0"
protocol_version = "sugar-component/1"
command = [$cmd]
TOML
}
write_component "rust-walk" "$BIN_DIR/sugar-walk-rpc" "--rpc"
write_component "rust-test-assertions" "$BIN_DIR/rust_test_assertions_rpc"
write_component "rust-cargo-test-witness" "$BIN_DIR/witness_rpc"
write_component "ir-compiler-smt-lib" "$BIN_DIR/sugar-ir-smt-lib"
export SUGAR_COMPONENT_PATH="$COMPONENTS"

VENDOR="$HERE/vendor"

clean() { local d="$1"; find "$d" -maxdepth 1 -name 'blake3-512_*.proof' -delete 2>/dev/null
  rm -rf "$d/.sugar/runs" "$d/.sugar/witnesses" "$d/target" 2>/dev/null
  rm -f "$d"/.prove*.json "$d"/.prove*.raw 2>/dev/null; }

echo
echo "==================== VENDOR mints its .proof ===================="
clean "$VENDOR"
(cd "$VENDOR" && "$BIN" mint --out . --quiet) >/dev/null || { echo "FAIL: vendor mint"; exit 1; }
VENDOR_PROOF="$(ls "$VENDOR"/blake3-512_*.proof 2>/dev/null | head -1)"
[ -f "$VENDOR_PROOF" ] || { echo "FAIL: vendor produced no .proof"; exit 1; }
echo "vendor .proof: $(basename "$VENDOR_PROOF")"

check_consumer() {
  local twin="$1" expect="$2"
  local dir="$HERE/consumer-$twin"
  echo
  echo "==================== CONSUMER: $twin (expect: $expect) ===================="
  clean "$dir"
  mkdir -p "$dir/.sugar/imports"
  rm -f "$dir/.sugar/imports/"*.proof
  cp "$VENDOR_PROOF" "$dir/.sugar/imports/"
  (cd "$dir" && "$BIN" mint --out . --quiet) >/dev/null || { echo "FAIL($twin): consumer mint"; return 1; }
  (cd "$dir" && "$BIN" prove --allow-failed-components . --json) >"$dir/.prove.raw" 2>&1
  local rc=$?
  python3 - "$dir/.prove.raw" "$twin" "$expect" "$rc" <<'PY'
import json, re, sys
raw, twin, expect, rc = sys.argv[1:5]
text = re.sub(r"\x1b\[[0-9;]*m", "", open(raw, encoding="utf-8", errors="replace").read())
dec = json.JSONDecoder()
doc = None
for i, ch in enumerate(text):
    if ch != "{":
        continue
    try:
        obj, _ = dec.raw_decode(text[i:])
    except Exception:
        continue
    if isinstance(obj, dict) and "rows" in obj:
        doc = obj
        break
if doc is None:
    print(f"FAIL({twin}): no JSON receipt"); raise SystemExit(1)
rows = [r for r in doc["rows"] if "unwrap#euf" in str(r.get("property", "")) and "b:true" in str(r.get("property",""))]
if not rows:
    print(f"FAIL({twin}): no matching consistency row"); raise SystemExit(1)
row = rows[0]
print(f"  consumer conjoin row: {row.get('status')}  file={row.get('file')} line={row.get('line')}")
print(f"  reason: {row.get('reason','')[:140]}")
if expect == "REFUSE":
    ok = row.get("status") == "refused"
else:
    ok = row.get("status") == "unsatisfied" and row.get("file", "").endswith("tests/consumer_test.rs") and int(rc) != 0
print(("OK" if ok else "FAIL") + f"({twin}): expected {expect}")
raise SystemExit(0 if ok else 1)
PY
}

fail=0
check_consumer good REFUSE || fail=1
check_consumer bad  UNSAT || fail=1

echo
if [ "$fail" -ne 0 ]; then echo "==== rust-serde-federation: FAIL ===="; exit 1; fi
echo "==== rust-serde-federation: PASS ===="
echo "A rust consumer's claim about a real serde_json vendor row is decided"
echo "refused/unsatisfied by conjoining the vendor's sworn fact (from the staged"
echo ".proof) with the consumer's own fact -- no re-derivation."
