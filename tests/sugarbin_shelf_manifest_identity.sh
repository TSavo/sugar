#!/usr/bin/env bash
# Filesystem-CAS membership is payload + stable source/platform/target/profile,
# not diagnostic cargo/rustc host residue. Local materializations stay strict.
set -euo pipefail

repo="${1:?usage: sugarbin_shelf_manifest_identity.sh REPO_ROOT}"
tmp_root="${SUGARBIN_EXEC_TMPDIR:-$repo/.sugar/test-tmp}"
mkdir -p "$tmp_root"
tmp="$(mktemp -d "$tmp_root/sugarbin-shelf-manifest.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/target/release" "$tmp/cache" "$tmp/shelf"
: >"$tmp/cargo.log"
printf '%s\n' 'Ubuntu 24.4' >"$tmp/cargo-os"

cat >"$tmp/bin/rustc" <<'SH'
#!/usr/bin/env bash
cat <<'EOF'
rustc 1.96.0 (fake 2026-01-01)
binary: rustc
commit-hash: fake
host: x86_64-unknown-linux-gnu
release: 1.96.0
LLVM version: 22.0.0
EOF
SH
cat >"$tmp/bin/cargo" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == -vV ]]; then
  cat <<EOF
cargo 1.96.0 (fake 2026-01-01)
release: 1.96.0
commit-hash: fake-cargo-commit
commit-date: 2026-01-01
host: x86_64-unknown-linux-gnu
libgit2: 1.9.0
libcurl: 8.12.0
ssl: OpenSSL 3.5.0
os: $(cat "$SUGARBIN_FAKE_CARGO_OS_FILE") [64-bit]
EOF
  exit 0
fi
printf '%s\n' "$*" >>"$SUGARBIN_FAKE_CARGO_LOG"
binary=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == --bin ]]; then binary="$2"; shift 2; else shift; fi
done
mkdir -p "$CARGO_TARGET_DIR/release"
cat >"$CARGO_TARGET_DIR/release/$binary" <<EOF
#!/usr/bin/env bash
printf '%s\\n' 'stable-payload:$binary'
EOF
chmod +x "$CARGO_TARGET_DIR/release/$binary"
SH
chmod +x "$tmp/bin/rustc" "$tmp/bin/cargo"

export PATH="$tmp/bin:$PATH"
export SUGARBIN_FAKE_CARGO_LOG="$tmp/cargo.log"
export SUGARBIN_FAKE_CARGO_OS_FILE="$tmp/cargo-os"
export SUGAR_BINARY_CARGO="$tmp/bin/cargo"
export SUGAR_BINARY_TARGET_ROOT="$tmp/target"
export SUGAR_BINARY_CACHE_DIR="$tmp/cache"
export SUGAR_BINARY_SHELF_ROOT="$tmp/shelf"
export SUGAR_BINARY_SOURCE_STAMP="blake3-512_$(printf 'a%.0s' {1..128})"
export SUGAR_BINARY_NO_SHELF=0
export SUGAR_BINARY_PUBLISH=1

clear_materialization() {
  rm -rf "$tmp/target" "$tmp/cache"
  mkdir -p "$tmp/target/release" "$tmp/cache"
}

clone_shelf() {
  local destination="$1"
  rm -rf "$destination"
  cp -a "$tmp/published-shelf" "$destination"
}

resolve_without_build() {
  SUGAR_BINARY_ALLOW_BUILD=0 SUGAR_BINARY_NO_SELF_HEAL=1 \
    "$repo/bin/sugarbin" --bin sugar
}

# Publish one byte-stable artifact under the Ubuntu diagnostic string.
published="$("$repo/bin/sugarbin" --bin sugar)"
[[ "$($published)" == stable-payload:sugar ]]
[[ "$(wc -l <"$tmp/cargo.log" | tr -d ' ')" == 1 ]]
cp -a "$tmp/shelf" "$tmp/published-shelf"
published_manifest="$tmp/published-manifest.json"
published_binary="$tmp/published-sugar"
cp "$tmp/target/release/sugar.sugarbin.json" "$published_manifest"
cp "$tmp/target/release/sugar" "$published_binary"
chmod +x "$published_binary"

# Positive arm: same source/platform/target/profile and identical payload under
# the same cargo commit, but different host-OS residue, is a filesystem-CAS hit.
printf '%s\n' 'Debian 12' >"$tmp/cargo-os"
clear_materialization
: >"$tmp/cargo.log"
set +e
cross_os_path="$(resolve_without_build 2>"$tmp/cross-os.err")"
cross_os_status=$?
set -e
if [[ "$cross_os_status" != 0 ]]; then
  echo 'byte-identical cross-OS filesystem-CAS resolve refused' >&2
  cat "$tmp/cross-os.err" >&2
  exit 1
