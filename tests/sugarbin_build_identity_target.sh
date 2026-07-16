#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_build_identity_target.sh REPO_ROOT}"
tmp_root="${SUGARBIN_EXEC_TMPDIR:-$repo/.sugar/test-tmp}"
mkdir -p "$tmp_root"
tmp="$(mktemp -d "$tmp_root/sugarbin-build-identity.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/target/release" "$tmp/cache"
: >"$tmp/cargo.log"

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
  cat <<'EOF'
cargo 1.96.0 (fake 2026-01-01)
release: 1.96.0
commit-hash: fake
commit-date: 2026-01-01
host: x86_64-unknown-linux-gnu
libgit2: 1.9.0
libcurl: 8.12.0
ssl: OpenSSL 3.5.0
os: Linux 6.1.0 [64-bit]
EOF
  exit 0
fi
target="${CARGO_TARGET_DIR:?sugarbin must isolate Cargo output by build identity}"
printf '%s|%s\n' "$target" "$*" >>"$SUGARBIN_FAKE_CARGO_LOG"
binary=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == --bin ]]; then binary="$2"; shift 2; else shift; fi
done
mkdir -p "$target/release"
cat >"$target/release/$binary" <<EOF
#!/usr/bin/env bash
printf '%s\\n' 'fresh:$binary'
EOF
chmod +x "$target/release/$binary"
SH
cat >"$tmp/bin/git" <<'SH'
#!/usr/bin/env bash
if [[ "$*" == *"rev-parse HEAD"* ]]; then
  printf '%s\n' "${SUGARBIN_FAKE_GIT_HEAD:?}"
  exit 0
fi
exec /usr/bin/git "$@"
SH
chmod +x "$tmp/bin/rustc" "$tmp/bin/cargo" "$tmp/bin/git"

export PATH="$tmp/bin:$PATH"
export SUGARBIN_FAKE_CARGO_LOG="$tmp/cargo.log"
export SUGAR_BINARY_CARGO="$tmp/bin/cargo"
export SUGAR_BINARY_TARGET_ROOT="$tmp/target"
export SUGAR_BINARY_CACHE_DIR="$tmp/cache"
export SUGAR_BINARY_SOURCE_STAMP="blake3-512:$(printf '7%.0s' {1..128})"
export SUGAR_BINARY_NO_SHELF=1 SUGAR_BINARY_PUBLISH=0
export SUGARBIN_FAKE_GIT_HEAD="head-before-unrelated-change"

# This is the exact persistent-runner hazard: a stale shared executable is
# newer than the checked-out source and Cargo could otherwise call it fresh.
printf '#!/usr/bin/env bash\nprintf "stale\\n"\n' >"$tmp/target/release/sugar"
chmod +x "$tmp/target/release/sugar"

touch -d '2030-01-01' "$tmp/target/release/sugar" 2>/dev/null || true
resolved="$("$repo/bin/sugarbin" --bin sugar)"
[[ "$resolved" == "$tmp/target/release/sugar" ]]
[[ "$($resolved)" == "fresh:sugar" ]] || {
  echo 'stale shared target was wrapped in a fresh manifest' >&2; exit 1;
}
[[ "$(wc -l <"$tmp/cargo.log" | tr -d ' ')" == 1 ]]
! grep -Fq "$tmp/target|" "$tmp/cargo.log" || {
  echo 'Cargo reused the shared published target instead of an identity cell' >&2; exit 1;
}
grep -Fq "$tmp/cache/.build/" "$tmp/cargo.log"

# Repository HEAD is not a build input. With the BLAKE3 source closure fixed,
# an unrelated commit must reuse the exact artifact without invoking Cargo.
export SUGARBIN_FAKE_GIT_HEAD="head-after-unrelated-change"
resolved_again="$("$repo/bin/sugarbin" --bin sugar)"
[[ "$resolved_again" == "$resolved" ]]
[[ "$(wc -l <"$tmp/cargo.log" | tr -d ' ')" == 1 ]]

echo 'PASS: sugarbin Cargo output is isolated by build identity'
