#!/usr/bin/env bash

# Shared battleaxe synchronization and ambient execution backend.
exclude_args=(
  --include='/examples/serde-json-showcase/bad/.sugar/runs/***'
  --include='/examples/serde-json-showcase/good/.sugar/runs/***'
  --exclude='target/' --exclude='.git/' --exclude='.jj/' --exclude='.worktrees/'
  --exclude='.claude/' --exclude='.ruff_cache/' --exclude='.venv-test-rust/'
  --exclude='.understand-anything/' --exclude='node_modules/' --exclude='bazel-bin'
  --exclude='__pycache__/' --exclude='*.py[cod]' --exclude='.pytest_cache/'
  --exclude='bazel-out' --exclude='bazel-sugar' --exclude='bazel-testlogs'
  --exclude='sugar-warnings/' --exclude='sugar-worktrees/'
  --exclude='.sugar/runs/' --exclude='.sugar/witnesses/'
)

sync_paths=(
  Cargo.toml
  Cargo.lock
  Makefile
  sugar-build.toml
  sugar-release.toml
  bin/bcargo
  bin/brun
  bin/bpytest
  bin/sugarbin
  bin/lib/sugar-bx.sh
  bin/lib/sugar-exec.sh
  package.json
  pnpm-lock.yaml
  rust-toolchain
  rust-toolchain.toml
  .sugar/config.toml
  .sugar/lift
  .sugar/realize
  .sugar/ir-compilers
  .sugar/components
  .github
  implementations/rust
  implementations/python
  implementations/go
  implementations/java
  examples
  menagerie/csharp-language-signature/specs
  menagerie/python-language-signature/specs
  tools
  protocol
  docs/perf
  docs/self-application
  docs/contributing
  docs/ledgers
  scripts
  bootstrap
  conformance
  tests
)

sugar_bx_quote() { printf "'"; printf %s "$1" | sed "s/'/'\\\\''/g"; printf "'"; }
# When already on the target machine (SUGAR_BX_LOCAL=1) run the command in a
# local login shell instead of over ssh; exit status propagates identically.
sugar_bx_ssh() {
  if [[ "${SUGAR_BX_LOCAL:-0}" == 1 ]]; then
    bash -lc "$*"
  else
    "$SUGAR_BX_SSH" -o BatchMode=yes "$SUGAR_BX_HOST" "$@"
  fi
}

