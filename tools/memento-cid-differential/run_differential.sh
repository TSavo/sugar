#!/usr/bin/env bash
# run_differential.sh -- differential runner for issue #5940.
#
# Parses the committed corpus/ tree through two Python backends -- the host
# interpreter and a docker image -- and diffs per-node-path mementos
# (span + segment-hash) emitted by memento_walker.py. Exits non-zero if any
# file diverges. Prints one summary line and, on divergence, full
# file:node_path detail from diff_mementos.py.
#
# Usage:
#   ./run_differential.sh <docker_image> [corpus_dir]
#
# Must be run from the repo root of the worktree that will be mounted into
# the container (docker file-mounts of individual files have been
# unreliable on battleaxe; this script mounts the WHOLE worktree).

set -euo pipefail

DOCKER_IMAGE="${1:?usage: run_differential.sh <docker_image> [corpus_dir]}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORPUS_DIR="${2:-$SCRIPT_DIR/corpus}"
OUT_DIR="$(mktemp -d)"

echo "== memento CID differential: host python3 vs $DOCKER_IMAGE =="
echo "repo root (mounted whole): $REPO_ROOT"
echo "corpus dir: $CORPUS_DIR"

HOST_PY_VERSION="$(python3 --version)"
echo "host python: $HOST_PY_VERSION"

REL_SCRIPT_DIR="${SCRIPT_DIR#$REPO_ROOT/}"

echo "-- verifying script visibility inside container --"
docker run --rm -v "$REPO_ROOT:/work" "$DOCKER_IMAGE" ls -la "/work/$REL_SCRIPT_DIR/memento_walker.py"
docker run --rm -v "$REPO_ROOT:/work" "$DOCKER_IMAGE" python3 --version

START_TIME=$(date +%s.%N)

TOTAL_FILES=0
TOTAL_DIVERGED=0

for src in "$CORPUS_DIR"/*.py; do
  name="$(basename "$src")"
  TOTAL_FILES=$((TOTAL_FILES + 1))
  host_out="$OUT_DIR/${name}.host.jsonl"
  docker_out="$OUT_DIR/${name}.docker.jsonl"

  python3 "$SCRIPT_DIR/memento_walker.py" "$src" > "$host_out"

  rel_src="${src#$REPO_ROOT/}"
  docker run --rm -v "$REPO_ROOT:/work" -w /work "$DOCKER_IMAGE" \
    python3 "$REL_SCRIPT_DIR/memento_walker.py" "$rel_src" > "$docker_out"

  if ! python3 "$SCRIPT_DIR/diff_mementos.py" "host-3.12.3" "$host_out" "docker-3.12.13" "$docker_out" > "$OUT_DIR/${name}.diff.txt" 2>&1; then
    TOTAL_DIVERGED=$((TOTAL_DIVERGED + 1))
    echo "---- DIVERGENCE in $name ----"
    cat "$OUT_DIR/${name}.diff.txt"
  else
    tail -n1 "$OUT_DIR/${name}.diff.txt"
  fi
done

END_TIME=$(date +%s.%N)
ELAPSED=$(python3 -c "print(f'{$END_TIME - $START_TIME:.2f}')")

echo "== summary =="
echo "files compared: $TOTAL_FILES"
echo "files with divergence: $TOTAL_DIVERGED"
echo "wall-clock: ${ELAPSED}s"

rm -rf "$OUT_DIR"

if [ "$TOTAL_DIVERGED" -gt 0 ]; then
  exit 1
fi
exit 0
