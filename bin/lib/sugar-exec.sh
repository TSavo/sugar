#!/usr/bin/env bash

sugar_exec_platform_key() {
  local os arch
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m | tr '[:upper:]' '[:lower:]')"
  case "$arch" in amd64|x64) arch=x86_64 ;; aarch64) arch=arm64 ;; esac
  printf '%s-%s\n' "$os" "$arch"
}

sugar_exec_validate_route() {
  local host="$1" env="$2" requested="$3" observed="$4"
  [[ "$host" == local && "$env" == ambient ]] || {
    printf 'sugarbin: unsupported execution route: host=%s env=%s\n' "$host" "$env" >&2
    return 2
  }
  [[ -z "$requested" || "$requested" == "$observed" ]] || {
    printf 'sugarbin: unsupported execution route: host=%s env=%s platform=%s available=%s\n' \
      "$host" "$env" "$requested" "$observed" >&2
    return 2
  }
}

sugar_exec_local_run() {
  "$@"
}
