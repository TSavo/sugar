#!/usr/bin/env bash
# std/core string predicate showcase: real Rust std/core source, zero std source changes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"
ASSERT_RPC="$BIN_DIR/rust_test_assertions_rpc"
source "$REPO/scripts/stdlib-solver-portfolio.sh"
WORK="${STD_CORE_STRING_PREDICATES_WORK:-$HERE/.work}"
GOOD="$WORK/good"
BAD="$WORK/bad"
STD_CORE_RUST_TOOLCHAIN="${STD_CORE_RUST_TOOLCHAIN:-1.96.0}"

echo "SCOPE: Rust std/core and alloc string predicate rows, zero std source changes."
echo "SCOPE: GOOD claims are vendor point assertions only; BAD is an explicit negative-control twin."
echo "SCOPE: lifted predicates = contains, starts_with/prefix-of, ends_with/suffix-of, str.len, str.is_ascii, literal chars().all/.any, literal bytes().is_ascii, char ASCII classes, literal char is_alphabetic, and bounded assert_all/assert_none literal macro rows."
echo "SCOPE: residuals = non-literal receivers, non-literal iterator/macro sources, unsupported closure bodies, and non-bedrockable custom assertion macros."

if [ "${STD_CORE_STRING_PREDICATES_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
  echo "== build local proof binaries =="
  cargo build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar \
    -p sugar-lift-rust-tests --bin rust_test_assertions_rpc \
    -p sugar-ir-compiler-smt-lib --bin sugar-ir-smt-lib \
    -p sugar-ir-compiler-coq --bin sugar-ir-coq \
    -p sugar-ir-compiler-lean --bin sugar-ir-lean \
    -p sugar-ir-compiler-maude --bin sugar-ir-maude >/dev/null
fi

for bin in "$SUGAR" "$ASSERT_RPC"; do
  if [ ! -x "$bin" ]; then
    echo "missing executable: $bin" >&2
    exit 1
  fi
done

STDROOT="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" --print sysroot)/lib/rustlib/src/rust/library"
RUSTC_VERSION="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" --version)"
RUSTC_VERBOSE="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" --version --verbose | tr '\n' ';')"
if [ ! -f "$STDROOT/alloctests/tests/str.rs" ] || [ ! -f "$STDROOT/coretests/tests/ascii.rs" ]; then
  echo "rust-src for $STD_CORE_RUST_TOOLCHAIN is missing under $STDROOT" >&2
  exit 1
fi
echo "rust-src: $STDROOT"
echo "toolchain: $RUSTC_VERSION"

rm -rf "$WORK"
mkdir -p "$GOOD/tests" "$GOOD/.sugar/lift/rust-test-assertions" "$BAD/tests" "$BAD/.sugar/lift/rust-test-assertions"

extract_functions() {
  local source="$1"
  local dest="$2"
  shift 2
  python3 - "$source" "$dest" "$@" <<'PY'
import sys

source, dest, *names = sys.argv[1:]
lines = open(source, encoding="utf-8").read().splitlines()

def extract(fn_name: str) -> list[str]:
    fn_idx = next(
        i for i, line in enumerate(lines)
        if line.startswith(f"fn {fn_name}(")
    )
    start = fn_idx
    while start > 0 and (lines[start - 1].startswith("#[") or lines[start - 1] == ""):
        start -= 1
    out = []
    depth = 0
    seen_open = False
    for line in lines[start:]:
        out.append(line)
        depth += line.count("{")
        if "{" in line:
            seen_open = True
        depth -= line.count("}")
        if seen_open and depth == 0:
            return out
    raise RuntimeError(f"unterminated function {fn_name}")

chunks = []
for name in names:
    if chunks:
        chunks.append("")
    chunks.extend(extract(name))
open(dest, "w", encoding="utf-8").write("\n".join(chunks) + "\n")
PY
}

extract_functions \
  "$STDROOT/alloctests/tests/str.rs" \
  "$GOOD/tests/str.rs" \
  test_starts_with test_ends_with test_contains test_contains_char test_join_for_different_lengths_with_long_separator

extract_functions \
  "$STDROOT/coretests/tests/ascii.rs" \
  "$GOOD/tests/ascii.rs" \
  test_is_ascii \
  test_is_ascii_alphabetic \
  test_is_ascii_uppercase \
  test_is_ascii_lowercase \
  test_is_ascii_alphanumeric \
  test_is_ascii_digit \
  test_is_ascii_octdigit \
  test_is_ascii_hexdigit \
  test_is_ascii_punctuation \
  test_is_ascii_graphic \
  test_is_ascii_whitespace \
  test_is_ascii_control

