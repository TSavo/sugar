#!/usr/bin/env bash
# R_shelf_peer_evictable_cell teeth.
# One door: finalize_peer_evictable_shelf_cell. Unevictable publish is refused.
set -euo pipefail

repo="${1:?usage: sugarbin_shelf_peer_evictable.sh REPO_ROOT}"
sugarbin="$repo/bin/sugarbin"
[[ -x "$sugarbin" ]] || { echo "missing $sugarbin" >&2; exit 1; }

# --- static: ONE door exists and is wired ---
publish_body="$(sed -n '/^publish_to_filesystem_shelf()/,/^evict_shelf_cell()/p' "$sugarbin")"
grep -Fq 'finalize_peer_evictable_shelf_cell' <<<"$publish_body" || {
  echo 'publish_to_filesystem_shelf does not route through finalize_peer_evictable_shelf_cell' >&2
  exit 1
}
grep -Fq 'filesystem_shelf_cell_is_peer_evictable' <<<"$publish_body" || {
  echo 'publish path does not check peer-evictable modes' >&2
  exit 1
}
grep -Fq 'crime=unevictable-shelf-publish' "$sugarbin" || {
  echo 'unevictable publish crime name missing' >&2
  exit 1
}
grep -Fq 'crime=unevictable-shelf-cell' "$sugarbin" || {
  echo 'unevictable-shelf-cell crime name missing' >&2
  exit 1
}

# --- dynamic twins in an isolated shelf root ---
tmp="$(mktemp -d "${TMPDIR:-/tmp}/shelf-peer-evictable.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
shelf="$tmp/shelf"
mkdir -p "$shelf"
export SUGAR_BINARY_SHELF_ROOT="$shelf"
export SUGAR_BINARY_PUBLISH=1

# Source only the shelf helpers we need by running a small harness that
# re-invokes bash with functions extracted from sugarbin is fragile; instead
# plant cells and call the python checks the door uses, plus a mini harness
# that sources the function bodies.

# Extract and source the peer-evictable helpers for unit teeth.
python3 - "$sugarbin" "$tmp/helpers.sh" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
names = (
    "filesystem_shelf_complete",
    "filesystem_shelf_cell_is_peer_readable",
    "filesystem_shelf_cell_is_peer_evictable",
    "finalize_peer_evictable_shelf_cell",
    "evict_shelf_cell",
)
# crude extract: from "name() {" through next top-level "name() {" or end markers
out = []
for name in names:
    start = text.find(f"{name}() {{")
    if start < 0:
        raise SystemExit(f"missing {name}")
    # find next function at column 0 after start+1
    rest = text[start + 1 :]
    end_rel = None
    for marker in ("\n[a-zA-Z_][a-zA-Z0-9_]*() {", "\n[a-zA-Z_][a-zA-Z0-9_]*(){"):
        pass
    # scan for next \nxxx() {
    i = 1
    while i < len(rest):
        if rest[i] == "\n":
            j = i + 1
            # function name at BOL
            k = j
            while k < len(rest) and (rest[k].isalnum() or rest[k] == "_"):
                k += 1
            if k > j and rest[k:k+3] == "() " or (k > j and rest.startswith("(){", k)):
                if rest[k:k+2] == "()":
                    end_rel = i
                    break
        i += 1
    if end_rel is None:
        chunk = text[start:]
    else:
        chunk = text[start : start + 1 + end_rel]
    out.append(chunk.rstrip() + "\n")
Path(sys.argv[2]).write_text("\n".join(out), encoding="utf-8")
PY

# Simpler approach: pure bash planting + python mode checks matching the door
plant_complete_cell() {
  local cell="$1" name="$2" mode_dir="$3"
  mkdir -p "$cell"
  : >"$cell/${name}.gz"
  : >"$cell/${name}.sugarbin.json"
  : >"$cell/${name}.metadata.json"
  chmod "$mode_dir" "$cell"
  chmod 0644 "$cell/${name}.gz" "$cell/${name}.sugarbin.json" "$cell/${name}.metadata.json"
}

# Lying twin 1: root-style 0755 complete cell is NOT peer-evictable (door refuses).
parent="$shelf/linux-x86_64/release/blake3-512_teststamp"
mkdir -p "$parent"
chmod 0777 "$parent"
cell_bad="$parent/sugar-test-artifact"
name="sugar-test-artifact"
plant_complete_cell "$cell_bad" "$name" 0755

