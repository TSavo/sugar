#!/bin/sh
# SPDX-License-Identifier: MIT OR Apache-2.0

set -eu

makefile="${1:-Makefile}"

if [ ! -f "$makefile" ]; then
  echo "FAIL: $makefile does not exist" >&2
  exit 2
fi

offenders="$(
  awk '
    /^[[:space:]]*#/ { next }
    /@echo/ { next }
    /(^|[[:space:];(&|])cargo[[:space:]]+(build|test|check|run|tree|clean)([[:space:]\\]|$)/ {
      print FILENAME ":" FNR ":" $0
    }
  ' "$makefile"
)"

if [ -n "$offenders" ]; then
  echo "FAIL: Makefile must route Rust Cargo work through \$(CARGO) or \$(CARGO_LOCAL), not raw cargo:" >&2
  echo "$offenders" >&2
  exit 1
fi

echo "PASS: Makefile Cargo commands use the project cargo entrypoints"