cat > "$GOOD/tests/char_methods_doctest.rs" <<'RS'
// Vendor source: rust-src library/core/src/char/methods.rs doctest examples
// for char::is_ascii and char::is_ascii_alphabetic.
#[test]
fn char_ascii_doctest_points() {
    assert!('a'.is_ascii());
    assert!('A'.is_ascii_alphabetic());
    assert!(!'0'.is_ascii_alphabetic());
    assert!('a'.is_alphabetic());
}
RS

cat > "$BAD/tests/str_bad.rs" <<'RS'
// Negative control derived from rust-src library/alloctests/tests/str.rs::test_contains.
// The first assertion is vendor-sourced; the second is an intentional contradictory twin.
#[test]
fn bad_contains_twin() {
    assert!("abcde".contains("bcd"));
    assert!(!"abcde".contains("bcd"));
}
RS

cat > "$BAD/tests/ascii_bad.rs" <<'RS'
// Negative control derived from rust-src library/coretests/tests/ascii.rs assert_all/assert_none shape.
// The two macro assertions intentionally contradict on the same bounded literal source.
#[test]
fn bad_assert_all_none_twin() {
    assert_all!(is_ascii_digit, "0");
    assert_none!(is_ascii_digit, "0");
}
RS

write_config() {
  local project="$1"
  cat > "$project/.sugar/config.toml" <<TOML
[[plugins]]
name = "rust-test-assertions-lift"
kind = "lift"
surface = "rust-test-assertions"
emit = "ir-document"

[platform_profile]
language = "rust"
library = "rust-std-core-string-predicates"
version = "$RUSTC_VERSION"
TOML
  append_sugar_solver_portfolio "$project/.sugar/config.toml" "$REPO"
  write_sugar_ir_compiler_manifests "$project" "$BIN_DIR"

  cat > "$project/.sugar/lift/rust-test-assertions/manifest.toml" <<TOML
name = "rust-test-assertions-lift"
version = "0.1.0"
protocol_version = "pep/1.7.0"
kind = "lift"
command = ["$ASSERT_RPC"]
working_dir = "."

[capabilities]
authoring_surfaces = ["rust-test-assertions"]
ir_version = "v1.1.0"
emits_signed_mementos = false
TOML
}

write_config "$GOOD"
write_config "$BAD"

run_mint_verify() {
  local project="$1"
  local label="$2"
  echo "== mint $label =="
  (cd "$project" && "$SUGAR" mint --out .) >/dev/null
  local proof_path
  proof_path="$(
    python3 - "$project" <<'PY'
import glob
import os
import sys
matches = sorted(glob.glob(os.path.join(sys.argv[1], "blake3-512_*.proof")))
print(matches[0] if matches else "")
PY
  )"
  if [ -z "$proof_path" ]; then
    echo "$label mint produced no .proof" >&2
    exit 1
  fi
  echo "$label proof: $(basename "$proof_path")"
  echo "== verify $label =="
  (cd "$project" && "$SUGAR" verify --project . --json) > "$project/.verify.json" 2>&1 || true
}

run_mint_verify "$GOOD" GOOD
run_mint_verify "$BAD" BAD

python3 - "$GOOD/.verify.json" "$BAD/.verify.json" <<'PY'
import json
import re
import sys

def receipt(path):
    text = open(path, encoding="utf-8").read()
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("kind") == "verification-receipt":
            return obj
    print(f"no verification-receipt in {path}", file=sys.stderr)
    print(text, file=sys.stderr)
    raise SystemExit(1)

good = receipt(sys.argv[1])
bad = receipt(sys.argv[2])
good_rows = [
    r for r in good.get("rows", [])
    if "#euf#" in (r.get("property") or "") or "tests/ascii.rs::test_is_ascii" in (r.get("property") or "")
]
bad_rows = [
    r for r in bad.get("rows", [])
    if "#euf#" in (r.get("property") or "") or "tests/ascii_bad.rs::bad_assert_all_none_twin" in (r.get("property") or "")
]

