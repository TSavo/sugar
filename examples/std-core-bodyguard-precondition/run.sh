#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"
WALK_RPC="$BIN_DIR/sugar-walk-rpc"
WITNESS_RPC="$BIN_DIR/witness_rpc"
DISCHARGE_CLI="$BIN_DIR/discharge_cli"
source "$REPO/scripts/stdlib-solver-portfolio.sh"
WORK="${STD_CORE_BODYGUARD_WORK:-$HERE/.work}"
STD_CORE_RUST_TOOLCHAIN="${STD_CORE_RUST_TOOLCHAIN:-1.96.0}"

CASES=(
  to-digit
  slice-chunks
  slice-chunks-exact
  slice-rchunks
  slice-rchunks-exact
)

echo "SCOPE: Rust std/core body guard -> precondition predicate, zero std source changes."
echo "SCOPE: chosen guards = char::to_digit radix range plus slice chunk-size guards from pinned rust-src $STD_CORE_RUST_TOOLCHAIN."
echo "SCOPE: proof property = caller value facts discharge/refuse callee precondition at the method-call seam."
echo "SCOPE: no panic semantics are modeled; panic is only the syntactic marker for the invalid-input branch."
echo "SCOPE: skipped residuals = split_at match/checked-helper shape, split_at_unchecked assert_unsafe_precondition!, windows NonZero::new(...).expect(...), non-flat guards, hidden expect/unwrap, loops, match arms, if-then-else strengthening, and early-return reasoning."

ensure_rust_src() {
  local sysroot stdroot
  sysroot="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" --print sysroot 2>/dev/null || true)"
  stdroot="$sysroot/lib/rustlib/src/rust/library"
  if [ ! -f "$stdroot/core/src/char/methods.rs" ] || [ ! -f "$stdroot/core/src/slice/mod.rs" ]; then
    if command -v rustup >/dev/null 2>&1; then
      echo "== install rust-src for pinned toolchain $STD_CORE_RUST_TOOLCHAIN ==" >&2
      rustup toolchain install "$STD_CORE_RUST_TOOLCHAIN" --profile minimal --component rust-src >/dev/null
      sysroot="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" --print sysroot)"
      stdroot="$sysroot/lib/rustlib/src/rust/library"
    fi
  fi
  for required in \
    "$stdroot/core/src/char/methods.rs" \
    "$stdroot/core/src/slice/mod.rs" \
    "$stdroot/coretests/tests/char.rs" \
    "$stdroot/alloctests/tests/slice.rs"
  do
    if [ ! -f "$required" ]; then
      echo "missing pinned rust-src file: $required" >&2
      exit 1
    fi
  done
  printf '%s\n' "$stdroot"
}

if [ "${STD_CORE_BODYGUARD_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
  echo "== build local proof binaries =="
  cargo build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar \
    -p sugar-walk --bin sugar-walk-rpc \
    -p sugar-lift-rust-cargo-test-witness --bin witness_rpc \
    -p sugar-lift-rust-cargo-test-witness --bin discharge_cli \
    -p sugar-ir-compiler-smt-lib --bin sugar-ir-smt-lib \
    -p sugar-ir-compiler-coq --bin sugar-ir-coq \
    -p sugar-ir-compiler-lean --bin sugar-ir-lean \
    -p sugar-ir-compiler-maude --bin sugar-ir-maude >/dev/null
fi

for bin in "$SUGAR" "$WALK_RPC" "$WITNESS_RPC" "$DISCHARGE_CLI"; do
  if [ ! -x "$bin" ]; then
    echo "missing executable: $bin" >&2
    exit 1
  fi
done

STDROOT="$(ensure_rust_src)"
RUSTC_VERSION="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" --version)"
RUSTC_VERBOSE="$(rustc "+$STD_CORE_RUST_TOOLCHAIN" --version --verbose | tr '\n' ';')"
echo "rust-src: $STDROOT"
echo "toolchain: $RUSTC_VERSION"

rm -rf "$WORK"
mkdir -p "$WORK"

