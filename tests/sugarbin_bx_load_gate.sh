#!/usr/bin/env bash
# Quiet gate + exclusive timing lease.
# - SUGAR_BX_REQUIRE_QUIET / SUGAR_BX_MAX_LOADAVG arm the gate.
# - Under the gate: remote exclusive flock, load sample under lock, refuse 76 if
#   load high, refuse 77 if lease busy (wait_s=0).
# - Ungated ordinary brun builds unchanged.
set -euo pipefail

repo_root="${1:-$(git rev-parse --show-toplevel)}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fake_bin="$tmp/bin"
mkdir -p "$fake_bin"
ssh_log="$tmp/ssh.log"
rsync_log="$tmp/rsync.log"
remote_exec_log="$tmp/remote-exec.log"

# Fake ssh:
# - pure load-sample probes (getloadavg / /proc/loadavg WITHOUT flock) print BX_FAKE_LOAD
# - quiet wrapper contains flock + load + measured command
# - ungated ambient is bash -lc '… exec …'
cat >"$fake_bin/ssh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$BX_FAKE_SSH_LOG"
joined="$*"

# Quiet-gated measurement wrapper (exclusive lease + load under lock).
if [[ "$joined" == *'flock'* && "$joined" == *'bx-load-gate'* ]]; then
  printf '%s\n' "$joined" >>"$BX_FAKE_REMOTE_EXEC_LOG"
  if [[ "${BX_FAKE_LEASE_BUSY:-0}" == 1 ]]; then
    echo "sugarbin: crime=timing-lease-busy host=battleaxe path=/var/tmp/sugar-bx-timing-measurement.lease" >&2
    exit 77
  fi
  # Load comes from BX_FAKE_LOAD (simulates remote /proc/loadavg). Ceiling:
  # BX_FAKE_MAX if set (explicit SUGAR_BX_MAX_LOADAVG tests), else nproc/4 floor 2
  # — mirrors the remote wrapper. Do not parse MAX_LIT from the double-quoted
  # ssh argv (nested sugar_bx_quote makes sed match escapes, not values).
  load="${BX_FAKE_LOAD:-0.50 32}"
  load1="${load%% *}"
  nproc="${load##* }"
  if [[ -n "${BX_FAKE_MAX:-}" ]]; then
    max="$BX_FAKE_MAX"
  else
    max="$(awk -v n="$nproc" 'BEGIN{ m=n/4.0; if (m < 2.0) m=2.0; printf "%.2f", m }')"
  fi
  echo "sugarbin: bx-timing-lease phase=acquired host=battleaxe path=/var/tmp/sugar-bx-timing-measurement.lease" >&2
  echo "sugarbin: bx-load-gate phase=before host=battleaxe load1=$load1 nproc=$nproc max=$max lease=held" >&2
  if awk -v l="$load1" -v m="$max" 'BEGIN{ exit !(l+0 > m+0) }'; then
    echo "sugarbin: crime=host-not-quiet host=battleaxe load1=$load1 nproc=$nproc max=$max lease=held" >&2
    exit 76
  fi
  echo "sugarbin: bx-load-gate phase=after host=battleaxe load1_before=$load1 load1_after=$load1 nproc=$nproc lease=held" >&2
  echo "sugarbin: bx-timing-lease phase=release host=battleaxe status=0" >&2
  exit "${BX_FAKE_REMOTE_STATUS:-0}"
fi

# Bare load sample (should not be the authoritative quiet path anymore, but
# keep for any residual probes).
case "$joined" in
  *'/proc/loadavg'*|*'getloadavg'*)
    if [[ "$joined" != *'flock'* ]]; then
      printf '%s\n' "${BX_FAKE_LOAD:-0.50 32}"
      exit 0
    fi
    ;;
esac

# Ungated ambient: bash -lc 'cd … && exec …' (not find -exec).
if [[ "$joined" == *'bash -lc'* && "$joined" == *' exec '* && "$joined" != *'flock'* ]]; then
  printf '%s\n' "$joined" >>"$BX_FAKE_REMOTE_EXEC_LOG"
  exit "${BX_FAKE_REMOTE_STATUS:-0}"
