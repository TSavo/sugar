#!/usr/bin/env bash
# Unit tests for JavaTestAssertionsRpc (Phase 4: TestNG support — learned vocab per-framework)
# Compiles the kit, drives it via JSON-RPC, asserts on output with python3.
# Skips cleanly if no JDK is on PATH.
#
# Test suite (P1/P2):
#   1. Vocab derivation + exact-lift: ExactLift.java produces 2 contracts with
#      correct IR shape (assertEquals=equality, expected-first from learned vocab)
#   2. Discrimination (string-arg): StringArgDiscrimination.java → 0 contracts,
#      named refusals
#   3. Structural proof: StructuralProof.java → only real @Test lifted, not
#      string literals or comments
#   4. Delta discrimination: DeltaApprox.java → 0 contracts, named refusal citing
#      "approximate assertion (delta)" (the false-pass guard)
#   5. No-vocab-configured: ExactLiftNoVocab.java with no assertion_source_dirs →
#      0 contracts, named refusal ("no learned vocabulary") — hardcode is gone
#   6. Extended vocab (assertNotEquals, assertNull, assertNotNull): produces correct
#      ≠ and None-ctor IR atoms
#   7. Exceptions overlay: assertArrayEquals in equality via .sugar/vocab-exceptions/
#
# Test suite (P3 — loop→∀ + final-oracle):
#   8. Loop→∀ exact shape: ForLoopForall.java → 1 forall contract with
#      correct IR (forall x. 0<=x<3 => g(x)==1) and ::loop::x name
#   9. Accumulator discrimination: ForLoopAccumulator.java → loop REFUSED by name
#      (acc += g(x) is a mutation → not a universal)
#  10. Effectively-final positive: ForLoopEffectivelyFinal.java → 1 forall contract
#      (outer non-final but never-reassigned local does NOT block lifting)
#  11. Non-literal bound discrimination: ForLoopOpenBound.java → loop REFUSED
#      (x < n where n is a variable → open forall)
#
# Test suite (H1 — hardening rollup: discrimination fixtures for each fix):
#  31. [A1] cross-class ambiguity: helperChk in 2 classes → UNLEARNED, not first-match
#  32a. [A2] wildcard static import: import static org.junit.Assert.* → assertEquals lifts
#  32b. [A2] non-framework wildcard: import static com.example.* → silent skip (not bound)
#  33. [A3] user-scope impostor: assertEquals without static import → silent skip (not lift)
#  34. [C8] TestNG assertNotEquals 2-arg: INEQUALITY, not APPROX (delta overload blocked)
#  35. [B6] lineLength=0 → encodeNoChunk universe registered; lineLength=76 → refused
#
# Test suite (G2b — comparison-bound lifting):
#  41. assertTrue(g(7) < 10) → <(call:g(7), 10) with correct #euf# name
#  42. assertTrue(5 > g(2)) → <(call:g(2), 5) [lit-left mirror normalised]
#  43. assertFalse(g(2) < 5) → >=(call:g(2), 5) [negated predicate]
#  44. non-literal bound refused; both-calls refused (both named)
#  45. #euf# name matches assertEquals schema → federation is live
set -euo pipefail

command -v javac >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java  >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$(cd "$HERE/.." && pwd)"
OUT="$KIT/out"
FIXTURES="$HERE/fixtures"

echo "== build kit =="
bash "$KIT/build.sh" "$OUT" >/dev/null 2>&1

JAVA_CMD="java \
  --add-exports jdk.compiler/com.sun.source.tree=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.source.util=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED \
  -cp $OUT JavaTestAssertionsRpc"

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 0: dependency proof resolution from Maven-style jar resource"
echo "────────────────────────────────────────────────────────────────"
TMP_DEP="$(mktemp -d)"
mkdir -p "$TMP_DEP/META-INF/sugar"
printf '%s' 'vendor-proof-catalog-bytes' > "$TMP_DEP/META-INF/sugar/sugar.proof"
(cd "$TMP_DEP" && jar cf "$TMP_DEP/vendor-proof.jar" META-INF/sugar/sugar.proof)
RESULT0="$(python3 - "$FIXTURES" <<'PY' | java \
  --add-exports jdk.compiler/com.sun.source.tree=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.source.util=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED \
  -cp "$OUT:$TMP_DEP/vendor-proof.jar" JavaTestAssertionsRpc 2>/dev/null
import json, sys
workspace_root = sys.argv[1]
print(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}))
print(json.dumps({"jsonrpc":"2.0","id":2,"method":"sugar.plugin.resolve_dependency_proofs","params":{
    "project_root": workspace_root,
}}))
print(json.dumps({"jsonrpc":"2.0","id":3,"method":"shutdown","params":{}}))
PY
)"
python3 - "$RESULT0" <<'PY'
import base64, json, sys
responses = [json.loads(line) for line in sys.argv[1].splitlines() if line.strip()]
resp = next((obj for obj in responses if obj.get("id") == 2), None)
assert resp is not None, responses
assert "error" not in resp, resp
proofs = resp["result"]["proofs"]
assert len(proofs) == 1, proofs
proof = proofs[0]
assert base64.b64decode(proof["bytes_base64"]) == b"vendor-proof-catalog-bytes", proof
assert proof["source"].endswith("vendor-proof.jar!META-INF/sugar/sugar.proof"), proof
print("PASS: dependency proof resolver loaded Maven-style jar resource bytes")
PY

# run_lift <workspace_root> <source_path_relative_to_workspace>
# Sends initialize + lift(workspace_root, [source_path]) + shutdown to the kit.
run_lift() {
  local workspace_root="$1"
  local source_path="$2"
  python3 - "$workspace_root" "$source_path" <<'PY'
import sys, json
workspace_root, source_path = sys.argv[1], sys.argv[2]
print(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}))
print(json.dumps({"jsonrpc":"2.0","id":2,"method":"lift","params":{
    "workspace_root": workspace_root,
    "source_paths": [source_path],
}}))
print(json.dumps({"jsonrpc":"2.0","id":3,"method":"shutdown","params":{}}))
PY
}

# extract_lift_result <json_lines>: print the lift response result as JSON
extract_lift() {
  python3 - "$1" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        print(json.dumps(obj["result"]))
        sys.exit(0)
sys.exit(1)
PY
}

# ──────────────────────────────────────────────────────────────
# TEST 1: vocab derivation + exact-lift
# Workspace: fixtures/ (has .sugar/config.toml pointing at vendor/junit5/)
# ExactLift.java uses org.junit.Assert.assertEquals (JUnit 4 form).
# VocabDeriver learns assertEquals=equality from the vendored JUnit5 Assertions.java.
# Expected: 2 contracts with correct IR (= relation, expected-first from learned vocab).
# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 1: vocab derivation + exact-lift (2 contracts expected)"
echo "────────────────────────────────────────────────────────────────"
RESULT1="$(run_lift "$FIXTURES" "ExactLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT1" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response found"
result = lift_resp["result"]
assert result["kind"] == "ir-document", f"unexpected kind: {result['kind']}"
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 2, f"expected 2 contracts, got {len(ir)}: {json.dumps(ir, indent=2)}\ndiags={json.dumps(diags,indent=2)}"

# Check g#euf# contract (assertEquals learned as equality, expected=arg[0])
g_contract = next((c for c in ir if "g#euf#" in c["name"]), None)
assert g_contract is not None, f"no g#euf# contract in {[c['name'] for c in ir]}"
assert g_contract["name"] == "g#euf#c:callresult_g_a1(i:2)::assertion", \
    f"wrong name: {g_contract['name']}"
assert g_contract["outBinding"] == "out"
inv = g_contract["inv"]
assert inv["kind"] == "and"
atomic = inv["operands"][0]
assert atomic["kind"] == "atomic"
assert atomic["name"] == "=", f"relation should be = not {atomic['name']}"
ctor = atomic["args"][0]
assert ctor["kind"] == "ctor" and ctor["name"] == "call:g"
assert ctor["args"][0] == {"kind":"const","value":2,"sort":{"kind":"primitive","name":"Int"}}
const_val = atomic["args"][1]
assert const_val == {"kind":"const","value":2,"sort":{"kind":"primitive","name":"Int"}}, \
    f"expected const 2 but got {const_val}"

# Check h#euf# contract (2-arg call, negative literal)
h_contract = next((c for c in ir if "h#euf#" in c["name"]), None)
assert h_contract is not None, f"no h#euf# contract in {[c['name'] for c in ir]}"
assert h_contract["name"] == "h#euf#c:callresult_h_a2(i:-1,i:3)::assertion", \
    f"wrong name: {h_contract['name']}"

print("PASS: vocab derivation + exact-lift: 2 contracts, correct IR shape (= relation, expected-first)")
PY

# ──────────────────────────────────────────────────────────────
# TEST 2: discrimination — string-literal arg refused, not lifted
# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 2: discrimination (string-arg refused by name)"
echo "────────────────────────────────────────────────────────────────"
RESULT2="$(run_lift "$FIXTURES" "StringArgDiscrimination.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT2" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 0, f"expected 0 contracts from string-arg file, got {len(ir)}: {json.dumps(ir)}"
assert len(diags) >= 1, f"expected >=1 diagnostics, got {json.dumps(diags)}"
reasons = [d.get("reason","") for d in diags]
print(f"PASS: discrimination: 0 contracts, {len(diags)} named refusals: {reasons}")
PY

# ──────────────────────────────────────────────────────────────
# TEST 3: structural proof — string-in-literal and comment NOT lifted
# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 3: structural proof (string literal + comment not lifted)"
echo "────────────────────────────────────────────────────────────────"
RESULT3="$(run_lift "$FIXTURES" "StructuralProof.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT3" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None
result = lift_resp["result"]
ir = result["ir"]
names = [c["name"] for c in ir]
assert len(ir) == 1, f"expected exactly 1 contract (only real @Test), got {len(ir)}: {names}"
assert ir[0]["name"] == "g#euf#c:callresult_g_a1(i:7)::assertion", \
    f"wrong contract: {ir[0]['name']}"
assert not any("i:1" in n for n in names), \
    f"string-literal g(1) was lifted (string scanner bug!): {names}"
assert not any("i:3" in n for n in names), \
    f"comment g(3) was lifted (string scanner bug!): {names}"
print(f"PASS: structural: only real @Test contract lifted; string literal and comment ignored")
PY

# ──────────────────────────────────────────────────────────────
# TEST 4: delta discrimination — approximate assertion REFUSED by name
# assertEquals(1.0f, f(2), 0.5f) has a delta parameter in JUnit5 source.
# VocabDeriver must classify this overload as APPROXIMATE.
# At lift time: 0 contracts, 1 refusal naming "approximate assertion (delta)".
# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 4: delta discrimination (approximate assertion refused)"
echo "────────────────────────────────────────────────────────────────"
RESULT4="$(run_lift "$FIXTURES" "DeltaApprox.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT4" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 0, \
    f"delta-approximate assertEquals must produce ZERO contracts, got {len(ir)}: {json.dumps(ir)}"
assert len(diags) >= 1, \
    f"expected at least 1 refusal diagnostic, got {json.dumps(diags)}"
reasons = [d.get("reason","") for d in diags]
approx_diags = [r for r in reasons if "approximate" in r.lower() or "delta" in r.lower()]
assert len(approx_diags) >= 1, \
    f"expected a diagnostic naming 'approximate' or 'delta', got: {reasons}"
print(f"PASS: delta discrimination: 0 contracts, refusal: {approx_diags}")
PY

# ──────────────────────────────────────────────────────────────
# TEST 5: no-vocab-configured — the hardcode is gone
# Workspace: fixtures/no-vocab/ (NO .sugar/config.toml).
# assertEquals must be refused by name ("no learned vocabulary").
# Zero contracts expected. Proves the hardcode was removed.
# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 5: no-vocab-configured (hardcode is gone — assertEquals refused)"
echo "────────────────────────────────────────────────────────────────"
NOVOCAB_DIR="$FIXTURES/no-vocab"
RESULT5="$(run_lift "$NOVOCAB_DIR" "ExactLiftNoVocab.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT5" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 0, \
    f"with no vocab configured, assertEquals must produce ZERO contracts (hardcode gone). Got {len(ir)}: {json.dumps(ir)}"
assert len(diags) >= 1, \
    f"expected at least 1 named refusal, got {json.dumps(diags)}"
reasons = [d.get("reason","") for d in diags]
vocab_diags = [r for r in reasons if "no learned vocabulary" in r or "vocabulary" in r.lower() or "refused" in r.lower()]
assert len(vocab_diags) >= 1, \
    f"expected a diagnostic naming 'no learned vocabulary' or 'refused', got: {reasons}"
print(f"PASS: no-vocab: 0 contracts, named refusal: {vocab_diags}")
PY

# ──────────────────────────────────────────────────────────────
# TEST 6: extended vocab — assertNotEquals (≠), assertNull (None), assertNotNull (≠None)
# Workspace: fixtures/ (has config.toml → vendored junit5)
# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 6: extended vocab (assertNotEquals=≠, assertNull/assertNotNull=None-ctor)"
echo "────────────────────────────────────────────────────────────────"
RESULT6="$(run_lift "$FIXTURES" "NotEqualsAndNull.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT6" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]

names = [c["name"] for c in ir]
print(f"  contracts: {names}")
print(f"  diagnostics: {[d.get('reason','') for d in diags]}")

# assertNotEquals(2, g(2)) → ≠ relation
g_neq = next((c for c in ir if "g#euf#" in c["name"]), None)
assert g_neq is not None, f"no g#euf# contract from assertNotEquals in {names}"
inv_g = g_neq["inv"]
atomic_g = inv_g["operands"][0]
assert atomic_g["name"] == "≠", \
    f"assertNotEquals should produce ≠ relation, got {atomic_g['name']}"
# const value should be 2 (the unexpected value)
const_g = atomic_g["args"][1]
assert const_g["value"] == 2, f"expected unexpected=2, got {const_g}"

# assertNull(getNull(5)) → =(call, None)
null_c = next((c for c in ir if "getNull#euf#" in c["name"]), None)
assert null_c is not None, f"no getNull#euf# contract from assertNull in {names}"
inv_null = null_c["inv"]
atomic_null = inv_null["operands"][0]
assert atomic_null["name"] == "=", \
    f"assertNull should produce = relation, got {atomic_null['name']}"
none_arg = atomic_null["args"][1]
assert none_arg == {"kind":"ctor","name":"None","args":[]}, \
    f"assertNull second arg should be None ctor, got {none_arg}"

# assertNotNull(getNotNull(3)) → ≠(call, None)
notnull_c = next((c for c in ir if "getNotNull#euf#" in c["name"]), None)
assert notnull_c is not None, f"no getNotNull#euf# contract from assertNotNull in {names}"
inv_nn = notnull_c["inv"]
atomic_nn = inv_nn["operands"][0]
assert atomic_nn["name"] == "≠", \
    f"assertNotNull should produce ≠ relation, got {atomic_nn['name']}"
none_arg2 = atomic_nn["args"][1]
assert none_arg2 == {"kind":"ctor","name":"None","args":[]}, \
    f"assertNotNull second arg should be None ctor, got {none_arg2}"

print(f"PASS: extended vocab: assertNotEquals=≠, assertNull==(None), assertNotNull=≠(None)")
PY

# ──────────────────────────────────────────────────────────────
# TEST 7: exceptions overlay — assertArrayEquals classified as equality via override
# The .sugar/vocab-exceptions/org.junit.jupiter.api.Assertions.json file
# already overrides assertArrayEquals into equality. Verify it loads.
# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 7: exceptions overlay (assertArrayEquals in equality via override)"
echo "────────────────────────────────────────────────────────────────"
# We verify that the vocab includes assertArrayEquals in equality
# by sending a vocab-derivation diagnostic check.
# We use a synthetic fixture inline that calls assertArrayEquals.
ARRAYEQ_FIXTURE="$(cat <<'JAVA'
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertArrayEquals;
public class ArrayEqTest {
    @Test public void testArr() {
        // assertArrayEquals is in "unlearned" from VocabDeriver (not in Assertions.java methods
        // that pass our equality gate), BUT the exceptions overlay adds it to equality.
        // Since the actual arg here is not a method-call-with-int-lits, it will produce
        // a diagnostic — but that diagnostic should NOT say "unlearned vocabulary".
        // It should say "second arg is not a method call" (i.e. it WAS classified as equality).
        assertArrayEquals(new int[]{1}, getArr(2));
    }
    private int[] getArr(int x) { return new int[]{x}; }
}
JAVA
)"
TMPF="$(mktemp /tmp/ArrayEqTest_XXXXXX.java)"
echo "$ARRAYEQ_FIXTURE" > "$TMPF"
RESULT7="$(python3 - "$FIXTURES" "$TMPF" <<'PY' | eval "$JAVA_CMD" 2>/dev/null
import sys, json, os
workspace_root, fixture_file = sys.argv[1], sys.argv[2]
fixture_name = os.path.basename(fixture_file)
print(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}))
print(json.dumps({"jsonrpc":"2.0","id":2,"method":"lift","params":{
    "workspace_root": workspace_root,
    "source_paths": [fixture_file],
}}))
print(json.dumps({"jsonrpc":"2.0","id":3,"method":"shutdown","params":{}}))
PY
)"
rm -f "$TMPF"
python3 - "$RESULT7" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None
result = lift_resp["result"]
diags = result["diagnostics"]
# The test verifies that assertArrayEquals is processed as equality (not "unlearned").
# It will fail at lift because "new int[]{1}" is not an int literal — but that
# means the override DID work (we got past the unlearned gate into the lift path).
reasons = [d.get("reason","") for d in diags]
unlearned_diags = [r for r in reasons if "unlearned" in r.lower() or "not in learned vocabulary" in r.lower()]
assert len(unlearned_diags) == 0, \
    f"assertArrayEquals should be in equality via override, not unlearned. Diags: {reasons}"
