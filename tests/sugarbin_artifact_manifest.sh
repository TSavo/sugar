#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_artifact_manifest.sh REPO_ROOT}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/target/release" "$tmp/cache"
: >"$tmp/cargo.log"
: >"$tmp/child.log"

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
if [[ "${1:-}" == -V || "${1:-}" == --version ]]; then echo 'cargo 1.96.0 (fake 2026-01-01)'; exit 0; fi
printf '%s\n' "$*" >>"$SUGARBIN_FAKE_CARGO_LOG"
binary=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == --bin ]]; then binary="$2"; shift 2; else shift; fi
done
cat >"$SUGAR_BINARY_TARGET_ROOT/release/$binary" <<EOF
#!/usr/bin/env bash
printf '%s\\n' '$binary' >>'$SUGARBIN_FAKE_CHILD_LOG'
EOF
chmod +x "$SUGAR_BINARY_TARGET_ROOT/release/$binary"
SH
chmod +x "$tmp/bin/rustc" "$tmp/bin/cargo"

export PATH="$tmp/bin:$PATH"
export SUGARBIN_FAKE_CARGO_LOG="$tmp/cargo.log"
export SUGARBIN_FAKE_CHILD_LOG="$tmp/child.log"
export SUGAR_BINARY_CARGO="$tmp/bin/cargo"
export SUGAR_BINARY_TARGET_ROOT="$tmp/target"
export SUGAR_BINARY_CACHE_DIR="$tmp/cache"
export SUGAR_BINARY_SOURCE_STAMP="blake3-512:$(printf '1%.0s' {1..128})"
export SUGAR_BINARY_NO_SHELF=1 SUGAR_BINARY_PUBLISH=0

# A stale sibling must not be blessed by building another executable.
printf '#!/usr/bin/env bash\nexit 99\n' >"$tmp/target/release/sugar-ir-smt-lib"
chmod +x "$tmp/target/release/sugar-ir-smt-lib"
"$repo/bin/sugarbin" --bin sugar >/dev/null
"$repo/bin/sugarbin" --bin sugar-ir-smt-lib >/dev/null
[[ "$(wc -l <"$tmp/cargo.log" | tr -d ' ')" == 2 ]] || {
  echo 'stale sibling was accepted under another executable identity' >&2; exit 1;
}
python3 - "$tmp/target/release/sugar.sugarbin.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f: data = json.load(f)
required = {"schema", "binary", "package", "sourceStamp", "buildIdentity", "platform",
            "targetTriple", "profile", "features", "rustc", "cargo", "sha256", "built", "executed"}
assert set(data) == required
assert data["binary"] == "sugar" and data["package"] == "sugar-cli"
assert data["buildIdentity"].startswith("blake3-512:")
assert data["built"] is True and data["executed"] is False
PY

# A valid manifest is a cache hit, but cache hits skip compilation only.
: >"$tmp/cargo.log"; : >"$tmp/child.log"
"$repo/bin/sugarbin" run --needs sugar -- "$tmp/target/release/sugar"
[[ ! -s "$tmp/cargo.log" ]] || { echo 'cache hit compiled' >&2; exit 1; }
[[ "$(wc -l <"$tmp/child.log" | tr -d ' ')" == 1 ]] || { echo 'cache hit skipped child command' >&2; exit 1; }

# Corruption is rejected loudly before execution and repaired by one build.
printf '\n# mutation\n' >>"$tmp/target/release/sugar"
: >"$tmp/cargo.log"; : >"$tmp/child.log"
"$repo/bin/sugarbin" run --needs sugar -- "$tmp/target/release/sugar" 2>"$tmp/corrupt.err"
grep -Fq 'artifact checksum mismatch' "$tmp/corrupt.err"
[[ "$(wc -l <"$tmp/cargo.log" | tr -d ' ')" == 1 ]] || { echo 'corruption did not rebuild exactly once' >&2; exit 1; }
[[ "$(wc -l <"$tmp/child.log" | tr -d ' ')" == 1 ]] || { echo 'corruption skipped or duplicated child' >&2; exit 1; }

# build resolves every requested executable without executing either.
: >"$tmp/child.log"
"$repo/bin/sugarbin" build --needs sugar,sugar-ir-smt-lib
[[ ! -s "$tmp/child.log" ]] || { echo 'build executed an artifact' >&2; exit 1; }

# The bx route performs resolution on bx and never pulls the Linux executable
# into the caller's target directory.
cat >"$tmp/bin/ssh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SUGARBIN_FAKE_SSH_LOG"
exit 0
SH
cat >"$tmp/bin/rsync" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SUGARBIN_FAKE_RSYNC_LOG"
exit 0
SH
chmod +x "$tmp/bin/ssh" "$tmp/bin/rsync"
: >"$tmp/ssh.log"; : >"$tmp/rsync.log"
(cd "$repo/implementations/rust" &&
  SUGARBIN_FAKE_SSH_LOG="$tmp/ssh.log" SUGARBIN_FAKE_RSYNC_LOG="$tmp/rsync.log" \
  BCARGO_SSH="$tmp/bin/ssh" BCARGO_RSYNC="$tmp/bin/rsync" \
  BCARGO_REMOTE_ROOT=/home/tsavo/remote/sugarbin-artifact-manifest-test \
  "$repo/bin/sugarbin" run --host bx --needs sugar -- true)
grep -Fq 'bin/sugarbin --platform' "$tmp/ssh.log"
grep -Fq -- '--bin "$b"' "$tmp/ssh.log"
! grep -Eq 'target/(release|debug)/sugar.*:' "$tmp/rsync.log"

echo 'PASS: sugarbin per-executable artifact manifests'