fi
exit 0
SH
cat >"$fake_bin/rsync" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$BX_FAKE_RSYNC_LOG"
exit 0
SH
chmod +x "$fake_bin/ssh" "$fake_bin/rsync"

fail() { echo "FAIL: $*" >&2; exit 1; }

run_bx() {
  # Load/lease unit tests skip the corpus pin (no pandas on the fake remote).
  (cd "$repo_root" &&
    PATH="$fake_bin:$PATH" BCARGO_SSH="$fake_bin/ssh" BCARGO_RSYNC="$fake_bin/rsync" \
    BX_FAKE_SSH_LOG="$ssh_log" BX_FAKE_RSYNC_LOG="$rsync_log" \
    BX_FAKE_REMOTE_EXEC_LOG="$remote_exec_log" \
    BX_FAKE_LOAD="${BX_FAKE_LOAD-}" \
    BX_FAKE_MAX="${BX_FAKE_MAX-}" \
    BX_FAKE_LEASE_BUSY="${BX_FAKE_LEASE_BUSY-}" \
    BX_FAKE_REMOTE_STATUS="${BX_FAKE_REMOTE_STATUS-}" \
    BCARGO_REMOTE_ROOT="${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-load-gate-test}" \
    BCARGO_FORCE_REMOTE=1 \
    SUGAR_BX_SKIP_CORPUS_PIN="${SUGAR_BX_SKIP_CORPUS_PIN:-1}" \
    "$repo_root/bin/sugarbin" run --host bx --env ambient "$@")
}

# 1) Gate off by default: busy load must NOT refuse, and command must run.
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="20.0 32"
export BX_FAKE_LEASE_BUSY=0
status=0
run_bx -- true >/dev/null 2>"$tmp/stderr1" || status=$?
[[ "$status" -eq 0 ]] || fail "ungated run failed status=$status (want 0)"
[[ -s "$remote_exec_log" ]] || fail "ungated run never reached remote exec"
grep -q 'bx-load-gate' "$tmp/stderr1" && fail "ungated run printed load gate noise" || true
grep -q 'flock' "$remote_exec_log" && fail "ungated run took timing lease" || true

# 2) REQUIRE_QUIET=1 + busy load → exit 76, quiet wrapper ran (lease path).
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="20.0 32"
status=0
SUGAR_BX_REQUIRE_QUIET=1 run_bx -- true >/dev/null 2>"$tmp/stderr2" || status=$?
[[ "$status" -eq 76 ]] || fail "busy host status=$status want 76"
[[ -s "$remote_exec_log" ]] || fail "busy host never entered quiet wrapper"
grep -Fq 'crime=host-not-quiet' "$tmp/stderr2" || fail "missing host-not-quiet crime line"
grep -Fq 'phase=before' "$tmp/stderr2" || fail "missing before load line"
grep -Fq 'lease=held' "$tmp/stderr2" || fail "load check not under lease"

# 3) REQUIRE_QUIET=1 + quiet load → runs, prints before+after under lease.
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="2.05 32"
status=0
SUGAR_BX_REQUIRE_QUIET=1 run_bx -- true >/dev/null 2>"$tmp/stderr3" || status=$?
[[ "$status" -eq 0 ]] || fail "quiet host status=$status want 0"
[[ -s "$remote_exec_log" ]] || fail "quiet host never reached remote exec"
grep -Fq 'phase=before' "$tmp/stderr3" || fail "quiet run missing before"
grep -Fq 'phase=after' "$tmp/stderr3" || fail "quiet run missing after"
grep -Fq 'bx-timing-lease phase=acquired' "$tmp/stderr3" || fail "quiet run missing lease acquire"
grep -Fq 'flock' "$remote_exec_log" || fail "quiet run missing flock in remote script"

