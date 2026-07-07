#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"

for suite in good bad; do
  if [ ! -d "$HERE/$suite" ]; then
    echo "missing suite directory: $HERE/$suite" >&2
    exit 1
  fi
done

if [ "${TOKIO_EFFECT_SHOWCASE_ON_REMOTE:-0}" != "1" ] \
  && [ "${TOKIO_EFFECT_SHOWCASE_USE_BCARGO:-1}" != "0" ] \
  && [ "$(uname -s)" != "Linux" ]; then
  echo "== run tokio effect showcase on battleaxe via bcargo =="
  "$REPO/bin/bcargo" build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar \
    -p sugar-lift-rust-tests --bin rust_test_assertions_rpc \
    -p sugar-lift-rust-cargo-test-witness --bin witness_rpc \
    -p sugar-lift-rust-cargo-test-witness --bin discharge_cli \
    -p sugar-walk --bin sugar-walk-rpc \
    -p sugar-ir-compiler-smt-lib --bin sugar-ir-smt-lib \
    -p sugar-ir-compiler-lean --bin sugar-ir-lean \
    -p sugar-ir-compiler-coq --bin sugar-ir-coq \
    -p sugar-ir-compiler-maude --bin sugar-ir-maude >/dev/null

  remote_host="${BCARGO_REMOTE_HOST:-battleaxe}"
  remote_tag="$(printf '%s' "$(cd "$REPO" && pwd -P)" | shasum 2>/dev/null | cut -c1-12)"
  remote_tag="${remote_tag:-default}"
  remote_root="${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-${remote_tag}}"
  remote_repo="$remote_root/sugar"
  remote_cmd="cd $(printf '%q' "$remote_repo") && TOKIO_EFFECT_SHOWCASE_ON_REMOTE=1 TOKIO_EFFECT_SHOWCASE_SKIP_LOCAL_BUILD=1 examples/tokio-effect-consistency/run.sh"
  ssh -o BatchMode=yes "$remote_host" "bash -lc $(printf '%q' "$remote_cmd")"
  exit $?
fi

echo "== resolve local proof binaries via sugarbin =="
SUGAR="$("$REPO/bin/sugarbin" --profile debug)"
BIN_DIR="$(dirname "$SUGAR")"
ASSERT_RPC="$("$REPO/bin/sugarbin" --profile debug --bin rust_test_assertions_rpc)"
WITNESS_RPC="$("$REPO/bin/sugarbin" --profile debug --bin witness_rpc)"
DISCHARGE_CLI="$("$REPO/bin/sugarbin" --profile debug --bin discharge_cli)"
WALK_RPC="$("$REPO/bin/sugarbin" --profile debug --bin sugar-walk-rpc)"
IR_SMT_LIB="$("$REPO/bin/sugarbin" --profile debug --bin sugar-ir-smt-lib)"
IR_LEAN="$("$REPO/bin/sugarbin" --profile debug --bin sugar-ir-lean)"
IR_COQ="$("$REPO/bin/sugarbin" --profile debug --bin sugar-ir-coq)"
IR_MAUDE="$("$REPO/bin/sugarbin" --profile debug --bin sugar-ir-maude)"

for bin in "$SUGAR" "$ASSERT_RPC" "$WITNESS_RPC" "$DISCHARGE_CLI" "$WALK_RPC" "$IR_SMT_LIB" "$IR_LEAN" "$IR_COQ" "$IR_MAUDE"; do
  if [ ! -x "$bin" ]; then
    echo "missing executable: $bin" >&2
    exit 1
  fi
done

# Do NOT fall back to the repo-root `.sugar/components` registry: it hardcodes
# `implementations/rust/target/debug/<bin>` paths that are only populated by a
# full local `cargo build`, not by this script's targeted sugarbin/bcargo
# resolution (#3755 recensus4: a fresh bcargo remote clone has only the four
# binaries this script asks for, so the ambient registry's ir-compiler-* /
# rust-walk components fail to spawn and `sugar mint`/`prove`/`verify` error
# out). Write a self-contained local registry pointing at the binaries this
# script itself resolved, same pattern as serde-json-showcase and
# rust-witness-showcase, and point every sugar invocation at it via
# SUGAR_COMPONENT_PATH (which takes precedence over ancestor project roots).
COMPONENTS_DIR="$HERE/.sugar/components"
write_component_manifest() {
  local name="$1" command="$2"
  local dir="$COMPONENTS_DIR/$name"
  mkdir -p "$dir"
  cat > "$dir/manifest.toml" <<TOML
name = "$name"
version = "0.1.0"
protocol_version = "sugar-component/1"
command = ["$command"]
TOML
}

