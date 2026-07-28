#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "6309" ]]; then
  echo "usage: $0 6309 [deadline-seconds] --only relative/path.py" >&2
  exit 2
fi
deadline="${2:-180}"
shift 2
if [[ "${1:-}" != "--only" || -z "${2:-}" ]]; then
  echo "usage: $0 6309 [deadline-seconds] --only relative/path.py" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${script_dir}/desugar_repro.py" \
  --file "${2}" \
  --deadline "${deadline}"