required = {
    "contains": "method:contains#euf#c:callresult_method_contains_a2(s:\"abcde\",s:\"bcd\")::assertion",
    "contains-char": "method:contains#euf#c:callresult_method_contains_a2(s:\"abc\",s:\"b\")::assertion",
    "starts-with": "method:starts_with#euf#c:callresult_method_starts_with_a2(s:\"abc\",s:\"a\")::assertion",
    "ends-with": "method:ends_with#euf#c:callresult_method_ends_with_a2(s:\"abc\",s:\"c\")::assertion",
    "len": "method:len#panic_callsite#euf#c:callresult_method_len_panic_callsite_a1(s:\"～～～～～\")::assertion",
    "str-is-ascii": "method:is_ascii#euf#c:callresult_method_is_ascii_a1(s:\"banana\\0\\u{7f}\")::assertion",
    "char-is-ascii": "method:is_ascii#euf#c:callresult_method_is_ascii_a1(s:\"a\")::assertion",
    "char-is-ascii-alpha": "method:is_ascii_alphabetic#euf#c:callresult_method_is_ascii_alphabetic_a1(s:\"A\")::assertion",
    "iterator-bytes-and-chars": "tests/ascii.rs::test_is_ascii",
    "assert-all-none-alpha": "tests/ascii.rs::test_is_ascii_alphabetic",
    "assert-all-none-uppercase": "tests/ascii.rs::test_is_ascii_uppercase",
    "assert-all-none-lowercase": "tests/ascii.rs::test_is_ascii_lowercase",
    "assert-all-none-alphanumeric": "tests/ascii.rs::test_is_ascii_alphanumeric",
    "assert-all-none-digit": "tests/ascii.rs::test_is_ascii_digit",
    "assert-all-none-octdigit": "tests/ascii.rs::test_is_ascii_octdigit",
    "assert-all-none-hexdigit": "tests/ascii.rs::test_is_ascii_hexdigit",
    "assert-all-none-punctuation": "tests/ascii.rs::test_is_ascii_punctuation",
    "assert-all-none-graphic": "tests/ascii.rs::test_is_ascii_graphic",
    "assert-all-none-whitespace": "tests/ascii.rs::test_is_ascii_whitespace",
    "assert-all-none-control": "tests/ascii.rs::test_is_ascii_control",
}

missing = [
    label for label, needle in required.items()
    if not any(needle in (row.get("property") or "") for row in good_rows)
]
failed_good = [row for row in good_rows if row.get("status") != "discharged"]
if missing:
    print("GOOD missing required rows:", ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
if failed_good:
    print("GOOD has non-discharged #euf# rows:", file=sys.stderr)
    for row in failed_good:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)

iterator_row = next(
    (row for row in good_rows if "tests/ascii.rs::test_is_ascii" in (row.get("property") or "")),
    None,
)
if iterator_row is None:
    print("GOOD missing iterator/byte row", file=sys.stderr)
    raise SystemExit(1)
if iterator_row.get("status") != "discharged":
    print("GOOD iterator/byte row was not discharged", file=sys.stderr)
    print(json.dumps(iterator_row, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)

bad_target = "method:contains#euf#c:callresult_method_contains_a2(s:\"abcde\",s:\"bcd\")::assertion"
bad_matches = [row for row in bad_rows if bad_target in (row.get("property") or "")]
bad_macro_target = "tests/ascii_bad.rs::bad_assert_all_none_twin"
bad_macro_matches = [row for row in bad_rows if bad_macro_target in (row.get("property") or "")]
if not bad_matches:
    print("BAD missing contradictory contains row", file=sys.stderr)
    raise SystemExit(1)
if not bad_macro_matches:
    print("BAD missing contradictory assert_all/assert_none row", file=sys.stderr)
    raise SystemExit(1)
if all(row.get("status") == "discharged" for row in bad_matches):
    print("BAD contradictory row discharged unexpectedly", file=sys.stderr)
    for row in bad_matches:
        print(json.dumps(row, indent=2), file=sys.stderr)
    raise SystemExit(1)
if all(row.get("status") == "discharged" for row in bad_macro_matches):
    print("BAD contradictory assert_all/assert_none row discharged unexpectedly", file=sys.stderr)
    for row in bad_macro_matches:
        print(json.dumps(row, indent=2), file=sys.stderr)
    raise SystemExit(1)

print(f"GOOD .verify.json ok={good.get('ok')} totalClaims={good.get('totalClaims')} eufRows={len(good_rows)}")
for label, needle in required.items():
    row = next(row for row in good_rows if needle in (row.get("property") or ""))
    print(f"GOOD {label}: {row.get('status')} {row.get('property')}")

print(f"BAD .verify.json ok={bad.get('ok')} totalClaims={bad.get('totalClaims')} eufRows={len(bad_rows)}")
for row in bad_matches:
    print(f"BAD contains twin: {row.get('status')} {row.get('property')} reason={row.get('reason')}")
for row in bad_macro_matches:
    print(f"BAD assert_all/assert_none twin: {row.get('status')} {row.get('property')} reason={row.get('reason')}")
PY

echo "toolchain-detail: $RUSTC_VERBOSE"
echo "std/core string predicate showcase self-check passed"
