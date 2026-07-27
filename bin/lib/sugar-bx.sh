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

sugar_bx_run_ambient() {
  local remote_cwd="$SUGAR_BX_REPO" arg inner="" prefix="" name
  [[ -n "$SUGAR_BX_REL_CWD" ]] && remote_cwd="$SUGAR_BX_REPO/$SUGAR_BX_REL_CWD"
  if ((${#SUGAR_BX_PATH_PREFIXES[@]} != 0)); then
    for prefix in "${SUGAR_BX_PATH_PREFIXES[@]}"; do
      [[ -z "$inner" ]] && inner="$prefix" || inner="$inner:$prefix"
    done
  fi
  local cmd="cd $(sugar_bx_quote "$remote_cwd") && "
  [[ -n "$inner" ]] && cmd+="PATH=$(sugar_bx_quote "$inner"):\$PATH "
  if ((${#SUGAR_BX_ENV_NAMES[@]} != 0)); then
    for name in "${SUGAR_BX_ENV_NAMES[@]}"; do [[ ${!name+x} == x ]] && cmd+="$name=$(sugar_bx_quote "${!name}") "; done
  fi
  cmd+="exec"
  for arg in "$@"; do
    if [[ "$arg" == "$SUGAR_BX_REPO_ROOT" ]]; then arg="$SUGAR_BX_REPO"; elif [[ "$arg" == "$SUGAR_BX_REPO_ROOT"/* ]]; then arg="$SUGAR_BX_REPO/${arg#"$SUGAR_BX_REPO_ROOT"/}"; fi
    cmd+=" $(sugar_bx_quote "$arg")"
  done
  sugar_bx_ssh "bash -lc $(sugar_bx_quote "$cmd")"
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

sugar_bx_build_artifacts_docker() {
  local image="$1" needs="$2" profile="$3"
  local image_digest="${image##*@sha256:}"
  local managed_target="${BCARGO_REMOTE_MANAGED_TARGET:-/home/tsavo/.cache/sugar/managed-targets/$image_digest}"
  sugar_bx_ssh "rm -rf $(sugar_bx_quote "$SUGAR_BX_ROOT/artifacts") && mkdir -p $(sugar_bx_quote "$SUGAR_BX_ROOT/artifacts") $(sugar_bx_quote "$SUGAR_BX_BINARY_CACHE") $(sugar_bx_quote "$managed_target")" || return $?
  local workspace_source artifacts_source cache_source target_source
  workspace_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_REPO")" || return $?
  artifacts_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_ROOT/artifacts")" || return $?
  cache_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_BINARY_CACHE")" || return $?
  target_source="$(sugar_bx_docker_bind_source "$managed_target")" || return $?
  local build_script
  build_script="set -euo pipefail; cd /workspace/sugar; printf '{\"artifacts\":[' >/out/required-artifacts.json; first=1; needs=$(sugar_bx_quote "$needs"); IFS=,; for b in \$needs; do [ -n \"\$b\" ] || continue; r=\$(env -u SUGAR_BIN -u SUGAR_BINARY_DIR SUGAR_BINARY_PUBLISH=0 bin/sugarbin --profile $(sugar_bx_quote "$profile") --platform linux-x86_64 --bin \"\$b\"); cp \"\$r\" /out/\"\$b\"; cp \"\$r.sugarbin.json\" /out/\"\$b.sugarbin.json\"; sum=\$(sha256sum /out/\"\$b\" | cut -d' ' -f1); [ \$first = 1 ] || printf ',' >>/out/required-artifacts.json; first=0; printf '{\"name\":\"%s\",\"sha256\":\"%s\"}' \"\$b\" \"\$sum\" >>/out/required-artifacts.json; done; printf ']}' >>/out/required-artifacts.json"
  local -a docker_args=(docker run --rm
    --workdir /workspace/sugar
    --env SUGAR_BINARY_PUBLISH=0
    --env CARGO_TARGET_DIR=/managed-target
    --env SUGAR_BINARY_TARGET_ROOT=/managed-target
    --env "SUGAR_BX_MOUNT_PROOF=$SUGAR_BX_MOUNT_PROOF"
    --mount "type=bind,src=$workspace_source,dst=/workspace/sugar"
    --mount "type=bind,src=$artifacts_source,dst=/out"
    --mount "type=bind,src=$cache_source,dst=/root/.cache/sugar/binaries"
    --mount "type=bind,src=$target_source,dst=/managed-target"
  )
  local name
  for name in ${SUGAR_BX_ENV_NAMES[@]+"${SUGAR_BX_ENV_NAMES[@]}"}; do
    [[ "$name" != SUGAR_BINARY_ALLOW_BUILD || ${!name+x} != x ]] \
      || docker_args+=(--env "$name=${!name}")
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
  local workspace_source artifacts_source manifest_source
  workspace_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_REPO")" || return $?
  local -a docker_args=(docker run --rm
    --workdir "$remote_cwd"
    --env PATH=/opt/sugar/bin:/opt/java/bin:/root/.cargo/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
    --env "SUGAR_BX_MOUNT_PROOF=$SUGAR_BX_MOUNT_PROOF"
    --mount "type=bind,src=$workspace_source,dst=/workspace/sugar")
  [[ "$network" != none ]] || docker_args+=(--network none)
  if [[ "$has_artifacts" == 1 ]]; then
    artifacts_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_ROOT/artifacts")" || return $?
    manifest_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_ROOT/artifacts/required-artifacts.json")" || return $?
    docker_args+=(--mount "type=bind,src=$artifacts_source,dst=/opt/sugar/bin,readonly")
    docker_args+=(--mount "type=bind,src=$manifest_source,dst=/opt/sugar/required-artifacts.json,readonly")
  fi
  local name arg command=""
  for name in ${SUGAR_BX_ENV_NAMES[@]+"${SUGAR_BX_ENV_NAMES[@]}"}; do
    [[ ${!name+x} == x ]] && docker_args+=(--env "$name=${!name}")
  done
  docker_args+=("$image" "$@")
  for arg in "${docker_args[@]}"; do command+=" $(sugar_bx_quote "$arg")"; done
  sugar_bx_ssh "exec${command}"
}

sugar_bx_is_foreign() { [[ "$(uname -s 2>/dev/null)" != Linux ]] && [[ "$(file -b "$1" 2>/dev/null || true)" == *ELF* ]]; }
sugar_bx_sync_back() {
  local remote="$1" local_path="$2" tmp
  if [[ "${SUGAR_BX_LOCAL:-0}" == 1 && "$remote" == "$local_path" ]]; then return 0; fi
  mkdir -p "$(dirname "$local_path")"; tmp="$(mktemp "${local_path}.sugar-bx-sync.XXXXXX")"
  local src="$SUGAR_BX_HOST:$remote"
  [[ "${SUGAR_BX_LOCAL:-0}" == 1 ]] && src="$remote"
  "$SUGAR_BX_RSYNC" -az "$src" "$tmp"
  if sugar_bx_is_foreign "$tmp"; then
    echo "sugarbin: refusing to deposit foreign-platform binary: crime=foreign-platform-binary owner=bin/lib/sugar-bx.sh path=$local_path replacement=run the binary on $SUGAR_BX_HOST or rebuild locally" >&2
    rm -f "$tmp"; [[ -e "$local_path" ]] && sugar_bx_is_foreign "$local_path" && rm -f "$local_path"; return 0
  fi
  mv -f "$tmp" "$local_path"
}
sugar_bx_cleanup() { sugar_bx_ssh "rm -rf $(sugar_bx_quote "$SUGAR_BX_ROOT")"; }
sugar_bx_finish() { local status="$1"; if [[ "$SUGAR_BX_CLEAN" == always || ( "$SUGAR_BX_CLEAN" == success && "$status" == 0 ) ]]; then sugar_bx_cleanup || true; fi; return "$status"; }
