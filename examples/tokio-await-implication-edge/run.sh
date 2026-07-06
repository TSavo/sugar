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

if [ "${TOKIO_AWAIT_EDGE_SHOWCASE_ON_REMOTE:-0}" != "1" ] \
  && [ "${TOKIO_AWAIT_EDGE_SHOWCASE_USE_BCARGO:-1}" != "0" ] \
  && [ "$(uname -s)" != "Linux" ]; then
  echo "== run tokio await implication edge showcase on battleaxe via bcargo =="
  "$REPO/bin/bcargo" build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar \
    -p sugar-walk --bin sugar-walk-rpc \
    -p sugar-lift-rust-cargo-test-witness --bin witness_rpc \
    -p sugar-lift-rust-cargo-test-witness --bin discharge_cli >/dev/null

  remote_host="${BCARGO_REMOTE_HOST:-battleaxe}"
  remote_tag="$(printf '%s' "$(cd "$REPO" && pwd -P)" | shasum 2>/dev/null | cut -c1-12)"
  remote_tag="${remote_tag:-default}"
  remote_root="${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-${remote_tag}}"
  remote_repo="$remote_root/sugar"
  remote_cmd="cd $(printf '%q' "$remote_repo") && TOKIO_AWAIT_EDGE_SHOWCASE_ON_REMOTE=1 TOKIO_AWAIT_EDGE_SHOWCASE_SKIP_LOCAL_BUILD=1 examples/tokio-await-implication-edge/run.sh"
  ssh -o BatchMode=yes "$remote_host" "bash -lc $(printf '%q' "$remote_cmd")"
  exit $?
fi

echo "== resolve local proof binaries via sugarbin =="
SUGAR="$("$REPO/bin/sugarbin" --profile debug)"
BIN_DIR="$(dirname "$SUGAR")"
WALK_RPC="$("$REPO/bin/sugarbin" --profile debug --bin sugar-walk-rpc)"
WITNESS_RPC="$("$REPO/bin/sugarbin" --profile debug --bin witness_rpc)"
DISCHARGE_CLI="$("$REPO/bin/sugarbin" --profile debug --bin discharge_cli)"

for bin in "$SUGAR" "$WALK_RPC" "$WITNESS_RPC" "$DISCHARGE_CLI"; do
  if [ ! -x "$bin" ]; then
    echo "missing executable: $bin" >&2
    exit 1
  fi
done

render_manifests() {
  local suite="$1"
  local base="$HERE/$suite/.sugar/lift"

  sed "s|@BIN_DIR@|$BIN_DIR|g" \
    "$base/rust-fn-contracts/manifest.toml.in" \
    > "$base/rust-fn-contracts/manifest.toml"

  sed "s|@BIN_DIR@|$BIN_DIR|g" \
    "$base/rust-implications/manifest.toml.in" \
    > "$base/rust-implications/manifest.toml"

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

edge_status() {
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
        continue
    if row.get("bridge") == "consumer" or row.get("callee") == "consumer":
        print(row.get("status") or row.get("result") or "")
        raise SystemExit(0)
print("MISSING")
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
  local expect_edge="$2"
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

  local got_edge got_witness
  got_edge="$(edge_status "$dir/.prove.json")"
  got_witness="$(witness_status "$dir/.prove.json")"

  if [ "$expect_edge" = "discharged" ]; then
    if [ "$got_edge" != "discharged" ]; then
      echo "$suite await implication edge expected discharged, got $got_edge" >&2
      cat "$dir/.prove.json" >&2
      exit 1
    fi
  else
    if [ "$got_edge" = "discharged" ] || [ "$got_edge" = "MISSING" ]; then
      echo "$suite await implication edge expected refusal, got $got_edge" >&2
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
    set +e
    (cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json) > "$dir/.verify.json" 2>&1
    set -e
    local verify_verdict
    verify_verdict="$(witness_verdict "$dir/.verify.json")"
    if [ "$verify_verdict" != "verified" ]; then
      echo "$suite witness verification expected verified, got $verify_verdict" >&2
      cat "$dir/.verify.json" >&2
      exit 1
    fi

    rm -rf "$dir/.sugar/witnesses"
    set +e
    (cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json) > "$dir/.verify_recompute.json" 2>&1
    set -e
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

  echo "$suite await_edge=$got_edge witness=$got_witness"
}

echo "EFFECT: Rust .await is a structural seam where producer.post must imply consumer.pre."
echo "SCOPE: self-checking the awaited implication edge row (bridge=consumer); unrelated producer/self-post rows are not this property."
run_suite good discharged discharged
run_suite bad refused refused

echo "tokio await implication edge showcase self-check passed"