case_package_base() {
  case "$1" in
    to-digit) echo "std-core-bodyguard-to-digit" ;;
    slice-chunks) echo "std-core-bodyguard-slice-chunks" ;;
    slice-chunks-exact) echo "std-core-bodyguard-slice-chunks-exact" ;;
    slice-rchunks) echo "std-core-bodyguard-slice-rchunks" ;;
    slice-rchunks-exact) echo "std-core-bodyguard-slice-rchunks-exact" ;;
    *) echo "unknown case: $1" >&2; exit 1 ;;
  esac
}

case_source_rel() {
  case "$1" in
    to-digit) echo "core/src/char/methods.rs" ;;
    slice-*) echo "core/src/slice/mod.rs" ;;
    *) echo "unknown case: $1" >&2; exit 1 ;;
  esac
}

case_source_link() {
  case "$1" in
    to-digit) echo "core_char_methods.rs" ;;
    slice-*) echo "core_slice_bodyguards.rs" ;;
    *) echo "unknown case: $1" >&2; exit 1 ;;
  esac
}

case_method() {
  case "$1" in
    to-digit) echo "method:to_digit" ;;
    slice-chunks) echo "method:chunks" ;;
    slice-chunks-exact) echo "method:chunks_exact" ;;
    slice-rchunks) echo "method:rchunks" ;;
    slice-rchunks-exact) echo "method:rchunks_exact" ;;
    *) echo "unknown case: $1" >&2; exit 1 ;;
  esac
}

case_good_arg() {
  case "$1" in
    to-digit) echo "16" ;;
    slice-*) echo "2" ;;
    *) echo "unknown case: $1" >&2; exit 1 ;;
  esac
}

case_bad_arg() {
  case "$1" in
    to-digit) echo "1" ;;
    slice-*) echo "0" ;;
    *) echo "unknown case: $1" >&2; exit 1 ;;
  esac
}

case_bad_attr() {
  case "$1" in
    to-digit) echo '    #[should_panic(expected = "to_digit: invalid radix")]' ;;
    slice-*) echo '    #[should_panic(expected = "chunk size must be non-zero")]' ;;
    *) echo "unknown case: $1" >&2; exit 1 ;;
  esac
}

case_good_assertion() {
  case "$1" in
    to-digit) echo "        assert_eq!(bodyguard_edge(), Some(10));" ;;
    slice-chunks) echo "        assert_eq!(bodyguard_edge(), 3);" ;;
    slice-chunks-exact) echo "        assert_eq!(bodyguard_edge(), 2);" ;;
    slice-rchunks) echo "        assert_eq!(bodyguard_edge(), 3);" ;;
    slice-rchunks-exact) echo "        assert_eq!(bodyguard_edge(), 2);" ;;
    *) echo "unknown case: $1" >&2; exit 1 ;;
  esac
}

case_predicate_label() {
  case "$1" in
    to-digit) echo "radix >= 2 && radix <= 36" ;;
    slice-*) echo "chunk_size != 0" ;;
    *) echo "unknown case: $1" >&2; exit 1 ;;
  esac
}

case_function_name() {
  case "$1" in
    to-digit) echo "char::to_digit" ;;
    slice-chunks) echo "slice::chunks" ;;
    slice-chunks-exact) echo "slice::chunks_exact" ;;
    slice-rchunks) echo "slice::rchunks" ;;
    slice-rchunks-exact) echo "slice::rchunks_exact" ;;
    *) echo "unknown case: $1" >&2; exit 1 ;;
  esac
}

