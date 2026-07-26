#!/usr/bin/env bash
# The shared binary cache is one host directory reached under two names, and it
# is written by several identities: root under bpytest, uid 1001 inside a runner
# container, uid 1000 interactively over ssh. Its artifact cells earn that
# sharing -- content-addressed, written once, never rewritten. Its Cargo build
# tree does not: Cargo rewrites 644 files on every invocation, so whichever
# identity touches a build family first owns it forever and the next one dies
# inside Cargo on .cargo-build-lock with a bare EACCES.
#
# So the Cargo scratch tree is partitioned by identity while the artifact cells
# stay shared, and a build root this identity cannot use refuses BY NAME rather
# than surfacing as a Cargo traceback.
set -euo pipefail

repo="${1:?usage: sugarbin_build_root_identity.sh REPO_ROOT}"
tmp_root="${SUGARBIN_EXEC_TMPDIR:-$repo/.sugar/test-tmp}"
mkdir -p "$tmp_root"
tmp="$(mktemp -d "$tmp_root/sugarbin-build-root.XXXXXX")"
trap 'chmod -R u+rwX "$tmp" 2>/dev/null || true; rm -rf "$tmp"' EXIT
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
printf '%s\n' "$target" >>"$SUGARBIN_FAKE_CARGO_LOG"
binary=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == --bin ]]; then binary="$2"; shift 2; else shift; fi
done
mkdir -p "$target/release"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "fresh:%s"\n' "$binary" >"$target/release/$binary"
chmod +x "$target/release/$binary"
SH
cat >"$tmp/bin/git" <<'SH'
#!/usr/bin/env bash
if [[ "$*" == *"rev-parse HEAD"* ]]; then
  printf '%s\n' "fake-head"
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
export SUGAR_BINARY_SOURCE_STAMP="blake3-512_$(printf '7%.0s' {1..128})"
export SUGAR_BINARY_NO_SHELF=1 SUGAR_BINARY_PUBLISH=0

uid="$(id -u)"

# --- The Cargo scratch tree is partitioned by identity ------------------------
# Two identities on one host share the cache and must not share the target dir.
"$repo/bin/sugarbin" --bin sugar >/dev/null
target_used="$(head -n 1 "$tmp/cargo.log")"
[[ "$target_used" == "$tmp/cache/.build/uid-$uid/"* ]] || {
  echo "build root is not partitioned by identity: $target_used" >&2
  echo "expected a prefix of $tmp/cache/.build/uid-$uid/" >&2
  exit 1
}

# --- The artifact cells stay shared ------------------------------------------
# Partitioning scratch must not partition the cache itself. Nothing outside
# .build may acquire a per-identity segment, or the shared cache is defeated.
while IFS= read -r entry; do
  [[ "$entry" == "$tmp/cache/.build" ]] && continue
  case "$(basename "$entry")" in
    uid-*)
      echo "artifact cell was partitioned by identity, defeating the shared cache: $entry" >&2
      exit 1
      ;;
  esac
done < <(find "$tmp/cache" -maxdepth 1 -mindepth 1)

# --- An unusable build root refuses by name ----------------------------------
# Not a Cargo EACCES traceback, and never a silent fallback to a private cache.
rm -f "$tmp/target/release/sugar" "$tmp/target/release/sugar.sugarbin.json"
cargo_calls_before="$(wc -l <"$tmp/cargo.log" | tr -d ' ')"
blocked_cache="$tmp/blocked-cache"
mkdir -p "$blocked_cache/.build"
# The per-identity build root cannot be created: its own path is a regular
# file. This is uid-agnostic -- ENOTDIR refuses root exactly as it refuses
# anyone else -- so this law is executed under every caller, including the
# root identity bpytest runs as.
: >"$blocked_cache/.build/uid-$uid"
set +e
refusal="$(SUGAR_BINARY_CACHE_DIR="$blocked_cache" "$repo/bin/sugarbin" --bin sugar 2>&1 >/dev/null)"
status=$?
set -e
[[ $status -ne 0 ]] || { echo 'an uncreatable build root did not refuse' >&2; exit 1; }
grep -Fq 'crime=uncreatable-build-root' <<<"$refusal" || {
  echo 'refusal was not named; the caller sees an anonymous failure' >&2
  printf '%s\n' "$refusal" >&2
  exit 1
}
grep -Fq "$blocked_cache/.build/uid-$uid" <<<"$refusal" || {
  echo 'refusal did not name the unusable path' >&2; printf '%s\n' "$refusal" >&2; exit 1;
}
grep -Fq 'do NOT repoint SUGAR_BINARY_CACHE_DIR' <<<"$refusal" || {
  echo 'refusal failed to rule out the workaround that abandons the shared cache' >&2
  printf '%s\n' "$refusal" >&2
  exit 1
}
[[ "$(wc -l <"$tmp/cargo.log" | tr -d ' ')" == "$cargo_calls_before" ]] || {
  echo 'sugarbin invoked Cargo against an unusable build root instead of refusing first' >&2
  exit 1
}

echo 'PASS: Cargo scratch is partitioned by identity, artifact cells stay shared, unusable build roots refuse by name'