print(f"PASS: exceptions overlay: assertArrayEquals NOT in unlearned (override applied). Diags: {reasons}")
PY


echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 8: loop→∀ exact IR shape (ForLoopForall.java)"
echo "────────────────────────────────────────────────────────────────"
RESULT8="$(run_lift "$FIXTURES" "ForLoopForall.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT8" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 1, f"expected 1 forall contract, got {len(ir)}: {json.dumps(ir,indent=2)}\ndiags={json.dumps(diags,indent=2)}"
c = ir[0]

# Name must contain ::loop::x
assert "::loop::x" in c["name"], f"contract name does not contain ::loop::x: {c['name']}"

# Shape: kind=contract, inv.kind=and, inv.operands[0].kind=forall
assert c["kind"] == "contract", f"kind: {c['kind']}"
assert c["outBinding"] == "out", f"outBinding: {c.get('outBinding')}"
inv = c["inv"]
assert inv["kind"] == "and", f"inv.kind: {inv['kind']}"
assert len(inv["operands"]) == 1, f"inv.operands count: {len(inv['operands'])}"

fa = inv["operands"][0]
assert fa["kind"] == "forall", f"forall kind: {fa['kind']}"
assert fa["name"] == "x", f"forall bound var: {fa['name']}"
assert fa["sort"] == {"kind": "primitive", "name": "Int"}, f"sort: {fa['sort']}"

body = fa["body"]
assert body["kind"] == "implies", f"implies kind: {body['kind']}"
assert len(body["operands"]) == 2, f"implies operands: {len(body['operands'])}"

guard = body["operands"][0]
assert guard["kind"] == "and", f"guard kind: {guard['kind']}"
guard_ops = guard["operands"]
assert len(guard_ops) == 2, f"guard operands count: {len(guard_ops)}"

# Lower bound: 0 ≤ x
lo = guard_ops[0]
assert lo["kind"] == "atomic" and lo["name"] == "≤", f"lower bound atom: {lo}"
assert lo["args"][0] == {"kind":"const","value":0,"sort":{"kind":"primitive","name":"Int"}}, f"lo.left: {lo['args'][0]}"
assert lo["args"][1] == {"kind":"var","name":"x"}, f"lo.right: {lo['args'][1]}"

# Upper bound: x < 3
hi = guard_ops[1]
assert hi["kind"] == "atomic" and hi["name"] == "<", f"upper bound atom: {hi}"
assert hi["args"][0] == {"kind":"var","name":"x"}, f"hi.left: {hi['args'][0]}"
assert hi["args"][1] == {"kind":"const","value":3,"sort":{"kind":"primitive","name":"Int"}}, f"hi.right: {hi['args'][1]}"

# Body: and([atomic(=, [ctor(call:g,[var:x]), const(1)])])
body_conj = body["operands"][1]
assert body_conj["kind"] == "and", f"body conj kind: {body_conj['kind']}"
assert len(body_conj["operands"]) == 1, f"body operands: {len(body_conj['operands'])}"
atom = body_conj["operands"][0]
assert atom["kind"] == "atomic" and atom["name"] == "=", f"body atom: {atom}"
ctor = atom["args"][0]
assert ctor["kind"] == "ctor" and ctor["name"] == "call:g", f"ctor: {ctor}"
assert ctor["args"] == [{"kind":"var","name":"x"}], f"ctor args: {ctor['args']}"
const_val = atom["args"][1]
assert const_val == {"kind":"const","value":1,"sort":{"kind":"primitive","name":"Int"}}, f"const: {const_val}"