write_slice_bodyguard_source() {
  python3 - "$STDROOT/core/src/slice/mod.rs" "$1" <<'PY'
import sys

source, dest = sys.argv[1:]
lines = open(source, encoding="utf-8").read().splitlines()
names = ["chunks", "chunks_exact", "rchunks", "rchunks_exact"]

def extract_method(name: str) -> list[str]:
    sig_idx = next(
        i for i, line in enumerate(lines)
        if f"pub const fn {name}(" in line
    )
    out = []
    depth = 0
    seen_open = False
    for line in lines[sig_idx:]:
        out.append(line)
        depth += line.count("{")
        if "{" in line:
            seen_open = True
        depth -= line.count("}")
        if seen_open and depth == 0:
            return out
    raise RuntimeError(f"unterminated method {name}")

chunks = [
    "// Extracted verbatim from pinned rust-src core/src/slice/mod.rs by run.sh.",
    "// Kept minimal so sugar-walk can parse the primitive-slice impl methods.",
    "impl<T> [T] {",
]
for name in names:
    chunks.extend(extract_method(name))
    chunks.append("")
chunks.append("}")
open(dest, "w", encoding="utf-8").write("\n".join(chunks))
PY
}

write_bodyguard_lib() {
  local case_name="$1"
  local arg="$2"
  local test_attr="$3"
  local expected_body="$4"
  local dest="$5"

  case "$case_name" in
    to-digit)
      cat > "$dest" <<RS
pub fn bodyguard_edge() -> Option<u32> {
    let ch = 'a';
    ch.to_digit($arg)
}

#[cfg(test)]
mod tests {
    use super::bodyguard_edge;

    #[test]
$test_attr
    fn bodyguard_witness() {
$expected_body
    }
}
RS
      ;;
    slice-chunks)
      cat > "$dest" <<RS
pub fn bodyguard_edge() -> usize {
    let values = [1, 2, 3, 4, 5];
    values.chunks($arg).len()
}

#[cfg(test)]
mod tests {
    use super::bodyguard_edge;

    #[test]
$test_attr
    fn bodyguard_witness() {
$expected_body
    }
}
RS
      ;;
    slice-chunks-exact)
      cat > "$dest" <<RS
pub fn bodyguard_edge() -> usize {
    let values = [1, 2, 3, 4, 5];
    values.chunks_exact($arg).len()
}

#[cfg(test)]
mod tests {
    use super::bodyguard_edge;

    #[test]
$test_attr
    fn bodyguard_witness() {
$expected_body
    }
}
RS
      ;;
    slice-rchunks)
      cat > "$dest" <<RS
pub fn bodyguard_edge() -> usize {
    let values = [1, 2, 3, 4, 5];
    values.rchunks($arg).len()
}

#[cfg(test)]
mod tests {
    use super::bodyguard_edge;

    #[test]
$test_attr
    fn bodyguard_witness() {
$expected_body
    }
}
RS
      ;;
    slice-rchunks-exact)
      cat > "$dest" <<RS
pub fn bodyguard_edge() -> usize {
    let values = [1, 2, 3, 4, 5];
    values.rchunks_exact($arg).len()
}

#[cfg(test)]
mod tests {
    use super::bodyguard_edge;

    #[test]
$test_attr
    fn bodyguard_witness() {
$expected_body
    }
}
RS
      ;;
    *) echo "unknown case: $case_name" >&2; exit 1 ;;
  esac
}

