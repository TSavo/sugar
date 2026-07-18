#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"

case_expansions="$(
  rg -n --pcre2 '\$\{[^}\n]*(?:,,|\^\^|(?<!\^)\^(?!\^))[^}\n]*\}' \
    "$repo_root/bin" "$repo_root/lib" 2>/dev/null || true
)"
if [[ -n "$case_expansions" ]]; then
  echo "bash-4 case expansion remains in build wrappers:" >&2
  echo "$case_expansions" >&2
  exit 1
fi

local_host="$(hostname 2>/dev/null || true)"
upper_host="$(printf '%s' "$local_host" | tr '[:lower:]' '[:upper:]')"

BCARGO_REMOTE_HOST="$upper_host" BCARGO_REAP_DAYS=0 /bin/bash -c '
  set -euo pipefail
  source "$1/bin/lib/sugar-bx.sh"
  sugar_bx_init "$1" "$1"
  [[ "$SUGAR_BX_LOCAL" == 1 ]]
' bash "$repo_root"

PATH="/bin:/usr/bin" /bin/bash "$repo_root/bin/brun" --help >/dev/null
PATH="/bin:/usr/bin" /bin/bash "$repo_root/bin/bpytest" --help >/dev/null

echo "PASS: macOS bash 3.2 build wrappers"
