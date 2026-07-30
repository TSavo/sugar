#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_python_demand_table_fixture.sh REPO_ROOT}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p \
  "$tmp/corpus/pkg" \
  "$tmp/seed-shelf" \
  "$tmp/private-shelf" \
  "$tmp/mutable-shelf" \
  "$tmp/blocked-shelf" \
  "$tmp/partial-shelf" \
  "$tmp/race-shelf"
printf 'alpha = 1\n' >"$tmp/corpus/pkg/a.py"
printf 'beta = 2\n' >"$tmp/corpus/pkg/b.py"
printf '{"rows":["publisher-a"]}\n' >"$tmp/table-a.json"
printf '{"rows":["publisher-b"]}\n' >"$tmp/table-b.json"

python_path="$repo/implementations/python/sugar-lift-py-tests/src:$repo/implementations/python/sugar-lift-python-source/src:$repo/implementations/python/sugar-source-tree/src"
content_key="$(PYTHONPATH="$python_path" python3 - "$repo" "$tmp/corpus" <<'PY'
import pathlib
import sys

from sugar_lift_py_tests.demand_table_identity import demand_table_identity

repo = pathlib.Path(sys.argv[1])
corpus = pathlib.Path(sys.argv[2])
identity = demand_table_identity(
    corpus,
    sorted(corpus.rglob("*.py")),
    source_root=repo / "implementations/python/sugar-lift-py-tests/src",
)
print(identity.content_key)
PY
)"

publish() {
  local shelf="$1" input="$2"
  "$repo/bin/sugarbin" artifact publish \
    --kind python-demand-table \
    --content-key "$content_key" \
    --input "$input" \
    --runtime cpython-3.12.13 \
    --platform test-platform \
    --profile test-profile \
    --shelf-root "$shelf"
}

pull() {
  local shelf="$1" output="$2"
  "$repo/bin/sugarbin" artifact pull \
    --kind python-demand-table \
    --content-key "$content_key" \
    --output "$output" \
    --runtime cpython-3.12.13 \
    --platform test-platform \
    --profile test-profile \
    --shelf-root "$shelf"
}

# The managed closure declares exactly one Python authority. A shelf request
# for workstation 3.14 testimony must refuse before looking for an artifact;
# accepting both would claim a second authenticated runtime cell exists.
set +e
"$repo/bin/sugarbin" artifact pull \
  --kind python-demand-table \
  --content-key "$content_key" \
  --output "$tmp/wrong-runtime.json" \
  --runtime cpython-3.14.4 \
  --platform test-platform \
  --profile test-profile \
  --shelf-root "$tmp/seed-shelf" \
  2>"$tmp/wrong-runtime.err"
wrong_runtime_status=$?
set -e
[[ "$wrong_runtime_status" == 78 ]] || {
  echo "undeclared runtime request returned $wrong_runtime_status; expected refusal 78" >&2
  exit 1
}
grep -Fq 'required=cpython-3.12.13 requested=cpython-3.14.4' "$tmp/wrong-runtime.err" || {
  echo 'undeclared runtime refusal did not name required and requested identities' >&2
  exit 1
}
[[ ! -e "$tmp/wrong-runtime.json" ]] || {
  echo 'undeclared runtime request materialized an artifact' >&2
  exit 1
}

# Obtain a real completed cell through the production publisher, then remove
# its compressed payload in a separate shelf. Pull must refuse that incomplete
# cell without materializing a placeholder into the destination.
publish "$tmp/seed-shelf" "$tmp/table-a.json"

# Truthful shared-permission face. The publisher and consumer may be root,
# uid 1001 in a runner container, or uid 1000 over SSH. Structural directories
# therefore remain writable by the next identity, while immutable cell bytes
# are world-readable and never need to be rewritten.
python3 - "$tmp/seed-shelf" <<'PY'
import pathlib
import stat
import sys

shelf = pathlib.Path(sys.argv[1]).resolve()
metadata = list(shelf.rglob("*.metadata.json"))
assert len(metadata) == 1, metadata
cell = metadata[0].parent
stamp_parent = cell.parent

current = shelf
while True:
    mode = stat.S_IMODE(current.stat().st_mode)
    assert mode == 0o777, (
        f"shared shelf structure must be writable by the next identity: "
        f"{current} mode={mode:04o}"
    )
    if current == stamp_parent:
        break
    relative = stamp_parent.relative_to(current)
    current = current / relative.parts[0]

incoming = stamp_parent / ".incoming"
assert stat.S_IMODE(incoming.stat().st_mode) == 0o777
assert stat.S_IMODE(cell.stat().st_mode) == 0o755
for artifact in cell.iterdir():
    assert artifact.is_file(), artifact
    mode = stat.S_IMODE(artifact.stat().st_mode)
    assert mode == 0o644, f"immutable shelf byte is not peer-readable: {artifact} mode={mode:04o}"
PY

