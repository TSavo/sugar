#!/usr/bin/env bash

# Shared battleaxe synchronization and ambient execution backend.
exclude_args=(
  --include='/examples/serde-json-showcase/bad/.sugar/runs/***'
  --include='/examples/serde-json-showcase/good/.sugar/runs/***'
  --exclude='target/' --exclude='.git/' --exclude='.jj/' --exclude='.worktrees/'
  --exclude='.claude/' --exclude='.ruff_cache/' --exclude='.venv-test-rust/'
  --exclude='.understand-anything/' --exclude='node_modules/' --exclude='bazel-bin'
  --exclude='bazel-out' --exclude='bazel-sugar' --exclude='bazel-testlogs'
  --exclude='sugar-warnings/' --exclude='sugar-worktrees/'
  --exclude='.sugar/runs/' --exclude='.sugar/witnesses/'
)

sync_paths=(
  Cargo.toml
  Cargo.lock
  Makefile
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
sugar_bx_ssh() { "$SUGAR_BX_SSH" -o BatchMode=yes "$SUGAR_BX_HOST" "$@"; }

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
  SUGAR_BX_SSH="${BCARGO_SSH:-ssh}"; SUGAR_BX_RSYNC="${BCARGO_RSYNC:-rsync}"
  SUGAR_BX_CLEAN="${BCARGO_CLEAN_REMOTE_ROOT:-never}"
  case "$SUGAR_BX_CLEAN" in ""|0|false|no|never) SUGAR_BX_CLEAN=never;; 1|true|yes|success) SUGAR_BX_CLEAN=success;; always);; *) echo "sugarbin: BCARGO_CLEAN_REMOTE_ROOT must be never, success, or always" >&2; return 2;; esac
  if [[ "$SUGAR_BX_CLEAN" != never && "$SUGAR_BX_ROOT" != /home/tsavo/remote/sugar-bcargo-* && "${BCARGO_CLEAN_REMOTE_ROOT_UNSAFE:-0}" != 1 ]]; then
    echo "sugarbin: refusing to clean unsafe remote root: $SUGAR_BX_ROOT" >&2
    echo "sugarbin: set BCARGO_CLEAN_REMOTE_ROOT_UNSAFE=1 only for an explicitly disposable root" >&2
    return 2
  fi
  local days="${BCARGO_REAP_DAYS:-2}"
  if [[ "$days" != 0 ]]; then
    sugar_bx_ssh "mkdir -p $(sugar_bx_quote "$SUGAR_BX_ROOT") && touch $(sugar_bx_quote "$SUGAR_BX_ROOT") && nohup find /home/tsavo/remote -mindepth 1 -maxdepth 1 -name 'sugar-bcargo-*' ! -path $(sugar_bx_quote "$SUGAR_BX_ROOT") -mtime +$(sugar_bx_quote "$days") -exec rm -rf {} + >/dev/null 2>&1 &" || true
  fi
}

sugar_bx_sync_workspace() {
  local existing=() rel manifest
  for rel in "${sync_paths[@]}"; do [[ -e "$SUGAR_BX_REPO_ROOT/$rel" ]] && existing+=("$rel"); done
  sugar_bx_ssh "rm -rf $(sugar_bx_quote "$SUGAR_BX_REPO/menagerie") && mkdir -p $(sugar_bx_quote "$SUGAR_BX_REPO")"
  (cd "$SUGAR_BX_REPO_ROOT" && "$SUGAR_BX_RSYNC" -azR --delete "${exclude_args[@]}" "${existing[@]}" "$SUGAR_BX_HOST:$SUGAR_BX_REPO/")
  manifest="$(mktemp)"
  if git -C "$SUGAR_BX_REPO_ROOT" ls-files -z >"$manifest" 2>/dev/null; then
    "$SUGAR_BX_RSYNC" -az "$manifest" "$SUGAR_BX_HOST:$SUGAR_BX_REPO/.bcargo-tracked-manifest"
  fi
  rm -f "$manifest"
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
  local source="$1"
  sugar_bx_ssh "if command -v wslpath >/dev/null 2>&1; then wslpath -w $(sugar_bx_quote "$source"); else printf '%s\\n' $(sugar_bx_quote "$source"); fi" | tr -d '\r'
}

sugar_bx_run_docker() {
  local image="$1"; shift
  local remote_cwd="/workspace/sugar"
  [[ -n "$SUGAR_BX_REL_CWD" ]] && remote_cwd="$remote_cwd/$SUGAR_BX_REL_CWD"
  local workspace_source artifacts_source manifest_source
  workspace_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_REPO")" || return $?
  artifacts_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_ROOT/artifacts")" || return $?
  manifest_source="$(sugar_bx_docker_bind_source "$SUGAR_BX_ROOT/required-artifacts.json")" || return $?
  local -a docker_args=(docker run --rm
    --workdir "$remote_cwd"
    --env SUGAR_BIN=/opt/sugar/bin/sugar
    --env SUGAR_BINARY_DIR=/opt/sugar/bin
    --env PATH=/opt/sugar/bin:/opt/java/bin:/root/.cargo/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
    --mount "type=bind,src=$workspace_source,dst=/workspace/sugar"
    --mount "type=bind,src=$artifacts_source,dst=/opt/sugar/bin,readonly"
    --mount "type=bind,src=$manifest_source,dst=/opt/sugar/required-artifacts.json,readonly")
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
  mkdir -p "$(dirname "$local_path")"; tmp="$(mktemp "${local_path}.sugar-bx-sync.XXXXXX")"
  "$SUGAR_BX_RSYNC" -az "$SUGAR_BX_HOST:$remote" "$tmp"
  if sugar_bx_is_foreign "$tmp"; then
    echo "sugarbin: refusing to deposit foreign-platform binary: crime=foreign-platform-binary owner=bin/lib/sugar-bx.sh path=$local_path replacement=run the binary on $SUGAR_BX_HOST or rebuild locally" >&2
    rm -f "$tmp"; [[ -e "$local_path" ]] && sugar_bx_is_foreign "$local_path" && rm -f "$local_path"; return 0
  fi
  mv -f "$tmp" "$local_path"
}
sugar_bx_cleanup() { sugar_bx_ssh "rm -rf $(sugar_bx_quote "$SUGAR_BX_ROOT")"; }
sugar_bx_finish() { local status="$1"; if [[ "$SUGAR_BX_CLEAN" == always || ( "$SUGAR_BX_CLEAN" == success && "$status" == 0 ) ]]; then sugar_bx_cleanup || true; fi; return "$status"; }
