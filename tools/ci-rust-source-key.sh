#!/usr/bin/env bash
# Content-address the Rust workspace (and build drivers) for CI cache keys.
# Key material is only local filesystem content — never github.sha / ref / run id.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$root"

toolchain="1.96.0"
hash_list="$(mktemp)"
trap 'rm -f "$hash_list"' EXIT

{
  printf 'toolchain:%s\n' "$toolchain"

  (
    cd implementations/rust
    find . \
      \( -path './target' -o -path '*/target/*' \) -prune -o \
      -type f \( \
        -name '*.rs' -o \
        -name 'Cargo.toml' -o \
        -name 'Cargo.lock' -o \
        -name 'build.rs' -o \
        -name '*.toml' \
      \) -print
  ) | LC_ALL=C sort | while IFS= read -r rel; do
    # rel is like ./sugar-cli/src/main.rs
    path="implementations/rust/${rel#./}"
    printf '%s  ' "$path"
    # portable content hash of file bytes
    sha256sum -- "$path" | awk '{print $1}'
  done

  for extra in \
    bin/sugarbin \
    bin/lib/sugar-exec.sh \
    .github/actions/setup-rust-cache/action.yml \
    tools/ci-rust-source-key.sh
  do
    if [[ -f "$extra" ]]; then
      printf '%s  ' "$extra"
      sha256sum -- "$extra" | awk '{print $1}'
    fi
  done
} >"$hash_list"

key="$(sha256sum "$hash_list" | awk '{print $1}')"
echo "Rust source cache key: ${key}" >&2
echo "manifest_lines: $(wc -l <"$hash_list")" >&2

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "key=${key}" >>"$GITHUB_OUTPUT"
fi
# Always print for non-GHA use
echo "key=${key}"
