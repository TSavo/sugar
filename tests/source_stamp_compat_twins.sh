#!/usr/bin/env bash
# Twins for sourceStamp-only kit/binary compatibility (#4577 redo).
set -euo pipefail
repo="${1:?usage: source_stamp_compat_twins.sh REPO_ROOT}"
cd "$repo"

stamp() {
  python3 tools/sugar_source_stamp.py --repo-root "$repo" --package sugar-cli
}

base="$(stamp)"
[[ "$base" == blake3-512_* ]] || { echo "bad stamp: $base" >&2; exit 1; }
[[ "$base" != *:* ]] || { echo "stamp must not contain colon: $base" >&2; exit 1; }

# Twin: same source, recomputed → identical sourceStamp.
again="$(stamp)"
[[ "$base" == "$again" ]] || { echo "non-deterministic sourceStamp" >&2; exit 1; }

# Twin: docs-only tree change must not affect stamp (hash only protocol sources).
tmp_doc="$(mktemp "$repo/docs/.source-stamp-twin.XXXXXX.md" 2>/dev/null || mktemp /tmp/source-stamp-twin.XXXXXX.md)"
echo "docs-only twin $(date)" >"$tmp_doc"
docs_stamp="$(stamp)"
rm -f "$tmp_doc"
[[ "$base" == "$docs_stamp" ]] || { echo "docs-only change altered sourceStamp" >&2; exit 1; }

# Twin: protocol Python change must alter stamp.
py_touch="$(mktemp "$repo/implementations/python/sugar-lift-py-tests/src/.stamp-twin.XXXXXX")"
echo "# twin" >"$py_touch"
py_stamp="$(stamp)"
rm -f "$py_touch"
[[ "$base" != "$py_stamp" ]] || { echo "python protocol change did not alter sourceStamp" >&2; exit 1; }

# Twin: after remove, stamp returns.
restored="$(stamp)"
[[ "$base" == "$restored" ]] || { echo "stamp did not restore after python twin cleanup" >&2; exit 1; }

# Twin: relevant Rust source change alters stamp.
rs_touch="$(mktemp "$repo/implementations/rust/sugar-cli/src/.stamp-twin.XXXXXX.rs")"
echo "// twin" >"$rs_touch"
rs_stamp="$(stamp)"
rm -f "$rs_touch"
[[ "$base" != "$rs_stamp" ]] || { echo "rust source change did not alter sourceStamp" >&2; exit 1; }

# Compatibility gate: mismatch is loud.
refuse_src="$(rg -n 'refuse_split_pipeline' implementations/rust/sugar-cli/src/lift_plugin.rs | head -1)"
[[ -n "$refuse_src" ]]
gate="$(rg -n 'binary_source_stamp|SUGAR_BUILD_STAMP' implementations/rust/sugar-cli/src/lift_plugin.rs | head -3)"
echo "$gate" | rg -q 'SUGAR_BUILD_STAMP' || { echo "gate still not on SUGAR_BUILD_STAMP" >&2; exit 1; }
! rg -n 'refuse_split_pipeline\(identity, env!\("SUGAR_BUILD_GIT_HEAD"\)\)' implementations/rust/sugar-cli/src/lift_plugin.rs \
  || { echo "gate still compares to SUGAR_BUILD_GIT_HEAD" >&2; exit 1; }

echo "PASS: sourceStamp twins (docs stable, rust/python protocol matter, gate uses SUGAR_BUILD_STAMP)"
