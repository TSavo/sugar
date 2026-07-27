#!/usr/bin/env bash
# Authenticated local macOS inner loop: CPython 3.12.13 plus corpus pins.
#
# A venv inherits its creator. Bare `python3` is 3.14.4 on this Mac and cannot
# create authenticated demand-table testimony. The installed authority is:
#   /usr/local/opt/python@3.12/bin/python3.12
#
# Feature worktrees must run this helper from their own checkout (or reinstall
# its editable packages there), then re-pin NumPy and pandas as done below.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$repo_root"

die() {
  echo "bootstrap-venv-py312: $*" >&2
  exit 2
}

py312="${PYTHON312:-}"
if [[ -z "$py312" ]]; then
  for candidate in \
    /usr/local/opt/python@3.12/bin/python3.12 \
    /usr/local/bin/python3.12 \
    /opt/homebrew/bin/python3.12 \
    "$(command -v python3.12 2>/dev/null || true)"
  do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      py312="$candidate"
      break
    fi
  done
fi
[[ -n "$py312" && -x "$py312" ]] || die \
  "need exact CPython 3.12.13 at /usr/local/opt/python@3.12/bin/python3.12 or set PYTHON312"

version="$("$py312" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
[[ "$version" == 3.12.13 ]] || die \
  "required exact CPython 3.12.13; observed $version at $py312"

venv_dir="${VENV_DIR:-$repo_root/.venv-py312}"
echo "Creating $venv_dir from $py312 ($version)"
"$py312" -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install -U pip setuptools wheel

"$venv_dir/bin/python" -m pip install \
  -e "$repo_root/implementations/python/sugar-source-tree" \
  -e "$repo_root/implementations/python/sugar-lift-python-source" \
  -e "$repo_root/implementations/python/sugar-lift-py-tests[test]" \
  "pytest==9.1.1"

# This must follow the editable install: old worktree extras floated pandas to
# 3.0.5. Re-pin the authenticated corpus before verifying what was imported.
"$venv_dir/bin/python" -m pip install "numpy==2.5.1" "pandas==3.0.3"

"$venv_dir/bin/python" - <<'PY'
import pathlib
import sys

import numpy
import pandas

assert sys.version_info[:3] == (3, 12, 13), sys.version
assert numpy.__version__ == "2.5.1", numpy.__version__
assert pandas.__version__ == "3.0.3", pandas.__version__
purelib = (
    pathlib.Path(sys.prefix)
    / "lib"
    / f"python{sys.version_info[0]}.{sys.version_info[1]}"
    / "site-packages"
)
assert purelib in pathlib.Path(numpy.__file__).resolve().parents
assert purelib in pathlib.Path(pandas.__file__).resolve().parents
print("interpreter", sys.version.split()[0], sys.executable)
print("numpy", numpy.__version__)
print("pandas", pandas.__version__)
print("PINS_OK")
PY

echo "Use: $venv_dir/bin/python -m pytest ..."