fi
[[ "$($cross_os_path)" == stable-payload:sugar ]]
[[ ! -s "$tmp/cargo.log" ]] || {
  echo 'cross-OS CAS hit rebuilt the byte-identical payload' >&2
  exit 1
}
grep -Fq 'phase=resolve-hit source=filesystem-shelf' "$tmp/cross-os.err"
# Materialization mints current local testimony; strict local verification is
# still meaningful after a shelf hit.
grep -Fq 'os: Debian 12 [64-bit]' "$tmp/target/release/sugar.sugarbin.json"

# Strict-local twin: the Ubuntu manifest cannot be blessed as a Debian local
# target merely because its bytes are valid shelf content.
clear_materialization
cp "$published_binary" "$tmp/target/release/sugar"
cp "$published_manifest" "$tmp/target/release/sugar.sugarbin.json"
chmod +x "$tmp/target/release/sugar"
set +e
SUGAR_BINARY_NO_SHELF=1 SUGAR_BINARY_ALLOW_BUILD=0 SUGAR_BINARY_NO_SELF_HEAL=1 \
  "$repo/bin/sugarbin" --bin sugar >"$tmp/local-strict.out" 2>"$tmp/local-strict.err"
local_strict_status=$?
set -e
[[ "$local_strict_status" != 0 ]] || {
  echo 'strict local verifier accepted cargo host-OS drift' >&2
  exit 1
}
grep -Fq 'artifact identity mismatch: cargo' "$tmp/local-strict.err"

# Lying twin 1: stable source authority remains part of shelf membership.
clone_shelf "$tmp/wrong-source-shelf"
export SUGAR_BINARY_SHELF_ROOT="$tmp/wrong-source-shelf"
python3 - "$SUGAR_BINARY_SHELF_ROOT" <<'PY'
import json
import pathlib
import sys

manifests = list(pathlib.Path(sys.argv[1]).glob("cas/*/sugar/sugar.sugarbin.json"))
assert len(manifests) == 1, manifests
data = json.loads(manifests[0].read_text(encoding="utf-8"))
data["sourceStamp"] = "blake3-512_" + "b" * 128
manifests[0].write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
clear_materialization
set +e
resolve_without_build >"$tmp/wrong-source.out" 2>"$tmp/wrong-source.err"
wrong_source_status=$?
set -e
[[ "$wrong_source_status" != 0 ]] || {
  echo 'wrong-source shelf manifest was accepted' >&2
  exit 1
}
grep -Fq 'crime=shelf-manifest-identity-mismatch' "$tmp/wrong-source.err"
grep -Fq 'field=sourceStamp' "$tmp/wrong-source.err"

# Lying twin 2: bytes under h' != h(payload) remain a CAS-address refusal.
clone_shelf "$tmp/wrong-payload-shelf"
export SUGAR_BINARY_SHELF_ROOT="$tmp/wrong-payload-shelf"
wrong_payload_cell="$(find "$SUGAR_BINARY_SHELF_ROOT/cas" -type f -name sugar.gz -print -quit)"
printf '#!/usr/bin/env bash\nprintf "wrong-payload\\n"\n' | gzip -9 >"$wrong_payload_cell"
clear_materialization
set +e
resolve_without_build >"$tmp/wrong-payload.out" 2>"$tmp/wrong-payload.err"
wrong_payload_status=$?
set -e
[[ "$wrong_payload_status" != 0 ]] || {
  echo 'payload under the wrong CAS address was accepted' >&2
  exit 1
}
grep -Fq 'crime=cas-address-payload-mismatch' "$tmp/wrong-payload.err"

# Recovery authority arm: the transport says this shelf is read-only. A stable
# manifest refusal must not attempt eviction or misreport ownership.
clone_shelf "$tmp/read-only-shelf"
export SUGAR_BINARY_SHELF_ROOT="$tmp/read-only-shelf"
read_only_cell="$(find "$SUGAR_BINARY_SHELF_ROOT/cas" -type f -name sugar.sugarbin.json -print -quit)"
python3 - "$read_only_cell" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data["sourceStamp"] = "blake3-512_" + "c" * 128
path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
read_only_cell_dir="$(dirname "$read_only_cell")"
clear_materialization
set +e
SUGAR_BINARY_SHELF_READ_ONLY=1 resolve_without_build \
  >"$tmp/read-only.out" 2>"$tmp/read-only.err"
read_only_status=$?
set -e
[[ "$read_only_status" != 0 ]] || {
  echo 'read-only shelf mismatch was accepted' >&2
  exit 1
}
grep -Fq 'crime=read-only-shelf-recovery' "$tmp/read-only.err"
[[ -d "$read_only_cell_dir" ]] || {
  echo 'declared read-only shelf cell was evicted' >&2
  exit 1
}

echo 'PASS: filesystem CAS authenticates stable identity, payload, and recovery authority'
