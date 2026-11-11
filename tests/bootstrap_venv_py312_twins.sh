#!/usr/bin/env bash
# Twins for scripts/bootstrap-venv-py312.sh — bankable on every worktree.
#
# Law: a venv only inherits the executable it was created from. A directory
# named .venv-py312 built from bare `python3` (3.14.4) is still 3.14.4.
# Exact CPython 3.12.13 is required; 3.12.x is not enough. Corpus pins are
# re-applied AFTER editable install (pandas floated 3.0.5 otherwise).
set -euo pipefail

repo="${1:?usage: bootstrap_venv_py312_twins.sh REPO_ROOT}"
cd "$repo"

fail() {
  echo "bootstrap_venv_py312_twins: $*" >&2
  exit 1
}

script="$repo/scripts/bootstrap-venv-py312.sh"
[[ -f "$script" ]] || fail "scripts/bootstrap-venv-py312.sh is not in the tree"
[[ -x "$script" ]] || fail "scripts/bootstrap-venv-py312.sh is not executable"

# -- script text teeth -------------------------------------------------------

rg -q '3\.12\.13' "$script" || fail "bootstrap does not require exact 3.12.13"
rg -q 'numpy==2\.5\.1' "$script" || fail "bootstrap missing numpy==2.5.1 pin"
rg -q 'pandas==3\.0\.3' "$script" || fail "bootstrap missing pandas==3.0.3 pin"
rg -q 'purelib|sysconfig' "$script" || fail "bootstrap does not verify load path / purelib"
rg -q 'BOOTSTRAP_CHECK_ONLY' "$script" || fail "bootstrap missing BOOTSTRAP_CHECK_ONLY gate"

editable_line="$(rg -n "sugar-lift-py-tests\[test\]" "$script" | head -1 | cut -d: -f1)"
numpy_line="$(rg -n 'numpy==2\.5\.1' "$script" | head -1 | cut -d: -f1)"
[[ -n "$editable_line" && -n "$numpy_line" ]] || fail "could not locate editable/pin order"
[[ "$numpy_line" -gt "$editable_line" ]] || fail "corpus pins must run AFTER editable [test] install"

optional_pins="$repo/scripts/corpus-env-optional.txt"
optional_verifier="$repo/scripts/verify_corpus_env_optional.py"
[[ -f "$optional_pins" ]] || fail "scripts/corpus-env-optional.txt is not in the tree"
[[ -f "$optional_verifier" ]] || fail "scripts/verify_corpus_env_optional.py is not in the tree"
rg -q -- '-r "\$optional_pins"' "$script" || fail "bootstrap does not pip-install the optional set"
rg -q '"\$optional_verifier" "\$optional_pins"' "$script" || fail "verify_pins does not assert the optional set"
for pin in 'matplotlib==3.11.2' 'tables==3.11.1' 'ipython==9.18.1' 'fsspec==2026.9.0' 'openpyxl==3.1.5'; do
  rg -qx -F "$pin" "$optional_pins" || fail "optional set missing $pin"
done
! rg -qi '^(numba|numpy|pandas|pyarrow)==' "$optional_pins" \
  || fail "optional set must not re-pin numpy/pandas/pyarrow or add numba"
if rg -v '^\s*(#|$)' "$optional_pins" | rg -qv '^[A-Za-z0-9._-]+==[^=\s]+$'; then
  fail "optional set has a line that is not an exact name==version pin"
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/bootstrap-venv-py312.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

# -- lying twin: non-exact 3.12.x (3.12.0) ------------------------------------

fake_3120="$tmp/fake-python-3.12.0"
cat >"$fake_3120" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "-c" ]]; then
  printf '%s\n' "3.12.0"
  exit 0
fi
echo "fake-python-3.12.0: unexpected: $*" >&2
exit 1
EOF
chmod +x "$fake_3120"

set +e
PYTHON312="$fake_3120" BOOTSTRAP_CHECK_ONLY=1 bash "$script" \
  >"$tmp/out-3120" 2>"$tmp/err-3120"
status_3120=$?
set -e
[[ "$status_3120" -ne 0 ]] || fail "bootstrap accepted CPython 3.12.0"
rg -q '3\.12\.13' "$tmp/err-3120" || fail "3.12.0 refusal did not name required 3.12.13"
rg -q '3\.12\.0' "$tmp/err-3120" || fail "3.12.0 refusal did not name observed 3.12.0"

# -- lying twin: bare python3 when it is not 3.12.13 -------------------------

bare=""
for candidate in /usr/local/bin/python3 /opt/homebrew/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    bare="$candidate"
    break
  fi
