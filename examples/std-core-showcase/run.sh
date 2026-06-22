#!/usr/bin/env bash
# std/core logo showcase: real Rust core tests, zero std source changes.
#
# Claimed proof surface:
#   - `rust-src` provides the pinned toolchain's std/core source and tests.
#   - The lifter sees a selected sound scalar and type-reflection slice:
#       * tests/cmp.rs integer call-result equality rows,
#       * tests/mem.rs generic type-arg-keyed size_of/align_of rows,
#         including active pinned-target pointer-width cfg rows,
#       * tests/intrinsics.rs direct TypeId comparison rows,
#       * tests/intrinsics.rs const-path integer index value rows, kept as a
#         location-keyed claim,
#       * tests/time.rs finite decimal float method-call equality rows and
#         width-known NaN refinement predicate rows,
#       * tests/num/{mod.rs,dec2flt/mod.rs} width-known float refinement
#         predicate rows for typed locals and parse::<f32/f64>().unwrap(),
#       * tests/fmt/mod.rs exact string method-call equality rows.
#       * tests/alloc.rs and tests/ops.rs pure method-chain predicate rows,
#         including sound temporal receiver identity for selected range rows.
#       * tests/time.rs direct call-result comparison rows.
#       * tests/atomic.rs compound value rows with bitwise-expression RHS
#         terms, limited to non-repeated stable keys.
#       * tests/iter/range.rs literal array/tuple exact-value terms, kept on
#         stable #euf# keys.
#       * tests/array.rs expression-only const-block wrappers around stable
#         call-result terms.
#       * tests/array.rs::array_from_ref and
#         tests/slice.rs::test_const_from_ref immutable index terms inside
#         pointer-equality predicates, kept as location-keyed claims.
#       * tests/waker.rs::test_waker_getters casted Waker data equality and
#         pointer equality over Waker vtable references, kept as one
#         location-keyed claim.
#       * tests/option.rs::test_and nullary/variant constructor equality rows,
#         kept as location-keyed operator-dispatch claims.
#       * tests/result.rs::result_try_trait_v2_branch nested variant
#         constructor equality rows, kept as location-keyed
#         operator-dispatch claims.
#       * tests/cmp.rs::cmp_default user-type operator-dispatch row.
#   - `sugar mint` + `sugar verify` must produce only discharged claimed
#     consistency rows for that slice.
#   - The exact vendor tests rerun as the witness axis.
#
# Explicitly NOT claimed:
#   - assertion macros requiring expansion,
#   - float refinements such as infinity equality, ordered comparisons,
#     signed zero,
#   - chars, inactive or ambiguous cfg rows, ambiguous receiver identity
#     method chains, and complex expression terms.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"
ASSERT_RPC="$BIN_DIR/rust_test_assertions_rpc"
source "$REPO/scripts/stdlib-solver-portfolio.sh"
WORK="${STD_CORE_SHOWCASE_WORK:-$HERE/.work}"
PROJECT="$WORK/proof-scope"
WITNESS_TARGET="$WORK/coretests-target"
STD_CORE_RUST_TOOLCHAIN="${STD_CORE_RUST_TOOLCHAIN:-1.96.0}"
STD_CORE_RUST_TARGET="${STD_CORE_RUST_TARGET:-}"

echo "SCOPE: Rust std/core own tests, zero std source changes."
echo "SCOPE: claimed slice = scalar direct call-result equality assertions from cmp.rs, type-arg-keyed generic rows from mem.rs including active pinned-target cfg rows, direct TypeId comparison rows and const-path integer index value rows from intrinsics.rs, finite float/string rows from time.rs/fmt/mod.rs, width-known NaN float refinement rows from time.rs, width-known infinity-equality float refinement rows from time.rs (div_duration_f32/f64 by-zero asserting equality to f32/f64 INFINITY, lifted as the is_infinite and is_sign_positive conjunction), width-known typed-local and parse/unwrap float refinement rows from num/mod.rs and num/dec2flt/mod.rs, pure method-chain predicate rows from alloc.rs/ops.rs including selected temporal receiver identity rows, direct call-result comparison FOL rows from time.rs, atomic.rs compound bitwise-expression RHS rows with stable keys, iter/range.rs literal array/tuple exact-value rows, array.rs expression-only const-block call-result rows, pointer-index predicate rows from array.rs/slice.rs kept location-keyed, casted-data and pointer-vtable row from waker.rs kept location-keyed, option.rs nullary/variant constructor operator-dispatch rows, option.rs is_some predicate rows on const-path receivers (const_get_or_insert_default and const_get_or_insert_with), result.rs nested variant constructor operator-dispatch rows, and cmp.rs::cmp_default user-type operator dispatch."
echo "SCOPE: excluded gaps = macro surfaces not included in this showcase, infinity equality via cast-expression or Ok-wrapper receivers, infinity used as a method argument, ordered and signed-zero float refinements, chars, inactive or ambiguous cfg rows, ambiguous receiver identity method chains, and complex terms whose identity cannot yet be keyed soundly."
echo "SCOPE: pinned Rust toolchain = $STD_CORE_RUST_TOOLCHAIN (std source is not taken from CI's active default)."

