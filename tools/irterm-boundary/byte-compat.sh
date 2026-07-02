#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# IrTerm boundary-collapse byte-compat harness (#3191).
#
# Compare baseline and changed `sugar` binaries on a fixed project fixture.
# The harness writes both JSON outputs, cmp checks them byte-for-byte, records
# SHA-256 + size evidence, and reports R(byte-drift). Later campaign slices
# should invoke this script instead of hand-rolling one-off cmp commands.

set -euo pipefail

usage() {
  cat <<'USAGE'
usage:
  tools/irterm-boundary/byte-compat.sh \
    --project-root <fixture> \
    --baseline-sugar <path> \
    --changed-sugar <path> \
    --out-dir <dir> \
    [--label <name>]

  tools/irterm-boundary/byte-compat.sh --self-test

Default cases:
  verify-json: sugar verify --project <fixture> --json
  prove-json:  sugar prove <fixture> --json

The script exits nonzero if any compared JSON output drifts.
USAGE
}

die() {
  echo "irterm-byte-compat: $*" >&2
  exit 2
}

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    die "need shasum or sha256sum"
  fi
}

file_size() {
  if stat -f %z "$1" >/dev/null 2>&1; then
    stat -f %z "$1"
  else
    stat -c %s "$1"
  fi
}

run_case() {
  local name=$1 sugar=$2 project_root=$3 output=$4
  case "$name" in
    verify-json)
      "$sugar" verify --project "$project_root" --json > "$output"
      ;;
    prove-json)
      "$sugar" prove "$project_root" --json > "$output"
      ;;
    *)
      die "unknown byte-compat case: $name"
      ;;
  esac
}

write_report_row() {
  local name=$1 before=$2 after=$3 drift=$4 report=$5
  local before_sha after_sha before_size after_size
  before_sha="$(sha256_file "$before")"
  after_sha="$(sha256_file "$after")"
  before_size="$(file_size "$before")"
  after_size="$(file_size "$after")"
  cat >> "$report" <<ROW
case=$name drift=$drift baseline_size=$before_size changed_size=$after_size baseline_sha256=$before_sha changed_sha256=$after_sha
ROW
}

run_harness() {
  local project_root=$1 baseline_sugar=$2 changed_sugar=$3 out_dir=$4 label=$5
  [ -d "$project_root" ] || die "project root not found: $project_root"
  [ -x "$baseline_sugar" ] || die "baseline sugar is not executable: $baseline_sugar"
  [ -x "$changed_sugar" ] || die "changed sugar is not executable: $changed_sugar"
  mkdir -p "$out_dir"

  local report="$out_dir/${label}.byte-compat.txt"
  : > "$report"
  local drift=0
  for case_name in verify-json prove-json; do
    local before="$out_dir/${label}.${case_name}.baseline.json"
    local after="$out_dir/${label}.${case_name}.changed.json"
    run_case "$case_name" "$baseline_sugar" "$project_root" "$before"
    run_case "$case_name" "$changed_sugar" "$project_root" "$after"
    if cmp -s "$before" "$after"; then
      write_report_row "$case_name" "$before" "$after" 0 "$report"
    else
      drift=$((drift + 1))
      write_report_row "$case_name" "$before" "$after" 1 "$report"
      echo "irterm-byte-compat: drift in $case_name" >&2
    fi
  done

  cat "$report"
  echo "R(byte-drift) = $drift"
  [ "$drift" -eq 0 ]
}

self_test() {
  local tmp baseline changed project out
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/irterm-byte-compat.XXXXXX")"
  trap 'rm -rf "$tmp"' RETURN
  project="$tmp/project"
  out="$tmp/out"
  mkdir -p "$project"
  baseline="$tmp/sugar-baseline"
  changed="$tmp/sugar-changed"
  cat > "$baseline" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  verify) printf '{"case":"verify","ok":true}\n' ;;
  prove) printf '{"case":"prove","ok":true}\n' ;;
  *) exit 2 ;;
esac
SH
  cp "$baseline" "$changed"
  chmod +x "$baseline" "$changed"
  run_harness "$project" "$baseline" "$changed" "$out" self-test >/dev/null

  cat > "$changed" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  verify) printf '{"case":"verify","ok":false}\n' ;;
  prove) printf '{"case":"prove","ok":true}\n' ;;
  *) exit 2 ;;
esac
SH
  chmod +x "$changed"
  if run_harness "$project" "$baseline" "$changed" "$out" self-test-drift >/dev/null 2>&1; then
    die "self-test expected drift to fail"
  fi
  echo "irterm-byte-compat self-test ok"
}

project_root=""
baseline_sugar=""
changed_sugar=""
out_dir=""
label="irterm-boundary"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --self-test)
      self_test
      exit 0
      ;;
    --project-root)
      [ "$#" -ge 2 ] || die "--project-root requires a value"
      project_root=$2
      shift 2
      ;;
    --baseline-sugar)
      [ "$#" -ge 2 ] || die "--baseline-sugar requires a value"
      baseline_sugar=$2
      shift 2
      ;;
    --changed-sugar)
      [ "$#" -ge 2 ] || die "--changed-sugar requires a value"
      changed_sugar=$2
      shift 2
      ;;
    --out-dir)
      [ "$#" -ge 2 ] || die "--out-dir requires a value"
      out_dir=$2
      shift 2
      ;;
    --label)
      [ "$#" -ge 2 ] || die "--label requires a value"
      label=$2
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[ -n "$project_root" ] || die "--project-root is required"
[ -n "$baseline_sugar" ] || die "--baseline-sugar is required"
[ -n "$changed_sugar" ] || die "--changed-sugar is required"
[ -n "$out_dir" ] || die "--out-dir is required"

run_harness "$project_root" "$baseline_sugar" "$changed_sugar" "$out_dir" "$label"
