#!/usr/bin/env bash
# R_shelf_exercise teeth: EXERCISED_CLEAN vs NEVER_TOUCHED vs UNMEASURED vs CRIME.
#
# The defect: a heavy run that dies before the filesystem shelf path is entered
# leaves no shelf crimes, and silence was being read as "doors load-cleared".
# Existing lease / identity receipts carry zero shelf-exercise fields — proven
# here as a lying twin, not a comment.
#
# No local pytest (watchdog). Pure python3 + fixtures.
set -euo pipefail

repo="${1:?usage: shelf_exercise_report.sh REPO_ROOT}"
tool="$repo/tools/shelf_exercise_report.py"
[[ -f "$tool" ]] || { echo "missing $tool" >&2; exit 1; }

tmp="$(mktemp -d "${TMPDIR:-/tmp}/shelf-exercise.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

classify() {
  python3 "$tool" classify "$@"
}

verdict_of() {
  # Last "**VERDICT**" style line from classify stdout.
  classify "$@" | sed -n 's/^- verdict: \*\*\(.*\)\*\*/\1/p' | tail -1
}

fail() { echo "FAIL: $*" >&2; exit 1; }

# --- Twin 0: lease receipt is silent on shelf (existing mechanism insufficient) ---
cat >"$tmp/lease.json" <<'JSON'
{
  "schemaVersion": 1,
  "leaseClass": "control-effect-recensus",
  "measurementStatus": "completed/findings",
  "supportsZeroClaim": false,
  "acquired": true,
  "measuredCommit": "8857e4071761174141f1c6c8ef8a05684f1316af",
  "waitSeconds": 0.0,
  "heldSeconds": 3.3
}
JSON
python3 - "$tmp/lease.json" "$tool" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[2]).resolve().parent.parent / "tools"))
# Import by path load
import importlib.util
spec = importlib.util.spec_from_file_location("shelf_exercise_report", sys.argv[2])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
lease = json.loads(Path(sys.argv[1]).read_text())
assert mod.lease_record_is_silent_on_shelf(lease), "lease must not carry shelf axes"
# Classifying a lease-as-if-receipt must not pretend EXERCISED_CLEAN
try:
    mod.load_receipt(Path(sys.argv[1]))
    raise SystemExit("lease must not load as shelf-exercise receipt")
except ValueError:
    pass
print("PASS: lease receipt is silent on shelf (no fourth-mechanism reuse)")
PY

# --- Twin 1: no testimony → UNMEASURED (not clean) ---
v="$(verdict_of --receipt "$tmp/missing.json" --advisory 2>/dev/null || true)"
# missing file: classify prints UNMEASURED; advisory exits 0
v="$(python3 "$tool" classify --receipt "$tmp/no-such.json" --advisory | sed -n 's/^- verdict: \*\*\(.*\)\*\*/\1/p' | tail -1)"
[[ "$v" == "SHELF_UNMEASURED" ]] || fail "missing receipt should be UNMEASURED, got $v"

# --- Twin 2: resolve opened, no shelf events → NEVER_TOUCHED ---
python3 "$tool" open --output "$tmp/never.json"
v="$(verdict_of --receipt "$tmp/never.json" --advisory)"
[[ "$v" == "SHELF_NEVER_TOUCHED" ]] || fail "open-only receipt should be NEVER_TOUCHED, got $v"
# Load-clear question must go red
if python3 "$tool" classify --receipt "$tmp/never.json" --require-exercised-clean >/dev/null 2>&1; then
  fail "NEVER_TOUCHED must fail --require-exercised-clean"
fi

# --- Twin 3: pull hit, no crime → EXERCISED_CLEAN ---
python3 "$tool" open --output "$tmp/clean.json"
python3 "$tool" event --output "$tmp/clean.json" --op pull --outcome hit --name sugar \
  --content-key blake3-512_$(printf 'a%.0s' {1..128} | tr -d '\n' | head -c 128)
v="$(verdict_of --receipt "$tmp/clean.json" --advisory)"
[[ "$v" == "SHELF_EXERCISED_CLEAN" ]] || fail "hit receipt should be EXERCISED_CLEAN, got $v"
python3 "$tool" classify --receipt "$tmp/clean.json" --require-exercised-clean >/dev/null

# --- Twin 4: crime event → EXERCISED_CRIME (not silence) ---
python3 "$tool" open --output "$tmp/crime.json"
python3 "$tool" event --output "$tmp/crime.json" --op crime --outcome crime \
  --crime unevictable-shelf-cell --name sugar
v="$(verdict_of --receipt "$tmp/crime.json" --advisory)"
[[ "$v" == "SHELF_EXERCISED_CRIME" ]] || fail "crime receipt should be EXERCISED_CRIME, got $v"

# Named shelf-verifier and recovery crimes remain instrumented after the
# generic corrupt/ownership terminals split. A more truthful reason must not
# disappear from the shelf-exercise receipt.
for named_crime in shelf-manifest-identity-mismatch read-only-shelf-recovery; do
  cat >"$tmp/named-crime.log" <<LOG
