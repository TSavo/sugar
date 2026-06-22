#!/usr/bin/env bash

count_rs_files() {
  local root="$1"
  if command -v fd >/dev/null 2>&1; then
    fd -e rs . "$root" 2>/dev/null | wc -l | tr -d ' '
  elif command -v fdfind >/dev/null 2>&1; then
    fdfind -e rs . "$root" 2>/dev/null | wc -l | tr -d ' '
  else
    find "$root" -type f -name '*.rs' 2>/dev/null | wc -l | tr -d ' '
  fi
}
