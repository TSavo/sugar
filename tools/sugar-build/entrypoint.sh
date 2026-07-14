#!/usr/bin/env bash
set -euo pipefail

contract_mismatch() {
  echo "managed environment contract mismatch: $1" >&2
  exit 70
}

[[ "$(rustc --version | awk '{print $2}')" == 1.96.0 ]] || contract_mismatch rustc
[[ "$(cargo --version | awk '{print $2}')" == 1.96.0 ]] || contract_mismatch cargo
[[ "$(python --version | awk '{print $2}')" == 3.12.13 ]] || contract_mismatch python
[[ "$(black --version | awk 'NR == 1 {print $2}')" == 26.5.1 ]] || contract_mismatch black
[[ "$(python -m pyright --version | awk '$1 == "pyright" {print $2}')" == 1.1.411 ]] || contract_mismatch pyright
[[ "$(b3sum --version | awk '{print $2}')" == 1.8.1 ]] || contract_mismatch b3sum

if [[ -f /opt/sugar/required-artifacts.json ]]; then
  python - /opt/sugar/required-artifacts.json <<'PY' || {
import hashlib, json, pathlib, sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text())
for item in manifest["artifacts"]:
    path = pathlib.Path("/opt/sugar/bin") / item["name"]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise SystemExit(1)
PY
    echo "artifact checksum mismatch" >&2
    exit 70
  }
  export SUGAR_BIN=/opt/sugar/bin/sugar
  export SUGAR_BINARY_DIR=/opt/sugar/bin
  export PATH=/opt/sugar/bin:$PATH
fi

exec "$@"
