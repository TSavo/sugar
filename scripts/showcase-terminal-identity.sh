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
  local stdout_capture
  local stderr_capture
  local command_status
  local had_errexit=0
  stdout_capture="$(mktemp -t sugar-showcase-stdout.XXXXXX)" || return 2
  stderr_capture="$(mktemp -t sugar-showcase-stderr.XXXXXX)" || {
    rm -f -- "${stdout_capture}"
    return 2
  }
  diagnostic="$(mktemp -t sugar-showcase-terminal.XXXXXX)" || {
    rm -f -- "${stdout_capture}" "${stderr_capture}"
    return 2
  }

  case "$-" in
    *e*) had_errexit=1 ;;
  esac
  set +e
  "$@" >"${stdout_capture}" 2>"${stderr_capture}"
  command_status=$?
  if [[ "${had_errexit}" -eq 1 ]]; then
    set -e
  fi

  cat "${stdout_capture}"
  cat "${stderr_capture}" >&2
  if [[ "${command_status}" -ne 0 ]]; then
    {
      cat "${stdout_capture}"
      cat "${stderr_capture}"
    } >"${diagnostic}"
    showcase_terminal_identity \
      --rpc-diagnostic "${diagnostic}" \
      --repo-root "${_showcase_terminal_repo_root}" \
      --entrance "${entrance}" || true
  fi

  rm -f -- "${stdout_capture}" "${stderr_capture}" "${diagnostic}"
  return "${command_status}"
}