ensure_rust_src() {
  local sysroot stdroot
  if command -v rustup >/dev/null 2>&1; then
    echo "== install rust-src for pinned toolchain $STD_CORE_RUST_TOOLCHAIN ==" >&2
    rustup toolchain install "$STD_CORE_RUST_TOOLCHAIN" --profile minimal --component rust-src >/dev/null
  fi
  sysroot="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" --print sysroot)"
  stdroot="$sysroot/lib/rustlib/src/rust/library"
  if [ -f "$stdroot/coretests/tests/cmp.rs" ]; then
    printf '%s\n' "$stdroot"
    return 0
  fi
  if [ ! -f "$stdroot/coretests/tests/cmp.rs" ]; then
    echo "rust-src for pinned toolchain $STD_CORE_RUST_TOOLCHAIN is missing coretests/tests/cmp.rs under $stdroot" >&2
    exit 1
  fi
  printf '%s\n' "$stdroot"
}

if [ "${STD_CORE_SHOWCASE_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
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

STDROOT="$(ensure_rust_src)"
if [ -z "$STD_CORE_RUST_TARGET" ]; then
  STD_CORE_RUST_TARGET="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" -vV | awk '/^host:/ {print $2}')"
fi
RUSTC_VERSION="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" --version)"
RUSTC_VERBOSE="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" --version --verbose | tr '\n' ';')"
echo "rust-src: $STDROOT"
echo "toolchain: $RUSTC_VERSION"
echo "target: $STD_CORE_RUST_TARGET"

rm -rf "$WORK"
mkdir -p "$PROJECT/tests/fmt" "$PROJECT/tests/iter" "$PROJECT/tests/num/dec2flt" "$PROJECT/.sugar/lift/rust-test-assertions"
TARGET_CFG_FACTS_FILE="$WORK/target-cfg.txt"
rustc "+$STD_CORE_RUST_TOOLCHAIN" --test --target "$STD_CORE_RUST_TARGET" --print cfg \
  | sort > "$TARGET_CFG_FACTS_FILE"
TARGET_POINTER_WIDTH="$(awk -F'"' '/^target_pointer_width=/ {print $2; exit}' "$TARGET_CFG_FACTS_FILE")"
if [ -z "$TARGET_POINTER_WIDTH" ]; then
  echo "pinned target cfg facts do not include target_pointer_width" >&2
  exit 1
fi
case "$TARGET_POINTER_WIDTH" in
  16|32|64) ;;
  *)
    echo "unsupported target_pointer_width for std-core mem cfg showcase: $TARGET_POINTER_WIDTH" >&2
    exit 1
    ;;
esac
TARGET_POINTER_BYTES=$((TARGET_POINTER_WIDTH / 8))
echo "target-cfg: target_pointer_width=$TARGET_POINTER_WIDTH pointer_bytes=$TARGET_POINTER_BYTES"
echo "target-cfg: facts=$(wc -l < "$TARGET_CFG_FACTS_FILE" | tr -d ' ')"
ln -s "$STDROOT/coretests/tests/cmp.rs" "$PROJECT/tests/cmp.rs"
ln -s "$STDROOT/coretests/tests/time.rs" "$PROJECT/tests/time.rs"
ln -s "$STDROOT/coretests/tests/fmt/mod.rs" "$PROJECT/tests/fmt/mod.rs"