# 4) Explicit MAX_LOADAVG alone arms the gate; load just under passes.
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="7.9 32"
export BX_FAKE_MAX=8
status=0
SUGAR_BX_MAX_LOADAVG=8 run_bx -- true >/dev/null 2>"$tmp/stderr4" || status=$?
[[ "$status" -eq 0 ]] || fail "max-load under ceiling status=$status want 0"
unset BX_FAKE_MAX

# 5) Explicit MAX_LOADAVG: load just over refuses.
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="8.01 32"
export BX_FAKE_MAX=8
status=0
SUGAR_BX_MAX_LOADAVG=8 run_bx -- true >/dev/null 2>"$tmp/stderr5" || status=$?
[[ "$status" -eq 76 ]] || fail "max-load over ceiling status=$status want 76"
unset BX_FAKE_MAX

# 6) Concurrent hole closed: lease busy → exit 77 (wait_s=0 refuse path).
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="2.05 32"
export BX_FAKE_LEASE_BUSY=1
status=0
SUGAR_BX_REQUIRE_QUIET=1 SUGAR_BX_TIMING_LEASE_WAIT_S=0 \
  run_bx -- true >/dev/null 2>"$tmp/stderr6" || status=$?
[[ "$status" -eq 77 ]] || fail "lease busy status=$status want 77"
grep -Fq 'crime=timing-lease-busy' "$tmp/stderr6" || fail "missing timing-lease-busy crime"
export BX_FAKE_LEASE_BUSY=0

# 7) brun adapter surfaces quiet + lease + pin env.
grep -Fq 'SUGAR_BX_REQUIRE_QUIET' "$repo_root/bin/brun" || fail "brun --help text missing quiet gate"
grep -Fq '.sugar-heavy-measurement.lease' "$repo_root/bin/lib/sugar-bx.sh" || fail "sugar-bx missing shared timing lease path"
grep -Fq 'timing-lease-busy' "$repo_root/bin/lib/sugar-bx.sh" || fail "sugar-bx missing lease-busy crime"
grep -Fq 'bx_corpus_pin_gate' "$repo_root/bin/lib/sugar-bx.sh" || fail "sugar-bx missing corpus pin gate"
grep -Fq 'exit 78' "$repo_root/bin/lib/sugar-bx.sh" || fail "sugar-bx missing pin exit 78"
# Pin-before-cd always 78'd relative paths (only absolute /tmp worked). Tooth:
# quiet wrapper must set REPO_ROOT and root relative PIN_PATH before pin-file check.
# Match wrapper-local REPO_ROOT= (not SUGAR_BX_REPO_ROOT elsewhere in the file).
bx_src="$repo_root/bin/lib/sugar-bx.sh"
cd_repo_line=$(grep -n 'REPO_ROOT=\$(sugar_bx_quote' "$bx_src" | head -1 | cut -d: -f1)
pin_rel_case=$(grep -n 'PIN_PATH=.*REPO_ROOT.*PIN_PATH' "$bx_src" | head -1 | cut -d: -f1)
if [[ -z "$pin_rel_case" ]]; then
  pin_rel_case=$(grep -n 'REPO_ROOT/\$PIN_PATH\|REPO_ROOT/\\$PIN_PATH' "$bx_src" | head -1 | cut -d: -f1)
fi
pin_file_line=$(grep -n 'corpus-pin-file-missing' "$bx_src" | head -1 | cut -d: -f1)
[[ -n "$cd_repo_line" && -n "$pin_file_line" ]] \
  || fail "sugar-bx missing REPO_ROOT= before pin-file check (relative pin always 78 without remote cd)"
[[ "$cd_repo_line" -lt "$pin_file_line" ]] \
  || fail "sugar-bx pin-file check (line $pin_file_line) must come AFTER REPO_ROOT= (line $cd_repo_line)"
[[ -n "$pin_rel_case" && "$pin_rel_case" -lt "$pin_file_line" ]] \
  || fail "sugar-bx must root relative PIN_PATH under REPO_ROOT before pin-file check"
