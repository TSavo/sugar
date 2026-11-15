#!/usr/bin/env bash
# Zero-setup environment for .github/workflows/main-scorecard.yml.
#
# WHY THIS EXISTS
#
# Every scorecard job used to rebuild the Python test environment: one job
# built a wheelhouse, uploaded it, and every other job downloaded it and
# installed a fresh venv. That is minutes of identical work per run. This
# script keeps ONE persistent venv per key on the runner host, in the cache
# directory every runner already shares (the sugarbin binary cache), and only
# builds it when the key is new:
#
#   key = interpreter (version + path) + the three dependency-authority
#         pyproject.toml files + this script.
#
# The venv holds third-party wheels only, read-only (same law as
# .github/actions/python-test-environment); first-party packages resolve from
# the checkout through PYTHONPATH. pandas comes from sugar-lift-py-tests[test]
# (pinned 3.0.3), so it is installed once per pin with the venv.
#
# It also makes sure `gh` is on PATH (the scorecard posts with it): the
# runner's own gh when present, else a pinned release cached under the same
# shared directory.
#
# Exports (GITHUB_ENV / GITHUB_PATH): SCORECARD_CACHE, SCORECARD_STORE,
# SCORECARD_RUNS, PYTHONPATH, SUGAR_CHECKOUT_PYTHONPATH,
# PYTHONDONTWRITEBYTECODE, and the venv's bin directory on PATH.
set -euo pipefail

t0=$(date +%s)
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cache="${SCORECARD_CACHE:-${SUGAR_BINARY_CACHE_DIR:-$HOME/.cache/sugar/binaries}/.scorecard}"
mkdir -p "$cache/venv" "$cache/store" "$cache/runs" "$cache/tools"

python_bin="$(command -v python)"
interp="$("$python_bin" -c 'import os, sys; print(sys.version.split()[0], os.path.realpath(sys.executable))')"
key="$(
  {
    printf '%s\n' "$interp"
    cat "$repo/implementations/python/sugar-lift-py-tests/pyproject.toml" \
        "$repo/implementations/python/sugar-lift-python-source/pyproject.toml" \
        "$repo/implementations/python/sugar-source-tree/pyproject.toml" \
        "${BASH_SOURCE[0]}"
  } | sha256sum | cut -c1-24
)"
venv="$cache/venv/$key"

build_venv() {
  local lock="$venv.lock" waited=0
  until mkdir "$lock" 2>/dev/null; do
    if [ -f "$venv/.complete" ]; then return 0; fi
    # A lock older than 30 minutes belongs to a dead build.
    if [ -n "$(find "$lock" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then rm -rf "$lock"; continue; fi
    sleep 2; waited=$((waited + 2))
    [ $((waited % 30)) -eq 0 ] && echo "scorecard env: waiting for another job to build $venv (${waited}s)"
  done
  trap 'rm -rf "$lock"' RETURN
  if [ -f "$venv/.complete" ]; then return 0; fi
  echo "scorecard env: building venv $key (first run for this key)"
  if [ -d "$venv" ]; then chmod -R u+w "$venv"; rm -rf "$venv"; fi
  local wheels="$venv.wheelhouse"
  rm -rf "$wheels"; mkdir -p "$wheels"
  "$python_bin" -m pip wheel --quiet --wheel-dir "$wheels" \
    "$repo/implementations/python/sugar-lift-py-tests[test]" \
    "$repo/implementations/python/sugar-lift-python-source" \
    "$repo/implementations/python/sugar-source-tree"
  rm -f "$wheels"/sugar_lift_*.whl "$wheels"/sugar_source_tree-*.whl
  "$python_bin" -m venv "$venv"
  "$venv/bin/python" -m pip install --quiet --upgrade pip wheel
  "$venv/bin/python" -m pip install --quiet --no-index "$wheels"/*.whl
  "$venv/bin/python" "$repo/tools/refuse_first_party_venv_contamination.py" \
    sugar-lift-py-tests sugar-lift-python-source sugar-source-tree
  "$venv/bin/python" -m pip freeze --all > "$venv/resolved-distributions.txt"
  rm -rf "$wheels"
  chmod -R a-w "$venv/lib"
  touch "$venv/.complete"
}

if [ -f "$venv/.complete" ]; then
  echo "scorecard env: venv hit $key"
else
  build_venv
fi

checkout_pythonpath="$(python3 "$repo/tools/managed_checkout_pythonpath.py" --repo-root "$repo")"

# gh: the scorecard posts its row with it.
ensure_gh() {
  if command -v gh >/dev/null 2>&1; then return 0; fi
  local version="2.63.2" dir="$cache/tools/gh-2.63.2"
  if [ ! -x "$dir/bin/gh" ]; then
    local tmp tarball="gh_${version}_linux_amd64.tar.gz"
    tmp="$(mktemp -d "$cache/tools/.gh.XXXXXX")"
    local base="https://github.com/cli/cli/releases/download/v${version}"
    curl -fsSL -o "$tmp/$tarball" "$base/$tarball"
    curl -fsSL -o "$tmp/checksums.txt" "$base/gh_${version}_checksums.txt"
    (cd "$tmp" && grep " $tarball\$" checksums.txt | sha256sum -c -)
    tar -xzf "$tmp/$tarball" -C "$tmp"
    rm -rf "$dir"; mv "$tmp/gh_${version}_linux_amd64" "$dir"; rm -rf "$tmp"
  fi
  echo "$dir/bin" >> "$GITHUB_PATH"
  echo "scorecard env: gh from $dir"
}
ensure_gh

{
  echo "SCORECARD_CACHE=$cache"
  echo "SCORECARD_STORE=$cache/store"
  echo "SCORECARD_RUNS=$cache/runs/${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
  echo "PYTHONPATH=$checkout_pythonpath"
  echo "SUGAR_CHECKOUT_PYTHONPATH=$checkout_pythonpath"
  echo "PYTHONDONTWRITEBYTECODE=1"
} >> "$GITHUB_ENV"
echo "$venv/bin" >> "$GITHUB_PATH"
echo "scorecard env: ready in $(( $(date +%s) - t0 ))s (venv $venv)"
