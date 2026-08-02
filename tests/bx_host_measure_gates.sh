#!/usr/bin/env bash
# Focused tests for tools/bx_host_measure_gates.sh — no corpus, no network.
# macOS often lacks util-linux flock; provide a stub that always acquires.
set -euo pipefail

repo_root="${1:-$(git rev-parse --show-toplevel)}"
gate="$repo_root/tools/bx_host_measure_gates.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
chmod +x "$gate"

fail() { echo "FAIL: $*" >&2; exit 1; }

fake_bin="$tmp/bin"
mkdir -p "$fake_bin"
cat >"$fake_bin/flock" <<'SH'
#!/usr/bin/env bash
# Stub: consume flock flags + optional FD; always succeed (no real lock).
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|-x|-n|-u) shift ;;
    -w) shift; [[ $# -gt 0 ]] && shift ;;
    -w*) shift ;;
    [0-9]*) shift; break ;;
    *) break ;;
  esac
done
if [[ $# -gt 0 ]]; then exec "$@"; fi
exit 0
SH
chmod +x "$fake_bin/flock"
export PATH="$fake_bin:$PATH"

# 1) Exclusive success on a private lease path under tmp.
lease="$tmp/host-shared/.sugar-heavy-measurement.lease"
mkdir -p "$(dirname "$lease")"
export SUGAR_BX_TIMING_LEASE_PATH="$lease"
export SUGAR_BX_TIMING_LEASE_WAIT_S=5
export SUGAR_BX_MAX_LOADAVG=999
status=0
"$gate" --exclusive -- true >/dev/null 2>"$tmp/err1" || status=$?
[[ "$status" -eq 0 ]] || fail "exclusive true status=$status want 0 stderr=$(cat "$tmp/err1")"
grep -Fq 'phase=acquired' "$tmp/err1" || fail "missing acquired"
grep -Fq 'phase=before' "$tmp/err1" || fail "missing load before"
grep -Fq 'phase=after' "$tmp/err1" || fail "missing load after"
grep -Fq 'mode=exclusive' "$tmp/err1" || fail "missing exclusive mode"

# 2) Shared success
status=0
"$gate" --shared -- true >/dev/null 2>"$tmp/err2" || status=$?
[[ "$status" -eq 0 ]] || fail "shared true status=$status"
grep -Fq 'mode=shared' "$tmp/err2" || fail "missing shared mode"

# 3) Load refuse (exit 76)
status=0
SUGAR_BX_MAX_LOADAVG=0 "$gate" --exclusive -- true >/dev/null 2>"$tmp/err3" || status=$?
[[ "$status" -eq 76 ]] || fail "load refuse status=$status want 76"
grep -Fq 'host-not-quiet' "$tmp/err3" || fail "missing host-not-quiet"

# 4) Command failure propagates
status=0
"$gate" --exclusive -- bash -c 'exit 42' >/dev/null 2>"$tmp/err4" || status=$?
[[ "$status" -eq 42 ]] || fail "status prop status=$status want 42"

# 5) Shared then exclusive sequential on same path
status=0
"$gate" --shared -- true >/dev/null 2>/dev/null || status=$?
[[ "$status" -eq 0 ]] || fail "shared pre-exclusive failed"
status=0
"$gate" --exclusive -- true >/dev/null 2>"$tmp/err5" || status=$?
[[ "$status" -eq 0 ]] || fail "exclusive after shared status=$status"

# 6) Default path preference documents host bind-mount (script source).
grep -Fq '/home/runner/.cache/sugar/binaries/.sugar-heavy-measurement.lease' "$gate" \
  || fail "gate missing runner bind-mount path"
grep -Fq '/var/tmp' "$gate" || fail "gate should mention /var/tmp only as last resort"

# 7) Workflow wires shared wrap
wf="$repo_root/.github/workflows/control-effect-recensus.yml"
grep -Fq 'bx_host_measure_gates.sh --shared' "$wf" \
  || fail "workflow missing shared measure wrap"
grep -Fq 'SUGAR_BX_TIMING_LEASE_PATH: /home/runner/.cache/sugar/binaries/.sugar-heavy-measurement.lease' "$wf" \
  || fail "workflow missing host lease path env"

echo "PASS: bx_host_measure_gates"
