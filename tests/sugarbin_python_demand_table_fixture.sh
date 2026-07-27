#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_python_demand_table_fixture.sh REPO_ROOT}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/corpus/pkg" "$tmp/seed-shelf" "$tmp/partial-shelf" "$tmp/race-shelf"
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
    --runtime python-test-runtime \
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
    --runtime python-test-runtime \
    --platform test-platform \
    --profile test-profile \
    --shelf-root "$shelf"
}

# Obtain a real completed cell through the production publisher, then remove
# its compressed payload in a separate shelf. Pull must refuse that incomplete
# cell without materializing a placeholder into the destination.
publish "$tmp/seed-shelf" "$tmp/table-a.json"
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