write_suite() {
  local case_name="$1"
  local suite="$2"
  local package="$3"
  local arg="$4"
  local test_attr="$5"
  local expected_body="$6"
  local dir="$WORK/$case_name/$suite"

  mkdir -p "$dir/src" \
    "$dir/.sugar/lift/rust-fn-contracts" \
    "$dir/.sugar/lift/rust-implications" \
    "$dir/.sugar/lift/rust-cargo-test-witness"
  if [ "$case_name" = "to-digit" ]; then
    ln -s "$STDROOT/$(case_source_rel "$case_name")" "$dir/src/$(case_source_link "$case_name")"
  else
    write_slice_bodyguard_source "$dir/src/$(case_source_link "$case_name")"
  fi

  cat > "$dir/Cargo.toml" <<TOML
[package]
name = "$package"
version = "0.1.0"
edition = "2021"
TOML

  write_bodyguard_lib "$case_name" "$arg" "$test_attr" "$expected_body" "$dir/src/lib.rs"

  cat > "$dir/.sugar/config.toml" <<TOML
[[plugins]]
name = "rust-fn-contracts"
surface = "rust-fn-contracts"
emit = "ir-document"

[[plugins]]
name = "rust-implications"
surface = "rust-implications"

[[plugins]]
name = "rust-cargo-test-witness"
surface = "rust-cargo-test-witness"

[platform_profile]
language = "rust"
family = "concept:family:sugar"
library = "$package"
version = "0.1.0"
TOML
  append_sugar_solver_portfolio "$dir/.sugar/config.toml" "$REPO"
  write_sugar_ir_compiler_manifests "$dir" "$BIN_DIR"

  cat > "$dir/.sugar/lift/rust-fn-contracts/manifest.toml" <<TOML
name = "rust-fn-contracts-lift"
command = ["$WALK_RPC", "--rpc"]
working_dir = "."
TOML

  cat > "$dir/.sugar/lift/rust-implications/manifest.toml" <<TOML
name = "rust-implications-lift"
command = ["$WALK_RPC", "--rpc"]
working_dir = "."
method = "sugar.plugin.lift_implications"
phase = "consumer"
TOML

  cat > "$dir/.sugar/lift/rust-cargo-test-witness/manifest.toml" <<TOML
name = "rust-cargo-test-witness-lift"
version = "0.1.0-draft"
protocol_version = "pep/1.7.0"
kind = "lift"
command = ["$WITNESS_RPC"]
discharge_command = ["$DISCHARGE_CLI"]
witness_tool = "cargo-test"
resolve_witness_command = ["$WITNESS_RPC"]
resolve_witness_method = "sugar.plugin.resolve_witness"
working_dir = "."

[capabilities]
authoring_surfaces = ["rust-cargo-test-witness"]
TOML
}

for case_name in "${CASES[@]}"; do
  base="$(case_package_base "$case_name")"
  write_suite \
    "$case_name" \
    good \
    "$base-good" \
    "$(case_good_arg "$case_name")" \
    "" \
    "$(case_good_assertion "$case_name")"
  write_suite \
    "$case_name" \
    bad \
    "$base-bad" \
    "$(case_bad_arg "$case_name")" \
    "$(case_bad_attr "$case_name")" \
    "        let _ = bodyguard_edge();"
done

edge_value() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
target_property_cid = sys.argv[2]
target_method = sys.argv[3]
field = sys.argv[4]
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
    if isinstance(obj, dict):
        receipt = obj
        break
if receipt is None:
    print("MISSING")
    raise SystemExit(0)
rows = receipt.get("rows") or receipt.get("obligations") or []
for row in rows:
    if row.get("propertyCid") == target_property_cid and row.get("bridge") == target_method:
        print(row.get(field) or "MISSING")
        raise SystemExit(0)
print("MISSING")
PY
}

bodyguard_contract_cid() {
  python3 - "$1" <<'PY'
import json
import sys

doc = json.load(open(sys.argv[1], encoding="utf-8"))
for cid, member in (doc.get("members") or {}).items():
    body = member.get("header") or (member.get("evidence") or {}).get("body") or {}
    kind = body.get("kind") or (member.get("evidence") or {}).get("kind")
    name = body.get("name") or body.get("contractName")
    if kind == "contract" and name == "bodyguard_edge":
        print(cid)
        raise SystemExit(0)
raise SystemExit("bodyguard_edge contract not found in proof")
PY
}

