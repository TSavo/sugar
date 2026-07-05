#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
#
# Measure peak RSS for `sugar verify` with the host `/usr/bin/time` format.
# Darwin reports bytes via `time -l`; Linux reports KiB via `time -v`.

set -euo pipefail

usage() {
  cat <<'USAGE'
usage:
  tools/perf/verify-rss.sh --project-root <fixture> [--sugar <path>] [--reference-kib <kib>] [--json-out <path>] [--label <name>] [-- <sugar verify args>...]
  tools/perf/verify-rss.sh --self-test

The optional --reference-kib is a baseline, not a threshold. The harness fails
when measured peak RSS exceeds reference_kib by more than 10%.
USAGE
}

die() {
  echo "verify-rss: $*" >&2
  exit 2
}

ceil_div() {
  local n=$1 d=$2
  echo $(((n + d - 1) / d))
}

parse_time_output() {
  awk '
    /Maximum resident set size \(kbytes\):/ {
      for (i = NF; i >= 1; i--) {
        if ($i ~ /^[0-9]+$/) {
          print "linux", $i * 1024, $i;
          found = 1;
          exit 0;
        }
      }
    }
    /maximum resident set size/ {
      for (i = 1; i <= NF; i++) {
        if ($i ~ /^[0-9]+$/) {
          bytes = $i;
          kib = int((bytes + 1023) / 1024);
          print "macos", bytes, kib;
          found = 1;
          exit 0;
        }
      }
    }
    END {
      if (!found) {
        exit 1;
      }
    }
  '
}

floor_status() {
  local measured_kib=$1 reference_kib=$2
  local budget_kib
  budget_kib="$(ceil_div "$((reference_kib * 110))" 100)"
  if [ "$measured_kib" -gt "$budget_kib" ]; then
    echo "regression-detected"
  else
    echo "within-floor"
  fi
}

self_test() {
  local mac parsed platform bytes kib status
  mac="$(printf '   123456  maximum resident set size\n' | parse_time_output)"
  read -r platform bytes kib <<<"$mac"
  [ "$platform" = "macos" ] || die "self-test expected macos parser, got $platform"
  [ "$bytes" = "123456" ] || die "self-test expected macOS bytes=123456, got $bytes"
  [ "$kib" = "121" ] || die "self-test expected macOS kib=121, got $kib"

  parsed="$(printf 'Maximum resident set size (kbytes): 345678\n' | parse_time_output)"
  read -r platform bytes kib <<<"$parsed"
  [ "$platform" = "linux" ] || die "self-test expected linux parser, got $platform"
  [ "$bytes" = "353974272" ] || die "self-test expected Linux bytes=353974272, got $bytes"
  [ "$kib" = "345678" ] || die "self-test expected Linux kib=345678, got $kib"

  status="$(floor_status 112 100)"
  [ "$status" = "regression-detected" ] || die "self-test expected floor regression, got $status"

  echo "perf-rss self-test ok: macos_kib=121 linux_kib=345678 floor_status=regression-detected"
}

project_root=""
sugar_bin="${SUGAR_BIN:-}"
reference_kib="${SUGAR_VERIFY_RSS_REFERENCE_KIB:-}"
json_out=""
label="sugar-verify"
verify_args=()

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
    --sugar)
      [ "$#" -ge 2 ] || die "--sugar requires a value"
      sugar_bin=$2
      shift 2
      ;;
    --reference-kib)
      [ "$#" -ge 2 ] || die "--reference-kib requires a value"
      reference_kib=$2
      shift 2
      ;;
    --json-out)
      [ "$#" -ge 2 ] || die "--json-out requires a value"
      json_out=$2
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
    --)
      shift
      verify_args=("$@")
      break
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[ -n "$project_root" ] || die "--project-root is required"
[ -d "$project_root" ] || die "project root not found: $project_root"
if [ -z "$sugar_bin" ]; then
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  sugar_bin="$("$repo_root/bin/sugarbin" --profile release)"
fi
if [ -n "$reference_kib" ] && ! [[ "$reference_kib" =~ ^[0-9]+$ ]]; then
  die "--reference-kib must be an integer KiB value"
fi

time_log="$(mktemp "${TMPDIR:-/tmp}/sugar-verify-rss.XXXXXX")"
cleanup() {
  rm -f "$time_log"
}
trap cleanup EXIT

platform="$(uname -s)"
case "$platform" in
  Darwin)
    time_args=(-l)
    ;;
  Linux)
    time_args=(-v)
    ;;
  *)
    die "unsupported platform for /usr/bin/time RSS parsing: $platform"
    ;;
esac

set +e
/usr/bin/time "${time_args[@]}" "$sugar_bin" verify --project "$project_root" "${verify_args[@]}" \
  2> >(tee "$time_log" >&2)
verify_status=$?
set -e

if [ "$verify_status" -ne 0 ]; then
  die "sugar verify exited with status $verify_status"
fi

parsed="$(parse_time_output < "$time_log")" || die "could not parse max RSS from /usr/bin/time output"
read -r parsed_platform rss_bytes rss_kib <<<"$parsed"

budget_kib=""
status="not-armed"
if [ -n "$reference_kib" ]; then
  budget_kib="$(ceil_div "$((reference_kib * 110))" 100)"
  status="$(floor_status "$rss_kib" "$reference_kib")"
fi

cat <<REPORT
verify-rss label=$label platform=$platform parser=$parsed_platform rss_bytes=$rss_bytes rss_kib=$rss_kib reference_kib=${reference_kib:-null} budget_kib=${budget_kib:-null} floor_status=$status
REPORT

if [ -n "$json_out" ]; then
  cat > "$json_out" <<JSON
{
  "label": "$label",
  "platform": "$platform",
  "parser": "$parsed_platform",
  "rss_bytes": $rss_bytes,
  "rss_kib": $rss_kib,
  "reference_kib": ${reference_kib:-null},
  "budget_kib": ${budget_kib:-null},
  "floor_status": "$status"
}
JSON
fi

if [ "$status" = "regression-detected" ]; then
  echo "verify-rss: peak RSS ${rss_kib} KiB exceeds 10% budget ${budget_kib} KiB from reference ${reference_kib} KiB" >&2
  exit 1
fi