done
if [[ -n "$bare" ]]; then
  bare_ver="$("$bare" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
  if [[ "$bare_ver" != "3.12.13" ]]; then
    set +e
    PYTHON312="$bare" BOOTSTRAP_CHECK_ONLY=1 VENV_DIR="$tmp/must-not-exist" bash "$script" \
      >"$tmp/out-bare" 2>"$tmp/err-bare"
    status_bare=$?
    set -e
    [[ "$status_bare" -ne 0 ]] || fail "bootstrap accepted bare python3 ($bare_ver)"
    rg -q '3\.12\.13' "$tmp/err-bare" || fail "bare-python3 refusal did not name required 3.12.13"
    rg -Fq "$bare_ver" "$tmp/err-bare" || fail "bare-python3 refusal did not name observed $bare_ver"
    [[ ! -e "$tmp/must-not-exist" ]] || fail "bootstrap created a venv after refusing the runtime"
  fi
fi

# -- simulated full bootstrap: editable float then post-editable re-pin ------
# Proves the pin step runs after [test] and that PINS_OK requires the re-pin.

fake_base="$tmp/fake-python-3.12.13"
fake_state="$tmp/state"
mkdir -p "$fake_state"
fake_venv_python="$tmp/fake-venv-python"

cat >"$fake_base" <<'FAKE_BASE'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == -c ]]; then
  printf '3.12.13\n'
  exit 0
fi
if [[ "${1:-}" == -m && "${2:-}" == venv ]]; then
  venv_dir="${3:?missing venv directory}"
  mkdir -p "$venv_dir/bin"
  cp "$FAKE_VENV_PYTHON" "$venv_dir/bin/python"
  chmod +x "$venv_dir/bin/python"
  exit 0
fi
echo "unexpected base interpreter arguments: $*" >&2
exit 97
FAKE_BASE
chmod +x "$fake_base"

cat >"$fake_venv_python" <<'FAKE_VENV'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_STATE/commands"
if [[ "${1:-}" == -m && "${2:-}" == pip ]]; then
  # Editable [test] install historically floated pandas to 3.0.5.
  case " $* " in
    *"sugar-lift-py-tests[test]"*) printf '3.0.5\n' >"$FAKE_STATE/pandas" ;;
  esac
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
  case " $* " in
    *" -r "*corpus-env-optional.txt*) : >"$FAKE_STATE/optional" ;;
  esac
  exit 0
fi
# Optional-set verifier: holds only once pip was handed the optional pin file.
if [[ "${1:-}" == *verify_corpus_env_optional.py ]]; then
  [[ -e "$FAKE_STATE/optional" ]] || {
    echo "optional set never installed" >&2
    exit 1
  }
  printf 'OPTIONAL_OK\n'
  exit 0
fi
# Post-install verification heredoc: stdin mode (`python -`).
if [[ "${1:-}" == - ]]; then
  [[ "$(cat "$FAKE_STATE/numpy")" == 2.5.1 ]] || {
    echo "post-editable pin missing: numpy not 2.5.1" >&2
    exit 1
  }
  [[ "$(cat "$FAKE_STATE/pandas")" == 3.0.3 ]] || {
    echo "post-editable pin missing: pandas still floated (not 3.0.3)" >&2
    exit 1
  }
  printf 'PINS_OK\n'
  exit 0
fi
echo "unexpected venv interpreter arguments: $*" >&2
exit 98
FAKE_VENV
chmod +x "$fake_venv_python"

truthful_out="$tmp/truthful.out"
FAKE_STATE="$fake_state" FAKE_VENV_PYTHON="$fake_venv_python" \
  PYTHON312="$fake_base" VENV_DIR="$tmp/venv" \
  bash "$script" >"$truthful_out"
rg -Fq PINS_OK "$truthful_out" || fail "simulated bootstrap did not reach PINS_OK"
rg -Fq 'numpy==2.5.1' "$fake_state/commands" || fail "simulated bootstrap never pip-installed numpy==2.5.1"
rg -Fq 'pandas==3.0.3' "$fake_state/commands" || fail "simulated bootstrap never pip-installed pandas==3.0.3"
rg -Fq OPTIONAL_OK "$truthful_out" || fail "simulated bootstrap did not assert the optional set"
rg -Fq 'corpus-env-optional.txt' "$fake_state/commands" || fail "simulated bootstrap never pip-installed the optional set"

# -- optional set: the real verifier over a synthetic site ---------------------
# One dist-info per pin (python -S: nothing else on the path). Truthful: all
# present. Lying: tables absent, or matplotlib at another version.

site="$tmp/site"
make_site() {
  rm -rf "$site"
  mkdir -p "$site"
  python3 - "$optional_pins" "$site" "$@" <<'PY'
import sys
from pathlib import Path

pins, site, *edits = sys.argv[1:]
drop = {e[1:] for e in edits if e.startswith("-")}
bump = dict(e[1:].split("==") for e in edits if e.startswith("~"))
for raw in Path(pins).read_text().splitlines():
    line = raw.split("#", 1)[0].strip()
    if not line:
        continue
    name, _, version = line.partition("==")
    if name in drop:
        continue
    version = bump.get(name, version)
    info = Path(site) / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
PY
}