target_precondition() {
  python3 - "$1" "$2" <<'PY'
import json
import sys

doc = json.load(open(sys.argv[1], encoding="utf-8"))
target = sys.argv[2]
member = (doc.get("members") or {}).get(target)
if not member:
    print("MISSING")
    raise SystemExit(0)
body = member.get("header") or (member.get("evidence") or {}).get("body") or {}
formula = body.get("pre")

def render_term(term):
    kind = term.get("kind")
    if kind == "var":
        return term.get("name", "?")
    if kind == "const":
        return str(term.get("value"))
    if kind == "ctor":
        args = ", ".join(render_term(arg) for arg in term.get("args", []))
        return f"{term.get('name', '?')}({args})"
    return json.dumps(term, sort_keys=True)

def render_formula(node):
    if not node:
        return "MISSING"
    kind = node.get("kind")
    if kind == "atomic":
        name = node.get("name", "?")
        args = node.get("args", [])
        op = {"\u2265": ">=", "\u2264": "<=", "\u2260": "!=", "!=": "!=", "=": "=", ">": ">", "<": "<"}.get(name, name)
        if op == "true":
            return "true"
        if len(args) == 2 and op in {"=", "!=", ">=", "<=", ">", "<"}:
            return f"{render_term(args[0])} {op} {render_term(args[1])}"
        return f"{op}({', '.join(render_term(arg) for arg in args)})"
    if kind == "and":
        return " && ".join(render_formula(part) for part in node.get("operands", []))
    if kind == "or":
        return " || ".join(render_formula(part) for part in node.get("operands", []))
    if kind == "not":
        return f"!({render_formula(node.get('operand') or {})})"
    return json.dumps(node, sort_keys=True)

print(render_formula(formula))
PY
}

witness_status() {
  python3 - "$1" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
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
    if isinstance(obj, dict):
        receipt = obj
        break
if receipt is None:
    print("MISSING")
    raise SystemExit(0)
rows = receipt.get("rows") or receipt.get("obligations") or []
for row in rows:
    prop = row.get("property") or row.get("predicate") or ""
    if "witness-package" in prop:
        print(row.get("status") or row.get("result") or "MISSING")
        raise SystemExit(0)
print("MISSING")
PY
}

witness_verdict() {
  python3 - "$1" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
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
    if isinstance(obj, dict):
        receipt = obj
        break
if receipt is None:
    print("MISSING")
    raise SystemExit(0)
for witness in receipt.get("witnessDimension", {}).get("witnesses", []):
    verdict = witness.get("verdict")
    if verdict:
        print(verdict)
        raise SystemExit(0)
print("MISSING")
PY
}

recompute_strategy() {
  python3 - "$1" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
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
    if isinstance(obj, dict):
        receipt = obj
        break
if receipt is None:
    print("MISSING")
    raise SystemExit(0)
for witness in receipt.get("witnessDimension", {}).get("witnesses", []):
    if "content-address:recompute" in (witness.get("checks") or []):
        print("content-address:recompute")
        raise SystemExit(0)
print("MISSING")
PY
}

