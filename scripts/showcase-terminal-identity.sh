#!/usr/bin/env bash
# Additive producer transport for exact showcase terminal testimony.
#
# This file is sourced by showcase scripts.  The caller selects the command
# whose structured RPC refusal is the showcase terminal; this wrapper only
# preserves and publishes that raw testimony.  It never infers an identity
# from the command's exit status or from human-readable output.

_showcase_terminal_script="${BASH_SOURCE[0]}"
_showcase_terminal_repo_root="$(
  cd "$(dirname "${_showcase_terminal_script}")/.." && pwd -P
)"

showcase_terminal_identity() {
  python3 \
    "${_showcase_terminal_repo_root}/tools/showcase_terminal_identity.py" \
    "$@"
}

showcase_run_with_terminal() {
  if [[ "$#" -lt 2 ]]; then
    echo "showcase-terminal-identity: REFUSED: expected entrance and command" >&2
    return 2
  fi

  local entrance="$1"
  shift
  local diagnostic
  local command_status
  local had_errexit=0
  diagnostic="$(mktemp -t sugar-showcase-terminal.XXXXXX)" || return 2

  case "$-" in
    *e*) had_errexit=1 ;;
  esac
  set +e
  "$@" 2>"${diagnostic}"
  command_status=$?
  if [[ "${had_errexit}" -eq 1 ]]; then
    set -e
  fi

  cat "${diagnostic}" >&2
  if [[ "${command_status}" -ne 0 ]]; then
    showcase_terminal_identity \
      --rpc-diagnostic "${diagnostic}" \
      --repo-root "${_showcase_terminal_repo_root}" \
      --entrance "${entrance}" || {
        local identity_status=$?
        rm -f -- "${diagnostic}"
        return "${identity_status}"
      }
  fi

  rm -f -- "${diagnostic}"
  return "${command_status}"
}