grep -Fq 'docs/ledgers' "$bx_src" || fail "sugar-bx sync_paths must include docs/ledgers (pin JSON)"
test -f "$repo_root/docs/contributing/battleaxe-timing.md" || fail "canonical timing doc missing"
grep -Fq 'timing-measurement.lease' "$repo_root/docs/contributing/battleaxe-timing.md" || fail "doc missing exclusive lease"
grep -Fq 'corpus-pin' "$repo_root/docs/contributing/battleaxe-timing.md" || fail "doc missing corpus pin gate"
test -f "$repo_root/tools/bx_corpus_pin_gate.py" || fail "bx_corpus_pin_gate.py missing"

# 8) Quiet path without SKIP must mention pin gate in remote wrapper.
: >"$ssh_log"; : >"$rsync_log"; : >"$remote_exec_log"
export BX_FAKE_LOAD="2.05 32"
status=0
SUGAR_BX_REQUIRE_QUIET=1 SUGAR_BX_SKIP_CORPUS_PIN=0 \
  run_bx -- true >/dev/null 2>"$tmp/stderr8" || status=$?
# Fake remote does not run real pin; wrapper must still carry pin gate text.
grep -Fq 'bx_corpus_pin_gate' "$remote_exec_log" \
  || grep -Fq 'bx_corpus_pin_gate' "$ssh_log" \
  || fail "quiet+pin wrapper missing bx_corpus_pin_gate"
grep -Fq 'PIN_PATH=' "$remote_exec_log" "$ssh_log" 2>/dev/null \
  || grep -Fq 'pandas-3.0.3.pin.json' "$remote_exec_log" "$ssh_log" \
  || fail "quiet+pin wrapper missing pin path"

# 9) Lease selection is a host-filesystem judgment. Prefer the authentic
# host-side tsavo cache when both candidates exist; do not inherit the caller's
# filesystem shape.
# shellcheck source=bin/lib/sugar-bx.sh
source "$repo_root/bin/lib/sugar-bx.sh"
lease_host="$tmp/lease-host"
tsavo_cache="$lease_host/home/tsavo/.cache/sugar/binaries"
runner_cache="$lease_host/home/runner/.cache/sugar/binaries"
mkdir -p "$tsavo_cache" "$runner_cache"
selected="$(sugar_bx_select_timing_lease "$tsavo_cache" "$runner_cache")"
[[ "$selected" == "$tsavo_cache/.sugar-heavy-measurement.lease" ]] \
  || fail "host with tsavo cache selected $selected"

# 10) No real shared cache means no lease. Refuse with both physical
# candidates named instead of fabricating a /var/tmp lock that cannot
# serialize host and container work.
missing_tsavo="$lease_host/missing/tsavo"
missing_runner="$lease_host/missing/runner"
status=0
sugar_bx_select_timing_lease "$missing_tsavo" "$missing_runner" \
  >"$tmp/missing-lease.out" 2>"$tmp/missing-lease.err" || status=$?
[[ "$status" -eq 77 ]] || fail "missing lease candidates status=$status want 77"
grep -Fq 'crime=timing-lease-path-unavailable' "$tmp/missing-lease.err" \
  || fail "missing lease candidates did not name the refusal"
grep -Fq "$missing_tsavo" "$tmp/missing-lease.err" \
  || fail "missing lease refusal omitted tsavo candidate"
grep -Fq "$missing_runner" "$tmp/missing-lease.err" \
  || fail "missing lease refusal omitted runner candidate"

# The selector itself must run on the remote wrapper, after transport. A local
# selection can only testify to the caller's filesystem.
grep -Fq 'sugar_bx_select_timing_lease' "$remote_exec_log" \
  || grep -Fq 'sugar_bx_select_timing_lease' "$ssh_log" \
  || fail "quiet wrapper did not defer lease selection to the remote host"

echo "PASS: sugarbin_bx_load_gate"