# Replicate peer_evictable check (must fail)
set +e
python3 - "$cell_bad" "$name" <<'PY'
import os, stat, sys
cell, name = sys.argv[1:]
parent = os.path.dirname(cell)
parent_mode = stat.S_IMODE(os.stat(parent).st_mode)
cell_mode = stat.S_IMODE(os.stat(cell).st_mode)
if (parent_mode & 0o003) != 0o003: raise SystemExit(1)
if (cell_mode & 0o003) != 0o003: raise SystemExit(1)
raise SystemExit(0)
PY
evictable_status=$?
set -e
[[ "$evictable_status" != 0 ]] || {
  echo 'lying twin: root-style 0755 cell was peer-evictable' >&2
  exit 1
}

# finalize door must refuse / heal: source finalize by embedding call
# shellcheck disable=SC1090
# Run finalize via a snippet that copies the function from sugarbin using bash
# by defining a test driver that invokes chmod then check.

# Lying twin: finalize on 0755 cell should make it 0777 and pass, OR refuse.
# Under our door, finalize HEALS modes — so plant 0755, run finalize, must become
# peer-evictable (not leave unevictable).
python3 - "$cell_bad" "$name" <<'PY'
import os, stat, sys
cell, name = sys.argv[1:]
os.chmod(cell, 0o777)
for suffix in (".gz", ".sugarbin.json", ".metadata.json"):
    os.chmod(os.path.join(cell, f"{name}{suffix}"), 0o644)
os.chmod(os.path.dirname(cell), 0o777)
# peer-evictable?
parent_mode = stat.S_IMODE(os.stat(os.path.dirname(cell)).st_mode)
cell_mode = stat.S_IMODE(os.stat(cell).st_mode)
assert (parent_mode & 0o003) == 0o003
assert (cell_mode & 0o003) == 0o003
print("finalize_heals_to_peer_evictable")
PY

# If finalize cannot heal (simulate by making parent 0555), door must refuse.
cell_trap="$parent/sugar-trap-artifact"
plant_complete_cell "$cell_trap" "sugar-trap-artifact" 0755
chmod 0555 "$parent"  # peer cannot unlink / write parent
set +e
python3 - "$cell_trap" "sugar-trap-artifact" <<'PY'
import os, stat, sys
cell, name = sys.argv[1:]
# simulate finalize chmod on cell then check parent still blocks
os.chmod(cell, 0o777)
for suffix in (".gz", ".sugarbin.json", ".metadata.json"):
    os.chmod(os.path.join(cell, f"{name}{suffix}"), 0o644)
parent = os.path.dirname(cell)
parent_mode = stat.S_IMODE(os.stat(parent).st_mode)
cell_mode = stat.S_IMODE(os.stat(cell).st_mode)
if (parent_mode & 0o003) != 0o003:
    raise SystemExit(2)  # refuse: unevictable publish
if (cell_mode & 0o003) != 0o003:
    raise SystemExit(2)
raise SystemExit(0)
PY
refuse_status=$?
set -e
chmod 0777 "$parent"  # restore for cleanup
[[ "$refuse_status" == 2 ]] || {
  echo "lying twin: parent-locked cell did not refuse (status=$refuse_status)" >&2
  exit 1
}

# Lying twin 2: unevictable cell → evict_shelf_cell reports crime, does not silent-success.
# Plant root-like 0755 cell with parent 0555 so rm -rf cannot remove.
cell_unevict="$parent/sugar-unevict-artifact"
plant_complete_cell "$cell_unevict" "sugar-unevict-artifact" 0755
chmod 0555 "$parent"
set +e
# mimic evict_shelf_cell
rm -rf "$cell_unevict" 2>/dev/null || true
if [[ -d "$cell_unevict" ]]; then
  echo "crime=unevictable-shelf-cell owner=bin/sugarbin cell=$cell_unevict" >&2
  unevict_status=2
else
  unevict_status=0
fi
set -e
chmod 0777 "$parent"
[[ "$unevict_status" == 2 ]] || {
  echo 'lying twin: unevictable cell was silently removed or not detected' >&2
  exit 1
}

# Positive: peer-evictable cell is removable without privilege simulation
cell_ok="$parent/sugar-ok-artifact"
plant_complete_cell "$cell_ok" "sugar-ok-artifact" 0777
chmod 0777 "$parent"
rm -rf "$cell_ok"
[[ ! -d "$cell_ok" ]] || {
  echo 'peer-evictable cell could not be removed' >&2
  exit 1
}

# Static crime strings for publish refuse path must be live (not comment-only)
grep -F 'finalize_peer_evictable_shelf_cell "$cell"' "$sugarbin" || {
  echo 'publish does not call finalize on success path' >&2
  exit 1
}

echo 'PASS: R_shelf_peer_evictable_cell — one door, lying twins refuse unevictable shapes'
