#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
bootstrap="$repo_root/scripts/bootstrap-venv-py312.sh"
authority=/usr/local/opt/python@3.12/bin/python3.12

[[ -x "$bootstrap" ]] || { echo "missing executable $bootstrap" >&2; exit 1; }
[[ -x "$authority" ]]
[[ "$($authority -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')" == 3.12.13 ]]

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/state"

cat >"$tmp/fake-base" <<'FAKE_BASE'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == -c ]]; then printf '3.12.13\n'; exit 0; fi
if [[ "${1:-}" == -m && "${2:-}" == venv ]]; then
  mkdir -p "$3/bin"
  cp "$FAKE_VENV" "$3/bin/python"
  chmod +x "$3/bin/python"
  exit 0
fi
exit 97
FAKE_BASE
chmod +x "$tmp/fake-base"

cat >"$tmp/fake-venv" <<'FAKE_VENV'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_STATE/commands"
if [[ "${1:-}" == -m && "${2:-}" == pip ]]; then
  saw_numpy=0
  saw_pandas=0
  for arg in "$@"; do
    [[ "$arg" != numpy==2.5.1 ]] || saw_numpy=1
    [[ "$arg" != pandas==3.0.3 ]] || saw_pandas=1
  done
  if [[ "$saw_numpy" == 1 && "$saw_pandas" == 1 ]]; then
    printf '2.5.1\n' >"$FAKE_STATE/numpy"
    printf '3.0.3\n' >"$FAKE_STATE/pandas"
  fi
  exit 0
fi
if [[ "${1:-}" == - ]]; then
  [[ "$(cat "$FAKE_STATE/numpy")" == 2.5.1 ]]
  [[ "$(cat "$FAKE_STATE/pandas")" == 3.0.3 ]]
  printf 'PINS_OK\n'
  exit 0
fi
exit 98
FAKE_VENV
chmod +x "$tmp/fake-venv"

FAKE_STATE="$tmp/state" FAKE_VENV="$tmp/fake-venv" \
  PYTHON312="$tmp/fake-base" VENV_DIR="$tmp/venv" \
  bash "$bootstrap" >"$tmp/truthful.out"
grep -Fq PINS_OK "$tmp/truthful.out"
grep -Fq 'numpy==2.5.1 pandas==3.0.3' "$tmp/state/commands"

rc=0
PYTHON312=/usr/local/bin/python3 VENV_DIR="$tmp/lying-venv" \
  bash "$bootstrap" >"$tmp/lying.out" 2>"$tmp/lying.err" || rc=$?
[[ "$rc" -eq 2 ]]
grep -Fq 'required exact CPython 3.12.13; observed 3.14.4 at /usr/local/bin/python3' "$tmp/lying.err"
[[ ! -e "$tmp/lying-venv" ]]

echo "PASS: exact CPython 3.12.13 venv bootstrap"