sugarbin: crime=$named_crime owner=bin/sugarbin cell=/cache/cas/x/sugar
LOG
  v="$(verdict_of --log "$tmp/named-crime.log" --advisory)"
  [[ "$v" == "SHELF_EXERCISED_CRIME" ]] || fail \
    "$named_crime log should be EXERCISED_CRIME, got $v"
done

# --- Twin 5: log of the 2026-08-01 failed recensus shape → NEVER_TOUCHED ---
# Identity/sourceStamp only; no filesystem shelf lines (the real failure mode).
cat >"$tmp/recensus-early-death.log" <<'LOG'
##[group]Prepare immutable Python test environment
environment identity: 3f098a85c3c6bd38269cce5b88ffd4e56bad737a4a1deb4d081ad8ce6e6112d5
- sourceStamp: `blake3-512_b536f988a64aa054491a35399fd25a8d5e296a07ab9c4738fcc64a8b05bb81163e06b79d35ec30ee58f4002a547fbf2382b45d1a72875e72d1105a4c1f5e0d05`
b3sum 1.8.1
##[error]cannot authenticate pandas corpus for the recensus
ExecutionEnvironmentMismatch: lift import escaped the synced checkout
LOG
v="$(verdict_of --log "$tmp/recensus-early-death.log" --advisory)"
[[ "$v" == "SHELF_UNMEASURED" || "$v" == "SHELF_NEVER_TOUCHED" ]] || fail \
  "early-death log must not be EXERCISED_CLEAN, got $v"
[[ "$v" != "SHELF_EXERCISED_CLEAN" ]] || fail "early-death log must not load-clear"

# --- Twin 6: log with shelf hit → EXERCISED_CLEAN ---
cat >"$tmp/shelf-hit.log" <<'LOG'
sugarbin: filesystem shelf hit for sugar content blake3-512_abc
LOG
v="$(verdict_of --log "$tmp/shelf-hit.log" --advisory)"
[[ "$v" == "SHELF_EXERCISED_CLEAN" ]] || fail "hit log should be EXERCISED_CLEAN, got $v"

# --- Twin 7: log with shelf crime → EXERCISED_CRIME ---
cat >"$tmp/shelf-crime.log" <<'LOG'
sugarbin: crime=unevictable-shelf-cell owner=bin/sugarbin cell=/cache/cas/x/sugar
LOG
v="$(verdict_of --log "$tmp/shelf-crime.log" --advisory)"
[[ "$v" == "SHELF_EXERCISED_CRIME" ]] || fail "crime log should be EXERCISED_CRIME, got $v"

# --- Twin 8: resolve log without shelf → NEVER_TOUCHED ---
cat >"$tmp/resolve-only.log" <<'LOG'
sugarbin: local target cache hit for sugar
sugarbin: building sugar once for this session (set SUGAR_BIN to skip)
LOG
v="$(verdict_of --log "$tmp/resolve-only.log" --advisory)"
[[ "$v" == "SHELF_NEVER_TOUCHED" ]] || fail "resolve-only log should be NEVER_TOUCHED, got $v"

# --- Twin 9: sugarbin producer wires open + event when receipt enrolled ---
if command -v python3 >/dev/null 2>&1; then
  export SUGAR_SHELF_EXERCISE_RECEIPT="$tmp/from-sugarbin.json"
  # Drive the reporter the same way log() does — static tooth that the helper
  # names exist in bin/sugarbin.
  grep -Fq 'shelf_exercise_open_resolve' "$repo/bin/sugarbin" || fail "sugarbin missing open hook"
  grep -Fq 'shelf_exercise_note_log' "$repo/bin/sugarbin" || fail "sugarbin missing log hook"
  grep -Fq 'tools/shelf_exercise_report.py' "$repo/bin/sugarbin" || fail "sugarbin missing reporter path"
  # Simulate the log path the hooks use
  python3 "$tool" open --output "$SUGAR_SHELF_EXERCISE_RECEIPT"
  # empty after open → NEVER_TOUCHED
  v="$(verdict_of --receipt "$SUGAR_SHELF_EXERCISE_RECEIPT" --advisory)"
  [[ "$v" == "SHELF_NEVER_TOUCHED" ]] || fail "producer open-only → NEVER_TOUCHED, got $v"
  python3 "$tool" event --output "$SUGAR_SHELF_EXERCISE_RECEIPT" --op publish --outcome already --name sugar
  v="$(verdict_of --receipt "$SUGAR_SHELF_EXERCISE_RECEIPT" --advisory)"
  [[ "$v" == "SHELF_EXERCISED_CLEAN" ]] || fail "producer publish → CLEAN, got $v"
fi

echo "PASS: R_shelf_exercise — EXERCISED_CLEAN ≠ NEVER_TOUCHED ≠ UNMEASURED ≠ CRIME"