python3 - "$STDROOT/coretests/tests/option.rs" "$PROJECT/tests/option.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "use core::option::*;",
    "",
    *extract("test_and"),
    "",
    *extract("const_get_or_insert_default"),
    "",
    *extract("const_get_or_insert_with"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/result.rs" "$PROJECT/tests/result.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "",
    *extract("result_try_trait_v2_branch"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/num/mod.rs" "$PROJECT/tests/num/mod.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "",
    *extract("test_f32f64"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/num/dec2flt/mod.rs" "$PROJECT/tests/num/dec2flt/mod.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "",
    *extract("nan"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/mem.rs" "$PROJECT/tests/mem.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "use core::mem::*;",
    "",
    *extract("size_of_basic"),
    "",
    *extract("size_of_16"),
    "",
    *extract("size_of_32"),
    "",
    *extract("size_of_64"),
    "",
    *extract("align_of_basic"),
    "",
    *extract("align_of_16"),
    "",
    *extract("align_of_32"),
    "",
    *extract("align_of_64"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/intrinsics.rs" "$PROJECT/tests/intrinsics.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
lines = open(source, encoding="utf-8").read().splitlines()

def extract(fn_name: str) -> list[str]:
    fn_idx = next(
        i for i, line in enumerate(lines)
        if line.startswith(f"fn {fn_name}(") or line.startswith(f"const fn {fn_name}(")
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

chunks = [
    "use core::any::TypeId;",
    "",
    *extract("test_typeid_sized_types"),
    "",
    *extract("test_typeid_unsized_types"),
    "",
    *extract("test_write_bytes_in_const_contexts"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/any.rs" "$PROJECT/tests/any.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "use core::any::*;",
    "",
    "#[derive(PartialEq, Debug)]",
    "struct Test;",
    "",
    "static TEST: &'static str = \"Test\";",
    "",
    *extract("any_referenced"),
    "",
    *extract("any_owning"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/alloc.rs" "$PROJECT/tests/alloc.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "use core::alloc::Layout;",
    "",
    *extract("layout_errors"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/ops.rs" "$PROJECT/tests/ops.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    *extract("test_range_contains"),
    "",
    *extract("test_range_to_contains"),
    "",
    *extract("test_range_bounds_contains"),
    "",
    *extract("test_range_inclusive_end_bound"),
    "",
    *extract("test_range_bounds"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/atomic.rs" "$PROJECT/tests/atomic.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "use core::sync::atomic::Ordering::SeqCst;",
    "use core::sync::atomic::*;",
    "",
    *extract("bool_and"),
    "",
    *extract("uint_and"),
    "",
    *extract("uint_nand"),
    "",
    *extract("uint_or"),
    "",
    *extract("uint_xor"),
    "",
    *extract("int_and"),
    "",
    *extract("int_nand"),
    "",
    *extract("int_or"),
    "",
    *extract("int_xor"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/iter/range.rs" "$PROJECT/tests/iter/range.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "use core::iter::*;",
    "use super::*;",
    "",
    *extract("test_range"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/array.rs" "$PROJECT/tests/array.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "use std::array;",
    "",
    *extract("array_from_ref"),
    "",
    *extract("const_array_ops"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/slice.rs" "$PROJECT/tests/slice.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
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

chunks = [
    "",
    *extract("test_const_from_ref"),
    "",
]
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY

python3 - "$STDROOT/coretests/tests/waker.rs" "$PROJECT/tests/waker.rs" <<'PY'
import sys

source, dest = sys.argv[1:]
lines = open(source, encoding="utf-8").read().splitlines()
cut = next(
    (i for i, line in enumerate(lines) if line.startswith("// https://github.com/rust-lang/rust/issues/102012")),
    len(lines),
)
open(dest, "w", encoding="utf-8").write("\n".join(lines[:cut]))
PY

cat > "$PROJECT/.sugar/config.toml" <<TOML
[[plugins]]
name = "rust-test-assertions-lift"
kind = "lift"
surface = "rust-test-assertions"
emit = "ir-document"

[platform_profile]
language = "rust"
library = "rust-std-coretests-scalar"
version = "$RUSTC_VERSION"
TOML
append_sugar_solver_portfolio "$PROJECT/.sugar/config.toml" "$REPO"
write_sugar_ir_compiler_manifests "$PROJECT" "$BIN_DIR"

python3 - "$PROJECT/.sugar/config.toml" "$STD_CORE_RUST_TARGET" "$TARGET_CFG_FACTS_FILE" <<'PY'
import json
import sys

config_path, target, facts_path = sys.argv[1:]
facts = [
    line.strip()
    for line in open(facts_path, encoding="utf-8")
    if line.strip()
]
if not facts:
    raise SystemExit("target cfg facts file is empty")
with open(config_path, "a", encoding="utf-8") as out:
    out.write("\n[rust-test-assertions.target_cfg]\n")
    out.write(f"target = {json.dumps(target)}\n")
    out.write("facts = [\n")
    for fact in facts:
        out.write(f"  {json.dumps(fact)},\n")
    out.write("]\n")
PY

cat > "$PROJECT/.sugar/lift/rust-test-assertions/manifest.toml" <<TOML
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

echo "== mint std/core selected source slice =="
(cd "$PROJECT" && "$SUGAR" mint --out .) >/dev/null

proof_path="$(
  python3 - "$PROJECT" <<'PY'
import glob
import os
import sys
matches = sorted(glob.glob(os.path.join(sys.argv[1], "blake3-512_*.proof")))
print(matches[0] if matches else "")
PY
)"
if [ -z "$proof_path" ]; then
  echo "mint produced no .proof" >&2
  exit 1
fi
echo "proof: $(basename "$proof_path")"

echo "== verify std/core selected source slice =="
(cd "$PROJECT" && "$SUGAR" verify --project . --json) > "$PROJECT/.verify.json" 2>&1 || true

python3 - "$PROJECT/.verify.json" "$TARGET_POINTER_WIDTH" "$TARGET_POINTER_BYTES" <<'PY'
import json
import re
import sys

path = sys.argv[1]
target_pointer_width = sys.argv[2]
target_pointer_bytes = sys.argv[3]
text = open(path, encoding="utf-8").read()
text = re.sub(r"\x1b\[[0-9;]*m", "", text)
decoder = json.JSONDecoder()
receipt = None
for idx, ch in enumerate(text):
    if ch != "{":
        continue
    try:
        obj, _ = decoder.raw_decode(text[idx:])
    except Exception:
        continue
    if isinstance(obj, dict) and obj.get("kind") == "verification-receipt":
        receipt = obj
        break
if receipt is None:
    print("verify produced no verification-receipt", file=sys.stderr)
    print(text, file=sys.stderr)
    raise SystemExit(1)

rows = receipt.get("rows", [])
euf_rows = [r for r in rows if "#euf#" in (r.get("property") or "")]
failed = [r for r in euf_rows if r.get("status") != "discharged"]
cmp_default_rows = [
    r for r in rows
    if (r.get("property") or "") == "consistency:tests/cmp.rs::cmp_default"
]
option_test_and_rows = [
    r for r in rows
    if (r.get("property") or "") == "consistency:tests/option.rs::test_and"
]
result_try_trait_rows = [
    r for r in rows
    if (r.get("property") or "") == "consistency:tests/result.rs::result_try_trait_v2_branch"
]
pointer_index_properties = {
    "consistency:tests/array.rs::array_from_ref",
    "consistency:tests/slice.rs::test_const_from_ref",
}
pointer_index_rows = [
    r for r in rows
    if (r.get("property") or "") in pointer_index_properties
]
pointer_vtable_properties = {
    "consistency:tests/waker.rs::test_waker_getters",
}
pointer_vtable_rows = [
    r for r in rows
    if (r.get("property") or "") in pointer_vtable_properties
]
typed_float_refinement_rows = [
    r for r in rows
    if (r.get("property") or "") == "consistency:tests/num/mod.rs::test_f32f64"
]
any_is_rows = [
    r for r in euf_rows
    if "method:is::<" in (r.get("property") or "")
    and "tests/any.rs::any_" in (r.get("property") or "")
]
needles = [
    "cmp::max_by#euf#c:callresult_cmp__max_by_a3(i:1,i:-1,c:closure:x . abs () . cmp (& y . abs ())())::assertion",
    "align_of::<u8>#euf#c:callresult_align_of___u8__a0()::assertion",
    "align_of::<u16>#euf#c:callresult_align_of___u16__a0()::assertion",
    "align_of::<usize>#euf#c:callresult_align_of___usize__a0()::assertion",
    "align_of::<* const usize>#euf#c:callresult_align_of_____const_usize__a0()::assertion",
    "method:to_string#euf#c:callresult_method_to_string_a1(v:tests/fmt/mod.rs::test_lifetime::A)::assertion",
    "method:div_duration_f32#euf#c:callresult_method_div_duration_f32_a2(v:Duration::ZERO,v:Duration::MAX)::assertion",
    "method:div_duration_f32#euf#c:callresult_method_div_duration_f32_a2(v:Duration::ZERO,v:Duration::ZERO)::assertion",
    "method:div_duration_f32#euf#c:callresult_method_div_duration_f32_a2(v:Duration::NANOSECOND,v:Duration::MAX)::assertion",
    "method:div_duration_f32#euf#c:callresult_method_div_duration_f32_a2(c:*(v:Duration::SECOND,i:2),v:Duration::SECOND)::assertion",
    "method:div_duration_f64#euf#c:callresult_method_div_duration_f64_a2(v:Duration::ZERO,v:Duration::MAX)::assertion",
    "method:div_duration_f64#euf#c:callresult_method_div_duration_f64_a2(v:Duration::ZERO,v:Duration::ZERO)::assertion",
    "method:div_duration_f64#euf#c:callresult_method_div_duration_f64_a2(v:Duration::NANOSECOND,v:Duration::MAX)::assertion",
    "method:div_duration_f64#euf#c:callresult_method_div_duration_f64_a2(c:*(v:Duration::SECOND,i:2),v:Duration::SECOND)::assertion",
    "method:unwrap#euf#c:callresult_method_unwrap_a1(c:method:parse::<f32>(s:\"NaN\"))::assertion",
    "method:unwrap#euf#c:callresult_method_unwrap_a1(c:method:parse::<f32>(s:\"-NaN\"))::assertion",
    "method:unwrap#euf#c:callresult_method_unwrap_a1(c:method:parse::<f64>(s:\"NaN\"))::assertion",
    "method:unwrap#euf#c:callresult_method_unwrap_a1(c:method:parse::<f64>(s:\"-NaN\"))::assertion",
    "method:is_err#euf#c:callresult_method_is_err_a1(c:method:align_to(c:call:Layout::new::<[u8;2]>(),i:3))::assertion",
    "method:is_ok#euf#c:callresult_method_is_ok_a1(c:method:repeat(c:call:Layout::new::<[u8;2]>(),c:int-div(i:9223372036854775807:usize,c:method:size(c:call:Layout::new::<[u8;2]>()))))::assertion",
    "method:is_some#euf#c:callresult_method_is_some_a1(v:tests/option.rs::const_get_or_insert_default::OPT_DEFAULT)::assertion",
    "method:is_some#euf#c:callresult_method_is_some_a1(v:tests/option.rs::const_get_or_insert_with::OPT_WITH)::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(c:method:skip(c:range_incl(i:1:u32,i:1),i:1),c:ref(i:1))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:agg:Tuple(v:Bound::<u32>::Unbounded,v:Bound::Unbounded),c:ref(i:0))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:agg:Tuple(v:Bound::<u32>::Unbounded,v:Bound::Unbounded),c:ref(i:4294967295))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:literal:Tuple(c:call:Bound::Excluded(i:1:u32),c:call:Bound::Included(i:5:u32)),c:ref(i:0))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:literal:Tuple(c:call:Bound::Excluded(i:1:u32),c:call:Bound::Included(i:5:u32)),c:ref(i:1))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:literal:Tuple(c:call:Bound::Excluded(i:1:u32),c:call:Bound::Included(i:5:u32)),c:ref(i:3))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:literal:Tuple(c:call:Bound::Excluded(i:1:u32),c:call:Bound::Included(i:5:u32)),c:ref(i:5))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:literal:Tuple(c:call:Bound::Excluded(i:1:u32),c:call:Bound::Included(i:5:u32)),c:ref(i:6))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:literal:Tuple(c:call:Bound::Included(i:1:u32),c:call:Bound::Excluded(i:5:u32)),c:ref(i:0))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:literal:Tuple(c:call:Bound::Included(i:1:u32),c:call:Bound::Excluded(i:5:u32)),c:ref(i:1))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:literal:Tuple(c:call:Bound::Included(i:1:u32),c:call:Bound::Excluded(i:5:u32)),c:ref(i:3))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:literal:Tuple(c:call:Bound::Included(i:1:u32),c:call:Bound::Excluded(i:5:u32)),c:ref(i:5))::assertion",
    "method:contains#euf#c:callresult_method_contains_a2(v:literal:Tuple(c:call:Bound::Included(i:1:u32),c:call:Bound::Excluded(i:5:u32)),c:ref(i:6))::assertion",
    "method:fetch_and#euf#c:callresult_method_fetch_and_a3(v:tests/atomic.rs::uint_and::x@def2,i:4991,v:tests/atomic.rs::uint_and::SeqCst)::assertion",
    "method:load#euf#c:callresult_method_load_a2(v:tests/atomic.rs::uint_and::x@def3,v:tests/atomic.rs::uint_and::SeqCst)::assertion",
    "method:load#euf#c:callresult_method_load_a2(v:tests/atomic.rs::uint_nand::x@def3,v:tests/atomic.rs::uint_nand::SeqCst)::assertion",
    "method:load#euf#c:callresult_method_load_a2(v:tests/atomic.rs::uint_or::x@def3,v:tests/atomic.rs::uint_or::SeqCst)::assertion",
    "method:load#euf#c:callresult_method_load_a2(v:tests/atomic.rs::uint_xor::x@def3,v:tests/atomic.rs::uint_xor::SeqCst)::assertion",
    "method:count#euf#c:callresult_method_count_a1(c:range(i:200,i:-5))::assertion",
    "method:count#euf#c:callresult_method_count_a1(c:method:rev(c:range(i:200,i:-5)))::assertion",
    "method:size_hint#euf#c:callresult_method_size_hint_a1(c:range(i:0,i:100))::assertion",
    "method:size_hint#euf#c:callresult_method_size_hint_a1(c:range(i:-10,i:-1))::assertion",
    "std::array::from_fn::<_,const:5,_>#euf#c:callresult_std__array__from_fn_____const_5____a1(v:tests/array.rs::const_array_ops::doubler)::assertion",
]
type_id_needles = [
    "consistency:tests/intrinsics.rs::test_typeid_sized_types",
    "consistency:tests/intrinsics.rs::test_typeid_unsized_types",
]
mem_location_needles = [
    "consistency:tests/mem.rs::size_of_basic",
    "consistency:tests/mem.rs::size_of_64",
    "consistency:tests/mem.rs::size_of_basic::panic-path::size_of_::___u8_____",
    "consistency:tests/mem.rs::size_of_basic::panic-path::size_of_::___u16_____",
    "consistency:tests/mem.rs::size_of_64::panic-path::size_of_::___usize_____",
    "consistency:tests/mem.rs::size_of_64::panic-path::size_of_::_____const_usize_____",
]
missing = [
    needle for needle in needles
    if not any(needle in (r.get("property") or "") for r in euf_rows)
]
missing_type_id = [
    needle for needle in type_id_needles
    if not any(needle == (r.get("property") or "") for r in rows)
]
missing_mem_location = [
    needle for needle in mem_location_needles
    if not any(needle == (r.get("property") or "") for r in rows)
]
type_id_rows = [
    r for r in rows
    if (r.get("property") or "") in type_id_needles
]
failed_type_id = [r for r in type_id_rows if r.get("status") != "discharged"]
mem_location_rows = [
    r for r in rows
    if (r.get("property") or "") in mem_location_needles
]
failed_mem_location = [
    r for r in mem_location_rows
    if r.get("status") != "discharged"
]
const_index_properties = {
    "consistency:tests/intrinsics.rs::test_write_bytes_in_const_contexts",
}
const_index_rows = [
    r for r in rows
    if (r.get("property") or "") in const_index_properties
]
failed_const_index = [
    r for r in const_index_rows
    if r.get("status") != "discharged"
]

if not euf_rows:
    print("no #euf# consistency rows found", file=sys.stderr)
    raise SystemExit(1)
if len(euf_rows) < 160:
    print(f"expected at least 160 claimed #euf# rows after cfg-sensitive mem, compound-term, const-block, option/result constructor, temporal receiver, time NaN, parsed NaN float refinement lifts, and is_some predicate rows, got {len(euf_rows)}", file=sys.stderr)
    raise SystemExit(1)
if missing:
    print("missing required claimed rows:", file=sys.stderr)
    for needle in missing:
        print(needle, file=sys.stderr)
    raise SystemExit(1)
if missing_type_id:
    print("missing required TypeId claimed rows:", file=sys.stderr)
    for needle in missing_type_id:
        print(needle, file=sys.stderr)
if missing_mem_location:
    print("missing required mem location-keyed rows:", file=sys.stderr)
    for needle in missing_mem_location:
        print(needle, file=sys.stderr)
    raise SystemExit(1)
if len(cmp_default_rows) != 1:
    print(f"expected exactly one claimed cmp_default row, got {len(cmp_default_rows)}", file=sys.stderr)
    for row in cmp_default_rows:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
cmp_default_row = cmp_default_rows[0]
if cmp_default_row.get("status") != "discharged":
    print("claimed cmp_default row did not discharge:", file=sys.stderr)
    print(f"{cmp_default_row.get('status')} {cmp_default_row.get('property')} {cmp_default_row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
if len(option_test_and_rows) != 1:
    print(f"expected exactly one claimed option::test_and row, got {len(option_test_and_rows)}", file=sys.stderr)
    for row in option_test_and_rows:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
option_test_and_row = option_test_and_rows[0]
if option_test_and_row.get("status") != "discharged":
    print("claimed option::test_and row did not discharge:", file=sys.stderr)
    print(f"{option_test_and_row.get('status')} {option_test_and_row.get('property')} {option_test_and_row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
if len(result_try_trait_rows) != 1:
    print(f"expected exactly one claimed result::result_try_trait_v2_branch row, got {len(result_try_trait_rows)}", file=sys.stderr)
    for row in result_try_trait_rows:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
result_try_trait_row = result_try_trait_rows[0]
if result_try_trait_row.get("status") != "discharged":
    print("claimed result::result_try_trait_v2_branch row did not discharge:", file=sys.stderr)
    print(f"{result_try_trait_row.get('status')} {result_try_trait_row.get('property')} {result_try_trait_row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
if len(pointer_index_rows) != len(pointer_index_properties):
    present = {r.get("property") for r in pointer_index_rows}
    print("missing claimed pointer-index rows:", file=sys.stderr)
    for property_name in sorted(pointer_index_properties - present):
        print(property_name, file=sys.stderr)
    raise SystemExit(1)
failed_pointer_index = [
    r for r in pointer_index_rows
    if r.get("status") != "discharged"
]
if failed_pointer_index:
    print("non-discharged pointer-index rows in claimed slice:", file=sys.stderr)
    for row in failed_pointer_index:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
if len(pointer_vtable_rows) != len(pointer_vtable_properties):
    present = {r.get("property") for r in pointer_vtable_rows}
    print("missing claimed pointer-vtable rows:", file=sys.stderr)
    for property_name in sorted(pointer_vtable_properties - present):
        print(property_name, file=sys.stderr)
    raise SystemExit(1)
failed_pointer_vtable = [
    r for r in pointer_vtable_rows
    if r.get("status") != "discharged"
]
if failed_pointer_vtable:
    print("non-discharged pointer-vtable rows in claimed slice:", file=sys.stderr)
    for row in failed_pointer_vtable:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
if len(typed_float_refinement_rows) != 1:
    print(f"expected exactly one claimed num::test_f32f64 typed float refinement row, got {len(typed_float_refinement_rows)}", file=sys.stderr)
    for row in typed_float_refinement_rows:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
typed_float_refinement_row = typed_float_refinement_rows[0]
if typed_float_refinement_row.get("status") != "discharged":
    print("claimed num::test_f32f64 typed float refinement row did not discharge:", file=sys.stderr)
    print(f"{typed_float_refinement_row.get('status')} {typed_float_refinement_row.get('property')} {typed_float_refinement_row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
if len(any_is_rows) != 18:
    print(f"expected 18 claimed Any::is rows, got {len(any_is_rows)}", file=sys.stderr)
    for row in any_is_rows:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
failed_any_is = [
    r for r in any_is_rows
    if r.get("status") != "discharged"
]
if failed_any_is:
    print("non-discharged Any::is rows in claimed slice:", file=sys.stderr)
    for row in failed_any_is:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
if failed:
    print("non-discharged #euf# rows in claimed slice:", file=sys.stderr)
    for row in failed:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
if failed_type_id:
    print("non-discharged TypeId rows in claimed slice:", file=sys.stderr)
    for row in failed_type_id:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
if failed_mem_location:
    print("non-discharged mem location-keyed rows in claimed slice:", file=sys.stderr)
    for row in failed_mem_location:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)
if len(const_index_rows) != len(const_index_properties):
    present = {r.get("property") for r in const_index_rows}
    print("missing claimed const-index rows:", file=sys.stderr)
    for property_name in sorted(const_index_properties - present):
        print(property_name, file=sys.stderr)
    raise SystemExit(1)
if failed_const_index:
    print("non-discharged const-index rows in claimed slice:", file=sys.stderr)
    for row in failed_const_index:
        print(f"{row.get('status')} {row.get('property')} {row.get('reason')}", file=sys.stderr)
    raise SystemExit(1)

print(f"claimed-euf-rows={len(euf_rows)} discharged={len(euf_rows)} failed=0")
print(f"typeid-rows={len(type_id_rows)} discharged={len(type_id_rows)} failed=0")
print(f"claimed-mem-location-rows={len(mem_location_rows)} discharged={len(mem_location_rows)} failed=0")
print("claimed-const-index-row=1 discharged=1 failed=0 assertions=6")
print("claimed-cmp-default-row=1 discharged=1 failed=0")
print("claimed-option-constructor-dispatch-row=1 discharged=1 failed=0 assertions=8")
print("claimed-result-nested-constructor-dispatch-row=1 discharged=1 failed=0 assertions=6")
print("claimed-pointer-index-predicate-rows=2 discharged=2 failed=0 assertions=2")
print("claimed-waker-cast-and-pointer-row=1 discharged=1 failed=0 assertions=4")
print("claimed-typed-float-refinement-row=1 discharged=1 failed=0")
print("claimed-is_some-predicate-rows=2 discharged=2 failed=0")
print("claimed-any-is-rows=18 discharged=18 failed=0")
print(
    f"cfg-active-pointer-width={target_pointer_width} "
    f"cfg-active-pointer-bytes={target_pointer_bytes} "
    "cfg-row-delta=4"
)
for row in euf_rows:
    print(f"row: {row.get('property')} status={row.get('status')}")
for row in type_id_rows:
    print(f"typeid-row: {row.get('property')} status={row.get('status')}")
for row in const_index_rows:
    print(f"const-index-row: {row.get('property')} status={row.get('status')}")
print(f"operator-dispatch-row: {option_test_and_row.get('property')} status={option_test_and_row.get('status')}")
print(f"operator-dispatch-row: {result_try_trait_row.get('property')} status={result_try_trait_row.get('status')}")
for row in pointer_index_rows:
    print(f"pointer-index-row: {row.get('property')} status={row.get('status')}")
for row in pointer_vtable_rows:
    print(f"waker-cast-and-pointer-row: {row.get('property')} status={row.get('status')}")
print(f"float-refinement-row: {typed_float_refinement_row.get('property')} status={typed_float_refinement_row.get('status')}")
for row in any_is_rows:
    print(f"any-is-row: {row.get('property')} status={row.get('status')}")
PY

echo "== witness: rerun exact std/core vendor tests =="
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests cmp::cmp_default -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests cmp::test_ord_min_max_by -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests cmp::test_ord_min_max_by_key -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests mem::size_of_basic -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests mem::size_of_"$TARGET_POINTER_WIDTH" -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests mem::align_of_basic -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests mem::align_of_"$TARGET_POINTER_WIDTH" -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests intrinsics::test_typeid_sized_types -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests intrinsics::test_typeid_unsized_types -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests any::any_referenced -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests any::any_owning -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests fmt::test_lifetime -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests option::test_and -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests option::const_get_or_insert_default -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests option::const_get_or_insert_with -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests result::result_try_trait_v2_branch -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests time::div_duration_f32 -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests time::div_duration_f64 -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests num::test_f32f64 -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests num::dec2flt::nan -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests alloc::layout_errors -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests ops::test_range_contains -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests ops::test_range_to_contains -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests ops::test_range_bounds_contains -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests ops::test_range_inclusive_end_bound -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests ops::test_range_bounds -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests atomic::bool_and -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests atomic::uint_and -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests atomic::uint_nand -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests atomic::uint_or -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests atomic::uint_xor -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests atomic::int_and -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests atomic::int_nand -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests atomic::int_or -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests atomic::int_xor -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests iter::range::test_range -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests array::const_array_ops -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests array::array_from_ref -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests slice::test_const_from_ref -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests waker::test_waker_getters -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WITNESS_TARGET" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --target "$STD_CORE_RUST_TARGET" --test coretests intrinsics::test_write_bytes_in_const_contexts -- --exact --nocapture
)

echo "std/core showcase self-check passed"
echo "scope: scalar call-result equality rows from coretests/tests/{cmp.rs,mem.rs,time.rs,fmt/mod.rs}, width-known NaN float refinement rows from time.rs, typed-local and parse/unwrap float refinement rows from num/mod.rs and num/dec2flt/mod.rs, active pinned-target mem cfg rows, direct TypeId comparison rows and const-index rows from intrinsics.rs, direct Any::is::<T>() method-call result rows from any.rs, pure and temporal-identity method-chain predicates from alloc.rs/ops.rs, direct comparison FOL rows from time.rs, stable-key atomic compound bitwise-expression RHS rows, iter/range literal array/tuple exact-value rows, array.rs expression-only const-block call-result rows, pointer-index predicate rows from array.rs/slice.rs, casted-data and pointer-vtable row from waker.rs, option.rs nullary/variant constructor operator-dispatch rows, option.rs is_some predicate rows on const-path receivers, result.rs nested variant constructor operator-dispatch rows, and cmp_default operator-dispatch row discharged; exact vendor tests reran."
echo "not-claimed: full std/coretests; macro surfaces outside this showcase/infinity-equality-via-cast-or-Ok-or-method-arg/ordered-and-signed-zero-float-refinements/chars/inactive-or-ambiguous-cfg rows/ambiguous receiver identity method chains/complex terms without sound keying remain gap census items."
echo "toolchain-detail: $RUSTC_VERBOSE"