# Lying shared-permission face. A privileged creator can read a private cell,
# but accepting it would manufacture a warm-shelf hit that uid 1001 cannot
# reproduce. The broker must reject the resident by its shared mode contract.
cp -R "$tmp/seed-shelf/." "$tmp/private-shelf/"
private_cell="$(
  find "$tmp/private-shelf" -type f -name '*.metadata.json' -exec dirname {} \;
)"
chmod 0700 "$private_cell"
find "$private_cell" -type f -exec chmod 0600 {} +
set +e
pull "$tmp/private-shelf" "$tmp/private-pull.json" 2>"$tmp/private.err"
private_status=$?
set -e
[[ "$private_status" != 0 ]] || {
  echo 'a private filesystem-shelf cell was accepted by its creating identity' >&2
  exit 1
}
grep -Fq 'crime=private-filesystem-shelf-cell' "$tmp/private.err" || {
  echo 'a private filesystem-shelf cell did not refuse by name' >&2
  cat "$tmp/private.err" >&2
  exit 1
}
[[ ! -e "$tmp/private-pull.json" ]] || {
  echo 'a private filesystem-shelf cell materialized output' >&2
  exit 1
}

# Lying immutability face. Peer read/traverse bits do not make a
# content-addressed resident immutable: another runner identity can rewrite a
# 0777 cell or any 0666 byte after the creator has authenticated it.
cp -R "$tmp/seed-shelf/." "$tmp/mutable-shelf/"
mutable_cell="$(
  find "$tmp/mutable-shelf" -type f -name '*.metadata.json' -exec dirname {} \;
)"
chmod 0777 "$mutable_cell"
find "$mutable_cell" -type f -exec chmod 0666 {} +
set +e
pull "$tmp/mutable-shelf" "$tmp/mutable-pull.json" 2>"$tmp/mutable.err"
mutable_status=$?
set -e
[[ "$mutable_status" != 0 ]] || {
  echo 'a world-writable filesystem-shelf cell was accepted by its creating identity' >&2
  exit 1
}
grep -Fq 'crime=private-filesystem-shelf-cell' "$tmp/mutable.err" || {
  echo 'a world-writable filesystem-shelf cell did not refuse by name' >&2
  cat "$tmp/mutable.err" >&2
  exit 1
}
[[ ! -e "$tmp/mutable-pull.json" ]] || {
  echo 'a world-writable filesystem-shelf cell materialized output' >&2
  exit 1
}

# Staging refusal face. In bash, errexit is disabled inside a function invoked
# by an `if`/`||` caller; an unchecked failed mktemp therefore assigns tmp=""
# and turns "$tmp/$name.gz" into a write under "/". Pin the real blocked
# staging shape and require refusal before any derived root path is attempted.
seed_incoming="$(find "$tmp/seed-shelf" -type d -name .incoming -print -quit)"
relative_incoming="${seed_incoming#"$tmp/seed-shelf/"}"
blocked_incoming="$tmp/blocked-shelf/$relative_incoming"
mkdir -p "$(dirname "$blocked_incoming")"
: >"$blocked_incoming"
set +e
publish "$tmp/blocked-shelf" "$tmp/table-a.json" 2>"$tmp/blocked.err"
blocked_status=$?
set -e
[[ "$blocked_status" != 0 ]] || {
  echo 'an uncreatable filesystem-shelf staging directory reported success' >&2
  exit 1
}
grep -Fq 'crime=uncreatable-filesystem-shelf-staging' "$tmp/blocked.err" || {
  echo 'an uncreatable filesystem-shelf staging directory did not refuse by name' >&2
  cat "$tmp/blocked.err" >&2
  exit 1
}
if grep -Fq '/python-demand-table.gz' "$tmp/blocked.err"; then
  echo 'failed shelf staging fell through to a derived write under /' >&2
  cat "$tmp/blocked.err" >&2
  exit 1
fi

cp -R "$tmp/seed-shelf/." "$tmp/partial-shelf/"
payload_count="$(find "$tmp/partial-shelf" -type f -name '*.gz' | wc -l | tr -d ' ')"
[[ "$payload_count" == 1 ]] || {
  echo "python-demand-table publication exposed $payload_count compressed payloads; expected one existing-shelf artifact cell" >&2
  exit 1
}
find "$tmp/partial-shelf" -type f -name '*.gz' -delete
set +e
pull "$tmp/partial-shelf" "$tmp/partial-pull.json" 2>"$tmp/partial.err"
partial_status=$?
set -e
[[ "$partial_status" != 0 ]] || { echo 'python-demand-table consumed a partially published shelf cell' >&2; exit 1; }
[[ ! -e "$tmp/partial-pull.json" ]] || { echo 'python-demand-table materialized bytes from an incomplete shelf cell' >&2; exit 1; }

# Two producers may race on one immutable content cell. Exactly one complete
# artifact may win; the consumer must observe all bytes from A or all from B.
set +e
publish "$tmp/race-shelf" "$tmp/table-a.json" >"$tmp/publish-a.out" 2>"$tmp/publish-a.err" &
publisher_a=$!
publish "$tmp/race-shelf" "$tmp/table-b.json" >"$tmp/publish-b.out" 2>"$tmp/publish-b.err" &
publisher_b=$!
wait "$publisher_a"; status_a=$?
wait "$publisher_b"; status_b=$?
set -e
[[ "$status_a" == 0 && "$status_b" == 0 ]] || {
  echo "python-demand-table racing publishers failed: publisher-a=$status_a publisher-b=$status_b" >&2
  exit 1
}
pull "$tmp/race-shelf" "$tmp/race-pull.json"
if cmp -s "$tmp/race-pull.json" "$tmp/table-a.json"; then
  winner=a
elif cmp -s "$tmp/race-pull.json" "$tmp/table-b.json"; then
  winner=b
else
  echo 'python-demand-table consumer observed a torn artifact from racing publishers' >&2
  exit 1
fi

echo "PASS: python-demand-table rejects incomplete publication and consumes coherent racing winner $winner"