rm -rf "$COMPONENTS_DIR"
write_component_manifest "rust-test-assertions" "$ASSERT_RPC"
write_component_manifest "rust-cargo-test-witness" "$WITNESS_RPC"
write_component_manifest "rust-walk" "$WALK_RPC"
write_component_manifest "ir-compiler-smt-lib" "$IR_SMT_LIB"
write_component_manifest "ir-compiler-lean" "$IR_LEAN"
write_component_manifest "ir-compiler-coq" "$IR_COQ"
write_component_manifest "ir-compiler-maude" "$IR_MAUDE"
export SUGAR_COMPONENT_PATH="$COMPONENTS_DIR"

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

json_status() {
  local path="$1"
  local mode="$2"
  python3 - "$path" "$mode" <<'PY'
import json
import re
import sys

path, mode = sys.argv[1], sys.argv[2]
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
        mode == "consistency"
        and prop.startswith("consistency:")
        and not prop.startswith("consistency:rust-source::")
        and "witness-package" not in prop
    ):
        print(row.get("status") or row.get("result") or "")
        raise SystemExit(0)
    if mode == "witness" and "witness-package" in prop:
        print(row.get("status") or row.get("result") or "")
        raise SystemExit(0)
print("MISSING")
PY
}

witness_verdict() {
  python3 - "$1" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], "r", encoding="utf-8").read()
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
PY
}

witness_recompute_strategy() {
  python3 - "$1" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], "r", encoding="utf-8").read()
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
print("MISSING")
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
  (cd "$dir" && "$SUGAR" mint --out .) >/dev/null

  local proof
  proof="$(find "$dir" -maxdepth 1 -name 'blake3-512_*.proof' -print -quit)"
  if [ -z "$proof" ]; then
    echo "$suite did not mint a proof" >&2
    exit 1
  fi

  echo "== prove $suite =="
  set +e
  (cd "$dir" && "$SUGAR" prove . --json) > "$dir/.prove.json" 2>&1
  set -e

  local got_consistency got_witness
  got_consistency="$(json_status "$dir/.prove.json" consistency)"
  got_witness="$(json_status "$dir/.prove.json" witness)"

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

    echo "== verify $suite witness =="
    # #3755: this call must NEVER die silently. It used to run bare under the
    # script's `set -euo pipefail`, so a nonzero/crashing `sugar verify` (its
    # own stdout+stderr captured into .verify.json, invisible to this log)
    # killed the whole script instantly with no PASS/FAIL line and no visible
    # diagnostic -- exactly the "dies right after the header" shape from
    # recensus4. Guard it like the `prove` call above, then print a named,
    # legible failure (with the captured output) instead of a silent abort.
    # `sugar verify`'s own process exit code reflects the verdict over ALL
    # claims in the project (including known-vacuous residual rows this
    # showcase doesn't care about, same as `prove`'s json_status above only
    # inspecting the first matching row) -- it is not the signal we gate on.
    # The signal is whether the witness dimension itself parses as "verified".
    # We still capture the exit code for the diagnostic message so a genuine
    # crash (nonzero rc AND no parseable witness verdict) is named, not silent.
    set +e
    (cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json) > "$dir/.verify.json" 2>&1
    local verify_rc=$?
    set -e
    local verify_verdict
    verify_verdict="$(witness_verdict "$dir/.verify.json")"
    if [ "$verify_verdict" != "verified" ]; then
      echo "$suite witness verification expected verified, got $verify_verdict (sugar verify exit code $verify_rc)" >&2
      cat "$dir/.verify.json" >&2
      exit 1
    fi

    rm -rf "$dir/.sugar/witnesses"
    set +e
    (cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json) > "$dir/.verify_recompute.json" 2>&1
    local recompute_rc=$?
    set -e
    local recompute_strategy
    recompute_strategy="$(witness_recompute_strategy "$dir/.verify_recompute.json")"
    if [ "$recompute_strategy" != "content-address:recompute" ]; then
      echo "$suite witness recompute expected content-address:recompute, got $recompute_strategy (sugar verify exit code $recompute_rc)" >&2
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

  echo "$suite consistency=$got_consistency witness=$got_witness"
}

echo "EFFECT: Rust .await is lifted as a structural await term inside the assertion-consistency obligation."
run_suite good discharged discharged
run_suite bad refused refused

echo "tokio effect consistency showcase self-check passed"