sugar_bx_init() {
  SUGAR_BX_REPO_ROOT="$(cd "$1" && pwd -P)"
  local cwd; cwd="$(cd "$2" && pwd -P)"
  case "$cwd" in
    "$SUGAR_BX_REPO_ROOT") SUGAR_BX_REL_CWD="" ;;
    "$SUGAR_BX_REPO_ROOT"/*) SUGAR_BX_REL_CWD="${cwd#"$SUGAR_BX_REPO_ROOT"/}" ;;
    *) echo "sugarbin: current directory is outside $SUGAR_BX_REPO_ROOT" >&2; return 2 ;;
  esac
  SUGAR_BX_HOST="${BCARGO_REMOTE_HOST:-battleaxe}"
  local tag; tag="$(printf %s "$SUGAR_BX_REPO_ROOT" | shasum 2>/dev/null | cut -c1-12)"; tag="${tag:-default}"
  SUGAR_BX_ROOT="${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-$tag}"
  SUGAR_BX_REPO="$SUGAR_BX_ROOT/sugar"
  SUGAR_BX_LOCAL=0
  local local_host; local_host="$(hostname 2>/dev/null || true)"
  if [[ "${BCARGO_FORCE_REMOTE:-0}" != 1 && -n "$local_host" ]]; then
    local a b
    a="$(printf '%s' "$local_host" | tr '[:upper:]' '[:lower:]')"
    b="$(printf '%s' "$SUGAR_BX_HOST" | tr '[:upper:]' '[:lower:]')"
    if [[ "$a" == "$b" ]]; then
      SUGAR_BX_LOCAL=1
      # Run directly in the current checkout: no scratch root, no sync.
      SUGAR_BX_REPO="$SUGAR_BX_REPO_ROOT"
      echo "bx: already on $SUGAR_BX_HOST; running locally" >&2
    fi
  fi
  SUGAR_BX_BINARY_CACHE="${BCARGO_REMOTE_BINARY_CACHE:-/home/tsavo/.cache/sugar/binaries}"
  SUGAR_BX_BINARY_SHELF="${BCARGO_REMOTE_BINARY_SHELF:-/home/tsavo/.cache/sugar/binary-shelf-v2}"
  SUGAR_BX_SSH="${BCARGO_SSH:-ssh}"; SUGAR_BX_RSYNC="${BCARGO_RSYNC:-rsync}"
  SUGAR_BX_CLEAN="${BCARGO_CLEAN_REMOTE_ROOT:-never}"
  case "$SUGAR_BX_CLEAN" in ""|0|false|no|never) SUGAR_BX_CLEAN=never;; 1|true|yes|success) SUGAR_BX_CLEAN=success;; always);; *) echo "sugarbin: BCARGO_CLEAN_REMOTE_ROOT must be never, success, or always" >&2; return 2;; esac
  if [[ "$SUGAR_BX_CLEAN" != never && "$SUGAR_BX_ROOT" != /home/tsavo/remote/sugar-bcargo-* && "${BCARGO_CLEAN_REMOTE_ROOT_UNSAFE:-0}" != 1 ]]; then
    echo "sugarbin: refusing to clean unsafe remote root: $SUGAR_BX_ROOT" >&2
    echo "sugarbin: set BCARGO_CLEAN_REMOTE_ROOT_UNSAFE=1 only for an explicitly disposable root" >&2
    return 2
  fi
  local days="${BCARGO_REAP_DAYS:-2}"
  if [[ "$days" != 0 && "$SUGAR_BX_LOCAL" != 1 ]]; then
    sugar_bx_ssh "mkdir -p $(sugar_bx_quote "$SUGAR_BX_ROOT") && touch $(sugar_bx_quote "$SUGAR_BX_ROOT") && nohup find /home/tsavo/remote -mindepth 1 -maxdepth 1 -name 'sugar-bcargo-*' ! -path $(sugar_bx_quote "$SUGAR_BX_ROOT") -mtime +$(sugar_bx_quote "$days") -exec rm -rf {} + >/dev/null 2>&1 &" || true
  fi
}

sugar_bx_sync_workspace() {
  # Local mode runs in the checkout itself: nothing to sync.
  if [[ "${SUGAR_BX_LOCAL:-0}" != 1 ]]; then
    local existing=() rel manifest
    for rel in "${sync_paths[@]}"; do [[ -e "$SUGAR_BX_REPO_ROOT/$rel" ]] && existing+=("$rel"); done
    sugar_bx_ssh "rm -rf $(sugar_bx_quote "$SUGAR_BX_REPO/menagerie") && mkdir -p $(sugar_bx_quote "$SUGAR_BX_REPO")"
    (cd "$SUGAR_BX_REPO_ROOT" && "$SUGAR_BX_RSYNC" -azR --delete "${exclude_args[@]}" "${existing[@]}" "$SUGAR_BX_HOST:$SUGAR_BX_REPO/")
    manifest="$(mktemp)"
    if git -C "$SUGAR_BX_REPO_ROOT" ls-files -z >"$manifest" 2>/dev/null; then
      "$SUGAR_BX_RSYNC" -az "$manifest" "$SUGAR_BX_HOST:$SUGAR_BX_REPO/.bcargo-tracked-manifest"
    fi
    rm -f "$manifest"
  fi
}

# A bind mount can start up cleanly and still be empty, stale, or point at an
# entirely different checkout -- on WSL2 hosts a plain Linux path silently
# binds an empty directory instead of failing. Stamp a fresh, unpredictable
# token into the just-synced workspace and require every container that
# mounts it (see tools/sugar-build/entrypoint.sh) to read the same token back
# before running anything. An empty or wrong mount cannot produce the token,
# so it cannot produce a plausible result either: it fails loudly instead.
SUGAR_BX_MOUNT_PROOF_NAME=".bcargo-mount-proof"
sugar_bx_write_mount_proof() {
  local head_sha manifest_sha
  head_sha="$(git -C "$SUGAR_BX_REPO_ROOT" rev-parse HEAD 2>/dev/null || echo no-head)"
  manifest_sha="$( (git -C "$SUGAR_BX_REPO_ROOT" ls-files -z 2>/dev/null | shasum -a 256 2>/dev/null || true) | cut -d' ' -f1)"
  SUGAR_BX_MOUNT_PROOF="${head_sha}:${manifest_sha:-no-manifest}:$$:${RANDOM:-0}:$(date +%s%N 2>/dev/null || date +%s)"
  if [[ "${SUGAR_BX_LOCAL:-0}" == 1 ]]; then
    printf '%s' "$SUGAR_BX_MOUNT_PROOF" >"$SUGAR_BX_REPO/$SUGAR_BX_MOUNT_PROOF_NAME"
  else
    printf '%s' "$SUGAR_BX_MOUNT_PROOF" | sugar_bx_ssh "cat > $(sugar_bx_quote "$SUGAR_BX_REPO/$SUGAR_BX_MOUNT_PROOF_NAME")"
  fi
}

# `systemctl is-active docker` reports active on battleaxe even when
# /var/run/docker.sock is a dead symlink into Docker Desktop's WSL2 shared
# sockets and nothing works -- it is a false-healthy reading. Prove the
# daemon actually answers the API before routing any command through it.
sugar_bx_require_docker_ready() {
  local out status
  set +e
  out="$(sugar_bx_ssh "docker info" 2>&1)"
  status=$?
  set -e
  if [[ "$status" != 0 ]]; then
    printf 'sugarbin: crime=false-healthy-docker-daemon host=%s reason=docker-info-failed status=%s detail=%s replacement=fix the Docker Desktop / WSL2 integration or start the daemon -- do not trust `systemctl is-active docker`, it reports active even when the socket is a dead symlink and nothing works\n' \
      "$SUGAR_BX_HOST" "$status" "${out:-<no output>}" >&2
    return 70
  fi
}

# Exit 76: host not quiet enough for a trusted wall-clock measurement.
# Exit 77: another quiet-gated timing measurement holds the exclusive lease.
# A number taken under contention is not a slow measurement — it is not a
# measurement. Timing runs must set SUGAR_BX_REQUIRE_QUIET=1 (or an explicit
# SUGAR_BX_MAX_LOADAVG). Ordinary builds leave both unset and are not gated.
# Sample is always the *remote* box load (via sugar_bx_ssh), never the laptop.
#
# Concurrency: load-at-start alone is not enough — six agents can all pass a
# quiet check then co-run and recreate contention on battleaxe. Quiet-gated
# ambient runs take an exclusive remote flock on the host bind-mount lease
# (/home/runner|tsavo/.cache/sugar/binaries/.sugar-heavy-measurement.lease;
# never /var/tmp on containers — lock theatre), re-sample load under that
# lock, then run. CI seats use shared flock on the same path
# (tools/bx_host_measure_gates.sh --shared). Serialize, do not rely on people.
sugar_bx_quiet_armed() {
  local require="${SUGAR_BX_REQUIRE_QUIET:-0}"
  local max_env="${SUGAR_BX_MAX_LOADAVG:-}"
  [[ -n "$max_env" || "$require" == 1 || "$require" == true || "$require" == yes ]]
}

# Select the one lease that is physically shared by host brun processes and
# CI containers. This judgment belongs to the host that will take the lock,
# not to the caller assembling the remote command. /var/tmp is deliberately
# not a fallback: on containerized runners it produces a different inode and
# only simulates serialization.
sugar_bx_select_timing_lease() {
  local tsavo_cache="${1:-/home/tsavo/.cache/sugar/binaries}"
  local runner_cache="${2:-/home/runner/.cache/sugar/binaries}"
  if [[ -d "$tsavo_cache" ]]; then
    printf '%s\n' "$tsavo_cache/.sugar-heavy-measurement.lease"
    return 0
  fi
  if [[ -d "$runner_cache" ]]; then
    printf '%s\n' "$runner_cache/.sugar-heavy-measurement.lease"
    return 0
  fi
  printf 'sugarbin: crime=timing-lease-path-unavailable candidates=%s,%s replacement=restore one shared host binary-cache directory; do not substitute a container-local lease\n' \
    "$tsavo_cache" "$runner_cache" >&2
  return 77
}

sugar_bx_sample_load() {
  # Prints: load1 nproc  (one line). Uses /proc/loadavg on Linux; falls back
  # to python getloadavg on platforms without it (local-mode macOS tests).
  sugar_bx_ssh 'bash -lc "
    set -e
    if [[ -r /proc/loadavg ]]; then
      read -r l1 _rest </proc/loadavg
    else
      l1=\$(python3 -c \"import os; print(os.getloadavg()[0])\" 2>/dev/null || echo 0)
    fi
    n=\$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)
    printf \"%s %s\\n\" \"\$l1\" \"\$n\"
  "'
}

sugar_bx_require_quiet() {
  # Arm the quiet gate. Authoritative load sample + exclusive lease happen
  # inside sugar_bx_run_ambient under flock so concurrent brun callers cannot
  # both pass a free load check and then co-measure.
  SUGAR_BX_QUIET_ARMED=0
  SUGAR_BX_LOAD_BEFORE=""
  if ! sugar_bx_quiet_armed; then
    return 0
  fi
  SUGAR_BX_QUIET_ARMED=1
  SUGAR_BX_LOAD_MAX="${SUGAR_BX_MAX_LOADAVG:-}"
  # An explicit path remains an explicit operator assertion. Otherwise leave
  # selection to the remote host, whose filesystem is authoritative. The
  # caller cannot truthfully choose between host paths from its own namespace.
  if [[ -n "${SUGAR_BX_TIMING_LEASE_PATH:-}" ]]; then
    SUGAR_BX_TIMING_LEASE="$SUGAR_BX_TIMING_LEASE_PATH"
  else
    SUGAR_BX_TIMING_LEASE=""
  fi
  # Default wait 2h (queue). Set SUGAR_BX_TIMING_LEASE_WAIT_S=0 to refuse
  # immediately with exit 77 when another measurement holds the lease.
  SUGAR_BX_TIMING_LEASE_WAIT="${SUGAR_BX_TIMING_LEASE_WAIT_S:-7200}"
  # Corpus pin (third gate). Quiet timing without a pin is a guess: battleaxe
  # system python has been pandas 2.3.3/1415 while the authenticated pin is
  # 3.0.3/1421. Default banked pin; SUGAR_BX_SKIP_CORPUS_PIN=1 only for
  # non-corpus quiet probes (load/lease unit tests).
  SUGAR_BX_CORPUS_PIN_PATH="${SUGAR_BX_REQUIRE_CORPUS_PIN:-docs/ledgers/pins/pandas-3.0.3.pin.json}"
  SUGAR_BX_CORPUS_PYTHON="${SUGAR_BX_CORPUS_PYTHON:-.venv-py312/bin/python}"
  SUGAR_BX_SKIP_CORPUS_PIN="${SUGAR_BX_SKIP_CORPUS_PIN:-0}"
  printf 'sugarbin: bx-load-gate phase=arm host=%s max=%s lease=%s wait_s=%s corpus_pin=%s skip_pin=%s\n' \
    "$SUGAR_BX_HOST" "${SUGAR_BX_LOAD_MAX:-auto(nproc/4,floor=2)}" \
    "${SUGAR_BX_TIMING_LEASE:-host-selected}" "$SUGAR_BX_TIMING_LEASE_WAIT" \
    "$SUGAR_BX_CORPUS_PIN_PATH" "$SUGAR_BX_SKIP_CORPUS_PIN" >&2
  return 0
}

sugar_bx_report_load_after() {
  # After-load is printed under the lease by the remote wrapper when quiet is
  # armed. This local hook is a no-op for quiet runs (remote already testified)
  # and a no-op when the gate was never armed.
  [[ "${SUGAR_BX_QUIET_ARMED:-0}" == 1 ]] && return 0
  [[ -n "${SUGAR_BX_LOAD_BEFORE:-}" ]] || return 0
  local sample load1
  set +e
  sample="$(sugar_bx_sample_load 2>/dev/null)"
  set -e
  sample="$(printf '%s' "$sample" | tr -d '\r' | tail -n 1)"
  load1="${sample%% *}"
  printf 'sugarbin: bx-load-gate phase=after host=%s load1_before=%s load1_after=%s nproc=%s\n' \
    "$SUGAR_BX_HOST" "$SUGAR_BX_LOAD_BEFORE" "${load1:-unknown}" "${SUGAR_BX_NPROC:-unknown}" >&2
}

sugar_bx_run_ambient() {
  local remote_cwd="$SUGAR_BX_REPO" arg inner="" prefix="" name
  [[ -n "$SUGAR_BX_REL_CWD" ]] && remote_cwd="$SUGAR_BX_REPO/$SUGAR_BX_REL_CWD"
  if ((${#SUGAR_BX_PATH_PREFIXES[@]} != 0)); then
    for prefix in "${SUGAR_BX_PATH_PREFIXES[@]}"; do
      [[ -z "$inner" ]] && inner="$prefix" || inner="$inner:$prefix"
    done
  fi
  local prefix_cmd="cd $(sugar_bx_quote "$remote_cwd") && "
  [[ -n "$inner" ]] && prefix_cmd+="PATH=$(sugar_bx_quote "$inner"):\$PATH "
  if ((${#SUGAR_BX_ENV_NAMES[@]} != 0)); then
    for name in "${SUGAR_BX_ENV_NAMES[@]}"; do [[ ${!name+x} == x ]] && prefix_cmd+="$name=$(sugar_bx_quote "${!name}") "; done
  fi
  local run_cmd=""
  for arg in "$@"; do
    if [[ "$arg" == "$SUGAR_BX_REPO_ROOT" ]]; then arg="$SUGAR_BX_REPO"; elif [[ "$arg" == "$SUGAR_BX_REPO_ROOT"/* ]]; then arg="$SUGAR_BX_REPO/${arg#"$SUGAR_BX_REPO_ROOT"/}"; fi
    run_cmd+=" $(sugar_bx_quote "$arg")"
  done

  # Ungated path: one-shot exec (unchanged contract).
  if [[ "${SUGAR_BX_QUIET_ARMED:-0}" != 1 ]]; then
    sugar_bx_ssh "bash -lc $(sugar_bx_quote "${prefix_cmd}exec${run_cmd}")"
    return $?
  fi

  # Quiet path: exclusive remote lease → load under lock → corpus pin →
  # measure. Do not exec-replace the shell that holds the flock fd.
  # Three gates, one law: quiet box, exclusive lease, correct corpus.
  local lock wait_s max_lit host_lit measured_cmd wrapper selector_def login_exec
  local compact_wrapper remote_wrapper
  local pin_path pin_py pin_skip
  lock="${SUGAR_BX_TIMING_LEASE:-}"
  selector_def="$(declare -f sugar_bx_select_timing_lease)"
  wait_s="${SUGAR_BX_TIMING_LEASE_WAIT:-7200}"
  max_lit="${SUGAR_BX_LOAD_MAX:-}"
  host_lit="$SUGAR_BX_HOST"
  pin_path="${SUGAR_BX_CORPUS_PIN_PATH:-docs/ledgers/pins/pandas-3.0.3.pin.json}"
  pin_py="${SUGAR_BX_CORPUS_PYTHON:-.venv-py312/bin/python}"
  pin_skip="${SUGAR_BX_SKIP_CORPUS_PIN:-0}"
  # prefix_cmd already ends with spaces/env; run_cmd starts with a leading space.
  measured_cmd="${prefix_cmd}${run_cmd# }"
  # Pin gate under lease after load. Identity mode (version+fileCount) default.
  # All remote expansions use \$ so local $? does not fire while building wrapper.
  #
  # REPO_ROOT first, then pin existence. Relative pin/python paths are
  # repo-root-relative (docs/ledgers/pins/…, .venv-py312/bin/python). Checking
  # them before cd lands in $HOME (ssh default) or a caller subdir and always
  # 78s — only absolute /tmp pins worked. Pin against SUGAR_BX_REPO, not
  # remote_cwd (may be a subdir when REL_CWD is set). measured_cmd still cds
  # to the caller's cwd via prefix_cmd after the pin authenticates.
  wrapper="$selector_def
set -euo pipefail
LOCK=$(sugar_bx_quote "$lock")
WAIT=$(sugar_bx_quote "$wait_s")
MAX_LIT=$(sugar_bx_quote "$max_lit")
HOST=$(sugar_bx_quote "$host_lit")
SKIP_PIN=$(sugar_bx_quote "$pin_skip")
PIN_PATH=$(sugar_bx_quote "$pin_path")
PIN_PY=$(sugar_bx_quote "$pin_py")
REPO_ROOT=$(sugar_bx_quote "$SUGAR_BX_REPO")
if [[ -z \"\$LOCK\" ]]; then
  if LOCK=\$(sugar_bx_select_timing_lease); then
    :
  else
    selector_status=\$?
    exit \"\$selector_status\"
  fi
fi
cd \"\$REPO_ROOT\" || { printf 'sugarbin: crime=corpus-pin-cwd-missing path=%s replacement=synced checkout at SUGAR_BX_REPO must exist before pin check\\n' \"\$REPO_ROOT\" >&2; exit 78; }
# Root relative pin/python against the synced checkout. Absolute paths (e.g.
# /tmp/pin.json or a fleet venv) pass through unchanged.
case \"\$PIN_PATH\" in
  /*) ;;
  *) PIN_PATH=\"\$REPO_ROOT/\$PIN_PATH\" ;;
esac
case \"\$PIN_PY\" in
  /*) ;;
  *) PIN_PY=\"\$REPO_ROOT/\$PIN_PY\" ;;
esac
touch \"\$LOCK\" || { printf 'sugarbin: crime=timing-lease-uncreatable path=%s\\n' \"\$LOCK\" >&2; exit 77; }
exec 9>>\"\$LOCK\"
if ! command -v flock >/dev/null 2>&1; then
  printf 'sugarbin: crime=timing-lease-flock-missing host=%s replacement=install util-linux flock on battleaxe\\n' \"\$HOST\" >&2
  exit 77
fi
printf 'sugarbin: bx-timing-lease phase=waiting host=%s path=%s wait_s=%s\\n' \"\$HOST\" \"\$LOCK\" \"\$WAIT\" >&2
if ! flock -w \"\$WAIT\" 9; then
  printf 'sugarbin: crime=timing-lease-busy host=%s path=%s wait_s=%s replacement=another quiet-gated measurement holds the exclusive lease — serialize; do not co-measure on battleaxe. exit 77\\n' \\
    \"\$HOST\" \"\$LOCK\" \"\$WAIT\" >&2
  exit 77
fi
printf 'sugarbin: bx-timing-lease phase=acquired host=%s path=%s\\n' \"\$HOST\" \"\$LOCK\" >&2
# Quiet metric: CPU idle percent (governs), with loadavg always testified beside it.
# On battleaxe, ~25 CI runner containers inflate loadavg via process churn while
# the box can still be CPU-available. Gating only on loadavg blocks honest
# measurements; raising SUGAR_BX_MAX_LOADAVG to sneak past is forbidden.
# Receipt carries BOTH so a reader can judge. Exit 76 still means not quiet.
if [[ -r /proc/loadavg ]]; then
  read -r l1 _rest </proc/loadavg
else
  l1=\$(python3 -c 'import os; print(os.getloadavg()[0])' 2>/dev/null || echo 0)
fi
n=\$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)
# Sample CPU idle over ~1s via /proc/stat deltas (field 5 = idle jiffies).
read_cpu_idle() {
  local t1 i1 t2 i2 dt di
  read -r t1 i1 < <(awk '/^cpu /{print \$2+\$3+\$4+\$5+\$6+\$7+\$8+\$9, \$5}' /proc/stat)
  sleep 1
  read -r t2 i2 < <(awk '/^cpu /{print \$2+\$3+\$4+\$5+\$6+\$7+\$8+\$9, \$5}' /proc/stat)
  dt=\$((t2-t1)); di=\$((i2-i1))
  if [[ \$dt -gt 0 ]]; then
    awk -v di=\"\$di\" -v dt=\"\$dt\" 'BEGIN{printf \"%.2f\", 100.0*di/dt}'
  else
    echo 0
  fi
}
if [[ -r /proc/stat ]]; then
  idle_pct=\$(read_cpu_idle)
else
  # Non-Linux / test hosts: fall back to treating idle as high when no load gate.
  idle_pct=100
fi
# Minimum idle percent that counts as quiet (default 50). Override with
# SUGAR_BX_MIN_CPU_IDLE (0-100). Explicit SUGAR_BX_MAX_LOADAVG still only
# *records* loadavg; it does not alone govern pass/fail when CPU idle is the
# governing metric (unless SUGAR_BX_QUIET_METRIC=loadavg).
# Calibration (battleaxe 2026-08-02T13:34Z, no heavy work): load1~19–20 from
# runner-container churn, cpu_idle_pct~39–44%, procs_blocked=0. Floor is set
# just under that idle band so a truly quiet box passes; do not raise loadavg.
MIN_IDLE=\${SUGAR_BX_MIN_CPU_IDLE:-35}
BASELINE_NOTE='bx-idle-baseline-2026-08-02 load1~19.5 cpu_idle~40% nproc=32'
QUIET_METRIC=\${SUGAR_BX_QUIET_METRIC:-cpu_idle}
if [[ -n \"\$MAX_LIT\" ]]; then
  max=\"\$MAX_LIT\"
else
  max=\$(awk -v n=\"\$n\" 'BEGIN{ m=n/4.0; if (m < 2.0) m=2.0; printf \"%.2f\", m }')
fi
printf 'sugarbin: bx-load-gate phase=before host=%s load1=%s cpu_idle_pct=%s nproc=%s min_idle=%s load_max=%s metric=%s baseline=%s lease=held\\n' \\
  \"\$HOST\" \"\$l1\" \"\$idle_pct\" \"\$n\" \"\$MIN_IDLE\" \"\$max\" \"\$QUIET_METRIC\" \"\$BASELINE_NOTE\" >&2
quiet_ok=1
if [[ \"\$QUIET_METRIC\" == loadavg ]]; then
  if awk -v l=\"\$l1\" -v m=\"\$max\" 'BEGIN{ exit !(l+0 > m+0) }'; then quiet_ok=0; fi
else
  # cpu_idle (default): pass when idle_pct >= min_idle. loadavg is testimony only.
  if awk -v i=\"\$idle_pct\" -v m=\"\$MIN_IDLE\" 'BEGIN{ exit !(i+0 < m+0) }'; then quiet_ok=0; fi
fi
if [[ \"\$quiet_ok\" != 1 ]]; then
  printf 'sugarbin: crime=host-not-quiet host=%s load1=%s cpu_idle_pct=%s nproc=%s min_idle=%s load_max=%s metric=%s lease=held replacement=wait for cpu_idle_pct>=%s (or set SUGAR_BX_QUIET_METRIC=loadavg / SUGAR_BX_MIN_CPU_IDLE with cause). Receipt carries loadavg+cpu_idle; do not raise load threshold to sneak past churn. A measurement that cannot testify to its own conditions is not a measurement.\\n' \\
    \"\$HOST\" \"\$l1\" \"\$idle_pct\" \"\$n\" \"\$MIN_IDLE\" \"\$max\" \"\$QUIET_METRIC\" \"\$MIN_IDLE\" >&2
  exit 76
fi
if [[ \"\$SKIP_PIN\" != 1 && \"\$SKIP_PIN\" != true && \"\$SKIP_PIN\" != yes ]]; then
  export PYTHONPATH=implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-source-tree/src:\${PYTHONPATH:-}
  if [[ ! -x \"\$PIN_PY\" ]]; then
    printf 'sugarbin: crime=corpus-pin-python-missing path=%s cwd=%s replacement=bin/brun -- bash scripts/bootstrap-venv-py312.sh (or absolute SUGAR_BX_CORPUS_PYTHON to a fleet venv with 3.0.3/1421). Relative .venv-py312 is resolved under the synced repo root AFTER remote cd — not from \$HOME.\\n' \"\$PIN_PY\" \"\$REPO_ROOT\" >&2
    exit 78
  fi
  if [[ ! -f \"\$PIN_PATH\" ]]; then
    printf 'sugarbin: crime=corpus-pin-file-missing path=%s cwd=%s replacement=docs/ledgers/pins/pandas-3.0.3.pin.json must be in the synced checkout (sync_paths includes docs/ledgers). Relative pin paths are resolved under repo root AFTER remote cd — a check before that cd always 78s.\\n' \"\$PIN_PATH\" \"\$REPO_ROOT\" >&2
    exit 78
  fi
  set +e
  \"\$PIN_PY\" \"\$REPO_ROOT\"/tools/bx_corpus_pin_gate.py --expected-pin \"\$PIN_PATH\" --python \"\$PIN_PY\"
  pin_st=\$?
  set -e
  if [[ \"\$pin_st\" != 0 ]]; then
    printf 'sugarbin: crime=corpus-pin-mismatch exit=%s (78=wrong corpus; a number against the wrong pandas is not a measurement)\\n' \"\$pin_st\" >&2
    exit 78
  fi
else
  printf 'sugarbin: bx-corpus-pin phase=skipped reason=SUGAR_BX_SKIP_CORPUS_PIN\\n' >&2
fi
set +e
${measured_cmd}
st=\$?
set -e
if [[ -r /proc/loadavg ]]; then
  read -r l2 _rest </proc/loadavg
else
  l2=\$(python3 -c 'import os; print(os.getloadavg()[0])' 2>/dev/null || echo unknown)
fi
if [[ -r /proc/stat ]]; then
  idle_after=\$(read_cpu_idle)
else
  idle_after=unknown
fi
printf 'sugarbin: bx-load-gate phase=after host=%s load1_before=%s load1_after=%s cpu_idle_before=%s cpu_idle_after=%s nproc=%s metric=%s lease=held\\n' \\
  \"\$HOST\" \"\$l1\" \"\$l2\" \"\$idle_pct\" \"\$idle_after\" \"\$n\" \"\$QUIET_METRIC\" >&2
printf 'sugarbin: bx-timing-lease phase=release host=%s path=%s status=%s\\n' \"\$HOST\" \"\$LOCK\" \"\$st\" >&2
exit \"\$st\""
  # OpenSSH multiplexes the command through a bounded Unix-domain socket
  # packet. Comments are not executable testimony; sending them made valid
  # artifact commands cross that transport boundary. Gate logic is unchanged.
  compact_wrapper="$(printf '%s\n' "$wrapper" | sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d')"
  # Keep login-shell initialization, then replace that shell before it can run
  # a status-bearing logout hook. On battleaxe /etc/bash.bash_logout invokes
  # clear_console, whose exit 1 replaced both remote success and remote 23.
  # The non-login wrapper's explicit exit is therefore the SSH verdict.
  login_exec='exec bash "$1"'
  # The OpenSSH ControlMaster mux has a bounded command packet. Passing the
  # full wrapper through bash -c makes a large payload fail as rc=255 with no
  # artifact. Stage the wrapper over stdin, then invoke it by reference so the
  # transport payload stays small. A staging failure is named, never mistaken
  # for a measurement result.
  remote_wrapper="$SUGAR_BX_REPO/.sugar-bx-wrapper-$$"
  if ! printf '%s\n' "$compact_wrapper" | sugar_bx_ssh "cat > $(sugar_bx_quote "$remote_wrapper")"; then
    printf 'sugarbin: crime=controlmaster-command-payload-refused limit=unknown stage=%s replacement=retry with staged command reference\n' "$remote_wrapper" >&2
    return 255
  fi
  set +e
  sugar_bx_ssh "bash -lc $(sugar_bx_quote "$login_exec") bash "$remote_wrapper""
  st=$?
  set -e
  if ((st != 0)); then
    sugar_bx_ssh "rm -f $(sugar_bx_quote "$remote_wrapper")" >/dev/null 2>&1 || true
    return "$st"
  fi
  sugar_bx_ssh "rm -f $(sugar_bx_quote "$remote_wrapper")" >/dev/null 2>&1 || true
}

sugar_bx_docker_bind_source() {
  local source="$1" resolved
  # On a WSL2 host, Docker Desktop's engine runs in a separate distro: a
  # plain Linux path like /home/tsavo/... does not fail to bind, it silently
  # binds an EMPTY directory. Only the Windows UNC form
  # (\\wsl.localhost\<distro>\...), produced by `wslpath -w`, resolves inside
  # the engine. If this is a WSL host and wslpath is unavailable, refuse
  # instead of silently constructing the path form that produces the empty
  # mount -- that silent fallback is exactly the hazard being closed here.
  resolved="$(sugar_bx_ssh "if command -v wslpath >/dev/null 2>&1; then wslpath -w $(sugar_bx_quote "$source"); elif grep -qi microsoft /proc/version 2>/dev/null; then printf 'SUGAR_BX_WSLPATH_MISSING\n'; else printf '%s\n' $(sugar_bx_quote "$source"); fi")" || return $?
  resolved="$(printf '%s' "$resolved" | tr -d '\r')"
  if [[ "$resolved" == SUGAR_BX_WSLPATH_MISSING ]]; then
    printf 'sugarbin: crime=empty-bind-mount-risk host=%s source=%s reason=wslpath-unavailable-on-wsl2-host replacement=install wslpath on the remote host; refusing to construct a plain Linux-path bind mount that Docker Desktop silently mounts empty\n' \
      "$SUGAR_BX_HOST" "$source" >&2
    return 70
  fi
  printf '%s\n' "$resolved"
}

sugar_bx_quarantine_required_artifacts() {
  local artifacts_dir="$1" quarantine_dir="$2" cap="${3:-64}"
  python3 - "$artifacts_dir/required-artifacts.json" "$quarantine_dir" "$cap" <<'PY'
import hashlib
import json
import os
import pathlib
import sys
import tempfile

manifest_path = pathlib.Path(sys.argv[1])
quarantine_dir = pathlib.Path(sys.argv[2])
cap = int(sys.argv[3])
if not manifest_path.is_file():
    raise SystemExit(0)

raw = manifest_path.read_bytes()
try:
    json.loads(raw)
except (json.JSONDecodeError, UnicodeDecodeError):
    pass
else:
    raise SystemExit(0)

digest = hashlib.sha256(raw).hexdigest()
quarantine_dir.mkdir(parents=True, exist_ok=True)
destination = quarantine_dir / f"required-artifacts.sha256-{digest}.json"
if not destination.exists():
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".required-artifacts-quarantine.", dir=quarantine_dir
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

entries = sorted(
    quarantine_dir.glob("required-artifacts.sha256-*.json"),
    key=lambda path: (path.stat().st_mtime_ns, path.name),
)
current_count = len(entries)
if current_count > cap:
    evicted = current_count - cap
    print(
        "sugarbin: crime=artifact-manifest-quarantine-cap-exceeded "
        f"path={quarantine_dir} currentCount={current_count} cap={cap} "
        f"evicted={evicted} remaining={cap} policy=oldest-first",
        file=sys.stderr,
    )
    for path in entries[:evicted]:
        path.unlink()
PY
}

sugar_bx_artifact_build_script() {
  local needs="$1" profile="$2"
  local workspace="${3:-/workspace/sugar}" out="${4:-/out}"
  {
    printf 'workspace=%q; out=%q; needs=%q; profile=%q; ' \
      "$workspace" "$out" "$needs" "$profile"
    cat <<'SCRIPT'
set -euo pipefail;
cd "$workspace";
manifest="$out/required-artifacts.json";
manifest_tmp="$(mktemp "$out/.required-artifacts.json.XXXXXX")";
cleanup_manifest_tmp() { [[ -z "${manifest_tmp:-}" ]] || rm -f -- "$manifest_tmp"; };
trap cleanup_manifest_tmp EXIT;
trap 'exit 129' HUP;
trap 'exit 130' INT;
trap 'exit 143' TERM;
printf '{"artifacts":[' >"$manifest_tmp";
first=1;
IFS=,;
for b in $needs; do
  [[ -n "$b" ]] || continue;
  r="$(env -u SUGAR_BIN -u SUGAR_BINARY_DIR bin/sugarbin --profile "$profile" --platform linux-x86_64 --bin "$b")";
  cp "$r" "$out/$b";
  cp "$r.sugarbin.json" "$out/$b.sugarbin.json";
  sum="$(sha256sum "$out/$b" | cut -d' ' -f1)";
  [[ "$first" == 1 ]] || printf ',' >>"$manifest_tmp";
  first=0;
  printf '{"name":"%s","sha256":"%s"}' "$b" "$sum" >>"$manifest_tmp";
done;
printf ']}' >>"$manifest_tmp";
chmod 0644 "$manifest_tmp";
mv -f -- "$manifest_tmp" "$manifest";
manifest_tmp="";
trap - EXIT HUP INT TERM;
SCRIPT
  } | tr '\n' ' '
  printf '\n'
}

sugar_bx_build_artifacts_docker() {
  local image="$1" needs="$2" profile="$3" provision_artifacts="${4:-0}"
  local image_digest="${image##*@sha256:}"
  local managed_target="${BCARGO_REMOTE_MANAGED_TARGET:-/home/tsavo/.cache/sugar/managed-targets/$image_digest}"
  local quarantine_def reset_command
  quarantine_def="$(declare -f sugar_bx_quarantine_required_artifacts)"
  reset_command="set -euo pipefail
$quarantine_def
sugar_bx_quarantine_required_artifacts $(sugar_bx_quote "$SUGAR_BX_ROOT/artifacts") $(sugar_bx_quote "$SUGAR_BX_ROOT/artifact-manifest-quarantine") 64
rm -rf $(sugar_bx_quote "$SUGAR_BX_ROOT/artifacts")
mkdir -p $(sugar_bx_quote "$SUGAR_BX_ROOT/artifacts") $(sugar_bx_quote "$SUGAR_BX_BINARY_CACHE") $(sugar_bx_quote "$SUGAR_BX_BINARY_SHELF") $(sugar_bx_quote "$managed_target")"
  sugar_bx_ssh "$reset_command" || return $?
  local workspace_source artifacts_source cache_source shelf_source target_source
  workspace_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_REPO")" || return $?
  artifacts_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_ROOT/artifacts")" || return $?
  cache_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_BINARY_CACHE")" || return $?
  shelf_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_BINARY_SHELF")" || return $?
  target_source="$(sugar_bx_docker_bind_source "$managed_target")" || return $?
  local build_script
  build_script="$(sugar_bx_artifact_build_script "$needs" "$profile")"
  local shelf_mount="type=bind,src=$shelf_source,dst=/root/.cache/sugar/binary-shelf-v2,readonly"
  local shelf_read_only=1
  local name
  if [[ "$provision_artifacts" == 1 ]]; then
    for name in ${SUGAR_BX_ENV_NAMES[@]+"${SUGAR_BX_ENV_NAMES[@]}"}; do
      [[ "$name" != SUGAR_BINARY_PUBLISH || ${!name:-0} != 1 ]] \
        || {
          shelf_mount="type=bind,src=$shelf_source,dst=/root/.cache/sugar/binary-shelf-v2"
          shelf_read_only=0
        }
    done
  fi
  local -a docker_args=(docker run --rm
    --workdir /workspace/sugar
    --env SUGAR_BINARY_ALLOW_BUILD=0
    --env SUGAR_BINARY_PUBLISH=0
    --env "SUGAR_BINARY_SHELF_READ_ONLY=$shelf_read_only"
    --env CARGO_TARGET_DIR=/managed-target
    --env SUGAR_BINARY_TARGET_ROOT=/managed-target
    --env "SUGAR_BX_MOUNT_PROOF=$SUGAR_BX_MOUNT_PROOF"
    --mount "type=bind,src=$workspace_source,dst=/workspace/sugar"
    --mount "type=bind,src=$artifacts_source,dst=/out"
    --mount "type=bind,src=$cache_source,dst=/root/.cache/sugar/binaries"
    --mount "$shelf_mount"
    --mount "type=bind,src=$target_source,dst=/managed-target"
  )
  for name in ${SUGAR_BX_ENV_NAMES[@]+"${SUGAR_BX_ENV_NAMES[@]}"}; do
    case "$name" in
      SUGAR_BINARY_ALLOW_BUILD|SUGAR_BINARY_PUBLISH|SUGAR_BINARY_REQUIRE_PUBLISH)
        if [[ "$provision_artifacts" == 1 || ${!name:-0} == 0 ]]; then
          [[ ${!name+x} != x ]] || docker_args+=(--env "$name=${!name}")
        fi
        ;;
    esac
  done
  docker_args+=("$image" bash -lc "$build_script")
  local arg command=""
  for arg in "${docker_args[@]}"; do command+=" $(sugar_bx_quote "$arg")"; done
  sugar_bx_ssh "exec${command}"
}

sugar_bx_run_docker() {
  local image="$1" network="$2" has_artifacts="$3"; shift 3
  local remote_cwd="/workspace/sugar"
  [[ -n "$SUGAR_BX_REL_CWD" ]] && remote_cwd="$remote_cwd/$SUGAR_BX_REL_CWD"
  local workspace_source artifacts_source manifest_source shelf_source
  workspace_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_REPO")" || return $?
  sugar_bx_ssh "mkdir -p $(sugar_bx_quote "$SUGAR_BX_BINARY_SHELF")" || return $?
  shelf_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_BINARY_SHELF")" || return $?
  local -a docker_args=(docker run --rm
    --workdir "$remote_cwd"
    --env PATH=/opt/sugar/bin:/opt/java/bin:/root/.cargo/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
    --env "SUGAR_BX_MOUNT_PROOF=$SUGAR_BX_MOUNT_PROOF"
    --mount "type=bind,src=$workspace_source,dst=/workspace/sugar"
    --mount "type=bind,src=$shelf_source,dst=/root/.cache/sugar/binary-shelf-v2,readonly")
  [[ "$network" != none ]] || docker_args+=(--network none)
  if [[ "$has_artifacts" == 1 ]]; then
    artifacts_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_ROOT/artifacts")" || return $?
    manifest_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_ROOT/artifacts/required-artifacts.json")" || return $?
    docker_args+=(--mount "type=bind,src=$artifacts_source,dst=/opt/sugar/bin,readonly")
    docker_args+=(--mount "type=bind,src=$manifest_source,dst=/opt/sugar/required-artifacts.json,readonly")
  fi
  local name arg command=""
  for name in ${SUGAR_BX_ENV_NAMES[@]+"${SUGAR_BX_ENV_NAMES[@]}"}; do
    # Transport-owned mount and publish authority cannot be forged by a
    # payload env. Final tasks may consume the shared shelf but only the
    # explicit managed publisher may stage or install shared cells.
    case "$name" in
      SUGAR_BINARY_SHELF_READ_ONLY|SUGAR_BINARY_PUBLISH) continue ;;
    esac
    [[ ${!name+x} == x ]] && docker_args+=(--env "$name=${!name}")
  done
  docker_args+=(--env SUGAR_BINARY_SHELF_READ_ONLY=1)
  docker_args+=(--env SUGAR_BINARY_PUBLISH=0)
  docker_args+=("$image")
  if [[ -n "${SUGAR_BX_MANAGED_PRECONDITION_PLAN:-}" ]]; then
    docker_args+=(python /workspace/sugar/tools/sugar-build/preflight.py run
      --plan-json "$SUGAR_BX_MANAGED_PRECONDITION_PLAN"
      --artifact-root /opt/sugar --)
  fi
  docker_args+=("$@")
  for arg in "${docker_args[@]}"; do command+=" $(sugar_bx_quote "$arg")"; done
  sugar_bx_ssh "exec${command}"
}

sugar_bx_is_foreign() { [[ "$(uname -s 2>/dev/null)" != Linux ]] && [[ "$(file -b "$1" 2>/dev/null || true)" == *ELF* ]]; }
sugar_bx_sync_back() {
  local remote="$1" local_path="$2" staging payload artifact prior
  local remote_base transfer_status deposit_status restore_status
  if [[ "${SUGAR_BX_LOCAL:-0}" == 1 && "$remote" == "$local_path" ]]; then return 0; fi
  while [[ "$local_path" != / && "$local_path" == */ ]]; do local_path="${local_path%/}"; done
  mkdir -p "$(dirname "$local_path")"
  staging="$(mktemp -d "${local_path}.sugar-bx-sync.XXXXXX")" || return $?
  payload="$staging/payload"
  local src="$SUGAR_BX_HOST:$remote"
  [[ "${SUGAR_BX_LOCAL:-0}" == 1 ]] && src="$remote"
  if "$SUGAR_BX_RSYNC" -az "$src" "$payload"; then
    :
  else
    transfer_status=$?
    rm -rf "$staging"
    return "$transfer_status"
  fi
  artifact="$payload"
  if [[ "$remote" != */ && -d "$payload" ]]; then
    remote_base="${remote##*/}"
    [[ ! -d "$payload/$remote_base" ]] || artifact="$payload/$remote_base"
  fi
  if sugar_bx_is_foreign "$artifact"; then
    echo "sugarbin: refusing to deposit foreign-platform binary: crime=foreign-platform-binary owner=bin/lib/sugar-bx.sh path=$local_path replacement=run the binary on $SUGAR_BX_HOST or rebuild locally" >&2
    rm -rf "$staging"; [[ -e "$local_path" ]] && sugar_bx_is_foreign "$local_path" && rm -f "$local_path"; return 0
  fi
  prior=""
  if [[ -e "$local_path" || -L "$local_path" ]]; then
    prior="$staging/prior"
    if mv "$local_path" "$prior"; then
      :
    else
      deposit_status=$?
      rm -rf "$staging"
      return "$deposit_status"
    fi
  fi
  if mv "$artifact" "$local_path"; then
    rm -rf "$staging"
    return 0
  else
    deposit_status=$?
    if [[ -z "$prior" ]]; then
      rm -rf "$staging"
      return "$deposit_status"
    fi
    if mv "$prior" "$local_path"; then
      rm -rf "$staging"
      return "$deposit_status"
    else
      restore_status=$?
      echo "sugarbin: crime=sync-back-prior-restore-failed local=$local_path staged_prior=$prior deposit_status=$deposit_status restore_status=$restore_status replacement=restore the byte-preserved prior from staged_prior; do not treat LOCAL existence as evidence" >&2
      return "$restore_status"
    fi
  fi
}
sugar_bx_cleanup() { sugar_bx_ssh "rm -rf $(sugar_bx_quote "$SUGAR_BX_ROOT")"; }
sugar_bx_finish() { local status="$1"; if [[ "$SUGAR_BX_CLEAN" == always || ( "$SUGAR_BX_CLEAN" == success && "$status" == 0 ) ]]; then sugar_bx_cleanup || true; fi; return "$status"; }