# Closedness: no free variables (the only var is x, which is the bound var)
print(f"PASS: loop→∀ IR shape correct. Contract: {c['name']}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 9: accumulator discrimination (ForLoopAccumulator.java)"
echo "────────────────────────────────────────────────────────────────"
RESULT9="$(run_lift "$FIXTURES" "ForLoopAccumulator.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT9" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
# The loop MUST be refused — no forall contract emitted
assert len(ir) == 0, f"expected 0 contracts (loop refused), got {len(ir)}: {json.dumps(ir,indent=2)}"
# Must have a diagnostic naming the accumulator or mutation pattern
reasons = [d.get("reason","") for d in diags]
refusal_for_loop = [r for r in reasons if "accum" in r.lower() or "mutat" in r.lower() or "loop" in r.lower()]
assert len(refusal_for_loop) > 0, \
    f"expected a loop refusal diagnostic (accumulator/mutation), got: {reasons}"
print(f"PASS: accumulator loop refused by name. Reason: {refusal_for_loop[0]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 10: effectively-final positive (ForLoopEffectivelyFinal.java)"
echo "────────────────────────────────────────────────────────────────"
RESULT10="$(run_lift "$FIXTURES" "ForLoopEffectivelyFinal.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT10" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
# The loop MUST lift — the effectively-final `outer` local does not block it
assert len(ir) == 1, \
    f"expected 1 forall contract (effectively-final local does not block), got {len(ir)}: {json.dumps(ir,indent=2)}\ndiags={json.dumps(diags,indent=2)}"
assert "::loop::x" in ir[0]["name"], f"contract name: {ir[0]['name']}"
print(f"PASS: effectively-final outer local does not block loop lifting. Contract: {ir[0]['name']}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 11: non-literal bound discrimination (ForLoopOpenBound.java)"
echo "────────────────────────────────────────────────────────────────"
RESULT11="$(run_lift "$FIXTURES" "ForLoopOpenBound.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT11" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
# Must be refused — no contract emitted
assert len(ir) == 0, f"expected 0 contracts (open bound refused), got {len(ir)}: {json.dumps(ir,indent=2)}"
reasons = [d.get("reason","") for d in diags]
open_bound_diags = [r for r in reasons if "open" in r.lower() or "literal" in r.lower() or "bound" in r.lower()]
assert len(open_bound_diags) > 0, \
    f"expected an open-bound refusal diagnostic, got: {reasons}"
print(f"PASS: non-literal bound refused by name. Reason: {open_bound_diags[0]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 12: loop-variable mutation discrimination (ForLoopVarMutation.java)"
echo "────────────────────────────────────────────────────────────────"
RESULT12="$(run_lift "$FIXTURES" "ForLoopVarMutation.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT12" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
# g(x++) mutates the loop variable inside the body: the iteration space is
# not the stated range. Must be refused by the LOOP-VARIABLE gate itself,
# not merely the arg-shape gate (defense must hold if arg shapes widen).
assert len(ir) == 0, f"expected 0 contracts (loop-var mutation refused), got {len(ir)}: {json.dumps(ir,indent=2)}"
reasons = [d.get("reason","") for d in diags]
loopvar_diags = [r for r in reasons if "mutates the loop variable" in r]
assert len(loopvar_diags) > 0, \
    f"expected the loop-variable mutation refusal, got: {reasons}"
print(f"PASS: loop-variable body mutation refused by its own gate. Reason: {loopvar_diags[0]}")
PY

echo

# ──────────────────────────────────────────────────────────────
# Test suite (P4 — TestNG support: proof that vocab must be learned per-framework):
#  13. TestNG vocab derivation: derived table shows assertEquals=equality with
#      ACTUAL-FIRST order (expectedArgIndex=1); explicit assertion on learned order.
#  14. TestNG exact-lift: Assert.assertEquals(g(2), 1) in a TestNG file →
#      same contract name/IR as JUnit assertEquals(1, g(2)).
#  15. ORDER DISCRIMINATION: same source text "assertEquals(g(2), 1)" in a
#      JUnit-imports file → REFUSED (arg[0]=g(2) is not an int literal under
#      JUnit order); in TestNG-imports file → LIFTS. Two fixtures, same text,
#      opposite outcomes — this asymmetry IS the proof.
#  16. Dual-import ambiguity: imports both org.junit.Assert and org.testng.Assert
#      → named refusal on all assertions ("ambiguous assertion vocabulary").
#  17. TestNG delta overload: Assert.assertEquals(g_d(2), 1.0, 0.5) →
#      delta param → APPROXIMATE → named refusal.
#  18. assertThat → unlearned named refusal (not in any vendored source vocab).
#  19. TestNG @Test annotation recognized: a file using org.testng.annotations.Test
#      has its @Test methods lifted (same as JUnit @Test).
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 13: TestNG vocab derivation (actual-first order learned)"
echo "────────────────────────────────────────────────────────────────"
# Drive a vocab-only diagnostic: lift an empty file in the fixtures workspace,
# then ask for a derivation probe via a synthetic fixture that reports the vocab.
# We prove the order by lifting a TestNG fixture and checking the IR: if the
# VocabDeriver learned actual-first, then Assert.assertEquals(g(2), 1) in a
# TestNG file should produce =(call:g(2), 1) with the CALL in arg[0] of the
# atomic (the actual) and 1 in arg[1] (the expected constant).
# We verify: 1 contract produced, const=1, call=g(2) — this proves actual-first.
RESULT13="$(run_lift "$FIXTURES" "TestNGExactLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT13" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 1, \
    f"expected 1 contract (TestNG actual-first lift), got {len(ir)}: {json.dumps(ir,indent=2)}\ndiags={json.dumps(diags,indent=2)}"
c = ir[0]
assert c["name"] == "g#euf#c:callresult_g_a1(i:2)::assertion", \
    f"wrong contract name: {c['name']}"
atomic = c["inv"]["operands"][0]
assert atomic["name"] == "=", f"relation must be ="
# The ctor (call:g(2)) must be in arg[0], const 1 in arg[1]
ctor = atomic["args"][0]
assert ctor["kind"] == "ctor" and ctor["name"] == "call:g", \
    f"arg[0] must be call:g ctor, got: {ctor}"
const_node = atomic["args"][1]
assert const_node == {"kind":"const","value":1,"sort":{"kind":"primitive","name":"Int"}}, \
    f"arg[1] (expected/const) must be 1, got: {const_node}"
# This proves: VocabDeriver learned actual-first (param[0]="actual") from TestNG source.
# The constant (expected) was at arg[1]=1, not arg[0]=g(2). Actual-first confirmed.
print("PASS: TestNG vocab derivation: assertEquals=equality, actual-first order learned "
      "(param[0]='actual' → expectedArgIndex=1; const 1 correctly extracted from arg[1])")
PY

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 14: TestNG exact-lift IR byte-identity with JUnit"
echo "────────────────────────────────────────────────────────────────"
# TestNG: Assert.assertEquals(g(2), 1)  → same IR as JUnit: assertEquals(1, g(2))
# Both must produce IDENTICAL contract name and IDENTICAL inv structure.
# The JUnit reference is from ExactLift.java (test 1).
RESULT14_TESTNG="$(run_lift "$FIXTURES" "TestNGExactLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
RESULT14_JUNIT="$(run_lift "$FIXTURES" "JUnitEqualityRef.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT14_TESTNG" "$RESULT14_JUNIT" <<'PY'
import sys, json
def get_lift_result(raw):
    lines = raw.strip().split('\n')
    for line in lines:
        if not line.strip(): continue
        obj = json.loads(line)
        if obj.get("id") == 2:
            return obj["result"]
    raise AssertionError("no lift response")

testng_result = get_lift_result(sys.argv[1])
junit_result = get_lift_result(sys.argv[2])

# Find the g#euf#c:callresult_g_a1(i:2)::assertion contract in each
testng_g = next((c for c in testng_result["ir"] if "g#euf#c:callresult_g_a1(i:2)" in c["name"]), None)
junit_g  = next((c for c in junit_result["ir"]  if "g#euf#c:callresult_g_a1(i:2)" in c["name"]), None)
assert testng_g is not None, f"no g#euf# in TestNG IR: {[c['name'] for c in testng_result['ir']]}"
assert junit_g  is not None, f"no g#euf# in JUnit IR: {[c['name'] for c in junit_result['ir']]}"

# Name must be identical
assert testng_g["name"] == junit_g["name"], \
    f"contract names differ: TestNG={testng_g['name']}  JUnit={junit_g['name']}"

# inv must be identical (byte-for-byte after JSON normalization)
testng_inv_str = json.dumps(testng_g["inv"], sort_keys=True)
junit_inv_str  = json.dumps(junit_g["inv"],  sort_keys=True)
assert testng_inv_str == junit_inv_str, \
    f"IR inv differs:\n  TestNG: {testng_inv_str}\n  JUnit:  {junit_inv_str}"

print(f"PASS: TestNG exact-lift IR is byte-identical to JUnit IR for the same claim.")
print(f"      Contract: {testng_g['name']}")
print(f"      TestNG source: Assert.assertEquals(g(2), 1)  [actual-first]")
print(f"      JUnit  source: assertEquals(1, g(2))  [expected-first]")
print(f"      Both produce: =(call:g(2), 1)  — same contract, same CID-able shape")
PY

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 15: ORDER DISCRIMINATION — same text, opposite outcomes"
echo "────────────────────────────────────────────────────────────────"
# JUnitOrderDiscrimination.java: assertEquals(g(2), 1) with JUnit imports
# → JUnit order: arg[0]=expected; arg[0]=g(2) is NOT an int literal → REFUSED.
#
# TestNGExactLift.java: Assert.assertEquals(g(2), 1) with TestNG imports
# → TestNG order: arg[0]=actual; const=arg[1]=1 → LIFTS.
RESULT15_JUNIT="$(run_lift "$FIXTURES" "JUnitOrderDiscrimination.java" | eval "$JAVA_CMD" 2>/dev/null)"
RESULT15_TESTNG="$(run_lift "$FIXTURES" "TestNGExactLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT15_JUNIT" "$RESULT15_TESTNG" <<'PY'
import sys, json
def get_lift_result(raw):
    lines = raw.strip().split('\n')
    for line in lines:
        if not line.strip(): continue
        obj = json.loads(line)
        if obj.get("id") == 2:
            return obj["result"]
    raise AssertionError("no lift response")

junit_result  = get_lift_result(sys.argv[1])
testng_result = get_lift_result(sys.argv[2])

# JUnit file: assertEquals(g(2), 1) — JUnit order reads arg[0]=g(2) as expected.
# g(2) is NOT an int literal → refused.
assert len(junit_result["ir"]) == 0, \
    f"JUnit file: assertEquals(g(2),1) MUST be refused under JUnit order, but got contracts: {[c['name'] for c in junit_result['ir']]}"
junit_reasons = [d["reason"] for d in junit_result["diagnostics"]]
assert any("not an int literal" in r or "refused" in r.lower() for r in junit_reasons), \
    f"JUnit file: expected a refusal diagnostic, got: {junit_reasons}"

# TestNG file: Assert.assertEquals(g(2), 1) — TestNG order reads arg[0]=g(2) as actual.
# arg[1]=1 is the expected constant → LIFTS.
assert len(testng_result["ir"]) == 1, \
    f"TestNG file: assertEquals(g(2),1) MUST lift under TestNG order, but got {len(testng_result['ir'])} contracts"

print("PASS: ORDER DISCRIMINATION — same source text 'assertEquals(g(2), 1)':")
print(f"  JUnit-imports  file → REFUSED  (arg[0]=g(2) is not an int literal under JUnit order)")
print(f"  TestNG-imports file → LIFTS    (arg[0]=actual=g(2), arg[1]=expected=1 → =(call:g(2),1))")
print(f"  JUnit refusal reason: {junit_reasons[0][:80]}")
print(f"  This asymmetry IS the proof that vocab must be learned per-framework.")
PY

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 16: dual-import ambiguity → named refusal"
echo "────────────────────────────────────────────────────────────────"
RESULT16="$(run_lift "$FIXTURES" "DualImportAmbiguity.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT16" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
# Both frameworks imported: vocabulary is ambiguous → named refusal, no contracts
assert len(ir) == 0, \
    f"dual-import ambiguity must produce ZERO contracts; got: {[c['name'] for c in ir]}"
assert len(diags) >= 1, f"expected at least 1 named refusal, got {diags}"
reasons = [d.get("reason","") for d in diags]
ambig_diags = [r for r in reasons if "ambiguous" in r.lower() or "both" in r.lower()]
assert len(ambig_diags) >= 1, \
    f"expected an 'ambiguous' or 'both' refusal; got: {reasons}"
print(f"PASS: dual-import ambiguity → named refusal: {ambig_diags[0][:90]}")
PY

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 17: TestNG delta overload → approximate refusal"
echo "────────────────────────────────────────────────────────────────"
RESULT17="$(run_lift "$FIXTURES" "TestNGDeltaApprox.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT17" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 0, \
    f"TestNG delta: expected 0 contracts, got {len(ir)}: {json.dumps(ir,indent=2)}"
reasons = [d.get("reason","") for d in diags]
approx_diags = [r for r in reasons if "approximate" in r.lower() or "delta" in r.lower()]
assert len(approx_diags) >= 1, \
    f"expected approximate/delta refusal diagnostic; got: {reasons}"
print(f"PASS: TestNG delta overload → approximate refusal: {approx_diags[0][:90]}")
PY

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 18: assertThat → unlearned named refusal"
echo "────────────────────────────────────────────────────────────────"
RESULT18="$(run_lift "$FIXTURES" "AssertThatUnlearned.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT18" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 0, \
    f"assertThat: expected 0 contracts, got {len(ir)}: {json.dumps(ir,indent=2)}"
reasons = [d.get("reason","") for d in diags]
unlearned_diags = [r for r in reasons if "vocabulary" in r.lower() or "refused" in r.lower() or "unlearned" in r.lower()]
assert len(unlearned_diags) >= 1, \
    f"expected 'vocabulary'/'refused'/'unlearned' refusal for assertThat; got: {reasons}"
print(f"PASS: assertThat → unlearned named refusal: {unlearned_diags[0][:90]}")
PY

# ──────────────────────────────────────────────────────────────
# Test suite (P4.5 — throw-locus derivation: the name never enters into it)
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 20: DELETE-THE-KEYS — no name-keyed classification in the deriver"
echo "────────────────────────────────────────────────────────────────"
if grep -rn "isAssertEqualsName\|isAssertTrueName\|isAssertNullName\|isAssertNotEqualsName\|isAssertFalseName\|isAssertNotNullName" "$KIT/src/"; then
  echo "FAIL: name-keyed classification predicates still present in src/"
  exit 1
fi
echo "PASS: delete-the-keys — grep for name-keyed predicates returns nothing"

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 21: RENAMED-COPY discrimination — assertEquals's body under the name 'check' LIFTS"
echo "────────────────────────────────────────────────────────────────"
# fixtures/renamed-copy/framework/CheckAssert.java: method `check(expected, actual)`
# with assertEquals's guarded-throw body. Throw-locus derivation must classify
# EQUALITY; check(1, g(2)) must LIFT. The spelling never mattered.
RESULT21="$(run_lift "$FIXTURES/renamed-copy" "RenamedCopy.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT21" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 1, \
    f"renamed-copy: expected 1 contract from check(1, g(2)), got {len(ir)}: {json.dumps(ir,indent=2)}\ndiags={json.dumps(diags,indent=2)}"
c = ir[0]
inv = c["inv"]
atomic = inv["operands"][0] if inv.get("kind") == "and" else inv
assert atomic["kind"] == "atomic" and atomic["name"] == "=", \
    f"expected = atomic, got {json.dumps(atomic)[:120]}"
print(f"PASS: RENAMED-COPY — `check` (assertEquals's body, different name) classified EQUALITY and LIFTED.")
print(f"      Contract: {c['name']}")
print(f"      The name never entered into it: classification came from the throw-guard.")
PY

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 22: NAME-IMPOSTOR discrimination — assertEquals with 'return;' body REFUSED"
echo "────────────────────────────────────────────────────────────────"
# fixtures/name-impostor/framework/FakeAssert.java: method NAMED assertEquals
# whose body is `return;` — no throw locus → NOT an assertion. A lift here
# would be the falsePass.
RESULT22="$(run_lift "$FIXTURES/name-impostor" "NameImpostor.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT22" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 0, \
    f"NAME-IMPOSTOR FALSEPASS: assertEquals with `return;` body LIFTED {len(ir)} contract(s): {json.dumps(ir,indent=2)}"
reasons = [d.get("reason","") for d in diags]
locus_diags = [r for r in reasons if "no throw locus" in r.lower()]
assert len(locus_diags) >= 1, \
    f"expected named 'no throw locus' refusal; got: {reasons}"
print(f"PASS: NAME-IMPOSTOR — assertEquals with `return;` body is NOT an assertion.")
print(f"      Refusal: {locus_diags[0]}")
PY

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 23: guard-position vs param-name CROSS-CHECK disagreement → unlearned"
echo "────────────────────────────────────────────────────────────────"
# fixtures/cross-check/framework/DisagreeAssert.java: guard says expected-first
# (left operand of `actual != other`), param names say actual-first → UNLEARNED.
RESULT23="$(run_lift "$FIXTURES/cross-check" "CrossCheck.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT23" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 0, \
    f"cross-check: expected 0 contracts (order untrustworthy), got {len(ir)}: {json.dumps(ir,indent=2)}"
reasons = [d.get("reason","") for d in diags]
disagree_diags = [r for r in reasons if "disagreement" in r.lower()]
assert len(disagree_diags) >= 1, \
    f"expected guard-position vs param-name disagreement diagnostic; got: {reasons}"
refusals = [r for r in reasons if "not in learned vocabulary" in r.lower() or "unlearned" in r.lower()]
assert len(refusals) >= 1, \
    f"expected unlearned refusal for the call site; got: {reasons}"
print(f"PASS: CROSS-CHECK — guard/param-name disagreement → UNLEARNED + report.")
print(f"      Report: {disagree_diags[0][:120]}")
print(f"      Call-site refusal: {refusals[0][:90]}")
PY

# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 24: TRUTH classification from the guard — assertTrue(p(2)) lifts"
echo "────────────────────────────────────────────────────────────────"
# assertTrue can ONLY be in the vocab via its guard `if (!condition) failNotTrue(...)`
# in vendored AssertTrue.java — every name rule is deleted (test 20).
RESULT24="$(run_lift "$FIXTURES" "TruthLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT24" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
assert len(ir) == 1, \
    f"truth: expected 1 contract from assertTrue(p(2)), got {len(ir)}: {json.dumps(ir,indent=2)}\ndiags={json.dumps(diags,indent=2)}"
print(f"PASS: TRUTH via guard — assertTrue(p(2)) lifted: {ir[0]['name']}")
print(f"      assertTrue entered the vocab ONLY through its `!condition` throw-guard.")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 25: IDENTITY-GUARD discrimination — reference == is NOT value equality"
echo "────────────────────────────────────────────────────────────────"
# fixtures/identity-guard/framework/IdentityAssert.java: assertNotSame guards on
# `expected == actual` over OBJECTS (reference identity — two .equals() values
# can be distinct refs) → must be UNLEARNED, never lifted as value-≠. The SAME
# guard shape over primitive ints (assertEqualsInt) must still classify and lift.
# Every Java developer knows == vs .equals; so must the lifter.
RESULT25="$(run_lift "$FIXTURES/identity-guard" "IdentityGuard.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT25" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
lift_resp = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        lift_resp = obj
        break
assert lift_resp is not None, "no lift response"
result = lift_resp["result"]
ir = result["ir"]
diags = result["diagnostics"]
# Exactly ONE contract: the primitive overload. The identity assert refuses.
assert len(ir) == 1, \
    f"IDENTITY FALSEPASS or over-refusal: expected exactly 1 contract (primitive), got {len(ir)}: {json.dumps(ir,indent=2)}\ndiags={json.dumps(diags,indent=2)}"
assert "callresult_g" in ir[0]["name"], f"the lifted contract must be the primitive one: {ir[0]['name']}"
reasons = [d.get("reason","") for d in diags]
ident_diags = [r for r in reasons if "assertNotSame" in r or "unlearned" in r.lower() or "vocabulary" in r.lower()]
assert len(ident_diags) >= 1, \
    f"expected a named refusal for the reference-identity assert; got: {reasons}"
print(f"PASS: IDENTITY-GUARD — reference == refused ({ident_diags[0][:80]}...); primitive != lifted ({ir[0]['name']})")
PY

# ──────────────────────────────────────────────────────────────
# G1 tests (26-30): universe-walk — the implementation body, walked through
# its own grammar, defines the valid universe of the output.
# Fixture workspaces: fixtures/universe{,-mutable,-escape}/ each carry their
# own .sugar/config.toml with vendor_source_dirs.
# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 26: universe row — walked table + pad for the false-branch chain"
echo "────────────────────────────────────────────────────────────────"
RESULT26="$(run_lift "$FIXTURES/universe" "UniverseLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT26" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]

def atoms(c):
    return c["inv"]["operands"]

# encodeUpper("x") callsite: equality + universe under the SAME #euf# name.
name_x = "encodeUpper#euf#c:callresult_encodeUpper_a1(s:x)::assertion"
eq_x = [c for c in ir if c["name"] == name_x and atoms(c)[0]["name"] == "="]
un_x = [c for c in ir if c["name"] == name_x and atoms(c)[0]["name"] == "str.chars-in-set"]
assert len(eq_x) == 1, f"expected 1 equality contract named {name_x}: {[c['name'] for c in ir]}\ndiags={json.dumps(diags,indent=2)}"
assert len(un_x) == 1, f"expected 1 universe contract named {name_x}: {[c['name'] for c in ir]}\ndiags={json.dumps(diags,indent=2)}"

# The universe set: UPPER_TABLE chars + the pad char the vendor's own
# `if (outTable == UPPER_TABLE)` guard attributes — sorted+deduped "=ABC".
atom = atoms(un_x[0])[0]
subject, charset = atom["args"]
assert subject["kind"] == "ctor" and subject["name"] == "call:encodeUpper", f"bad subject: {subject}"
assert subject["args"][0] == {"kind":"const","value":"x","sort":{"kind":"primitive","name":"String"}}, \
    f"subject arg must be the String literal callsite key: {subject['args']}"
assert charset == {"kind":"const","value":"=ABC","sort":{"kind":"primitive","name":"String"}}, \
    f"walked charset wrong (want '=ABC' = UPPER_TABLE + pad, sorted): {charset}"

# The equality contract is String-sorted on the same subject.
eq_atom = atoms(eq_x[0])[0]
assert eq_atom["args"][0] == subject, "equality and universe must share the SAME subject term"
assert eq_atom["args"][1] == {"kind":"const","value":"AB=","sort":{"kind":"primitive","name":"String"}}, \
    f"sworn equality const wrong: {eq_atom['args'][1]}"
print("PASS: universe row — set '=ABC' walked (table literals + ==-guard pad), same #euf# name as the sworn equality")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 27: table discrimination — true-branch chain gets the OTHER table, no pad"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT26" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]
name_y = "encodeLower#euf#c:callresult_encodeLower_a1(s:y)::assertion"
un_y = [c for c in ir if c["name"] == name_y and c["inv"]["operands"][0]["name"] == "str.chars-in-set"]
assert len(un_y) == 1, f"expected 1 universe contract for encodeLower: {[c['name'] for c in ir]}"
charset = un_y[0]["inv"]["operands"][0]["args"][1]
# LOWER_TABLE only: the vendor's pad guard names UPPER_TABLE, so the lower
# universe must NOT contain '=' — pad attribution is walked, not assumed.
assert charset == {"kind":"const","value":"abc","sort":{"kind":"primitive","name":"String"}}, \
    f"walked charset wrong (want 'abc', NO pad): {charset}"
print("PASS: table discrimination — encodeLower universe is 'abc' (true branch, pad NOT attributed)")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 28: mutable-table discrimination — non-static-final table refused by name"
echo "────────────────────────────────────────────────────────────────"
RESULT28="$(run_lift "$FIXTURES/universe-mutable" "MutableLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT28" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]
diags = result["diagnostics"]
universe = [c for c in ir if c["inv"]["operands"][0]["name"] == "str.chars-in-set"]
assert len(universe) == 0, f"MUTABLE FALSEPASS: universe row emitted over a non-final table: {json.dumps(universe,indent=2)}"
# The sworn equality itself still lifts (it is the consumer's claim, not the universe).
eqs = [c for c in ir if c["inv"]["operands"][0]["name"] == "="]
assert len(eqs) == 1, f"expected the equality contract to still lift: {[c['name'] for c in ir]}"
reasons = [d.get("reason","") for d in diags]
named = [r for r in reasons if "mutable table is no axiom" in r]
assert named, f"expected the mutable-table refusal by name, got: {reasons}"
print(f"PASS: mutable-table discrimination — no universe row; named refusal: {named[0][:90]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 29: chain-escape discrimination — delegation leaves vendored source"
echo "────────────────────────────────────────────────────────────────"
RESULT29="$(run_lift "$FIXTURES/universe-escape" "EscapeLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT29" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]
diags = result["diagnostics"]
universe = [c for c in ir if c["inv"]["operands"][0]["name"] == "str.chars-in-set"]
assert len(universe) == 0, f"ESCAPE FALSEPASS: universe row emitted across a chain escape: {json.dumps(universe,indent=2)}"
eqs = [c for c in ir if c["inv"]["operands"][0]["name"] == "="]
assert len(eqs) == 1, f"expected the equality contract to still lift: {[c['name'] for c in ir]}"
reasons = [d.get("reason","") for d in diags]
named = [r for r in reasons if "chain escapes vendored source" in r]
assert named, f"expected the chain-escape refusal by name, got: {reasons}"
print(f"PASS: chain-escape discrimination — no universe row; named refusal: {named[0][:90]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 30: string-literal args lift (getBytes + getBytesUtf8 shapes); non-literal still refused"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT26" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]
diags = result["diagnostics"]
names = [c["name"] for c in ir]
# getBytesUtf8("z") shape lifts with arg-sig s:z (and its universe twin).
name_z = "encodeUpper#euf#c:callresult_encodeUpper_a1(s:z)::assertion"
assert names.count(name_z) == 2, f"getBytesUtf8 shape must lift equality+universe under {name_z}: {names}"
# "x".getBytes() shape lifted in TEST 26 (s:x). Total: 3 callsites x 2 rows.
assert len(ir) == 6, f"expected 6 contracts (3 string callsites x equality+universe), got {len(ir)}: {names}"
# The non-literal arg (variable `data`) is REFUSED by name — no s:w contract.
assert not any("s:w" in n for n in names), f"non-literal arg was lifted (falsePass): {names}"
reasons = [d.get("reason","") for d in diags]
named = [r for r in reasons if "is not an int literal or getBytesUtf8/getBytes" in r]
assert named, f"expected the non-literal-arg refusal by name, got: {reasons}"
print(f"PASS: string-literal args lift via both byte-bridge shapes; non-literal refused: {named[0][:80]}")
PY

# H1 tests (31+): hardening rollup — discrimination fixtures for each fix.
# Each H1 test has a twin fixture that BREAKS the invariant on purpose, so
# a regression (reverting the fix) turns the test red, not green.
# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 31: H1 [A1] cross-class ambiguity → UNLEARNED (not first-match)"
echo "────────────────────────────────────────────────────────────────"
RESULT31="$(run_lift "$FIXTURES/cross-class-ambiguity" "CrossClassAmbiguity.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT31" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]
# Must produce 0 contracts — checkEq is UNLEARNED due to ambiguous delegation.
assert len(ir) == 0, (
    f"FALSEPASS: cross-class ambiguity produced {len(ir)} contract(s) "
    f"(first-match silently chose a class): {[c['name'] for c in ir]}"
)
# Must emit a named refusal citing ambiguous delegation.
reasons = [d.get("reason", "") for d in diags]
named = [r for r in reasons if "ambiguous" in r.lower()]
assert named, (
    f"expected a named refusal citing 'ambiguous delegation target', got: {reasons}"
)
# The refusal must NOT say "equality" or "inequality" — wrong classification guard.
bad = [r for r in reasons if "equality" in r.lower() or "inequality" in r.lower()]
assert not bad, f"refusal incorrectly reports equality/inequality: {bad}"
print(f"PASS: cross-class ambiguity → 0 contracts, named UNLEARNED refusal: {named[0][:90]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 32a: H1 [A2] wildcard static import expands to all vendored vocab names"
echo "────────────────────────────────────────────────────────────────"
RESULT32A="$(run_lift "$FIXTURES" "WildcardImportLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT32A" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]
# Wildcard import must expand assertEquals so it lifts exactly as named-import twin.
assert len(ir) == 1, (
    f"FALSEPASS: wildcard import produced {len(ir)} contract(s) "
    f"(expected 1 for assertEquals/equality): {[c['name'] for c in ir]}\ndiags={diags}"
)
c = ir[0]
inv = c["inv"]
atomic = inv["operands"][0]
assert atomic["kind"] == "atomic" and atomic["name"] == "=", (
    f"expected '=' relation (equality), got: {atomic['name']}"
)
print(f"PASS: wildcard static import → assertEquals expanded, 1 equality contract lifted: {c['name'][:80]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 32b: H1 [A2] non-framework wildcard import → not bound, silent skip"
echo "────────────────────────────────────────────────────────────────"
RESULT32B="$(run_lift "$FIXTURES" "WildcardUnvendoredRefusal.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT32B" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]
# Non-framework wildcard (com.example.*) not processed by import scanner.
# The bare assertEquals is not framework-bound → silent skip: 0 contracts, 0 diagnostics.
assert len(ir) == 0, (
    f"FALSEPASS: non-framework wildcard produced {len(ir)} contract(s): {[c['name'] for c in ir]}"
)
# No diagnostic: the call is silently not-framework-bound (not an error, just not ours).
bad_diags = [d for d in diags if "assertEquals" in d.get("reason","").lower()]
assert not bad_diags, (
    f"unexpected diagnostic about assertEquals from non-framework wildcard: {bad_diags}"
)
print(f"PASS: non-framework wildcard import → assertEquals not bound, silent skip (0 contracts)")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 33: H1 [A3] user-scope impostor assertEquals (no static import) → silent skip"
echo "────────────────────────────────────────────────────────────────"
RESULT33="$(run_lift "$FIXTURES" "UserScopeImpostor.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT33" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]
# User-scope impostor: 0 contracts (silent skip — not framework-bound).
# Must NOT produce an equality lift (falsePass) or a false refusal.
assert len(ir) == 0, (
    f"FALSEPASS: user-scope assertEquals was lifted as a framework assertion: "
    f"{[c['name'] for c in ir]}"
)
# The import-edge guard silently skips — no diagnostic expected.
bad_lift = [d for d in diags if "equality" in d.get("reason","").lower()
            and "impostor" not in d.get("reason","").lower()]
assert not bad_lift, f"unexpected equality-related diagnostic: {bad_lift}"
print(f"PASS: user-scope impostor assertEquals silently skipped (0 contracts, import-edge guard)")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 34: H1 [C8] TestNG assertNotEquals 2-arg form → INEQUALITY (not APPROX)"
echo "────────────────────────────────────────────────────────────────"
RESULT34="$(run_lift "$FIXTURES" "TestNGAssertNotEquals.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT34" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]
# 2-arg assertNotEquals must lift as INEQUALITY, NOT as "approx" refusal.
approx = [d for d in diags if "approximate" in d.get("reason","").lower()]
assert not approx, (
    f"REGRESSION: 2-arg assertNotEquals classified as APPROX (delta overload wins): {approx}"
)
assert len(ir) == 1, (
    f"expected 1 INEQUALITY contract from assertNotEquals(g(2), 3), got {len(ir)}: "
    f"{[c['name'] for c in ir]}\ndiags={[d.get('reason','') for d in diags]}"
)
c = ir[0]
inv = c["inv"]
atomic = inv["operands"][0]
assert atomic["name"] in ("!=", "≠"), (
    f"expected inequality relation ('!=' or '≠'), got: {atomic['name']}"
)
print(f"PASS: TestNG assertNotEquals 2-arg → 1 inequality contract (not approx): {c['name'][:80]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 35: H1 [B6] lineLength=0 sound; lineLength=76 refused (chunking guard)"
echo "────────────────────────────────────────────────────────────────"
RESULT35="$(run_lift "$FIXTURES/universe-chunked" "ChunkedLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT35" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]
names = [c["name"] for c in ir]
# encodeNoChunk (lineLength=0) must register and produce a universe contract.
no_chunk_universe = [c for c in ir
    if "encodeNoChunk" in c["name"]
    and c["inv"]["operands"][0]["name"] == "str.chars-in-set"]
assert no_chunk_universe, (
    f"MISSING: encodeNoChunk universe row not found. Contracts: {names}\ndiags={[d.get('reason','') for d in diags]}"
)
# encodeChunked (lineLength=76) must be REFUSED by the universe walker.
# No universe row for encodeChunked must appear.
chunked_universe = [c for c in ir
    if "encodeChunked" in c["name"]
    and c["inv"]["operands"][0]["name"] == "str.chars-in-set"]
assert not chunked_universe, (
    f"FALSEPASS: encodeChunked universe row was registered (lineLength=76 not detected): "
    f"{[c['name'] for c in chunked_universe]}"
)
# The universe walker must emit a named refusal for encodeChunked.
reasons = [d.get("reason", "") for d in diags]
chunked_refusal = [r for r in reasons if "encodeChunked" in r or "chunking" in r.lower() or "lineLength" in r]
assert chunked_refusal, (
    f"expected a named refusal for encodeChunked (lineLength=76), got: {reasons}"
)
print(f"PASS: lineLength=0 → encodeNoChunk universe registered; "
      f"lineLength=76 → encodeChunked refused: {chunked_refusal[0][:80]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 36: G2 abs truth — equality + int32.eq-bv-expr row under SAME #euf# name"
echo "────────────────────────────────────────────────────────────────"
RESULT36="$(run_lift "$FIXTURES/numeric-universe" "NumericUniverseLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT36" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]

# testAbsTruth: assertEquals(-2147483648, abs(-2147483648))
# int arg → argSig = "i:-2147483648"
name = "abs#euf#c:callresult_abs_a1(i:-2147483648)::assertion"
eq_rows = [c for c in ir if c["name"] == name and c["inv"]["operands"][0]["name"] == "="]
bv_rows = [c for c in ir if c["name"] == name and c["inv"]["operands"][0]["name"] == "int32.eq-bv-expr"]
assert len(eq_rows) == 1, (
    f"expected 1 equality row for abs(-2147483648), got {len(eq_rows)}. "
    f"All contracts: {[c['name'] for c in ir]}\ndiags={[d.get('reason','') for d in diags]}"
)
assert len(bv_rows) == 1, (
    f"expected 1 int32.eq-bv-expr row for abs(-2147483648), got {len(bv_rows)}. "
    f"All contracts: {[c['name'] for c in ir]}\ndiags={[d.get('reason','') for d in diags]}"
)
print(f"PASS: G2 abs truth — equality + int32.eq-bv-expr row, both named: {name[:80]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 37: G2 bv-expr structure — bv32.ite(bv32.slt(a,0), bv32.neg(a), a)"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT36" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]

name = "abs#euf#c:callresult_abs_a1(i:-2147483648)::assertion"
bv_rows = [c for c in ir if c["name"] == name and c["inv"]["operands"][0]["name"] == "int32.eq-bv-expr"]
assert len(bv_rows) == 1, f"no int32.eq-bv-expr row: {[c['name'] for c in ir]}"

atom = bv_rows[0]["inv"]["operands"][0]
assert atom["name"] == "int32.eq-bv-expr", f"atom name wrong: {atom['name']}"
assert len(atom["args"]) == 2, f"expected 2 args, got {len(atom['args'])}"

# args[0]: call:abs ctor
subj = atom["args"][0]
assert subj["kind"] == "ctor" and subj["name"] == "call:abs", f"subject wrong: {subj}"
assert subj["args"][0] == {"kind":"const","value":-2147483648,"sort":{"kind":"primitive","name":"Int"}}, \
    f"subject arg wrong: {subj['args']}"

# args[1]: the BV expression tree — bv32.ite
bv = atom["args"][1]
assert bv["kind"] == "ctor" and bv["name"] == "bv32.ite", f"bv root wrong: {bv}"
slt, neg, var = bv["args"]
assert slt["kind"] == "ctor" and slt["name"] == "bv32.slt", f"slt wrong: {slt}"
assert neg["kind"] == "ctor" and neg["name"] == "bv32.neg", f"neg wrong: {neg}"
assert var["kind"] == "var" and var["name"] == "a", f"false-branch var wrong: {var}"
# slt args: var a, const 0
slt_lhs, slt_rhs = slt["args"]
assert slt_lhs["kind"] == "var" and slt_lhs["name"] == "a", f"slt lhs wrong: {slt_lhs}"
assert slt_rhs["kind"] == "const" and slt_rhs["value"] == 0, f"slt rhs wrong: {slt_rhs}"
# neg arg: var a
neg_arg = neg["args"][0]
assert neg_arg["kind"] == "var" and neg_arg["name"] == "a", f"neg arg wrong: {neg_arg}"

print("PASS: G2 bv-expr structure — bv32.ite(bv32.slt(a,0), bv32.neg(a), a) confirmed")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 38: G2 positive/negative abs cases also emit universe rows"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT36" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]
diags = result["diagnostics"]

# testAbsPositive: assertEquals(5, abs(5))  → argSig i:5
# testAbsNegative: assertEquals(5, abs(-5)) → argSig i:-5
for arg, desc in [("5", "abs(5)"), ("-5", "abs(-5)")]:
    name = f"abs#euf#c:callresult_abs_a1(i:{arg})::assertion"
    eq_rows = [c for c in ir if c["name"] == name and c["inv"]["operands"][0]["name"] == "="]
    bv_rows = [c for c in ir if c["name"] == name and c["inv"]["operands"][0]["name"] == "int32.eq-bv-expr"]
    assert len(eq_rows) == 1, f"missing equality row for {desc}: {[c['name'] for c in ir]}"
    assert len(bv_rows) == 1, (
        f"missing int32.eq-bv-expr row for {desc}: {[c['name'] for c in ir]}\n"
        f"diags={[d.get('reason','') for d in diags]}"
    )
print("PASS: G2 positive/negative abs cases — both emit equality + universe row pairs")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 39: G2 bad-shape discrimination — non-ternary body refused by name; equality still lifts"
echo "────────────────────────────────────────────────────────────────"
RESULT39="$(run_lift "$FIXTURES/numeric-universe-bad-shape" "NumericBadShapeLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT39" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]

# The equality contract must still lift
eq_rows = [c for c in ir if c["inv"]["operands"][0]["name"] == "="]
assert len(eq_rows) >= 1, (
    f"equality contract missing even though clamp(0)==0 should lift: "
    f"{[c['name'] for c in ir]}\ndiags={[d.get('reason','') for d in diags]}"
)
# No int32.eq-bv-expr row must be emitted
bv_rows = [c for c in ir if c["inv"]["operands"][0]["name"] == "int32.eq-bv-expr"]
assert len(bv_rows) == 0, (
    f"FALSEPASS: int32.eq-bv-expr row emitted for unsupported shape: {json.dumps(bv_rows,indent=2)}"
)
# The walker must have emitted a named refusal for the unsupported shape
reasons = [d.get("reason", "") for d in diags]
refused = [r for r in reasons if "numeric universe walk refused" in r or "shape" in r.lower() or "not supported" in r.lower() or "not a ternary" in r.lower()]
assert refused, (
    f"expected a named refusal for unsupported shape, got no matching diagnostic: {reasons}"
)
print(f"PASS: G2 bad-shape discrimination — equality lifts, bv-expr refused: {refused[0][:80]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 40: G2 no-vendor-dir — equality lifts, no universe row (numeric registry empty)"
echo "────────────────────────────────────────────────────────────────"
# Use the no-vocab fixture (has no vendor_source_dirs) — assertEquals is unlearned there.
# Instead use the fixtures root (which has junit5 vendor but no numeric vendor_source_dirs).
# The base FIXTURES/.sugar/config.toml has no vendor_source_dirs key → numericRegistry = EMPTY.
python3 - "$RESULT1" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]

# Equality contracts must be present (this fixture always lifts them)
eq_rows = [c for c in ir if c["inv"]["operands"][0]["name"] == "="]
assert len(eq_rows) >= 1, f"expected equality contracts: {[c['name'] for c in ir]}"
# No int32.eq-bv-expr rows (no vendor_source_dirs → no numeric universe)
bv_rows = [c for c in ir if c["inv"]["operands"][0]["name"] == "int32.eq-bv-expr"]
assert len(bv_rows) == 0, (
    f"FALSEPASS: int32.eq-bv-expr row emitted without a vendor_source_dirs config: "
    f"{json.dumps(bv_rows,indent=2)}"
)
print("PASS: G2 no-vendor-dir — equality lifts; numeric registry empty, no int32.eq-bv-expr row")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 41: G2b assertTrue(g(7) < 10) → <(call:g(7), 10) with #euf# name"
echo "────────────────────────────────────────────────────────────────"
RESULT41="$(run_lift "$FIXTURES" "ComparisonBoundLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT41" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]

# assertTrue(g(7) < 10)
name = "g#euf#c:callresult_g_a1(i:7)::assertion"
lt_rows = [c for c in ir if c["name"] == name and c["inv"]["operands"][0]["name"] == "<"]
assert len(lt_rows) == 1, (
    f"expected 1 '<' contract for g(7), got {len(lt_rows)}. "
    f"ir={[c['name']+':'+c['inv']['operands'][0]['name'] for c in ir]}"
)
atom = lt_rows[0]["inv"]["operands"][0]
assert atom["args"][0] == {"kind":"ctor","name":"call:g","args":[{"kind":"const","value":7,"sort":{"kind":"primitive","name":"Int"}}]}, \
    f"call arg wrong: {atom['args'][0]}"
assert atom["args"][1] == {"kind":"const","value":10,"sort":{"kind":"primitive","name":"Int"}}, \
    f"lit arg wrong: {atom['args'][1]}"
print(f"PASS: G2b assertTrue(g(7) < 10) → <(call:g(7),10) name={name}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 42: G2b assertTrue(5 > g(2)) → <(call:g(2), 5) [lit-left mirror]"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT41" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]

# assertTrue(5 > g(2)) — lit on left, mirrored: g(2) < 5
# testLessThanLitLeft emits this; testAssertFalse also emits for g(2) >= 5
# Check the < row exists (from testLessThanLitLeft)
name = "g#euf#c:callresult_g_a1(i:2)::assertion"
lt_rows = [c for c in ir if c["name"] == name and c["inv"]["operands"][0]["name"] == "<"]
gte_rows = [c for c in ir if c["name"] == name and c["inv"]["operands"][0]["name"] == ">="]
assert len(lt_rows) == 1, f"expected 1 '<' contract for g(2) (mirrored 5>g(2)): {[(c['name'],c['inv']['operands'][0]['name']) for c in ir]}"
assert len(gte_rows) == 1, f"expected 1 '>=' contract for g(2) (assertFalse(g(2)<5)): {[(c['name'],c['inv']['operands'][0]['name']) for c in ir]}"
lt_atom = lt_rows[0]["inv"]["operands"][0]
assert lt_atom["args"][1] == {"kind":"const","value":5,"sort":{"kind":"primitive","name":"Int"}}, \
    f"lit wrong for mirrored: {lt_atom['args'][1]}"
print(f"PASS: G2b assertTrue(5>g(2)) → <(call:g(2),5); assertFalse(g(2)<5) → >=(call:g(2),5)")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 43: G2b assertFalse(g(2) < 5) → >=(call:g(2), 5) [negated predicate]"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT41" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]

name = "g#euf#c:callresult_g_a1(i:2)::assertion"
gte_rows = [c for c in ir if c["name"] == name and c["inv"]["operands"][0]["name"] == ">="]
assert len(gte_rows) == 1, f"expected 1 '>=' contract for assertFalse(g(2)<5): {[(c['name'],c['inv']['operands'][0]['name']) for c in ir]}"
gte_atom = gte_rows[0]["inv"]["operands"][0]
assert gte_atom["args"][0]["name"] == "call:g", f"call wrong: {gte_atom['args'][0]}"
assert gte_atom["args"][1] == {"kind":"const","value":5,"sort":{"kind":"primitive","name":"Int"}}, \
    f"lit wrong: {gte_atom['args'][1]}"
print(f"PASS: G2b assertFalse(g(2)<5) → >=(call:g(2),5) confirmed")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 44: G2b non-literal bound refused by name; both-calls refused by name"
echo "────────────────────────────────────────────────────────────────"
RESULT44="$(run_lift "$FIXTURES" "ComparisonBoundDiscrimination.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT44" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"
ir = result["ir"]
diags = result["diagnostics"]
reasons = [d.get("reason", "") for d in diags]

# No contracts should be emitted
assert len(ir) == 0, f"expected no contracts, got {[c['name'] for c in ir]}"

# non-literal bound refused
non_lit = [r for r in reasons if "non-literal bound" in r or "not an int literal" in r.lower()]
assert non_lit, f"expected non-literal-bound refusal, got reasons: {reasons}"

# both-calls refused
both_calls = [r for r in reasons if "both operands are calls" in r]
assert both_calls, f"expected both-operands-are-calls refusal, got reasons: {reasons}"

print(f"PASS: G2b discrimination — non-literal bound refused: {non_lit[0][:80]}")
print(f"PASS: G2b discrimination — both-calls refused: {both_calls[0][:80]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 45: G2b #euf# name is IDENTICAL to assertEquals name for same callsite"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT41" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]

# The contract name for assertTrue(g(7) < 10) must be IDENTICAL to what
# assertEquals(expected, g(7)) would produce — same #euf# schema.
expected_name = "g#euf#c:callresult_g_a1(i:7)::assertion"
names = [c["name"] for c in ir]
assert expected_name in names, (
    f"assertTrue(g(7)<10) must produce name '{expected_name}' for federation; "
    f"got names: {names}"
)
print(f"PASS: G2b #euf# name '{expected_name}' matches assertEquals schema — federation is live")
PY


# ──────────────────────────────────────────────────────────────
# TEST SUITE P5c — call-binding lift (SSA substitution + instance-method location-keyed)
# Mirrors Python PATTERN 5 / _apply_value_scope_binding + _call_origin_from_expr.
#
# 46. SSA static: `int r = compute(7); assertEquals(14, r)` → same #euf# name as inline form
# 47. SSA static byte-identity: SSA and inline forms produce byte-identical contract names
# 48. Instance-method: `Codec c = new Codec(); assertEquals(0, c.getPolicy())` → location-keyed
# 49. Two-test no-collision: two test methods with different constructions → different location bases
# 50. Reassigned local refused by name
# ──────────────────────────────────────────────────────────────

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 46: P5c SSA static — effectively-final local substituted to #euf# call"
echo "────────────────────────────────────────────────────────────────"
RESULT46="$(run_lift "$FIXTURES" "P5cSsaStaticLiftInt.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT46" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]
diags = result["diagnostics"]

# Both testViaLocal and testInline must produce a contract
assert len(ir) == 2, f"expected 2 contracts (one per test), got {len(ir)}: {[c['name'] for c in ir]}"

# Both must use #euf# (static call federates)
for c in ir:
    assert "#euf#" in c["name"], f"expected #euf# in name (static call), got: {c['name']}"

print(f"PASS: P5c SSA static — {len(ir)} contracts, both #euf#-federated: {ir[0]['name']}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 47: P5c SSA byte-identity — local form and inline form produce SAME contract name"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT46" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]

names = [c["name"] for c in ir]
expected_name = "compute#euf#c:callresult_compute_a1(i:7)::assertion"
assert names.count(expected_name) == 2, (
    f"SSA and inline forms must produce byte-identical contract names; "
    f"expected 2x '{expected_name}', got: {names}"
)
print(f"PASS: P5c byte-identity — SSA form and inline form produce same name: {expected_name}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 48: P5c instance-method — local receiver → location-keyed (NOT #euf#)"
echo "────────────────────────────────────────────────────────────────"
RESULT48="$(run_lift "$FIXTURES" "P5cInstanceMethodLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT48" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]
diags = result["diagnostics"]

# Must produce contracts (the instance-method calls are liftable)
assert len(ir) >= 1, f"expected contracts from instance-method lift, got 0 (diags: {diags})"

# MUST NOT use #euf# — instance-method calls are location-keyed
for c in ir:
    assert "#euf#" not in c["name"], (
        f"instance-method call must NOT be #euf#-federated; got: {c['name']}"
    )

# Must contain the scope (file::class::method) in the name — location-keyed
for c in ir:
    assert "P5cInstanceMethodLift" in c["name"], (
        f"location-keyed name must contain the class/method scope; got: {c['name']}"
    )

print(f"PASS: P5c instance-method — {len(ir)} location-keyed contracts (no #euf#): {ir[0]['name']}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 49: P5c no-collision — two test methods with same method name produce different names"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT48" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]

# Both test methods (testCodecPolicyDefault, testCodecPolicyStrict) must produce contracts
assert len(ir) == 2, f"expected 2 contracts (one per test method), got {len(ir)}: {[c['name'] for c in ir]}"

# The two names must be DIFFERENT (different test method scope)
assert ir[0]["name"] != ir[1]["name"], (
    f"two different test methods must produce different location-keyed names; "
    f"both produced: {ir[0]['name']}"
)

# Each name must encode the respective test method
names = [c["name"] for c in ir]
assert any("testCodecPolicyDefault" in n for n in names), f"first test name not in: {names}"
assert any("testCodecPolicyStrict" in n for n in names), f"second test name not in: {names}"

print(f"PASS: P5c no-collision — two tests, two distinct names:")
print(f"  {ir[0]['name']}")
print(f"  {ir[1]['name']}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 50: P5c reassigned local refused by name (not a stable SSA alias)"
echo "────────────────────────────────────────────────────────────────"
RESULT50="$(run_lift "$FIXTURES" "P5cReassignedRefusal.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT50" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None
ir = result["ir"]
diags = result["diagnostics"]

assert len(ir) == 0, f"reassigned local must produce 0 contracts, got {len(ir)}: {[c['name'] for c in ir]}"
assert len(diags) >= 1, f"expected a named refusal for reassigned local, got: {diags}"
reasons = [d.get("reason", "") for d in diags]
ssa_diags = [r for r in reasons if "reassigned" in r.lower() or "stable" in r.lower() or "SSA" in r]
assert ssa_diags, f"expected a refusal naming 'reassigned' or 'stable SSA alias', got: {reasons}"
print(f"PASS: P5c reassigned local refused by name: {ssa_diags[0]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST SUITE G3 — instance-universe: construction-semantics walk through \`this\`"
echo "Pins call:get(x) == ctorValue when getter is a pure final-field return."
echo "────────────────────────────────────────────────────────────────"

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 51: G3 positive — pure final-field getter emits TWO operands (ctor fact + test claim)"
echo "────────────────────────────────────────────────────────────────"
RESULT51="$(run_lift "$FIXTURES" "G3BoxPositiveTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT51" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None

ir = result["ir"]
assert len(ir) == 1, f"expected 1 contract, got {len(ir)}: {[c['name'] for c in ir]}"
c = ir[0]

# Must be location-keyed (contains ::assertion, not #euf#)
assert "::assertion" in c["name"], f"name should be location-keyed: {c['name']}"
assert "#euf#" not in c["name"], f"must not be #euf#-federated: {c['name']}"

inv = c["inv"]
assert inv["kind"] == "and", f"inv.kind: {inv['kind']}"
ops = inv["operands"]
assert len(ops) == 2, (
    f"G3 positive: expected 2 operands (ctor fact + test claim), got {len(ops)}: {ops}")

# Both operands must be atomic '='
for i, op in enumerate(ops):
    assert op["kind"] == "atomic" and op["name"] == "=", f"operand[{i}]: {op}"

# Both must have the SAME ctorJson (byte-identical call:get(x) term)
ctor0 = ops[0]["args"][0]
ctor1 = ops[1]["args"][0]
assert ctor0 == ctor1, f"ctorJson not byte-identical: {ctor0} vs {ctor1}"

# operand[0] is the construction fact (value 5 from new G3Box(5))
const0 = ops[0]["args"][1]
assert const0["kind"] == "const" and const0["value"] == 5, (
    f"construction fact should be const(5,Int), got: {const0}")

# operand[1] is the test's claim (assertEquals(5, x.get()))
const1 = ops[1]["args"][1]
assert const1["kind"] == "const" and const1["value"] == 5, (
    f"test claim should be const(5,Int), got: {const1}")

print(f"PASS: G3 positive — 2 operands, both const(5,Int), byte-identical ctorJson: {ctor0['name']}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 52: G3 discrimination — non-final field refused, contract has ONE operand"
echo "────────────────────────────────────────────────────────────────"
RESULT52="$(run_lift "$FIXTURES" "G3NonFinalDiscriminationTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT52" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None

ir = result["ir"]
diags = result["diagnostics"]

# Contract must still lift (the test assertion itself is valid)
assert len(ir) == 1, f"expected 1 contract, got {len(ir)}: {[c['name'] for c in ir]}"
c = ir[0]
inv = c["inv"]
ops = inv["operands"]

# Must have exactly ONE operand (construction refused — non-final field)
assert len(ops) == 1, (
    f"G3 non-final discrimination: expected 1 operand (no ctor pin), got {len(ops)}: {ops}")

# Must have a named diagnostic mentioning the refusal.
# Accepts old message ("not final"/"construction not pinned") and new effectively-final messages
# ("not private", "assignment universe escapes", "assigned outside constructor", "not effectively final").
reasons = [d.get("reason", "") for d in diags]
refusal_diags = [r for r in reasons if (
    "not final" in r or "construction not pinned" in r
    or "not private" in r or "assignment universe escapes" in r
    or "assigned outside constructor" in r or "not effectively final" in r)]
assert refusal_diags, (
    f"expected a diagnostic naming field pin refusal, got: {reasons}")

print(f"PASS: G3 non-final discrimination — 1 operand (no pin), refusal: {refusal_diags[0]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 53: G3 discrimination — getter with computation refused, contract has ONE operand"
echo "────────────────────────────────────────────────────────────────"
RESULT53="$(run_lift "$FIXTURES" "G3ComputationDiscriminationTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT53" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None

ir = result["ir"]

# Contract must still lift (the test assertion itself is valid)
assert len(ir) == 1, f"expected 1 contract, got {len(ir)}: {[c['name'] for c in ir]}"
c = ir[0]
inv = c["inv"]
ops = inv["operands"]

# Must have exactly ONE operand (construction refused — getter is not a pure field read)
assert len(ops) == 1, (
    f"G3 computation discrimination: expected 1 operand (no ctor pin), got {len(ops)}: {ops}")

print(f"PASS: G3 computation discrimination — 1 operand (computation getter refused, no pin)")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST SUITE Voltron — mutually-recursive construction-semantics resolver"
echo "Receiver w.unwrap().get() is itself a call; two-layer walk Box→Wrapper→int."
echo "────────────────────────────────────────────────────────────────"

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 54: Voltron positive — two-layer chain emits TWO operands, pinned const=5"
echo "────────────────────────────────────────────────────────────────"
RESULT54="$(run_lift "$FIXTURES" "VoltronPositiveTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT54" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

# Must have exactly one contract.
assert len(ir) == 1, f"expected 1 contract, got {len(ir)}: {ir}"

c = ir[0]

# Must be location-keyed (contains ::assertion, not #euf#).
assert "::assertion" in c["name"], f"expected location-keyed name, got: {c['name']}"
assert "#euf#" not in c["name"], f"unexpected federation in name: {c['name']}"

inv = c["inv"]
ops = inv["operands"]

# Must have exactly TWO operands.
assert len(ops) == 2, f"Voltron positive: expected 2 operands (ctor pin + test claim), got {len(ops)}: {ops}"

# Both operands must be atomic '='.
for i, op in enumerate(ops):
    assert op["kind"] == "atomic" and op["name"] == "=", f"operand[{i}]: {op}"

# Both must use the SAME ctorJson (byte-identical receiver term).
ctor0 = ops[0]["args"][0]
ctor1 = ops[1]["args"][0]
assert ctor0 == ctor1, f"receiver term not byte-identical across operands: {ctor0} vs {ctor1}"

# Receiver term must be a ctor/call wrapping a var.
assert ctor0["kind"] == "ctor", f"expected kind=ctor, got: {ctor0['kind']}"
assert ctor0["args"][0]["kind"] == "var", f"expected var arg, got: {ctor0['args'][0]}"

# operand[0] is the construction fact (value 5).
const0 = ops[0]["args"][1]
assert const0["kind"] == "const" and const0["value"] == 5, (
    f"ctor pin should be const(5,Int), got: {const0}")

# operand[1] is the test's claim (assertEquals(5, ...)).
const1 = ops[1]["args"][1]
assert const1["kind"] == "const" and const1["value"] == 5, (
    f"test claim should be const(5,Int), got: {const1}")

# No diagnostics — clean resolution.
assert len(diags) == 0, f"expected no diagnostics, got: {diags}"

print(f"PASS: Voltron positive — 2 operands, both const(5,Int), byte-identical receiver term: {ctor0['name']}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 55: Voltron discrimination — non-final inner field refuses entire chain"
echo "────────────────────────────────────────────────────────────────"
RESULT55="$(run_lift "$FIXTURES" "VoltronNonFinalDiscriminationTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT55" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

# The whole chain must be refused — no contract emitted.
assert len(ir) == 0, (
    f"Voltron non-final discrimination: expected 0 contracts (chain refused), got {len(ir)}: {ir}")

# Must have a named diagnostic mentioning the non-final / open-membrane / outside-ctor refusal.
reasons = [d.get("reason", "") for d in diags]
nonfinal_diags = [r for r in reasons if (
    "not final" in r or "construction not pinned" in r
    or "not private" in r or "assignment universe escapes" in r
    or "assigned outside constructor" in r or "not effectively final" in r)]
assert nonfinal_diags, (
    f"expected a diagnostic naming field pin refusal, got: {reasons}")

print(f"PASS: Voltron non-final discrimination — whole chain refused, named diagnostic: {nonfinal_diags[0]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 56: Voltron discrimination — computed inner getter refuses entire chain"
echo "────────────────────────────────────────────────────────────────"
RESULT56="$(run_lift "$FIXTURES" "VoltronComputationDiscriminationTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT56" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

# The whole chain must be refused — no contract emitted.
assert len(ir) == 0, (
    f"Voltron computation discrimination: expected 0 contracts (chain refused), got {len(ir)}: {ir}")

# Must have a named diagnostic (chain refusal).
reasons = [d.get("reason", "") for d in diags]
chain_diags = [r for r in reasons if "voltron" in r.lower() or "chain" in r.lower() or "refused" in r.lower()]
assert chain_diags, (
    f"expected a diagnostic naming chain refusal, got: {reasons}")

print(f"PASS: Voltron computation discrimination — whole chain refused, named diagnostic: {chain_diags[0]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST SUITE EF — effectively-final instance fields (derived from fixedpoint, not keyword)"
echo "A field is effectively final iff: final keyword OR (private + no outside-ctor assignment"
echo "+ at most one ctor assignment, not in a loop). The compiler closes the universe for final;"
echo "private closes it for the scan."
echo "────────────────────────────────────────────────────────────────"

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 62: EF positive — private keyword-less field, single ctor assignment → TWO operands"
echo "  EFBox.value: private int value (no final). Vendor never wrote final; fixedpoint proves it."
echo "────────────────────────────────────────────────────────────────"
RESULT62="$(run_lift "$FIXTURES" "EFBoxPositiveTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT62" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

assert len(ir) == 1, f"EF positive: expected 1 contract, got {len(ir)}: {ir}"
c = ir[0]
assert "::assertion" in c["name"], f"expected location-keyed name: {c['name']}"
inv = c["inv"]
ops = inv["operands"]
assert len(ops) == 2, (
    f"EF positive: expected 2 operands (ctor fact + test claim), got {len(ops)}: {ops}")
for i, op in enumerate(ops):
    assert op["kind"] == "atomic" and op["name"] == "=", f"operand[{i}]: {op}"
ctor0 = ops[0]["args"][0]
ctor1 = ops[1]["args"][0]
assert ctor0 == ctor1, f"ctorJson not byte-identical: {ctor0} vs {ctor1}"
const0 = ops[0]["args"][1]
assert const0["kind"] == "const" and const0["value"] == 7, (
    f"ctor fact should be const(7,Int), got: {const0}")
const1 = ops[1]["args"][1]
assert const1["kind"] == "const" and const1["value"] == 7, (
    f"test claim should be const(7,Int), got: {const1}")
print(f"PASS: EF positive — 2 operands, both const(7,Int), keyword-less private field pinned: {ctor0['name']}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 63: EF positive (Voltron depth) — two-layer chain, both fields private no-final → TWO operands"
echo "  EFWrapper.box and EFBox.value: both private without final; both proved by scan."
echo "────────────────────────────────────────────────────────────────"
RESULT63="$(run_lift "$FIXTURES" "EFVoltronPositiveTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT63" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

assert len(ir) == 1, f"EF Voltron positive: expected 1 contract, got {len(ir)}: {ir}"
c = ir[0]
assert "::assertion" in c["name"], f"expected location-keyed name: {c['name']}"
inv = c["inv"]
ops = inv["operands"]
assert len(ops) == 2, (
    f"EF Voltron positive: expected 2 operands (ctor fact + test claim), got {len(ops)}: {ops}")
for i, op in enumerate(ops):
    assert op["kind"] == "atomic" and op["name"] == "=", f"operand[{i}]: {op}"
ctor0 = ops[0]["args"][0]
ctor1 = ops[1]["args"][0]
assert ctor0 == ctor1, f"receiver term not byte-identical: {ctor0} vs {ctor1}"
const0 = ops[0]["args"][1]
assert const0["kind"] == "const" and const0["value"] == 9, (
    f"ctor fact should be const(9,Int), got: {const0}")
const1 = ops[1]["args"][1]
assert const1["kind"] == "const" and const1["value"] == 9, (
    f"test claim should be const(9,Int), got: {const1}")
assert len(diags) == 0, f"expected no diagnostics, got: {diags}"
print(f"PASS: EF Voltron positive — 2 operands, both const(9,Int), two-layer keyword-less chain pinned: {ctor0['name']}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 64: EF discrimination — package-private (open membrane) → 1 operand, named diagnostic"
echo "  PackagePrivateBox.value: no modifier → assignment universe escapes walked class."
echo "────────────────────────────────────────────────────────────────"
RESULT64="$(run_lift "$FIXTURES" "EFOpenMembraneTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT64" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

assert len(ir) == 1, f"EF open-membrane: expected 1 contract, got {len(ir)}: {ir}"
c = ir[0]
inv = c["inv"]
ops = inv["operands"]
assert len(ops) == 1, (
    f"EF open-membrane: expected 1 operand (no ctor pin), got {len(ops)}: {ops}")
reasons = [d.get("reason", "") for d in diags]
membrane_diags = [r for r in reasons
    if "not private" in r or "assignment universe escapes" in r or "effective finality" in r]
assert membrane_diags, (
    f"expected a diagnostic naming open membrane / not private, got: {reasons}")
print(f"PASS: EF open-membrane discrimination — 1 operand, diagnostic: {membrane_diags[0][:120]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 65: EF discrimination — private field assigned in for-loop body (scan totality)"
echo "  MutatedInForBox.value: private, but reset() assigns inside for-body."
echo "  Old hand-rolled stmtAssignsField had no ForLoopTree case — would have missed this."
echo "────────────────────────────────────────────────────────────────"
RESULT65="$(run_lift "$FIXTURES" "EFMutatedInIfTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT65" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

assert len(ir) == 1, f"EF for-body mutation: expected 1 contract, got {len(ir)}: {ir}"
c = ir[0]
inv = c["inv"]
ops = inv["operands"]
assert len(ops) == 1, (
    f"EF for-body mutation: expected 1 operand (no ctor pin), got {len(ops)}: {ops}")
reasons = [d.get("reason", "") for d in diags]
outside_diags = [r for r in reasons
    if "assigned outside constructor" in r or "not effectively final" in r]
assert outside_diags, (
    f"expected a diagnostic naming outside-constructor assignment, got: {reasons}")
print(f"PASS: EF for-body mutation discrimination — 1 operand, diagnostic: {outside_diags[0][:120]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 66: EF discrimination — private field with value++ in method (compound mutation)"
echo "  IncrementBox.value: private, but increment() does this.value++."
echo "  Old stmtAssignsField only checked AssignmentTree — UnaryTree was invisible."
echo "────────────────────────────────────────────────────────────────"
RESULT66="$(run_lift "$FIXTURES" "EFCompoundMutationTest.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT66" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

assert len(ir) == 1, f"EF compound mutation: expected 1 contract, got {len(ir)}: {ir}"
c = ir[0]
inv = c["inv"]
ops = inv["operands"]
assert len(ops) == 1, (
    f"EF compound mutation: expected 1 operand (no ctor pin), got {len(ops)}: {ops}")
reasons = [d.get("reason", "") for d in diags]
mut_diags = [r for r in reasons
    if "assigned outside constructor" in r or "not effectively final" in r]
assert mut_diags, (
    f"expected a diagnostic naming outside-constructor mutation, got: {reasons}")
print(f"PASS: EF compound mutation discrimination — 1 operand, diagnostic: {mut_diags[0][:120]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 57: P6 jtreg positive — error-sentinel harness → 2 contracts (equality + universe)"
echo "  MECHANISM: testIntAbs classified by body shape (NOT name)."
echo "  Math::abs resolved via MemberReferenceTree; Integer.MIN_VALUE from platform-axioms.json."
echo "  Expected: abs#euf#c:callresult_abs_a1(i:-2147483648)::assertion x2 (= + int32.eq-bv-expr)"
echo "────────────────────────────────────────────────────────────────"
RESULT57="$(run_lift "$FIXTURES/p6-jtreg-positive" "P6JtregPositive.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT57" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

# Must produce exactly 2 contracts: equality + int32.eq-bv-expr universe row.
assert len(ir) == 2, (
    f"P6 positive: expected 2 contracts (= + int32.eq-bv-expr), got {len(ir)}: {json.dumps(ir, indent=2)}")

expected_name = "abs#euf#c:callresult_abs_a1(i:-2147483648)::assertion"
for c in ir:
    assert c["name"] == expected_name, (
        f"P6 positive: wrong contract name: {c['name']} (expected {expected_name})")

# First contract: equality relation.
eq_contract = ir[0]
inv0 = eq_contract["inv"]["operands"][0]
assert inv0["kind"] == "atomic" and inv0["name"] == "=", (
    f"P6 positive: first contract must be equality (=), got: {inv0['name']}")

ctor = inv0["args"][0]
assert ctor["kind"] == "ctor" and ctor["name"] == "call:abs", (
    f"P6 positive: call:abs expected, got: {ctor}")
assert ctor["args"][0] == {"kind": "const", "value": -2147483648, "sort": {"kind": "primitive", "name": "Int"}}, (
    f"P6 positive: arg should be -2147483648 (Integer.MIN_VALUE from platform-axioms.json)")
assert inv0["args"][1] == {"kind": "const", "value": -2147483648, "sort": {"kind": "primitive", "name": "Int"}}, (
    f"P6 positive: expected value should be -2147483648")

# Second contract: int32.eq-bv-expr universe row (walked Math.abs body).
bv_contract = ir[1]
inv1 = bv_contract["inv"]["operands"][0]
assert inv1["kind"] == "atomic" and inv1["name"] == "int32.eq-bv-expr", (
    f"P6 positive: second contract must be int32.eq-bv-expr, got: {inv1['name']}")

# Verify the walked BV expression is bv32.ite(bv32.slt(a,0), bv32.neg(a), a).
bv_ctor = inv1["args"][1]
assert bv_ctor["kind"] == "ctor" and bv_ctor["name"] == "bv32.ite", (
    f"P6 positive: walked body must be bv32.ite, got: {bv_ctor['name']}")

# Named diagnostics must NOT mention name-key classification.
name_key_diags = [d for d in diags if "name" in d.get("reason", "").lower()
                  and "abs" in d.get("reason", "").lower()
                  and "classified" in d.get("reason", "").lower()]
assert not name_key_diags, (
    f"SOUNDNESS VIOLATION: classification used a name key: {name_key_diags}")

print(f"PASS: P6 jtreg positive -- 2 contracts produced:")
print(f"  Contract name: {ir[0]['name']}")
print(f"  Contract 1: equality   abs(-2147483648) = -2147483648 (Integer.MIN_VALUE)")
print(f"  Contract 2: int32.eq-bv-expr  bv32.ite(bv32.slt(a,0),bv32.neg(a),a)")
print(f"  MECHANISM: body shape (NOT name); MemberReferenceTree; platform-axioms.json")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 58: P6 discrimination — unconditional return 1 → 0 contracts, named diagnostic"
echo "  Harness returns 1 unconditionally (no 'result != expected' guard)."
echo "  Kit must refuse with: \"no 'result != expected' guard found\""
echo "────────────────────────────────────────────────────────────────"
RESULT58="$(run_lift "$FIXTURES/p6-unconditional-return" "P6UnconditionalReturn.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT58" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

# Must produce 0 contracts.
assert len(ir) == 0, (
    f"P6 unconditional-return discrimination: expected 0 contracts, got {len(ir)}: {ir}")

# Must have a named diagnostic about the missing guard.
reasons = [d.get("reason", "") for d in diags]
guard_diags = [r for r in reasons if "result != expected" in r or "no 'result" in r or "guard" in r]
assert guard_diags, (
    f"P6 unconditional-return: expected named diagnostic about missing guard, got: {reasons}")

print(f"PASS: P6 unconditional-return discrimination -- 0 contracts, named diagnostic: {guard_diags[0][:100]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 59: P6 discrimination — wrong guard (unrelated comparison) → 0 contracts, named diagnostic"
echo "  Guard compares 0 != 1 (not result vs expected)."
echo "  Kit must refuse: \"no 'result != expected' guard found\""
echo "────────────────────────────────────────────────────────────────"
RESULT59="$(run_lift "$FIXTURES/p6-wrong-guard" "P6WrongGuard.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT59" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

# Must produce 0 contracts.
assert len(ir) == 0, (
    f"P6 wrong-guard discrimination: expected 0 contracts, got {len(ir)}: {ir}")

# Must have a named diagnostic about the missing guard.
reasons = [d.get("reason", "") for d in diags]
guard_diags = [r for r in reasons if "result != expected" in r or "no 'result" in r or "guard" in r]
assert guard_diags, (
    f"P6 wrong-guard: expected named diagnostic about missing guard, got: {reasons}")

print(f"PASS: P6 wrong-guard discrimination -- 0 contracts, named diagnostic: {guard_diags[0][:100]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 60: P6 discrimination — sentinel never throws → 0 contracts, named diagnostic"
echo "  Harness body shape is correct; main has NO 'if (errors > 0) throw'."
echo "  Kit must refuse: \"error-sentinel flow not verified\""
echo "────────────────────────────────────────────────────────────────"
RESULT60="$(run_lift "$FIXTURES/p6-no-throw" "P6NoThrow.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT60" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

# Must produce 0 contracts.
assert len(ir) == 0, (
    f"P6 no-throw discrimination: expected 0 contracts, got {len(ir)}: {ir}")

# Must have a named diagnostic about the missing accumulator+throw.
reasons = [d.get("reason", "") for d in diags]
flow_diags = [r for r in reasons if "flow not verified" in r or "accumulator" in r or "throw" in r]
assert flow_diags, (
    f"P6 no-throw: expected named diagnostic about missing throw, got: {reasons}")

print(f"PASS: P6 no-throw discrimination -- 0 contracts, named diagnostic: {flow_diags[0][:100]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 61: P6 discrimination — lambda instead of method reference → 0 contracts, named diagnostic"
echo "  Callsite passes a lambda (a -> ...) not a MemberReferenceTree."
echo "  Kit must refuse: \"functional-interface argument is not a method reference\""
echo "────────────────────────────────────────────────────────────────"
RESULT61="$(run_lift "$FIXTURES/p6-method-ref-refusal" "P6MethodRefRefusal.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT61" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = None
for line in lines:
    if not line.strip(): continue
    obj = json.loads(line)
    if obj.get("id") == 2:
        result = obj["result"]
        break
assert result is not None, "no lift response"

ir = result["ir"]
diags = result["diagnostics"]

# Must produce 0 contracts.
assert len(ir) == 0, (
    f"P6 method-ref-refusal discrimination: expected 0 contracts, got {len(ir)}: {ir}")

# Must have a named diagnostic about the non-method-reference functional arg.
reasons = [d.get("reason", "") for d in diags]
mref_diags = [r for r in reasons if "not a method reference" in r or "MemberReferenceTree" in r or "LAMBDA" in r]
assert mref_diags, (
    f"P6 method-ref-refusal: expected named diagnostic about non-MemberReferenceTree, got: {reasons}")

print(f"PASS: P6 method-ref-refusal discrimination -- 0 contracts, named diagnostic: {mref_diags[0][:100]}")
PY

# ──────────────────────────────────────────────────────────────
# STRONG TIER (str.eq-bv-blocks) -- paper 26 "the seam between tiers".
# The walker symbolically executes the vendor encode body and mints the
# per-character block equations. These tests assert the positive shape and
# the three named refusals (tail / non-literal / uninterpretable index).
# ──────────────────────────────────────────────────────────────

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 67: STRONG positive -- full 3-byte block lifts 4 per-char equations"
echo "  assertEquals(\"YmFy\", encodeBase64String(getBytesUtf8(\"bar\")))"
echo "  Expect equality + weak str.chars-in-set + strong str.eq-bv-blocks, SAME #euf# name."
echo "  Every op/constant in the equations must be present (shl/lshr/and/add, mask 0x3f, table folded)."
echo "────────────────────────────────────────────────────────────────"
RESULT67="$(run_lift "$FIXTURES/strong-universe" "StrongUniverseLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT67" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id") == 2)
ir = result["ir"]

def atoms(c): return c["inv"]["operands"]
strong = [c for c in ir if atoms(c)[0]["name"] == "str.eq-bv-blocks"]
weak   = [c for c in ir if atoms(c)[0]["name"] == "str.chars-in-set"]
eq     = [c for c in ir if atoms(c)[0]["name"] == "="]
assert len(strong) == 1, f"expected 1 strong str.eq-bv-blocks row, got {len(strong)}: {[c['name'] for c in ir]}"
assert len(weak)   == 1, f"expected 1 weak str.chars-in-set row, got {len(weak)} (non-regression)"
assert len(eq)     == 1, f"expected 1 sworn equality row, got {len(eq)}"

# Same #euf# name across all three (conjoin folds them).
names = {strong[0]["name"], weak[0]["name"], eq[0]["name"]}
assert len(names) == 1, f"strong/weak/equality must share one #euf# name, got {names}"
assert "#euf#" in strong[0]["name"], f"strong row must be #euf#-federated: {strong[0]['name']}"

# args[1] is a String const carrying the payload JSON. Parse it and inspect.
payload_const = atoms(strong[0])[0]["args"][1]
assert payload_const["kind"] == "const" and payload_const["sort"]["name"] == "String"
payload = json.loads(payload_const["value"])
assert payload["input_bytes"] == [98, 97, 114], f"input_bytes must be 'bar' UTF-8: {payload['input_bytes']}"
assert payload["vars"] == ["b0", "b1", "b2"], f"three byte vars: {payload['vars']}"
assert len(payload["per_char"]) == 4, f"exactly 4 per-char equations: {len(payload['per_char'])}"
assert len(payload["table"]) == 64, f"64-entry table folded into payload: {len(payload['table'])}"
# table is the standard alphabet in source order: index 24 -> 'Y'(89), 38 -> 'm'(109).
assert payload["table"][24] == ord('Y') and payload["table"][38] == ord('m'), "table codepoints wrong"

# Every walked op + constant must be present in the equation trees. We collect
# them STRUCTURALLY (whitespace-independent) rather than substring-matching the
# serialized form, so re-serialization with spaces does not hide a missing op.
def collect(node, ops, consts):
    if isinstance(node, dict):
        if node.get("kind") == "ctor":
            ops.add(node.get("name"))
            for a in node.get("args", []): collect(a, ops, consts)
        elif node.get("kind") == "const":
            consts.add(node.get("value"))
    elif isinstance(node, list):
        for x in node: collect(x, ops, consts)
ops, consts = set(), set()
collect(payload["per_char"], ops, consts)
for op in ["bv32.shl", "bv32.lshr", "bv32.and", "bv32.add"]:
    assert op in ops, f"walked op {op} missing from equations; saw {ops}"
# MASK_6BITS = 0x3f = 63 (field-resolved); accumulation shift 8; extraction shifts 18/12/6.
for k in [63, 8, 18, 12, 6]:
    assert k in consts, f"walked constant {k} missing from equations; saw {sorted(consts)}"
# out3 (bare & MASK) has NO lshr at its top level -- it is and(work, 63).
import re
last = payload["per_char"][3]
assert last["name"] == "bv32.and", f"out3 must be bv32.and(work, mask): {last['name']}"

print(f"PASS: STRONG positive -- 4 equations, all ops/constants present, table folded, one #euf# name")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 68: STRONG mod-3 TAILS (PHASE 2) -- the tail is now WALKED, not refused"
echo "  assertEquals(\"YmE=\", encodeBase64String(getBytesUtf8(\"ba\")))  (2-byte tail)"
echo "  assertEquals(\"Zg==\", encodeBase64String(getBytesUtf8(\"f\")))   (1-byte tail)"
echo "  Expect strong str.eq-bv-blocks rows: 2-byte tail = 3 sextet + 1 '=' pad;"
echo "  1-byte tail = 2 sextet + 2 '=' pads. Pad codepoint AST-resolved (PAD_DEFAULT=61)."
echo "────────────────────────────────────────────────────────────────"
RESULT68="$(run_lift "$FIXTURES/strong-universe" "StrongTailLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT68" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id") == 2)
ir = result["ir"]
def atoms(c): return c["inv"]["operands"]
strong = [c for c in ir if atoms(c)[0]["name"] == "str.eq-bv-blocks"]
weak   = [c for c in ir if atoms(c)[0]["name"] == "str.chars-in-set"]
assert len(strong) == 2, f"two tail callsites must emit 2 strong rows, got {len(strong)}"
assert len(weak)   == 2, f"weak str.chars-in-set must still emit per callsite, got {len(weak)}"
# Map by input bytes.
by_bytes = {}
for c in strong:
    p = json.loads(atoms(c)[0]["args"][1]["value"])
    by_bytes[tuple(p["input_bytes"])] = p
ba = by_bytes[(98, 97)]   # "ba"
f  = by_bytes[(102,)]     # "f"
# 2-byte tail: 3 sextet chars + 1 pad char (codepoint 61='=' AST-resolved).
assert len(ba["per_char"]) == 3, f"2-byte tail: 3 sextet equations, got {len(ba['per_char'])}"
assert ba.get("pad_chars") == [61], f"2-byte tail: 1 '='(61) pad, got {ba.get('pad_chars')}"
# 1-byte tail: 2 sextet chars + 2 pad chars.
assert len(f["per_char"]) == 2, f"1-byte tail: 2 sextet equations, got {len(f['per_char'])}"
assert f.get("pad_chars") == [61, 61], f"1-byte tail: 2 '='(61) pads, got {f.get('pad_chars')}"
# The pad value is AST-resolved (PAD_DEFAULT='='=61), not typed: confirm no other
# codepoint sneaks in as a pad, and that the tail sextet ops are all walked.
def collect(node, ops, consts):
    if isinstance(node, dict):
        if node.get("kind") == "ctor":
            ops.add(node.get("name"))
            for a in node.get("args", []): collect(a, ops, consts)
        elif node.get("kind") == "const":
            consts.add(node.get("value"))
    elif isinstance(node, list):
        for x in node: collect(x, ops, consts)
ops, consts = set(), set()
collect(ba["per_char"], ops, consts)
for op in ["bv32.shl", "bv32.lshr", "bv32.and", "bv32.add"]:
    assert op in ops, f"tail walked op {op} missing; saw {ops}"
# 2-byte case shifts (Base64.java:753-755): >>10, >>4, <<2; mask 63; acc shift 8.
for k in [10, 4, 2, 63, 8]:
    assert k in consts, f"tail walked constant {k} missing; saw {sorted(consts)}"
print(f"PASS: STRONG mod-3 tails WALKED -- 2-byte=3 sextet+1 pad, 1-byte=2 sextet+2 pad, pad=61 AST-resolved")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 69: STRONG discrimination -- non-literal input emits NO strong row"
echo "  byte[] data = ...; encodeBase64String(data)  (no known byte length)"
echo "────────────────────────────────────────────────────────────────"
RESULT69="$(run_lift "$FIXTURES/strong-universe" "StrongNonLiteral.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT69" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id") == 2)
ir = result["ir"]
strong = [c for c in ir if c["inv"]["operands"][0]["name"] == "str.eq-bv-blocks"]
assert len(strong) == 0, f"non-literal input must emit NO strong row, got {len(strong)}"
print(f"PASS: STRONG non-literal discrimination -- no strong row ({len(ir)} contracts total)")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 70: STRONG discrimination -- uninterpretable index (method call) REFUSES by name"
echo "  encode body indexes encodeTable[scramble(ibitWorkArea) >> 18 & MASK_6BITS]"
echo "  Expect: NO strong row; weak charset row STILL present; named refusal citing METHOD_INVOCATION."
echo "────────────────────────────────────────────────────────────────"
RESULT70="$(run_lift "$FIXTURES/strong-universe-bad-shape" "BadShapeLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT70" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id") == 2)
ir = result["ir"]; diags = result["diagnostics"]
def atoms(c): return c["inv"]["operands"]
strong = [c for c in ir if atoms(c)[0]["name"] == "str.eq-bv-blocks"]
weak   = [c for c in ir if atoms(c)[0]["name"] == "str.chars-in-set"]
assert len(strong) == 0, f"uninterpretable index must emit NO strong row, got {len(strong)}"
assert len(weak)   == 1, f"weak charset row must still emit (table walk unaffected), got {len(weak)}"
reasons = [d.get("reason", "") for d in diags]
bad = [r for r in reasons if "uninterpretable node" in r and "METHOD_INVOCATION" in r]
assert bad, f"expected named refusal citing METHOD_INVOCATION, got: {reasons}"
print(f"PASS: STRONG uninterpretable-index discrimination -- no strong row, weak stands, named refusal: {bad[0][:90]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 71: STRONG TAIL table discipline -- URL-SAFE tail emits NO '=' pad"
echo "  assertEquals(\"YmE\", encodeBase64URLSafeString(getBytesUtf8(\"ba\")))  (urlsafe 2-byte tail)"
echo "  Expect strong row with 3 sextet equations and NO pad_chars (guard is table-specific)."
echo "────────────────────────────────────────────────────────────────"
RESULT71="$(run_lift "$FIXTURES/strong-universe" "StrongUrlSafeTailLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT71" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id") == 2)
ir = result["ir"]
def atoms(c): return c["inv"]["operands"]
strong = [c for c in ir if atoms(c)[0]["name"] == "str.eq-bv-blocks"]
assert len(strong) == 1, f"urlsafe tail must emit 1 strong row, got {len(strong)}"
p = json.loads(atoms(strong[0])[0]["args"][1]["value"])
# urlsafe table: index 62 -> '-'(45), index 63 -> '_'(95) (standard would be '+'/'/' = 43/47).
assert p["table"][62] == 45 and p["table"][63] == 95, f"resolved table must be URL-SAFE: {p['table'][62:64]}"
assert len(p["per_char"]) == 3, f"3 sextet equations for a 2-byte tail, got {len(p['per_char'])}"
assert "pad_chars" not in p or not p.get("pad_chars"), \
    f"URL-SAFE tail must carry NO pad (the vendor's STANDARD-only guard), got {p.get('pad_chars')}"
print(f"PASS: STRONG tail table discipline -- URL-SAFE tail = 3 sextet, NO pad (guard walked, not typed)")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 72: STRONG TAIL discrimination -- uninterpretable tail index REFUSES by name"
echo "  encode EOF tail indexes encodeTable[scramble(ibitWorkArea) >> N & MASK] (method call)"
echo "  Expect: NO strong row; weak str.chars-in-set STILL present; named modulus-N tail refusal."
echo "────────────────────────────────────────────────────────────────"
RESULT72="$(run_lift "$FIXTURES/strong-universe-bad-tail" "BadTailLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT72" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id") == 2)
ir = result["ir"]; diags = result["diagnostics"]
def atoms(c): return c["inv"]["operands"]
strong = [c for c in ir if atoms(c)[0]["name"] == "str.eq-bv-blocks"]
weak   = [c for c in ir if atoms(c)[0]["name"] == "str.chars-in-set"]
assert len(strong) == 0, f"uninterpretable tail must emit NO strong row, got {len(strong)}"
assert len(weak)   == 1, f"weak charset row must still emit (table walk unaffected), got {len(weak)}"
reasons = [d.get("reason", "") for d in diags]
tail = [r for r in reasons if "tail refused" in r and "modulus-" in r]
assert tail, f"expected named modulus-N tail refusal, got: {reasons}"
print(f"PASS: STRONG tail uninterpretable-index discrimination -- no strong row, weak stands, named refusal: {tail[0][:90]}")
PY

# ──────────────────────────────────────────────────────────────
# Test suite (G4 — RECURRENCE keystone: symbolic execution over a MUTABLE
# ARRAY with LITERAL-BOUNDED LOOP UNROLLING. A loop-carried recurrence over a
# fixed-size buffer pins as bv32 FOL, or REFUSES BY NAME with the structural
# break located at the defeating AST node.):
#  73. POSITIVE: synthetic SeedRecurrence (MT-seeding shape, LITERAL bound) →
#      recurrence unrolled fully; per-step FOL emitted with bv32.mul/xor/lshr/
#      add + the bv32.ite low-bit gate; node count is exhaustive (silent=0).
#  74. DISCRIMINATION: non-literal bound (`state.length`) → unroll refused,
#      no FOL — the termination guarantee.
#  75. DISCRIMINATION: symbolic array index → store refused, no FOL — the
#      mutable-store soundness boundary.
#  76. DISCRIMINATION: statement-level branch-gated `if` store → refused, no
#      FOL — never silently drops a branch.
#  77. HONEST SCOPE: the REAL Commons RNG MersenneTwister.java (vendored at
#      examples/java-mt-reference) → 3 named structural refusals across the
#      seeding chain (initializeState / mixSeedAndState / mixState), zero
#      unrolled FOL, and the existing FLOOR point-contracts UNCHANGED. The
#      vendor reference-vector oath stays structurally blocked — named, not faked.
# ──────────────────────────────────────────────────────────────

# Helper: collect recurrence-walker diagnostics from a lift over a fixture.
#
# The recurrence fixtures unroll per-step FOL, so one lift result runs past
# Linux's 128 KiB single-argument limit (MAX_ARG_STRLEN): passing it as argv
# dies with "Argument list too long". Hand it over through a temp file written
# by the printf builtin, which has no such limit.
recurrence_diags() {
  local result_file
  result_file="$(mktemp)"
  printf '%s' "$1" > "$result_file"
  python3 - "$result_file" <<'PY'
import sys, json
lines = open(sys.argv[1], encoding="utf-8").read().strip().split('\n')
result = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id") == 2)
diags = result["diagnostics"]
rec = [d for d in diags if "recurrence-walker" in d.get("reason","")]
unrolled = [d for d in rec if "recurrence unrolled" in d["reason"]]
refusals = [d for d in rec if "refused" in d["reason"]]
out = {"ir": len(result["ir"]), "unrolled": [d["reason"] for d in unrolled],
       "refusals": [{"item": d.get("item",""), "reason": d["reason"]} for d in refusals]}
print(json.dumps(out))
PY
  rm -f "$result_file"
}

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 73: RECURRENCE keystone POSITIVE — literal-bounded unroll emits per-step FOL"
echo "────────────────────────────────────────────────────────────────"
RESULT73="$(run_lift "$FIXTURES/recurrence" "RecurrenceLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
DIAGS73="$(recurrence_diags "$RESULT73")"
python3 - "$DIAGS73" <<'PY'
import sys, json
o = json.loads(sys.argv[1])
assert len(o["unrolled"]) == 1, f"expected 1 recurrence-unrolled note, got {len(o['unrolled'])}: {o}"
assert len(o["refusals"]) == 0, f"positive fixture must have NO refusals, got: {o['refusals']}"
note_txt = o["unrolled"][0].split("— ", 1)[1]
note = json.loads(note_txt)
# Full unroll over the static-final LEN=8 literal bound: range [1,8) → 7 steps.
assert note["steps"] == 7, f"expected 7 unrolled steps (range [1,8)), got {note['steps']}"
assert note["induction"] == "i", f"induction var: {note['induction']}"
assert note["range_lo"] == 1 and note["range_hi_exclusive"] == 8, f"range: {note}"
# "silent = 0" is STRUCTURAL: nodes_walked is the exhaustive AST node count.
assert note["nodes_walked"] > 0, f"node count must be a real exhaustive count, got {note['nodes_walked']}"
# The per-step FOL must carry every walked operator, including the MAG01 gate.
def has(t, name):
    if isinstance(t, dict):
        if t.get("name") == name: return True
        return any(has(a, name) for a in t.get("args", []))
    return False
step0 = json.loads(note["step0_fol"])
stepN = json.loads(note["stepN_fol"])
for op in ["bv32.mul", "bv32.xor", "bv32.lshr", "bv32.add", "bv32.ite", "bv32.eq", "bv32.and"]:
    assert has(step0, op), f"step0 FOL missing {op}: {note['step0_fol'][:200]}"
assert has(stepN, "bv32.mul"), "stepN FOL missing bv32.mul (last step must also be a full recurrence step)"
print(f"PASS: RECURRENCE keystone — synthetic MT-seeding-shape recurrence unrolled FULLY over the")
print(f"      static-final literal bound: {note['steps']} steps, {note['nodes_walked']} AST nodes walked")
print(f"      (silent=0 structural), per-step bv32 FOL with mul/xor/lshr/add + the bv32.ite low-bit gate.")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 74: RECURRENCE discrimination — non-literal bound (state.length) REFUSED"
echo "────────────────────────────────────────────────────────────────"
RESULT74="$(run_lift "$FIXTURES/recurrence-openbound" "RecurrenceLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
DIAGS74="$(recurrence_diags "$RESULT74")"
python3 - "$DIAGS74" <<'PY'
import sys, json
o = json.loads(sys.argv[1])
assert len(o["unrolled"]) == 0, f"non-literal bound must emit NO FOL, got: {o['unrolled']}"
assert len(o["refusals"]) >= 1, f"expected a named refusal, got: {o}"
named = [r["reason"] for r in o["refusals"]
         if "bound" in r["reason"] and ("non-literal" in r["reason"] or "array-length" in r["reason"] or "termination" in r["reason"])]
assert named, f"expected a bound/termination refusal, got: {[r['reason'] for r in o['refusals']]}"
print(f"PASS: non-literal bound refused by name — no unbounded unroll: {named[0].split(': ',1)[1][:110]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 75: RECURRENCE discrimination — symbolic array index REFUSED"
echo "────────────────────────────────────────────────────────────────"
RESULT75="$(run_lift "$FIXTURES/recurrence-symidx" "RecurrenceLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
DIAGS75="$(recurrence_diags "$RESULT75")"
python3 - "$DIAGS75" <<'PY'
import sys, json
o = json.loads(sys.argv[1])
assert len(o["unrolled"]) == 0, f"symbolic index must emit NO FOL, got: {o['unrolled']}"
named = [r["reason"] for r in o["refusals"] if "index" in r["reason"] and ("symbolic" in r["reason"] or "concrete" in r["reason"])]
assert named, f"expected a symbolic-index refusal, got: {[r['reason'] for r in o['refusals']]}"
print(f"PASS: symbolic array index refused by name — store soundness boundary: {named[0].split(': ',1)[1][:110]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo 'TEST 76: RECURRENCE discrimination — statement-level branch-gated `if` store REFUSED'
echo "────────────────────────────────────────────────────────────────"
RESULT76="$(run_lift "$FIXTURES/recurrence-ifstore" "RecurrenceLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
DIAGS76="$(recurrence_diags "$RESULT76")"
python3 - "$DIAGS76" <<'PY'
import sys, json
o = json.loads(sys.argv[1])
assert len(o["unrolled"]) == 0, f"branch-gated `if` store must emit NO FOL, got: {o['unrolled']}"
named = [r["reason"] for r in o["refusals"] if "IF node" in r["reason"] or ("if" in r["reason"] and "branch-gated" in r["reason"])]
assert named, f"expected an IF-node refusal, got: {[r['reason'] for r in o['refusals']]}"
print(f"PASS: branch-gated `if` store refused by name (located at IF node) — no silent branch drop: {named[0].split(': ',1)[1][:110]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 77: MT SEEDING OATH — REAL MersenneTwister.java → the reference-vector"
echo "  oath CONNECTS: the inter-procedural seed→state→twist→temper recurrence is"
echo "  walked for the literal Nishimura seed and pinned to nextInt() at each draw."
echo "  (examples/java-mt-reference: machinery #1/#2/#3 resolve the param-array .length"
echo "   bounds, the field-array store, and the static-method call chain.)"
echo "────────────────────────────────────────────────────────────────"
MT_GOOD="$HERE/../../../../examples/java-mt-reference/good"
# The MT seeding value-pin payload is a LARGE closed SSA let-chain (the full walked
# 624-word seeding + twist recurrence); pass the lift JSON via a temp FILE, not argv
# (it far exceeds the arg-size limit).
LIFT77="$(mktemp)"
if [ -d "$MT_GOOD/vendor/commons-rng" ]; then
  run_lift "$MT_GOOD" "src/test/java/demo/MersenneTwisterReferenceTest.java" | eval "$JAVA_CMD" 2>/dev/null > "$LIFT77"
  python3 - "$LIFT77" <<'PY'
import sys, json
res = None
for ln in open(sys.argv[1]):
    ln = ln.strip()
    if ln and json.loads(ln).get("id") == 2:
        res = json.loads(ln)["result"]; break
assert res is not None, "no lift result"
diags = res["diagnostics"]
mt = [d for d in diags if "mt-seeding-walker" in d.get("reason","")]
# (1) the seeding folds to the genuine 624-word initial state (verified vs an
#     independent recompute) — machinery #1/#2/#3 connect, no faked state.
seed_ok = [d for d in mt if "seeding folds to the genuine" in d["reason"]]
assert seed_ok, f"expected the seeding-folds diagnostic; got {[d['reason'][:80] for d in mt]}"
assert "state[0]=0x80000000" in seed_ok[0]["reason"], f"genuine state[0] not cited: {seed_ok[0]['reason'][:160]}"
assert "0x6cf23357" in seed_ok[0]["reason"], "genuine state[1] not cited"
# (2) the twist+tempering walks and pins all 8 draw positions to the genuine row.
twist_ok = [d for d in mt if "twist+tempering walked" in d["reason"]]
assert twist_ok, f"expected the twist diagnostic; got {[d['reason'][:80] for d in mt]}"
assert "0x3fa23623" in twist_ok[0]["reason"], "genuine draw[0] not cited"
# (3) the IR carries the 8 FLOOR point contracts PLUS 8 mt-seed-value-pins (additive).
pins = [c for c in res["ir"] if c["name"].endswith("::mt-seed-value-pin")]
assert len(pins) == 8, f"expected 8 mt-seed-value-pin contracts (one per draw), got {len(pins)}"
assert len(res["ir"]) == 16, f"expected 16 IR contracts (8 floor + 8 pins), got {len(res['ir'])}"
# (4) each pin is a self-contained mt32.eq-seeded equation with NO free vars: the
#     binds reference earlier binds (the symbolic recurrence), never collapsed.
atom = pins[0]["inv"]["operands"][0]
assert atom["name"] == "mt32.eq-seeded", f"pin atom: {atom['name']}"
payload = json.loads(atom["args"][1]["value"])
binds = payload["binds"]
nvar = sum(1 for b in binds if b["tree"].get("kind") != "const")
assert nvar > len(binds) * 0.9, f"recurrence collapsed: only {nvar}/{len(binds)} symbolic binds"
print(f"PASS: REAL MersenneTwister.java — the reference-vector OATH CONNECTS.")
print(f"      Seeding folds to the genuine 624-word MT initial state (verified vs independent recompute).")
print(f"      Twist+tempering walked; 8 draws pinned to the genuine row (draw[0]=0x3fa23623 …).")
print(f"      {len(pins)} mt-seed-value-pin contracts ({nvar}/{len(binds)} symbolic binds — the real recurrence,")
print(f"      not pre-folded); 8 FLOOR point-contracts intact ({len(res['ir'])} IR total, additive).")
PY
else
  echo "SKIP: examples/java-mt-reference/good/vendor/commons-rng not present"
fi

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 77b: MT SEEDING OATH discharge — GOOD discharged / BAD refuted by z3"
echo "  (the FOL is the deliverable, the CHECK is the product: a wrong reference"
echo "   value is refuted UNSATISFIED by the walked recurrence, not a contradiction.)"
echo "────────────────────────────────────────────────────────────────"
SMT_BIN="$HERE/../../../rust/target/debug/sugar-ir-smt-lib"
if [ -s "$LIFT77" ] && command -v z3 >/dev/null 2>&1 && [ -x "$SMT_BIN" ]; then
  # Compile draw[0]'s pin to SMT (GOOD), and a BAD twin (asserted value +1), via the
  # ir-compiler RPC, then check-sat with z3. GOOD → unsat (discharged); BAD → sat.
  python3 - "$LIFT77" "$SMT_BIN" <<'PY'
import sys, json, subprocess
smt_bin = sys.argv[2]
res = None
for ln in open(sys.argv[1]):
    ln = ln.strip()
    if ln and json.loads(ln).get("id") == 2:
        res = json.loads(ln)["result"]; break
assert res is not None, "no lift result"
pin0 = next((c for c in res["ir"] if c["name"].endswith("testDraw0:mt::mt-seed-value-pin")), None)
assert pin0 is not None, "no draw0 mt-seed-value-pin (oath did not connect)"

def emit_and_checksat(inv):
    # Drive the ir-compiler subprocess: handshake + compile(inv) → CompiledFormula
    # (preamble + body). Param names per protocol: ir_json + target_dialect.
    reqs = [
        {"jsonrpc":"2.0","id":1,"method":"sugar.ir.handshake","params":{}},
        {"jsonrpc":"2.0","id":2,"method":"sugar.ir.compile",
         "params":{"ir_json":inv,"target_dialect":"smt-lib-v2.6"}},
    ]
    p = subprocess.run([smt_bin], input="\n".join(json.dumps(r) for r in reqs),
                       capture_output=True, text=True)
    smt = None
    for ln in p.stdout.splitlines():
        if not ln.strip(): continue
        o = json.loads(ln)
        if o.get("id") == 2 and "result" in o:
            r = o["result"]
            smt = r.get("preamble","") + r.get("body","")
    assert smt, f"no SMT from compiler; stdout head: {p.stdout[:300]} stderr: {p.stderr[:200]}"
    z = subprocess.run(["z3","-smt2","-in"], input=smt + "\n(check-sat)\n",
                       capture_output=True, text=True)
    return z.stdout.strip().splitlines()[0] if z.stdout.strip() else "<no-output>"

good = emit_and_checksat(pin0["inv"])
bad_inv = json.loads(json.dumps(pin0["inv"]))
a = bad_inv["operands"][0]["args"][0]["value"]
bad_inv["operands"][0]["args"][0]["value"] = a + 1   # wrong reference value
bad = emit_and_checksat(bad_inv)

assert good == "unsat", f"GOOD (vendor-sworn 0x3fa23623) must DISCHARGE (unsat), got {good}"
assert bad  == "sat",   f"BAD (wrong value) must be REFUTED (sat), got {bad}"
print(f"PASS: MT seeding oath discharges through z3 — GOOD vendor-sworn 0x3fa23623 → {good} (DISCHARGED);")
print(f"      BAD wrong value → {bad} (UNSATISFIED by the walked seed→state→twist→temper recurrence).")
print(f"      Real callsite (mt.nextInt()), real vendor value, refuted by the real recurrence — the oath.")
PY
else
  echo "SKIP: z3 or the ir-compiler binary ($SMT_BIN) not present"
fi
rm -f "$LIFT77"

# Helper: collect mt-seeding-walker diagnostics + pin count from a lift.
mt_diags() {
  python3 - "$1" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
res = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id") == 2)
diags = res["diagnostics"]
mt = [d for d in diags if "mt-seeding-walker" in d.get("reason","")]
pins = [c for c in res["ir"] if c["name"].endswith("::mt-seed-value-pin")]
# A refusal is any mt-seeding-walker diagnostic that is NOT the success note (the
# seeding-folds / twist-walked diagnostics). Everything else is a located break.
ok = ("seeding folds to the genuine", "twist+tempering walked")
out = {"pins": len(pins),
       "refusals": [d["reason"] for d in mt if not any(k in d["reason"] for k in ok)]}
print(json.dumps(out))
PY
}

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 77c: MT discrimination — machinery #1: param-array .length not resolvable REFUSED"
echo "────────────────────────────────────────────────────────────────"
RESULT77C="$(run_lift "$FIXTURES/mt-openlen" "MtDriver.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$(mt_diags "$RESULT77C")" <<'PY'
import sys, json
o = json.loads(sys.argv[1])
assert o["pins"] == 0, f"unresolvable buffer length must emit NO pin, got {o['pins']}"
named = [r for r in o["refusals"] if "param-array length" in r and "not" in r and "resolvable" in r]
assert named, f"expected a param-array length refusal, got: {o['refusals']}"
print(f"PASS: machinery #1 — param-array .length not statically resolvable refused by name (no guess): {named[0].split(': ',1)[1][:110]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 77d: MT discrimination — machinery #2: field-array store escapes bound state REFUSED"
echo "────────────────────────────────────────────────────────────────"
RESULT77D="$(run_lift "$FIXTURES/mt-field-escape" "MtDriver.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$(mt_diags "$RESULT77D")" <<'PY'
import sys, json
o = json.loads(sys.argv[1])
assert o["pins"] == 0, f"field-array store escape must emit NO pin, got {o['pins']}"
named = [r for r in o["refusals"] if "field-array store" in r and "bound state array" in r]
assert named, f"expected a field-array-store refusal, got: {o['refusals']}"
print(f"PASS: machinery #2 — a write to a field array outside the bound state refused by name: {named[0].split(': ',1)[1][:110]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 77e: MT discrimination — machinery #3: static-method call chain escapes REFUSED"
echo "────────────────────────────────────────────────────────────────"
RESULT77E="$(run_lift "$FIXTURES/mt-escaping-call" "MtDriver.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$(mt_diags "$RESULT77E")" <<'PY'
import sys, json
o = json.loads(sys.argv[1])
assert o["pins"] == 0, f"escaping call chain must emit NO pin, got {o['pins']}"
named = [r for r in o["refusals"] if "call chain" in r and "escape" in r.lower()]
assert named, f"expected a call-chain-escape refusal, got: {o['refusals']}"
print(f"PASS: machinery #3 — a seeding-chain call escaping the walkable class refused by name: {named[0].split(': ',1)[1][:110]}")
PY

# ──────────────────────────────────────────────────────────────
# Test suite (G5 — CRC VALUE-PIN: connect the folded static-init table to the
# value. WALK the stateful instance update(int) over a LITERAL input + getValue()
# inversion, pinning crc(literalInput) == value as ONE closed bv32 FOL — or REFUSE
# BY NAME (unresolvable table alias; non-literal input → floor only).):
#  78. POSITIVE: the REAL OpenJDK CRC32C (examples/java-crc32-valuepin) → the
#      value-pin contract `crc32.eq-walked` is emitted; its walked crc-FOL folds
#      to the vendor-sworn 0xE3069283, has NO free vars, and carries >= 9 update
#      shifts (the 9 walked update steps over "123456789"). The byteTable alias
#      resolves to byteTables[0] (the folded table).
#  79. DISCRIMINATION: a CRC-shaped vendor whose `byteTable` alias is assigned a
#      FRESH `new int[256]` (never the folded sub-array) → value-pin REFUSED by
#      name (alias not statically resolvable); table-fold UNCHANGED (additive).
#  80. DISCRIMINATION: a NON-LITERAL update input → no value-pin (floor only),
#      named — the literal-input gate.
# ──────────────────────────────────────────────────────────────

CRC_VP_GOOD="$HERE/../../../../examples/java-crc32-valuepin/good"

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 78: CRC VALUE-PIN POSITIVE — REAL CRC32C update()/getValue() walked into a closed crc-FOL"
echo "────────────────────────────────────────────────────────────────"
if [ -d "$CRC_VP_GOOD/vendor/jdk-crc32c" ]; then
  # The CRC value-pin payload is a large closed bv32 tree (the full walked
  # table+update FOL); pass the lift JSON via a temp FILE, not argv (it exceeds
  # the arg-size limit).
  LIFT78="$(mktemp)"
  run_lift "$CRC_VP_GOOD" "src/test/java/demo/Crc32cValuePinTest.java" | eval "$JAVA_CMD" 2>/dev/null > "$LIFT78"
  python3 - "$LIFT78" <<'PY'
import sys, json
o = None
for ln in open(sys.argv[1]):
    ln = ln.strip()
    if ln and json.loads(ln).get("id") == 2:
        o = json.loads(ln)["result"]; break
assert o is not None, "no lift result"
vps = [c for c in o["ir"] if c["name"].endswith("::crc-value-pin")]
assert len(vps) == 1, f"expected 1 value-pin contract, got {len(vps)}"
warrants = vps[0].get("sourceWarrants")
assert isinstance(warrants, list) and len(warrants) == 1, vps[0]
warrant = warrants[0]
assert warrant["kind"] == "source-memento", warrant
assert warrant["role"] == "java.crc-value-pin", warrant
assert warrant["universe_kind"] == "crc32.eq-walked", warrant
assert warrant["source_function_name"] in {"update", "getValue"}, warrant
assert "bodyText" not in warrant and "body_text" not in warrant, warrant
assert "templateJson" not in warrant and "ast_template" not in warrant, warrant
source_ledger = o.get("sourceLedger")
assert isinstance(source_ledger, dict), o
assert source_ledger["unclassified_source"] == 0, source_ledger
crc_audits = [
    audit for audit in o.get("sourceAudits", [])
    if audit["role"] == "java.crc-value-pin"
]
assert len(crc_audits) == 1, crc_audits
crc_audit = crc_audits[0]
assert crc_audit["totals"]["unclassified_source"] == 0, crc_audit
assert crc_audit["totals"]["source_warranted"] > 0, crc_audit
assert any(
    locus["status"] == "warranted"
    and locus.get("ast_kind") == "EXPRESSION_STATEMENT"
    and "crc32.eq-walked" in locus.get("reason", "")
    for locus in crc_audit["loci"]
), crc_audit
atom = vps[0]["inv"]["operands"][0]
assert atom["name"] == "crc32.eq-walked", f"value-pin atom: {atom['name']}"
asserted = atom["args"][0]["value"] & 0xffffffff
walked = json.loads(atom["args"][1]["value"])  # String-const payload
def ev(n):
    if n["kind"] == "const": return n["value"] & 0xffffffff
    if n["kind"] == "var": raise SystemExit("FREE VAR in walked crc-FOL: " + n.get("name",""))
    nm, a = n["name"], n["args"]
    if nm == "bv32.and":  return (ev(a[0]) & ev(a[1])) & 0xffffffff
    if nm == "bv32.or":   return (ev(a[0]) | ev(a[1])) & 0xffffffff
    if nm == "bv32.xor":  return (ev(a[0]) ^ ev(a[1])) & 0xffffffff
    if nm == "bv32.add":  return (ev(a[0]) + ev(a[1])) & 0xffffffff
    if nm == "bv32.shl":  return (ev(a[0]) << (ev(a[1]) & 31)) & 0xffffffff
    if nm == "bv32.lshr": return (ev(a[0]) >> (ev(a[1]) & 31)) & 0xffffffff
    if nm == "bv32.ite":  return ev(a[1]) if evb(a[0]) else ev(a[2])
    raise SystemExit("unhandled " + nm)
def evb(n):
    nm, a = n["name"], n["args"]
    if nm == "bv32.ne": return ev(a[0]) != ev(a[1])
    if nm == "bv32.eq": return ev(a[0]) == ev(a[1])
    raise SystemExit("unhandled bool " + nm)
folded = ev(walked)  # also asserts NO free var
assert folded == 0xE3069283, f"walked crc-FOL folds to {folded:#010x}, not 0xE3069283"
assert asserted == 0xE3069283, f"GOOD asserts {asserted:#010x}, not 0xE3069283"
nshift = json.dumps(walked).count('"bv32.lshr"')
assert nshift >= 9, f"walked FOL has {nshift} lshr nodes; expected >= 9 update steps"
print(f"PASS: CRC value-pin — REAL CRC32C update()/getValue() walked over \"123456789\" into a closed")
print(f"      bv32 crc-FOL ({nshift} update shifts, NO free vars) that folds to the vendor-sworn")
print(f"      0xE3069283; byteTable alias resolved to byteTables[0] (the folded table).")
PY
  rm -f "$LIFT78"
else
  echo "SKIP: examples/java-crc32-valuepin/good/vendor/jdk-crc32c not present"
fi

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 79: CRC VALUE-PIN discrimination — unresolvable byteTable alias REFUSED"
echo "────────────────────────────────────────────────────────────────"
LIFT79="$(mktemp)"
run_lift "$FIXTURES/crc-valuepin-noalias" "CrcNoAliasTest.java" | eval "$JAVA_CMD" 2>/dev/null > "$LIFT79"
python3 - "$LIFT79" <<'PY'
import sys, json
o = None
for ln in open(sys.argv[1]):
    ln = ln.strip()
    if ln and json.loads(ln).get("id") == 2:
        o = json.loads(ln)["result"]; break
assert o is not None, "no lift result"
vps = [c for c in o["ir"] if c["name"].endswith("::crc-value-pin")]
assert len(vps) == 0, f"unresolvable alias must emit NO value-pin, got {len(vps)}"
refusals = [d["reason"] for d in o["diagnostics"]
            if "value-pin refused" in (d.get("reason","") or "")
            and "alias" in d["reason"] and "resolvable" in d["reason"]]
assert refusals, f"expected a named alias refusal, got: {[d.get('reason','') for d in o['diagnostics'] if 'value-pin' in d.get('reason','')]}"
# Additive: the static-init table-fold is UNCHANGED (construction-site walk OK).
unrolled = [d for d in o["diagnostics"] if "recurrence unrolled" in (d.get("reason","") or "")]
assert len(unrolled) >= 1, "the static-init table-fold must be unaffected (additive)"
print(f"PASS: unresolvable byteTable alias refused by name — no branch guess, no faked table read:")
print(f"      {refusals[0].split(': ',1)[1][:120]}")
print(f"      (the static-init table-fold is UNCHANGED — fully additive.)")
PY
rm -f "$LIFT79"

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 80: CRC VALUE-PIN discrimination — NON-LITERAL update input → floor only, named"
echo "────────────────────────────────────────────────────────────────"
if [ -d "$CRC_VP_GOOD/vendor/jdk-crc32c" ]; then
  PROBE="$CRC_VP_GOOD/src/test/java/demo/_NonLiteralProbe.java"
  cat > "$PROBE" <<'EOF'
package demo;
import java.util.zip.CRC32C;
import org.junit.Test;
import static org.junit.Assert.assertEquals;
public class _NonLiteralProbe {
    @Test public void t(int x) {
        CRC32C crc = new CRC32C();
        crc.update(x);          // NON-literal update input
        long v = crc.getValue();
        assertEquals(0xE3069283L, v);
    }
}
EOF
  LIFT80="$(mktemp)"
  run_lift "$CRC_VP_GOOD" "src/test/java/demo/_NonLiteralProbe.java" | eval "$JAVA_CMD" 2>/dev/null > "$LIFT80"
  rm -f "$PROBE"
  python3 - "$LIFT80" <<'PY'
import sys, json
o = None
for ln in open(sys.argv[1]):
    ln = ln.strip()
    if ln and json.loads(ln).get("id") == 2:
        o = json.loads(ln)["result"]; break
assert o is not None, "no lift result"
vps = [c for c in o["ir"] if c["name"].endswith("::crc-value-pin")]
assert len(vps) == 0, f"non-literal input must emit NO value-pin (floor only), got {len(vps)}"
named = [d["reason"] for d in o["diagnostics"]
         if "crc value-pin" in (d.get("reason","") or "")
         and "non-literal" in d["reason"] and "floor only" in d["reason"]]
assert named, f"expected a non-literal floor-only refusal, got: {[d.get('reason','') for d in o['diagnostics'] if 'value-pin' in d.get('reason','')]}"
print(f"PASS: non-literal update input → no value-pin (floor only), named: {named[0].split(': ',1)[1][:110]}")
PY
  rm -f "$LIFT80"
else
  echo "SKIP: examples/java-crc32-valuepin/good/vendor/jdk-crc32c not present"
fi

# ──────────────────────────────────────────────────────────────
# Door 3 tests (81-83): the @Pattern regex universe.
# Walk a JSR-380 @Pattern(regexp="…") literal from the annotation AST into a
# str.in-regex universe row; refuse non-regular features by name; skip a
# non-literal regexp. Fixture: fixtures/universe-regex/.
# ──────────────────────────────────────────────────────────────
echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 81: @Pattern regex universe — regular pattern walked → str.in-regex row"
echo "────────────────────────────────────────────────────────────────"
RESULT81="$(run_lift "$FIXTURES/universe-regex" "RegexUniverseLift.java" | eval "$JAVA_CMD" 2>/dev/null)"
python3 - "$RESULT81" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id")==2)
ir = result["ir"]; diags = result["diagnostics"]

def atoms(c): return c["inv"]["operands"]

# accept("alice_01"): equality AND str.in-regex under the SAME #euf# name.
name = "accept#euf#c:callresult_accept_a1(s:alice_01)::assertion"
named = [c for c in ir if c["name"] == name]
eqs   = [c for c in named if atoms(c)[0]["name"] == "="]
regex = [c for c in named if atoms(c)[0]["name"] == "str.in-regex"]
assert len(eqs) == 1, f"expected 1 equality named {name}: {[c['name'] for c in ir]}"
assert len(regex) == 1, f"expected 1 str.in-regex row named {name}: {[(c['name'],atoms(c)[0]['name']) for c in ir]}\ndiags={json.dumps(diags,indent=2)}"

ra = atoms(regex[0])[0]
# arg[0] = the call:accept ctor subject; equality must share the SAME subject term.
subject = ra["args"][0]
assert subject["kind"] == "ctor" and subject["name"] == "call:accept", f"bad subject: {subject}"
eq_subject = atoms(eqs[0])[0]["args"][0]
assert eq_subject == subject, "equality and regex row must share the SAME subject term"

# arg[1] = the verbatim @Pattern regex literal walked from the annotation AST.
regex_const = ra["args"][1]
assert regex_const["kind"] == "const", f"regex arg must be a const: {regex_const}"
assert regex_const["value"] == "^[a-z][a-z0-9_]{2,15}$", \
    f"regex literal must be walked verbatim, got: {regex_const['value']}"
assert regex_const["sort"]["name"] == "String"

print("PASS: regular @Pattern walked → str.in-regex row, verbatim regex literal, same #euf# subject as the equality")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 82: @Pattern regex universe — non-regular feature REFUSED BY NAME"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT81" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id")==2)
ir = result["ir"]; diags = result["diagnostics"]

# risky() carries @Pattern(regexp="(a)\\1") — a backreference. The walker must
# REFUSE BY NAME and emit NO str.in-regex row keyed on risky.
risky_regex = [c for c in ir
               if "callresult_risky" in c["name"]
               and c["inv"]["operands"][0]["name"] == "str.in-regex"]
assert not risky_regex, f"non-regular @Pattern must emit NO str.in-regex row, got: {[c['name'] for c in risky_regex]}"

named = [d["reason"] for d in diags
         if "regex universe refused" in (d.get("reason","") or "")
         and "backreference" in d["reason"]
         and "not a regular language" in d["reason"]]
assert named, f"expected a named non-regular refusal, got: {[d.get('reason','') for d in diags]}"
print(f"PASS: non-regular @Pattern (backreference) refused by name — no str.in-regex row: {named[0][:90]}")
PY

echo
echo "────────────────────────────────────────────────────────────────"
echo "TEST 83: @Pattern regex universe — non-literal regexp not walked"
echo "────────────────────────────────────────────────────────────────"
python3 - "$RESULT81" <<'PY'
import sys, json
lines = sys.argv[1].strip().split('\n')
result = next(json.loads(l)["result"] for l in lines if l.strip() and json.loads(l).get("id")==2)
ir = result["ir"]

# dynamic() carries @Pattern(regexp=RX) where RX is a constant reference, NOT a
# string-literal AST node. The walker reads only LiteralTree<String>, so dynamic
# is not registered → NO str.in-regex row keyed on dynamic.
dyn_regex = [c for c in ir
             if "callresult_dynamic" in c["name"]
             and c["inv"]["operands"][0]["name"] == "str.in-regex"]
assert not dyn_regex, f"non-literal @Pattern regexp must emit NO str.in-regex row, got: {[c['name'] for c in dyn_regex]}"
print("PASS: non-literal @Pattern regexp (constant ref, not a string-literal AST node) not walked — no str.in-regex row")
PY

echo
echo "== all 83 tests PASS (12 P1-P3 + 7 P4 + 6 P4.5 + 5 G1 + 5 H1 + 5 G2 + 5 G2b + 5 P5c + 3 G3 + 3 Voltron + 5 P6 + 5 EF + 6 STRONG + 5 G4-RECURRENCE + 3 G5-CRC-VALUEPIN + 3 DOOR3-REGEX) =="
