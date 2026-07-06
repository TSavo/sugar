#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"
ASSERT_RPC="$BIN_DIR/rust_test_assertions_rpc"
WITNESS_RPC="$BIN_DIR/witness_rpc"
DISCHARGE_CLI="$BIN_DIR/discharge_cli"
WALK_RPC="$BIN_DIR/sugar-walk-rpc"
SMT_IR="$BIN_DIR/sugar-ir-smt-lib"
LEAN_IR="$BIN_DIR/sugar-ir-lean"
COQ_IR="$BIN_DIR/sugar-ir-coq"
MAUDE_IR="$BIN_DIR/sugar-ir-maude"

for suite in good bad; do
  if [ ! -d "$HERE/$suite" ]; then
    echo "missing suite directory: $HERE/$suite" >&2
    exit 1
  fi
done

if [ "${POLARS_SHOWCASE_ON_REMOTE:-0}" != "1" ] \
  && [ "${POLARS_SHOWCASE_USE_BCARGO:-1}" != "0" ] \
  && [ "$(uname -s)" != "Linux" ]; then
  echo "== run polars showcase on battleaxe via bcargo =="
  "$REPO/bin/bcargo" build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar \
    -p sugar-ir-compiler-smt-lib --bin sugar-ir-smt-lib \
    -p sugar-ir-compiler-lean --bin sugar-ir-lean \
    -p sugar-ir-compiler-coq --bin sugar-ir-coq \
    -p sugar-ir-compiler-maude --bin sugar-ir-maude \
    -p sugar-walk --bin sugar-walk-rpc \
    -p sugar-lift-rust-tests --bin rust_test_assertions_rpc \
    -p sugar-lift-rust-cargo-test-witness --bin witness_rpc \
    -p sugar-lift-rust-cargo-test-witness --bin discharge_cli >/dev/null

  remote_host="${BCARGO_REMOTE_HOST:-battleaxe}"
  remote_tag="$(printf '%s' "$(cd "$REPO" && pwd -P)" | shasum 2>/dev/null | cut -c1-12)"
  remote_tag="${remote_tag:-default}"
  remote_root="${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-${remote_tag}}"
  remote_repo="$remote_root/sugar"
  remote_cmd="cd $(printf '%q' "$remote_repo") && POLARS_SHOWCASE_ON_REMOTE=1 POLARS_SHOWCASE_SKIP_LOCAL_BUILD=1 examples/polars-showcase/run.sh"
  ssh -o BatchMode=yes "$remote_host" "bash -lc $(printf '%q' "$remote_cmd")"
  exit $?
fi

