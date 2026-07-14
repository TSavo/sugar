#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_docker_core_offline.sh REPO_ROOT}"
image="${SUGAR_CORE_IMAGE:-}"
if [[ -z "$image" ]]; then
  image="$(python3 "$repo/tools/sugar-build/contract.py" resolve-environment docker:core \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["image"])')"
  docker pull "$image" >/dev/null
elif [[ "${SUGAR_CORE_PULL:-0}" == 1 ]]; then
  docker pull "$image" >/dev/null
fi
volume="sugar-core-offline-$RANDOM-$$"
docker volume create "$volume" >/dev/null
trap 'docker volume rm -f "$volume" >/dev/null' EXIT

docker run --rm --network none \
  --mount "type=volume,src=$volume,dst=/receipt" \
  "$image" sh -lc \
  'cat /opt/pyright/node-version; python -m pyright --version; printf "child\n" >>/receipt/children'

children="$(docker run --rm --entrypoint cat \
  --mount "type=volume,src=$volume,dst=/receipt" "$image" /receipt/children)"
[[ "$children" == child ]] || {
  echo "offline core child did not execute exactly once" >&2
  exit 1
}
