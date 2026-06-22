#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=examples/rust-coretests-report/run-lib.sh
source "$HERE/run-lib.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/a" "$tmp/b"
touch "$tmp/a/one.rs" "$tmp/b/two.rs" "$tmp/b/not-rust.txt"

count="$(PATH=/usr/bin:/bin count_rs_files "$tmp")"
if [[ "$count" != "2" ]]; then
  echo "expected fd-less fallback to count 2 Rust files, got $count" >&2
  exit 1
fi
