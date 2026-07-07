#!/usr/bin/env bash
# rust-forall-universe-federation: a rust VENDOR whose only testimony is a
# lifted forall UNIVERSE, and a separate rust CONSUMER decided against it --
# the rust parity of examples/python-base64-federation's CASE 2 (vendor
# universe + DERIVED vendor fact), on the bounded-loop law the rust kit
# already lifts end-to-end (see
# implementations/rust/sugar-cli/tests/cmd_verify_lifted_forall_universe.rs).
#
#   VENDOR (vendor/): `blockfmt::block_width`, a real function. Its test swears
#                 the LAW `for x in 0..8 { assert_eq!(block_width(x), 64) }`.
#                 `sugar mint` lifts it to the universe
#                 `forall x in 0..8. block_width(x) == 64` and packages it into
#                 a content-addressed .proof. NO per-point vector for x=3 or
#                 x=5 exists anywhere.
#
#   CONSUMER stages the vendor .proof in .sugar/imports/ and asserts a point
#   the vendor never named:
#     BAD  consumer: block_width(3) == 128 (lie)  -> z3 instantiates the
#                    universe at 3 -> UNSAT -> unsatisfied, anchored at the
#                    CONSUMER's OWN tests/consumer_test.rs line. The squiggle
#                    detail carries the universe (vendorUniverseFol) AND the
#                    DERIVED vendor fact (vendorFactFol: block_width(3) = 64,
#                    computed by z3.model from the universe, never executed).
#     GOOD consumer: block_width(5) == 64 (true)  -> DISCHARGED (the
#                    floor-derived universe is independent-KIND testimony,
#                    #3445 Part-2 ruling).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BIN="$("$REPO/bin/sugarbin" --profile release)"

echo "== resolve the CLI + rust lifters via sugarbin =="
for b in rust_test_assertions_rpc witness_rpc discharge_cli sugar-ir-smt-lib sugar-walk-rpc; do
  "$REPO/bin/sugarbin" --profile release --bin "$b" >/dev/null || { echo "FAIL: $b build"; exit 1; }
done
# The CLI may resolve to the stamp-named prebuilt cache; the lifter binaries
# always land in the workspace target dir -- take BIN_DIR from one of them.
BIN_DIR="$(dirname "$("$REPO/bin/sugarbin" --profile release --bin rust_test_assertions_rpc 2>/dev/null | tail -1)")"
command -v z3 >/dev/null 2>&1 || { echo "FAIL: z3 is required"; exit 1; }

for d in vendor consumer-good consumer-bad; do
  sed "s#@BIN_DIR@#$BIN_DIR#g" "$HERE/$d/.sugar/lift/rust-test-assertions/manifest.toml.in" \
    > "$HERE/$d/.sugar/lift/rust-test-assertions/manifest.toml"
  sed "s#@BIN_DIR@#$BIN_DIR#g" "$HERE/$d/.sugar/lift/rust-cargo-test-witness/manifest.toml.in" \
    > "$HERE/$d/.sugar/lift/rust-cargo-test-witness/manifest.toml"
done

# Hermetic component registry with the REAL release paths (overrides the
# repo-root dev-profile registry -- see rust-serde-federation/run.sh).
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
  # Disk-load face (#3809): when a Cargo.toml is present, `sugar prove` prefers
  # the kit fold path (re-lift). For this federation receipt the sealed
  # consumer + vendor .proof files are the authority -- prove them in a
  # Cargo.toml-free sandbox so solve_project loads the minted envelopes.
  local sandbox="$dir/.prove-sandbox"
  rm -rf "$sandbox"
  mkdir -p "$sandbox/.sugar/imports"
  local consumer_proof
  consumer_proof="$(ls "$dir"/blake3-512_*.proof 2>/dev/null | head -1)"
  [ -f "$consumer_proof" ] || { echo "FAIL($twin): consumer mint produced no .proof"; return 1; }
  cp "$consumer_proof" "$sandbox/"
  cp "$dir/.sugar/imports/"*.proof "$sandbox/.sugar/imports/" 2>/dev/null || true
  set +e
  (cd "$sandbox" && "$BIN" prove --allow-failed-components . --json) >"$dir/.prove.raw" 2>&1
  local rc=$?
  set -e
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
rows = [r for r in doc["rows"]
        if "block_width#euf#" in str(r.get("property", ""))
        and str(r.get("file", "")).endswith("tests/consumer_test.rs")]
if not rows:
    print(f"FAIL({twin}): no consumer #euf# row"); raise SystemExit(1)
row = rows[0]
print(f"  consumer row: {row.get('status')}  @ {row.get('file','')}:{row.get('line','')}")
ver = row.get("verification") or {}
uni = ver.get("vendorUniverseFol", "")
fact = ver.get("vendorFactFol", "")
print(f"  vendorUniverseFol: {uni[:120]}")
print(f"  vendorFactFol:     {fact[:120]}")
ok = True
if expect == "UNSAT":
    ok &= row.get("status") == "unsatisfied" and int(rc) != 0
    # CASE 2 receipts: the squiggle carries the vendor UNIVERSE (a forall law)
    # and the DERIVED vendor fact at the consumer's own argument.
    ok &= "∀" in uni or "forall" in uni.lower()
    ok &= "64" in fact and "block_width" in fact
else:
    ok &= row.get("status") == "discharged"
print(("OK" if ok else "FAIL") + f"({twin}): expected {expect}")
raise SystemExit(0 if ok else 1)
PY
}

fail=0
check_consumer good DISCHARGED || fail=1
check_consumer bad  UNSAT || fail=1

echo
if [ "$fail" -ne 0 ]; then echo "==== rust-forall-universe-federation: FAIL ===="; exit 1; fi
echo "==== rust-forall-universe-federation: PASS ===="
echo "A rust consumer's point-claim is decided by the vendor's lifted forall"
echo "UNIVERSE from the staged .proof: the lie is UNSAT at the consumer's own"
echo "line, and the vendor's correct value is DERIVED by z3.model -- never executed."
