#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_shelf_immutability.sh REPO_ROOT}"
sugarbin="$repo/bin/sugarbin"
[[ -x "$sugarbin" ]] || { echo "missing $sugarbin" >&2; exit 1; }

fail() { echo "FAIL: $*" >&2; exit 1; }

# B: dead GitHub Releases shelf path must stay deleted (zero callers → gone).
for dead in publish_if_absent pull_from_shelf upload_shelf_file ensure_shelf_release \
  shelf_tag_for_stamp shelf_asset_names purge_incomplete_shelf_asset \
  shelf_has_complete_artifact github_repo verify_attestation_if_present; do
  if grep -Eq "^${dead}\(\)" "$sugarbin"; then
    fail "dead GH shelf function still defined: $dead"
  fi
done

# Live filesystem shelf is the only publish/pull door from main().
main_body="$(sed -n '/^main()/,$p' "$sugarbin")"
grep -Fq 'pull_from_filesystem_shelf' <<<"$main_body" || fail 'main missing FS pull'
grep -Fq 'publish_to_filesystem_shelf' <<<"$main_body" || fail 'main missing FS publish'
if grep -Eq 'pull_from_shelf|publish_if_absent' <<<"$main_body"; then
  fail 'sugarbin main still routes shelf traffic through GitHub Releases'
fi

# Atomic cell install must not clobber via --clobber (GH-era defect class).
publish_body="$(sed -n '/^publish_to_filesystem_shelf()/,/^evict_shelf_cell()/p' "$sugarbin")"
if grep -Fq -- '--clobber' <<<"$publish_body"; then
  fail 'filesystem shelf publisher can replace a content-addressed asset via --clobber'
fi
grep -Fq 'peer won' <<<"$publish_body" || fail 'FS publish does not recognize concurrent winner'

echo 'PASS: sugarbin shelf assets are immutable and race-idempotent (FS-only)'

# R_shelf_peer_evictable_cell: regenerable cells must be peer-evictable.
"$repo/tests/sugarbin_shelf_peer_evictable.sh" "$repo"

# R_shelf_content_addressed_cell: address = h(payload), not sourceStamp name.
"$repo/tests/sugarbin_shelf_content_addressed.sh" "$repo"

# R_shelf_rebuild_single_flight: 36 matrix jobs must not each cargo the same stamp.
"$repo/tests/sugarbin_rebuild_single_flight.sh" "$repo"

# R_shelf_exercise: SHELF_EXERCISED_CLEAN ≠ SHELF_NEVER_TOUCHED ≠ SHELF_UNMEASURED.
"$repo/tests/shelf_exercise_report.sh" "$repo"

# Exercise the python-demand-table artifact through the shelf boundary.
"$repo/tests/sugarbin_python_demand_table_fixture.sh" "$repo"
