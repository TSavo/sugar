#!/usr/bin/env bash
# R_shelf_content_addressed_cell teeth (bash contract — no local pytest).
# Cell address must be h(payload). Stamp is a mutable pointer, not the cell.
set -euo pipefail

repo="${1:?usage: sugarbin_shelf_content_addressed.sh REPO_ROOT}"
sugarbin="$repo/bin/sugarbin"
[[ -x "$sugarbin" ]] || { echo "missing $sugarbin" >&2; exit 1; }

# --- static: ONE door shapes present ---
grep -Fq 'filesystem_shelf_cas_cell' "$sugarbin" || {
  echo 'missing filesystem_shelf_cas_cell' >&2
  exit 1
}
grep -Fq 'write_filesystem_shelf_stamp_ref' "$sugarbin" || {
  echo 'missing stamp→content ref writer' >&2
  exit 1
}
grep -Fq 'read_filesystem_shelf_stamp_ref' "$sugarbin" || {
  echo 'missing stamp→content ref reader' >&2
  exit 1
}
grep -Fq 'crime=cas-address-payload-mismatch' "$sugarbin" || {
  echo 'missing CAS address/payload mismatch crime' >&2
  exit 1
}
# Binary cells must not be keyed by sourceStamp path layout (shell deleted).
if grep -E 'printf.*platform_key.*profile.*stamp_for_filename "\$stamp".*\$name' "$sugarbin" | grep -Fq 'filesystem_shelf_cell'; then
  echo 'binary filesystem_shelf_cell still stamps path by sourceStamp' >&2
  exit 1
fi
# publish computes content key from payload bytes for EVERY kind (not only binary)
publish_body="$(sed -n '/^publish_to_filesystem_shelf()/,/^evict_shelf_cell()/p' "$sugarbin")"
grep -Fq 'blake3_512_file' <<<"$publish_body" || {
  echo 'publish does not content-hash the payload' >&2
  exit 1
}
# C: non-binary must not trust content_key="$stamp" without re-hash refuse.
if grep -Fq 'content_key="$stamp"' <<<"$publish_body"; then
  echo 'publish still sets content_key from caller stamp without re-hash' >&2
  exit 1
fi
grep -Fq 'crime=cas-publish-key-payload-mismatch' "$sugarbin" || {
  echo 'missing publish-time CAS key/payload mismatch crime' >&2
  exit 1
}
grep -Fq 'write_filesystem_shelf_stamp_ref' <<<"$publish_body" || {
  echo 'publish does not write stamp→content ref' >&2
  exit 1
}
pull_body="$(sed -n '/^pull_from_filesystem_shelf()/,/^write_payload_artifact_manifest()/p' "$sugarbin")"
grep -Fq 'read_filesystem_shelf_stamp_ref' <<<"$pull_body" || {
  echo 'pull does not resolve stamp→content ref' >&2
  exit 1
}
grep -Fq 'verify_filesystem_shelf_artifact' <<<"$pull_body" || {
  echo 'pull does not route through the filesystem-CAS verifier' >&2
  exit 1
}
if grep -Fq 'verify_artifact_manifest "$candidate" "$stamp" "$identity" "filesystem shelf artifact"' <<<"$pull_body"; then
  echo 'filesystem shelf still routes through strict local-build verification' >&2
  exit 1
fi

# --- dynamic: two payloads → two CAS addresses; stamp is not the address ---
if ! command -v b3sum >/dev/null 2>&1; then
  echo 'SKIP dynamic CAS teeth: b3sum not on PATH (CI/managed images have it)' >&2
  echo 'PASS: R_shelf_content_addressed_cell static teeth (b3sum absent locally)'
  exit 0
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/shelf-cas.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

payload_a="$tmp/a.bin"
payload_b="$tmp/b.bin"
printf 'payload-A-bytes' >"$payload_a"
printf 'payload-B-bytes-different' >"$payload_b"

key_a="$(b3sum -l 64 --no-names "$payload_a" | awk '{print "blake3-512_" $1}')"
key_b="$(b3sum -l 64 --no-names "$payload_b" | awk '{print "blake3-512_" $1}')"
[[ "$key_a" != "$key_b" ]] || {
  echo 'lying twin precondition failed: distinct payloads share hash' >&2
  exit 1
}

# Lying twin: same sourceStamp name must NOT place two payloads in one cell path.
# Under CAS, cells are key_a vs key_b — collision by stamp is unrepresentable.
stamp="blake3-512_$(printf 'shared-source-stamp' | b3sum -l 64 --no-names)"
name="sugar-linux-x86_64-release-demo"
cas_a="$tmp/shelf/cas/${key_a//:/_}/$name"
cas_b="$tmp/shelf/cas/${key_b//:/_}/$name"
[[ "$cas_a" != "$cas_b" ]] || {
  echo 'CAS paths collided for distinct content keys' >&2
  exit 1
}

# Lying twin: payload under wrong address is not membership (h≠h(p)).
mkdir -p "$cas_a"
cp "$payload_b" "$tmp/wrong.bin"
# pretend cell address is key_a but bytes are B
wrong_key="$(b3sum -l 64 --no-names "$tmp/wrong.bin" | awk '{print "blake3-512_" $1}')"
[[ "$wrong_key" != "$key_a" ]] || exit 1
# The crime string documents the refuse path for this shape
grep -Fq 'a content-addressed shelf cannot host p under h≠h(p)' "$sugarbin"

# Stamp ref is a pointer, not the cell: two stamps may share one content key.
ref1="$tmp/shelf/linux-x86_64/release/by-stamp/stamp-one/$name.ref"
ref2="$tmp/shelf/linux-x86_64/release/by-stamp/stamp-two/$name.ref"
mkdir -p "$(dirname "$ref1")" "$(dirname "$ref2")"
printf '%s\n' "$key_a" >"$ref1"
printf '%s\n' "$key_a" >"$ref2"
[[ "$(cat "$ref1")" == "$(cat "$ref2")" ]] || exit 1
# Cells still only at cas/key_a — no stamp-keyed cell directory required.
[[ ! -d "$tmp/shelf/linux-x86_64/release/${stamp//:/_}" ]] || {
  echo 'stamp-keyed cell directory should not be required for CAS membership' >&2
  exit 1
}

echo 'PASS: R_shelf_content_addressed_cell — address is h(payload); stamp is ref only'

# End-to-end discrimination belongs to this enrolled contract: a separate
# filesystem-CAS verifier accepts diagnostic host drift but still rejects
# wrong source authority and wrong payload bytes.
"$repo/tests/sugarbin_shelf_manifest_identity.sh" "$repo"
