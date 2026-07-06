#!/usr/bin/env bash
# base64 0.22.1 showcase: real base64 vendor rows lifted as Rust assertion
# consistency contracts and witnessed by re-running cargo test.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"

echo "SCOPE: base64 0.22.1 exact vendor rows from tests/encode.rs::encoded_len_unpadded/encoded_len_padded and src/decode.rs::decoded_len_est."
echo "SCOPE: GOOD claims are point-wise exact integer-scalar rows over the public encoded_len/decoded_len_estimate fns; BAD is a contradiction twin."
echo "SCOPE: residuals = exact encode/decode byte-vector rows (STANDARD.encode(b\"foo\")==\"Zm9v\", decode(...)==b\"...\"): NOT liftable, the rust assertion lifter has no Lit::ByteStr term case (translate_lit covers Int/Float/Str/Char/Bool only), so every byte-string-literal vector is released to layer 0; plus roundtrip-random tests and the 256-byte encode_all_bytes vector."

echo "== build the CLI + Rust assertion, body, implication, and cargo-test witness lifters =="
cargo build --manifest-path "$RUST/Cargo.toml" \
  -p sugar-cli --bin sugar \
  -p sugar-walk --bin sugar-walk-rpc \
  -p sugar-lift-rust-tests --bin rust_test_assertions_rpc \
  -p sugar-lift-rust-cargo-test-witness --bin witness_rpc \
  -p sugar-lift-rust-cargo-test-witness --bin discharge_cli \
  -p sugar-ir-compiler-smt-lib --bin sugar-ir-smt-lib \
  -p sugar-ir-compiler-coq --bin sugar-ir-coq \
  -p sugar-ir-compiler-lean --bin sugar-ir-lean \
  -p sugar-ir-compiler-maude --bin sugar-ir-maude >/dev/null