if [ "${POLARS_SHOWCASE_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
  echo "== build local proof binaries =="
  cargo build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar \
    -p sugar-ir-compiler-smt-lib --bin sugar-ir-smt-lib \
    -p sugar-ir-compiler-lean --bin sugar-ir-lean \
    -p sugar-ir-compiler-coq --bin sugar-ir-coq \
    -p sugar-ir-compiler-maude --bin sugar-ir-maude \
    -p sugar-walk --bin sugar-walk-rpc \
    -p sugar-lift-rust-tests --bin rust_test_assertions_rpc \
    -p sugar-lift-rust-cargo-test-witness --bin witness_rpc \
    -p sugar-lift-rust-cargo-test-witness --bin discharge_cli >/dev/null
fi

for bin in "$SUGAR" "$ASSERT_RPC" "$WITNESS_RPC" "$DISCHARGE_CLI" "$WALK_RPC" "$SMT_IR" "$LEAN_IR" "$COQ_IR" "$MAUDE_IR"; do
  if [ ! -x "$bin" ]; then
    echo "missing executable: $bin" >&2
    exit 1
  fi
done

write_component_manifest() {
  local name="$1"
  local command="$2"
  local dir="$HERE/.sugar/components/$name"
  mkdir -p "$dir"
  cat > "$dir/manifest.toml" <<TOML
name = "$name"
version = "0.1.0"
protocol_version = "sugar-component/1"
command = ["$command"]
TOML
}

write_component_registry() {
  rm -rf "$HERE/.sugar/components"
  write_component_manifest "rust-test-assertions" "$ASSERT_RPC"
  write_component_manifest "rust-cargo-test-witness" "$WITNESS_RPC"
  write_component_manifest "rust-walk" "$WALK_RPC"
  write_component_manifest "ir-compiler-smt-lib" "$SMT_IR"
  write_component_manifest "ir-compiler-lean" "$LEAN_IR"
  write_component_manifest "ir-compiler-coq" "$COQ_IR"
  write_component_manifest "ir-compiler-maude" "$MAUDE_IR"
}

render_manifests() {
  local suite="$1"
  local base="$HERE/$suite/.sugar/lift"

  sed "s|@BIN_DIR@|$BIN_DIR|g" \
    "$base/rust-test-assertions/manifest.toml.in" \
    > "$base/rust-test-assertions/manifest.toml"

  sed "s|@BIN_DIR@|$BIN_DIR|g" \
    "$base/rust-cargo-test-witness/manifest.toml.in" \
    > "$base/rust-cargo-test-witness/manifest.toml"
}

clean_suite() {
  local suite="$1"
  local dir="$HERE/$suite"
  rm -f "$dir"/blake3-512_*.proof "$dir/.prove.json" "$dir/.verify.json" "$dir/.verify_recompute.json"
  rm -rf "$dir/.sugar/runs" "$dir/.sugar/witnesses" "$dir/target"
}

consistency_status() {
  python3 - "$1" <<'PY'
import json
import re
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
match = re.search(r"(?m)^\{", text)
if not match:
    print("MISSING")
    raise SystemExit(0)
data = json.loads(text[match.start():])

rows = data.get("rows") or data.get("obligations") or (data if isinstance(data, list) else [])
for row in rows:
    prop = row.get("property") or row.get("predicate") or ""
    # The TEST-ASSERTION consistency row, NOT the production function's own
    # `consistency:rust-source::<fn>` value self-contract. The SourceOracle
    # audit (PR #2138) emits that single-fact production self-contract into the
    # same report; it is trivially SAT and always discharges, but this receipt
    # asserts about the TEST's assertion-set consistency (the row carrying the
    # test source path), so skip the `rust-source::` production prefix.
    if (
        prop.startswith("consistency:")
        and not prop.startswith("consistency:rust-source::")
        and "witness-package" not in prop
    ):
        print(row.get("status") or row.get("result") or "")
        raise SystemExit(0)
print("MISSING")
raise SystemExit(0)
PY
}

witness_status() {
  python3 - "$1" <<'PY'
import json
import re
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
match = re.search(r"(?m)^\{", text)
if not match:
    print("MISSING")
    raise SystemExit(0)
data = json.loads(text[match.start():])

rows = data.get("rows") or data.get("obligations") or (data if isinstance(data, list) else [])
for row in rows:
    prop = row.get("property") or row.get("predicate") or ""
    if "witness-package" in prop:
        print(row.get("status") or row.get("result") or "")
        raise SystemExit(0)
print("MISSING")
raise SystemExit(0)
PY
}

witness_verdict() {
  python3 - "$1" <<'PY'
import json
import re
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
match = re.search(r"(?m)^\{", text)
if not match:
    print("MISSING")
    raise SystemExit(0)
data = json.loads(text[match.start():])

for witness in data.get("witnessDimension", {}).get("witnesses", []):
    verdict = witness.get("verdict")
    if verdict:
        print(verdict)
        raise SystemExit(0)
print("MISSING")
raise SystemExit(0)
PY
}

witness_recompute_strategy() {
  python3 - "$1" <<'PY'
import json
import re
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
match = re.search(r"(?m)^\{", text)
if not match:
    print("MISSING")
    raise SystemExit(0)
data = json.loads(text[match.start():])

for witness in data.get("witnessDimension", {}).get("witnesses", []):
    checks = witness.get("checks") or []
    if "content-address:recompute" in checks:
        print("content-address:recompute")
        raise SystemExit(0)
    strategy = witness.get("resolution_strategy") or witness.get("resolutionStrategy")
    if strategy:
        print(strategy)
        raise SystemExit(0)
print("MISSING")
raise SystemExit(0)
PY
}

bridge_resolution_status() {
  python3 - "$1" <<'PY'
import json
import re
import sys

path = sys.argv[1]
text = open(path, "r", encoding="utf-8").read()
match = re.search(r"(?m)^\{", text)
if not match:
    print("MISSING")
    raise SystemExit(0)
data = json.loads(text[match.start():])

rows = data.get("rows") or data.get("obligations") or (data if isinstance(data, list) else [])
for row in rows:
    if row.get("bridge") != "call:scalar_sum":
        continue
    reason = row.get("reason") or ""
    target = row.get("targetCid") or row.get("targetContractCid")
    if "not in pool" in reason:
        print("MISSING")
        raise SystemExit(0)
    if isinstance(target, str) and target.startswith("blake3-512:"):
        print("resolved")
        raise SystemExit(0)
print("MISSING")
raise SystemExit(0)
PY
}

run_suite() {
  local suite="$1"
  local expect_consistency="$2"
  local expect_witness="$3"
  local dir="$HERE/$suite"

  render_manifests "$suite"
  clean_suite "$suite"

  echo "== mint $suite =="
  (cd "$dir" && SUGAR_COMPONENT_PATH="$HERE/.sugar/components" "$SUGAR" mint --out .) >/dev/null

  local proof
  proof="$(find "$dir" -maxdepth 1 -name 'blake3-512_*.proof' -print -quit)"
  if [ -z "$proof" ]; then
    echo "$suite did not mint a proof" >&2
    exit 1
  fi

  echo "== prove $suite =="
  set +e
  (cd "$dir" && PATH="$BIN_DIR:$PATH" SUGAR_COMPONENT_PATH="$HERE/.sugar/components" "$SUGAR" prove . --json) > "$dir/.prove.json" 2>&1
  local prove_rc=$?
  set -e

  local got_consistency
  got_consistency="$(consistency_status "$dir/.prove.json")"
  local got_witness
  got_witness="$(witness_status "$dir/.prove.json")"
  local got_bridge
  got_bridge="$(bridge_resolution_status "$dir/.prove.json")"

  if [ "$got_bridge" != "resolved" ]; then
    echo "$suite bridge target expected resolved proof-pool member, got $got_bridge" >&2
    cat "$dir/.prove.json" >&2
    exit 1
  fi

  if [ "$expect_consistency" = "discharged" ]; then
    if [ "$got_consistency" != "discharged" ]; then
      echo "$suite consistency expected discharged, got $got_consistency" >&2
      cat "$dir/.prove.json" >&2
      exit 1
    fi
  else
    if [ "$got_consistency" = "discharged" ] || [ "$got_consistency" = "MISSING" ]; then
      echo "$suite consistency expected refusal, got $got_consistency" >&2
      cat "$dir/.prove.json" >&2
      exit 1
    fi
  fi

  if [ "$expect_witness" = "discharged" ]; then
    if [ "$got_witness" != "discharged" ]; then
      echo "$suite witness expected discharged, got $got_witness" >&2
      cat "$dir/.prove.json" >&2
      exit 1
    fi
    : "$prove_rc"

    echo "== verify $suite witness =="
    set +e
    (cd "$dir" && PATH="$BIN_DIR:$PATH" SUGAR_COMPONENT_PATH="$HERE/.sugar/components" "$SUGAR" verify --project . --json) > "$dir/.verify.json" 2>&1
    local verify_rc=$?
    set -e
    : "$verify_rc"
    local verify_verdict
    verify_verdict="$(witness_verdict "$dir/.verify.json")"
    if [ "$verify_verdict" != "verified" ]; then
      echo "$suite witness verification expected verified, got $verify_verdict" >&2
      cat "$dir/.verify.json" >&2
      exit 1
    fi

    rm -rf "$dir/.sugar/witnesses"
    set +e
    (cd "$dir" && PATH="$BIN_DIR:$PATH" SUGAR_COMPONENT_PATH="$HERE/.sugar/components" "$SUGAR" verify --project . --json) > "$dir/.verify_recompute.json" 2>&1
    local verify_recompute_rc=$?
    set -e
    : "$verify_recompute_rc"
    local recompute_strategy
    recompute_strategy="$(witness_recompute_strategy "$dir/.verify_recompute.json")"
    if [ "$recompute_strategy" != "content-address:recompute" ]; then
      echo "$suite witness recompute expected content-address:recompute, got $recompute_strategy" >&2
      cat "$dir/.verify_recompute.json" >&2
      exit 1
    fi
  else
    if [ "$got_witness" = "discharged" ] || [ "$got_witness" = "MISSING" ]; then
      echo "$suite witness expected refusal, got $got_witness" >&2
      cat "$dir/.prove.json" >&2
      exit 1
    fi
  fi

  echo "$suite bridge=$got_bridge consistency=$got_consistency witness=$got_witness"
}

write_component_registry

# The bridge-linkage tooth is: call:scalar_sum resolves to a loaded proof-pool
# member, the truthful witness discharges, and the lying twin remains
# unsatisfied. The singleton consistency row still follows the current
# vacuity/body-discharge law and is not this showcase's green criterion.
run_suite good refused discharged
run_suite bad refused refused

echo "polars showcase self-check passed"
