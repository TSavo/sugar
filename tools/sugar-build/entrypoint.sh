#!/usr/bin/env bash
set -euo pipefail

# A bind mount can start successfully and still be empty or point at the
# wrong tree: WSL2 hosts silently mount an empty directory when a plain
# Linux-style path is bound instead of the UNC form the Docker Desktop
# engine (running in its own WSL distro) can actually resolve. That failure
# mode produces plausible-looking output with no error, so prove the mounted
# workspace is the one the caller intended before anything else -- including
# the toolchain contract below -- runs.
if [[ -n "${SUGAR_BX_MOUNT_PROOF:-}" ]]; then
  proof_file="${SUGAR_BX_MOUNT_PROOF_FILE:-/workspace/sugar/.bcargo-mount-proof}"
  actual="$(cat "$proof_file" 2>/dev/null || true)"
  if [[ "$actual" != "$SUGAR_BX_MOUNT_PROOF" ]]; then
    echo "sugarbin: crime=empty-or-stale-bind-mount workspace=$proof_file expected=$SUGAR_BX_MOUNT_PROOF actual=${actual:-<missing>} replacement=verify the bind mount source resolves inside the container -- WSL2 hosts need the UNC \\\\wsl.localhost\\<distro>\\... form, not a plain Linux path, and the workspace must be synced immediately before this run" >&2
    exit 70
  fi
fi

contract_mismatch() {
  echo "managed environment contract mismatch: $1" >&2
  exit 70
}

[[ "$(rustc --version | awk '{print $2}')" == 1.96.0 ]] || contract_mismatch rustc
[[ "$(cargo --version | awk '{print $2}')" == 1.96.0 ]] || contract_mismatch cargo
[[ "$(python --version | awk '{print $2}')" == 3.12.13 ]] || contract_mismatch python
[[ "$(black --version | awk 'NR == 1 {print $2}')" == 26.5.1 ]] || contract_mismatch black
[[ "$(python -m pyright --version | awk '$1 == "pyright" {print $2}')" == 1.1.411 ]] || contract_mismatch pyright
[[ -x /opt/pyright/nodeenv/bin/node ]] || contract_mismatch pyright-node
[[ "$(python -c 'from pyright.node import version; print("node " + ".".join(map(str, version("node"))))')" == "$(cat /opt/pyright/node-version)" ]] \
  || contract_mismatch pyright-node
[[ "$(b3sum --version | awk '{print $2}')" == 1.8.1 ]] || contract_mismatch b3sum

if [[ -f /opt/sugar/required-artifacts.json ]]; then
  artifact_count="$(python - /opt/sugar/required-artifacts.json <<'PY' || {
import hashlib, json, pathlib, sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text())
for item in manifest["artifacts"]:
    path = pathlib.Path("/opt/sugar/bin") / item["name"]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise SystemExit(1)
print(len(manifest["artifacts"]))
PY
    echo "artifact checksum mismatch" >&2
    exit 70
  })"
  if [[ "$artifact_count" -gt 0 ]]; then
    export SUGAR_BINARY_DIR=/opt/sugar/bin
    if [[ -x /opt/sugar/bin/sugar ]]; then
      export SUGAR_BIN=/opt/sugar/bin/sugar
    else
      unset SUGAR_BIN
    fi
    export PATH=/opt/sugar/bin:$PATH
  fi
fi

exec "$@"