[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not built at $SUGAR"; exit 1; }
[ -x "$BIN_DIR/sugar-walk-rpc" ] || { echo "FAIL: sugar-walk-rpc not built"; exit 1; }
[ -x "$BIN_DIR/rust_test_assertions_rpc" ] || { echo "FAIL: rust_test_assertions_rpc not built"; exit 1; }
[ -x "$BIN_DIR/witness_rpc" ] || { echo "FAIL: witness_rpc not built"; exit 1; }
[ -x "$BIN_DIR/discharge_cli" ] || { echo "FAIL: discharge_cli not built"; exit 1; }
[ -x "$BIN_DIR/sugar-ir-smt-lib" ] || { echo "FAIL: sugar-ir-smt-lib not built"; exit 1; }
[ -x "$BIN_DIR/sugar-ir-coq" ] || { echo "FAIL: sugar-ir-coq not built"; exit 1; }
[ -x "$BIN_DIR/sugar-ir-lean" ] || { echo "FAIL: sugar-ir-lean not built"; exit 1; }
[ -x "$BIN_DIR/sugar-ir-maude" ] || { echo "FAIL: sugar-ir-maude not built"; exit 1; }

prepare_base64_vendor_source() {
  local suite_dir="$1"
  local cargo_home="${CARGO_HOME:-$HOME/.cargo}"
  local src_root=""
  local candidate

  cargo fetch --manifest-path "$suite_dir/Cargo.toml" >/dev/null
  for candidate in "$cargo_home"/registry/src/*/base64-0.22.1; do
    [ -d "$candidate" ] || continue
    src_root="$candidate"
    break
  done
  [ -n "$src_root" ] || { echo "FAIL: could not find downloaded base64-0.22.1 source under $cargo_home/registry/src"; exit 1; }

  mkdir -p "$suite_dir/vendor"
  if [ -L "$suite_dir/vendor/base64-0.22.1" ] || [ -e "$suite_dir/vendor/base64-0.22.1" ]; then
    rm -f "$suite_dir/vendor/base64-0.22.1"
  fi
  [ ! -e "$suite_dir/vendor/base64-0.22.1" ] || { echo "FAIL: $suite_dir/vendor/base64-0.22.1 exists and is not a symlink"; exit 1; }
  ln -s "$src_root" "$suite_dir/vendor/base64-0.22.1"
}

assert_zero_config_suite() {
  local suite_dir="$1"
  local cursor="$suite_dir"
  if [ -d "$suite_dir/.sugar/lift" ]; then
    find "$suite_dir/.sugar/lift" -name 'manifest.toml' -delete
  fi
  [ ! -e "$suite_dir/.sugar/config.toml" ] || {
    echo "FAIL: $suite_dir must run without .sugar/config.toml"
    exit 1
  }
  if [ -d "$suite_dir/.sugar/lift" ] && find "$suite_dir/.sugar/lift" -name 'manifest.toml*' -print -quit | grep -q .; then
    echo "FAIL: $suite_dir must run without .sugar/lift/*/manifest.toml*"
    exit 1
  fi
  while :; do
    if [ -d "$cursor/.sugar/ir-compilers" ] && find "$cursor/.sugar/ir-compilers" -name 'manifest.toml' -print -quit | grep -q .; then
      echo "FAIL: $suite_dir must run without inherited .sugar/ir-compilers/*/manifest.toml"
      exit 1
    fi
    [ "$cursor" = "$REPO" ] && break
    local next
    next="$(dirname "$cursor")"
    [ "$next" != "$cursor" ] || break
    cursor="$next"
  done
  if [ -d "${HOME:-}/.config/sugar/ir-compilers" ] && find "${HOME:-}/.config/sugar/ir-compilers" -name 'manifest.toml' -print -quit | grep -q .; then
    echo "FAIL: $suite_dir must run without user .config/sugar/ir-compilers/*/manifest.toml"
    exit 1
  fi
}

for suite in good bad; do
  prepare_base64_vendor_source "$HERE/$suite"
  assert_zero_config_suite "$HERE/$suite"
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" "$HERE/$suite/.sugar/witnesses" "$HERE/$suite/target" 2>/dev/null || true
  rm -f "$HERE/$suite"/.prove*.json "$HERE/$suite"/.verify*.json "$HERE/$suite/Cargo.lock" 2>/dev/null || true
done

pyget() { python3 "$REPO/tools/showcase/json_get.py" "$1" "$2"; }

write_lying_discharge() {
  local script="$1"
  mkdir -p "$(dirname "$script")"
  cat > "$script" <<'SH'
#!/usr/bin/env sh
echo '{"verdict":"DISCHARGED","reason":"lying discharge regression"}'
SH
  chmod +x "$script"
}

run_suite() {
  local suite="$1" expect_consistency="$2" expect_witness="$3"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite ===================="

  echo "-- mint: lift Rust assertions and cargo-test witness package --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  echo "-- prove: consistency rows plus witness-package row --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json ) > "$prove_json" 2>/dev/null || true

  local consistency_status witness_status
  consistency_status="$(pyget "$prove_json" "
','.join([r.get('status') for r in d.get('rows', []) if (r.get('property', '') or '').startswith('consistency:') and 'witness-package' not in (r.get('property', '') or '')]) or 'MISSING'
")"
  witness_status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows', []) if 'witness-package' in (r.get('property', '') or '')), 'MISSING')
")"
  echo "   prove consistency statuses: $consistency_status"
  echo "   prove witness-package status: $witness_status"

  # STRICT ENCODER GATE: the encode64 consistency row is str.eq-bv-blocks-teethed
  # and must DISCHARGE (good) or be UNSATISFIED (bad).  This is the marquee claim.
  local encoder64_status encoder20_status pick_status classify_status
  encoder64_status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows', []) if 'encode64#euf#' in (r.get('property', '') or '') and 'consistency:' in (r.get('property', '') or '')), 'MISSING')
")"
  encoder20_status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows', []) if 'encode20#euf#' in (r.get('property', '') or '') and 'consistency:' in (r.get('property', '') or '')), 'MISSING')
")"
  # STRICT IF/ELSE + NESTED-IF GATE: pick (if/else) and classify (nested-if
  # guard-clause) rows prove that BlockSugar discharges symbolically (good)
  # and refutes subtle wrong values (bad) via QF_BV.  Filter on #euf# to skip
  # the #panic_callsite#euf# rows (those are always refused, expected).
  pick_status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows', []) if 'pick#euf#' in (r.get('property', '') or '') and 'consistency:' in (r.get('property', '') or '')), 'MISSING')
")"
  classify_status="$(pyget "$prove_json" "
next((r.get('status') for r in d.get('rows', []) if 'classify#euf#' in (r.get('property', '') or '') and 'consistency:' in (r.get('property', '') or '')), 'MISSING')
")"
  echo "   encode64 consistency row: $encoder64_status"
  echo "   encode20 consistency row: $encoder20_status"
  echo "   pick    consistency row: $pick_status"
  echo "   classify consistency row: $classify_status"

  if [ "$expect_consistency" = "DISCHARGE" ]; then
    # Good suite: encoder row must be discharged (body + assertion are SAT).
    [ "$encoder64_status" = "discharged" ] || {
      echo "FAIL[$suite]: encode64 consistency row must be discharged, got $encoder64_status"; exit 1
    }
    [ "$encoder20_status" = "discharged" ] || {
      echo "FAIL[$suite]: encode20 consistency row must be discharged, got $encoder20_status"; exit 1
    }
    # pick/classify: BlockSugar if/else + nested-if must discharge symbolically.
    [ "$pick_status" = "discharged" ] || {
      echo "FAIL[$suite]: pick consistency row must be discharged, got $pick_status"; exit 1
    }
    [ "$classify_status" = "discharged" ] || {
      echo "FAIL[$suite]: classify consistency row must be discharged, got $classify_status"; exit 1
    }
    # No other consistency row should be unsatisfied (no false refutations).
    if echo "$consistency_status" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: a true assertion was refuted (unsatisfied): $consistency_status"; exit 1
    fi
  else
    # Bad suite: encode64 row must be UNSATISFIED (body contradicts wrong assertion).
    [ "$encoder64_status" = "unsatisfied" ] || {
      echo "FAIL[$suite]: encode64 consistency row must be unsatisfied (refuted), got $encoder64_status"; exit 1
    }
    [ "$encoder20_status" = "unsatisfied" ] || {
      echo "FAIL[$suite]: encode20 consistency row must be unsatisfied (refuted), got $encoder20_status"; exit 1
    }
    # pick/classify wrong-value twins must also be UNSATISFIED (BlockSugar teeth).
    [ "$pick_status" = "unsatisfied" ] || {
      echo "FAIL[$suite]: pick consistency row must be unsatisfied (refuted), got $pick_status"; exit 1
    }
    [ "$classify_status" = "unsatisfied" ] || {
      echo "FAIL[$suite]: classify consistency row must be unsatisfied (refuted), got $classify_status"; exit 1
    }
  fi

  if [ "$expect_witness" = "DISCHARGE" ]; then
    [ "$witness_status" = "discharged" ] || { echo "FAIL[$suite]: expected witness discharge, got $witness_status"; exit 1; }
  else
    if [ "$witness_status" = "discharged" ] || [ "$witness_status" = "MISSING" ]; then
      echo "FAIL[$suite]: expected witness refusal, got $witness_status"
      exit 1
    fi
    echo "-- prove (LYING DISCHARGE): stdout says DISCHARGED, package body still has a failed outcome --"
    local lie="$dir/.sugar/lying-discharge.sh"
    write_lying_discharge "$lie"
    local lie_json="$dir/.prove_lie.json"
    ( cd "$dir" && SUGAR_WITNESS_DISCHARGE_CARGO_TEST="$lie" "$SUGAR" prove . --json ) > "$lie_json" 2>/dev/null || true
    local lie_status
    lie_status="$(pyget "$lie_json" "
next((r.get('status') for r in d.get('rows', []) if 'witness-package' in (r.get('property', '') or '')), 'MISSING')
")"
    echo "   lying-discharge witness-package status: $lie_status"
    if [ "$lie_status" = "discharged" ]; then
      echo "FAIL[$suite]: lying discharge stdout flipped a failing witness package"
      exit 1
    fi
  fi

  echo "-- verify durable artifact --"
  local verify_json="$dir/.verify.json"
  ( cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json ) > "$verify_json" 2>/dev/null || true
  python3 - "$suite" "$expect_consistency" "$expect_witness" "$verify_json" <<'PY'
import json
import sys

suite, expect_consistency, expect_witness, path = sys.argv[1:]
receipt = json.load(open(path, encoding="utf-8"))
rows = receipt.get("rows", [])
consistency = [
    r.get("status")
    for r in rows
    if (r.get("property") or "").startswith("consistency:")
    and "witness-package" not in (r.get("property") or "")
]
witness = [
    r.get("status")
    for r in rows
    if "witness-package" in (r.get("property") or "")
]
encoder64_rows = [
    r.get("status")
    for r in rows
    if "encode64#euf#" in (r.get("property") or "")
    and "consistency:" in (r.get("property") or "")
]
encoder20_rows = [
    r.get("status")
    for r in rows
    if "encode20#euf#" in (r.get("property") or "")
    and "consistency:" in (r.get("property") or "")
]
pick_rows = [
    r.get("status")
    for r in rows
    if "pick#euf#" in (r.get("property") or "")
    and "consistency:" in (r.get("property") or "")
]
classify_rows = [
    r.get("status")
    for r in rows
    if "classify#euf#" in (r.get("property") or "")
    and "consistency:" in (r.get("property") or "")
]
if not consistency:
    raise SystemExit(f"FAIL[{suite}]: durable verify has no consistency rows")

# STRICT ENCODER + IF/ELSE + NESTED-IF GATE (marquee claim and BlockSugar teeth).
if expect_consistency == "DISCHARGE":
    # Good: encoder rows must be discharged, no other unsatisfied.
    if encoder64_rows != ["discharged"]:
        raise SystemExit(f"FAIL[{suite}]: encode64 durable consistency must be ['discharged'], got {encoder64_rows}")
    if encoder20_rows != ["discharged"]:
        raise SystemExit(f"FAIL[{suite}]: encode20 durable consistency must be ['discharged'], got {encoder20_rows}")
    # pick (if/else) and classify (nested-if guard-clause) must discharge.
    if not pick_rows or any(s != "discharged" for s in pick_rows):
        raise SystemExit(f"FAIL[{suite}]: pick durable consistency must all be 'discharged', got {pick_rows}")
    if not classify_rows or any(s != "discharged" for s in classify_rows):
        raise SystemExit(f"FAIL[{suite}]: classify durable consistency must all be 'discharged', got {classify_rows}")
    if "unsatisfied" in consistency:
        raise SystemExit(f"FAIL[{suite}]: a true assertion was refuted (unsatisfied): {consistency}")
else:
    # Bad: encode64 row must be unsatisfied (refuted by body post).
    if encoder64_rows != ["unsatisfied"]:
        raise SystemExit(f"FAIL[{suite}]: encode64 durable consistency must be ['unsatisfied'], got {encoder64_rows}")
    if encoder20_rows != ["unsatisfied"]:
        raise SystemExit(f"FAIL[{suite}]: encode20 durable consistency must be ['unsatisfied'], got {encoder20_rows}")
    # pick/classify wrong-value twins must all be unsatisfied (BlockSugar refutes).
    if not pick_rows or any(s != "unsatisfied" for s in pick_rows):
        raise SystemExit(f"FAIL[{suite}]: pick durable consistency must all be 'unsatisfied', got {pick_rows}")
    if not classify_rows or any(s != "unsatisfied" for s in classify_rows):
        raise SystemExit(f"FAIL[{suite}]: classify durable consistency must all be 'unsatisfied', got {classify_rows}")

if expect_witness == "DISCHARGE":
    if witness != ["discharged"]:
        raise SystemExit(f"FAIL[{suite}]: durable witness statuses {witness}")
else:
    if witness == ["discharged"] or not witness:
        raise SystemExit(f"FAIL[{suite}]: durable witness statuses {witness}")
verified = any(
    w.get("verdict") == "verified"
    for w in receipt.get("witnessDimension", {}).get("witnesses", [])
)
if not verified:
    raise SystemExit(f"FAIL[{suite}]: witness dimension did not verify")
print(f"   durable consistency statuses: {','.join(consistency)}")
print(f"   encode64 consistency: {','.join(encoder64_rows)}")
print(f"   encode20 consistency: {','.join(encoder20_rows)}")
print(f"   pick    consistency: {','.join(pick_rows)}")
print(f"   classify consistency: {','.join(classify_rows)}")
print(f"   durable witness statuses: {','.join(witness)}")
print("   durable witness dimension: verified")
PY
}

run_suite good DISCHARGE DISCHARGE
run_suite bad REFUSE REFUSE

echo
echo "== base64 0.22.1 showcase: PASS =="