make_site
PYTHONPATH="$site" python3 -S "$optional_verifier" "$optional_pins" >"$tmp/opt-ok" 2>"$tmp/opt-ok.err" \
  || fail "optional verifier refused a site holding every pin: $(cat "$tmp/opt-ok.err")"
rg -q 'OPTIONAL_OK 76 packages' "$tmp/opt-ok" || fail "truthful optional twin did not print OPTIONAL_OK"

make_site -tables
set +e
PYTHONPATH="$site" python3 -S "$optional_verifier" "$optional_pins" >/dev/null 2>"$tmp/opt-missing.err"
status_missing=$?
set -e
[[ "$status_missing" -ne 0 ]] || fail "optional verifier accepted a site without tables"
rg -Fq 'tables==3.11.1: not installed' "$tmp/opt-missing.err" || fail "missing-tables refusal did not name tables"

make_site ~matplotlib==3.10.0
set +e
PYTHONPATH="$site" python3 -S "$optional_verifier" "$optional_pins" >/dev/null 2>"$tmp/opt-drift.err"
status_drift=$?
set -e
[[ "$status_drift" -ne 0 ]] || fail "optional verifier accepted matplotlib 3.10.0"
rg -Fq 'matplotlib==3.11.2: observed 3.10.0' "$tmp/opt-drift.err" || fail "drift refusal did not name matplotlib"

# -- lying twin through the script: BOOTSTRAP_VERIFY_ONLY on a venv without tables
# The verify-only path must reject it and must not create, lock or install.

make_site -tables
lying_venv="$tmp/lying-venv"
mkdir -p "$lying_venv/bin"
cat >"$lying_venv/bin/python" <<EOF
#!/usr/bin/env bash
[[ "\${1:-}" == -c ]] && { printf '3.12.13\n'; exit 0; }
PYTHONPATH="$site" exec python3 -S "\$@"
EOF
chmod +x "$lying_venv/bin/python"
set +e
BOOTSTRAP_VERIFY_ONLY=1 VENV_DIR="$lying_venv" BOOTSTRAP_LOCK_DIR="$tmp/must-not-lock" \
  bash "$script" >"$tmp/out-lying" 2>"$tmp/err-lying"
status_lying=$?
set -e
[[ "$status_lying" -ne 0 ]] || fail "bootstrap verify-only accepted a venv without tables"
rg -Fq 'tables==3.11.1: not installed' "$tmp/err-lying" || fail "verify-only refusal did not name tables"
[[ ! -e "$tmp/must-not-lock" ]] || fail "verify-only took the bootstrap lock"

# -- truthful twin: real 3.12.13 when available --------------------------------

real_312=""
for candidate in \
  /usr/local/opt/python@3.12/bin/python3.12 \
  /usr/local/bin/python3.12 \
  /opt/homebrew/bin/python3.12 \
  "$(command -v python3.12 2>/dev/null || true)"
do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    cand_ver="$("$candidate" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
    if [[ "$cand_ver" == "3.12.13" ]]; then
      real_312="$candidate"
      break
    fi
  fi
done

if [[ -n "$real_312" ]]; then
  PYTHON312="$real_312" BOOTSTRAP_CHECK_ONLY=1 bash "$script" \
    >"$tmp/out-ok" 2>"$tmp/err-ok" \
    || fail "bootstrap check-only refused real CPython 3.12.13 at $real_312"
  rg -q 'check-only OK' "$tmp/out-ok" || fail "truthful twin did not print check-only OK"
else
  echo "bootstrap_venv_py312_twins: note: no local CPython 3.12.13; skipped real-executable twin"
fi

# -- runtime coordinate API (same required string as the shell gate) ----------

python3 - <<'PY' || fail "runtime coordinate twin failed"
from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path("implementations/python/sugar-lift-py-tests/src").resolve()),
)
from sugar_lift_py_tests.authenticated_pytest import (
    ExecutionEnvironmentMismatch,
    InterpreterIdentity,
    authenticate_interpreter_runtime,
    declared_interpreter_runtime,
)

assert declared_interpreter_runtime() == "cpython-3.12.13"
authenticate_interpreter_runtime(
    InterpreterIdentity("cpython", "3.12.13", Path("/declared"))
)
try:
    authenticate_interpreter_runtime(
        InterpreterIdentity("cpython", "3.14.4", Path("/bare-python3-venv"))
    )
except ExecutionEnvironmentMismatch as exc:
    text = str(exc)
    assert "cpython-3.12.13" in text and "cpython-3.14.4" in text, text
else:
    raise SystemExit("3.14.4 identity was not refused")
print("runtime-coordinate twin OK")
PY

echo "PASS: bootstrap-venv-py312 twins (exact 3.12.13, post-editable pins, optional set, bare-python3 refuse, runtime coordinate)"
