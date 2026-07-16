#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_shelf_immutability.sh REPO_ROOT}"
body="$(sed -n '/^upload_shelf_file()/,/^}/p' "$repo/bin/sugarbin")"

if grep -Fq -- '--clobber' <<<"$body"; then
  echo 'sugarbin shelf publisher can replace a content-addressed asset' >&2
  exit 1
fi
grep -Fq 'shelf_asset_names' <<<"$body" || {
  echo 'sugarbin shelf publisher does not recognize a concurrent winner' >&2
  exit 1
}
grep -Fq 'ensure_shelf_release' <<<"$body" || {
  echo 'sugarbin upload retry does not re-resolve its release' >&2
  exit 1
}
grep -Fq 'purge_incomplete_shelf_asset' <<<"$body" || {
  echo 'sugarbin upload retry leaves poisoned starter assets behind' >&2
  exit 1
}

purge_body="$(sed -n '/^purge_incomplete_shelf_asset()/,/^}/p' "$repo/bin/sugarbin")"
grep -Fq 'asset.get("state") == "starter"' <<<"$purge_body" || {
  echo 'sugarbin may purge an immutable uploaded shelf asset' >&2
  exit 1
}

echo 'PASS: sugarbin shelf assets are immutable and race-idempotent'