run_suite() {
  local case_name="$1"
  local suite="$2"
  local expect_edge="$3"
  local method
  method="$(case_method "$case_name")"
  local dir="$WORK/$case_name/$suite"

  rm -f "$dir"/blake3-512_*.proof "$dir/.prove.json" "$dir/.verify.json" "$dir/.verify_recompute.json" "$dir/.proof-dump.json"
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/target"

  echo "== mint $case_name $suite =="
  (cd "$dir" && "$SUGAR" mint --out .) >/dev/null
  proof_path="$(
    python3 - "$dir" <<'PY'
import glob
import os
import sys
matches = sorted(glob.glob(os.path.join(sys.argv[1], "blake3-512_*.proof")))
print(matches[0] if matches else "")
PY
  )"
  if [ -z "$proof_path" ]; then
    echo "$case_name $suite did not mint a proof" >&2
    exit 1
  fi
  "$SUGAR" dump "$proof_path" --json > "$dir/.proof-dump.json"
  echo "$case_name $suite proof: $(basename "$proof_path")"
  local bodyguard_cid
  bodyguard_cid="$(bodyguard_contract_cid "$dir/.proof-dump.json")"
  echo "$case_name $suite bodyguard contract: $bodyguard_cid"

  echo "== prove $case_name $suite =="
  set +e
  (cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" prove . --json) > "$dir/.prove.json" 2>&1
  set -e

  echo "== verify $case_name $suite =="
  set +e
  (cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json) > "$dir/.verify.json" 2>&1
  set -e

  local got_edge got_witness target_cid predicate pair
  got_edge="$(edge_value "$dir/.verify.json" "$bodyguard_cid" "$method" status)"
  got_witness="$(witness_status "$dir/.verify.json")"
  target_cid="$(edge_value "$dir/.verify.json" "$bodyguard_cid" "$method" targetCid)"
  pair="$(edge_value "$dir/.verify.json" "$bodyguard_cid" "$method" property)"
  predicate="$(target_precondition "$dir/.proof-dump.json" "$target_cid")"

  if [ "$expect_edge" = "discharged" ]; then
    if [ "$got_edge" != "discharged" ]; then
      echo "$case_name $suite bodyguard edge expected discharged, got $got_edge" >&2
      cat "$dir/.verify.json" >&2
      exit 1
    fi
  else
    if [ "$got_edge" = "discharged" ] || [ "$got_edge" = "MISSING" ]; then
      echo "$case_name $suite bodyguard edge expected refusal, got $got_edge" >&2
      cat "$dir/.verify.json" >&2
      exit 1
    fi
  fi
  if [ "$got_witness" != "discharged" ]; then
    echo "$case_name $suite cargo-test witness expected discharged, got $got_witness" >&2
    cat "$dir/.verify.json" >&2
    exit 1
  fi

  rm -rf "$dir/.sugar/witnesses"
  set +e
  (cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json) > "$dir/.verify_recompute.json" 2>&1
  set -e
  local recompute verified
  recompute="$(recompute_strategy "$dir/.verify_recompute.json")"
  if [ "$recompute" != "content-address:recompute" ]; then
    echo "$case_name $suite witness recompute expected content-address:recompute, got $recompute" >&2
    cat "$dir/.verify_recompute.json" >&2
    exit 1
  fi
  verified="$(witness_verdict "$dir/.verify_recompute.json")"
  if [ "$verified" != "verified" ]; then
    echo "$case_name $suite witness recompute expected verified, got $verified" >&2
    cat "$dir/.verify_recompute.json" >&2
    exit 1
  fi

  echo "$case_name $suite function=$(case_function_name "$case_name") method=$method predicate=$predicate expected-predicate=$(case_predicate_label "$case_name") verify-json=$dir/.verify.json edge=$got_edge witness=$got_witness recompute=$recompute pair=$pair"
}

for case_name in "${CASES[@]}"; do
  run_suite "$case_name" good discharged
  run_suite "$case_name" bad refused
done

echo "== witness: rerun exact std/core and alloc vendor should_panic tests =="
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WORK/coretests-target" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests char::test_to_digit_radix_too_low -- --exact --nocapture
)
(
  cd "$STDROOT/coretests"
  CARGO_TARGET_DIR="$WORK/coretests-target" RUSTC_BOOTSTRAP=1 \
    cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test coretests char::test_to_digit_radix_too_high -- --exact --nocapture
)

for vendor_test in \
  slice::test_chunks_iterator_0 \
  slice::test_chunks_exact_iterator_0 \
  slice::test_rchunks_iterator_0 \
  slice::test_rchunks_exact_iterator_0
do
  (
    cd "$STDROOT/alloctests"
    CARGO_TARGET_DIR="$WORK/alloctests-target" RUSTC_BOOTSTRAP=1 \
      cargo "+$STD_CORE_RUST_TOOLCHAIN" test --test alloctests "$vendor_test" -- --exact --nocapture
  )
done

echo "std/core bodyguard precondition showcase self-check passed"
echo "effects-free: lifted only body guard conditions as FOL over inputs; no panic/divergence/effect/control-flow semantics introduced."
echo "residuals: skipped split_at because it is match self.split_at_checked(mid) with None panic; skipped split_at_unchecked because the guard is assert_unsafe_precondition!; skipped windows because the panic is hidden behind NonZero::new(size).expect(...); skipped array_windows because no pinned vendor should_panic witness was found."
echo "toolchain-detail: $RUSTC_VERBOSE"
