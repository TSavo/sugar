#!/usr/bin/env bash
# java-crc32-valuepin showcase: THE VALUE-PIN RUNG. The merged construction-site
# walk folds OpenJDK CRC32C's real lookup table from the `static {}` initializer;
# THIS showcase connects that folded table to the VALUE — it WALKS the vendor's
# stateful instance `update(int b)` over the canonical literal input "123456789"
# (reading the folded table at each concrete index) and getValue()'s final
# inversion, pinning crc("123456789") == value as ONE closed bv32 FOL.
#
# THE OATH IS THE VENDOR'S. OpenJDK's own test suite swears, verbatim:
#   test/jdk/java/util/zip/TestCRC32C.java:
#     ChecksumBase.testAll(new CRC32C(), 0xE3069283L);
#   ChecksumBase feeds the canonical input "123456789" and asserts
#   getValue()==expected. 0xE3069283 is the value the VENDOR SWORE.
#
# GOOD: the JDK-sworn value 0xE3069283 → DISCHARGED against the walked crc-FOL
#       (the vendor-sworn value IS the value the walked table+update produces).
# BAD:  a SINGLE wrong value 0xE3069284 → UNSATISFIED BY THE WALKED COMPUTATION
#       (one equation `(= #xe3069284 <walked FOL>)` → UNSAT). NOT a within-test
#       contradiction — the universe (folded table + walked update) does the work,
#       like java-b64-strong refuting "ZmFy".
#
# WALK OR SILENCE: every constant/op/index in the walked FOL traces to a
# com.sun.source tree node of the vendor's CRC32C AST. The byteTable alias is
# RESOLVED to byteTables[0] by walking the endianness if/else; an unresolvable
# alias or a non-literal input is REFUSED BY NAME (floor only), never faked.
#
# Runs real sugar mint -> prove -> verify and parses real JSON receipts.
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"
KIT_JAVA="$(which java)"

echo "SCOPE: java-crc32-valuepin — THE VALUE-PIN RUNG over OpenJDK CRC32C (jdk-21+35), GPLv2+CE."
echo "SCOPE: Vendor-sworn value: TestCRC32C.java → testAll(new CRC32C(), 0xE3069283L)."
echo "SCOPE: GOOD: 0xE3069283 → DISCHARGED against the walked table+update crc-FOL."
echo "SCOPE: BAD:  0xE3069284 (single wrong value) → UNSAT BY THE WALKED COMPUTATION (not a contradiction)."
echo "SCOPE: WALKED: static-init table-gen (256 steps) + stateful update(int) over \"123456789\" (9 steps)"
echo "SCOPE:         + getValue() inversion → ONE closed bv32 FOL. byteTable alias resolved to byteTables[0]."

echo
echo "== THE DOG THAT DID NOT BARK =="
echo "-- the sworn value is the VENDOR'S; we did not author it: OpenJDK's TestCRC32C oath --"
python3 - <<'PY'
POLY = 0x82F63B78  # Integer.reverse(0x1EDC6F41)
T = []
for index in range(256):
    r = index
    for _ in range(8):
        r = (r >> 1) ^ POLY if (r & 1) else (r >> 1)
    T.append(r & 0xffffffff)
crc = 0xffffffff
for b in b"123456789":
    crc = ((crc >> 8) ^ T[(crc ^ b) & 0xff]) & 0xffffffff
val = crc ^ 0xffffffff
assert val == 0xE3069283, "cross-check failed: %08X" % val
print("   independent CRC-32C(\"123456789\") cross-check = 0x%08X (matches the vendor oath)" % val)
PY

echo
echo "== build the sugar CLI =="
if [ "${JAVA_CRC32_SHOWCASE_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
  cargo build --manifest-path "$RUST/Cargo.toml" -p sugar-cli --bin sugar >/dev/null
fi
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not at $SUGAR"; exit 1; }

echo
echo "== build the Java kit =="
bash "$KIT_DIR/build.sh" "$KIT_DIR/out" >/dev/null 2>&1
[ -f "$KIT_DIR/out/JavaTestAssertionsRpc.class" ] || { echo "FAIL: kit not built"; exit 1; }

echo
echo "== THE VALUE-PIN: the keystone WALKS update()/getValue() into a closed crc-FOL =="
# Drive the lift directly and assert the value-pin contract is emitted AND its
# walked crc-FOL constant-folds to the vendor-sworn 0xE3069283 with NO free vars.
JAVA_CMD="$KIT_JAVA \
  --add-exports jdk.compiler/com.sun.source.tree=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.source.util=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED \
  -cp $KIT_DIR/out JavaTestAssertionsRpc"
LIFT_JSON="$HERE/.lift.json"
( python3 - "$HERE/good" "src/test/java/demo/Crc32cValuePinTest.java" <<'PY'
import sys, json
wr, sp = sys.argv[1], sys.argv[2]
print(json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}))
print(json.dumps({"jsonrpc":"2.0","id":2,"method":"lift","params":{"workspace_root":wr,"source_paths":[sp]}}))
print(json.dumps({"jsonrpc":"2.0","id":3,"method":"shutdown","params":{}}))
PY
) | eval "$JAVA_CMD" 2>/dev/null > "$LIFT_JSON"
python3 - "$LIFT_JSON" <<'PY'
import sys, json
result = None
for ln in open(sys.argv[1]):
    ln = ln.strip()
    if not ln: continue
    o = json.loads(ln)
    if o.get("id") == 2:
        result = o["result"]; break
if result is None:
    raise SystemExit("FAIL: no lift result")
ir = result.get("ir", [])
vps = [c for c in ir if c["name"].endswith("::crc-value-pin")]
if not vps:
    raise SystemExit("FAIL: no ::crc-value-pin contract emitted (the value-pin rung did not connect)")
warrants = vps[0].get("sourceWarrants")
if not isinstance(warrants, list) or len(warrants) != 1:
    raise SystemExit(f"FAIL: expected one source warrant on crc value-pin, got {warrants!r}")
warrant = warrants[0]
if warrant.get("role") != "java.crc-value-pin" or warrant.get("universe_kind") != "crc32.eq-walked":
    raise SystemExit(f"FAIL: wrong crc source warrant envelope: {warrant!r}")
if "bodyText" in warrant or "body_text" in warrant or "templateJson" in warrant or "ast_template" in warrant:
    raise SystemExit("FAIL: crc source warrant embeds source/template body")
crc_audits = [
    audit for audit in result.get("sourceAudits", [])
    if audit.get("role") == "java.crc-value-pin"
]
if len(crc_audits) != 1:
    raise SystemExit(f"FAIL: expected one crc source audit, got {len(crc_audits)}")
crc_audit = crc_audits[0]
totals = crc_audit.get("totals", {})
if totals.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: crc source audit has unclassified source: {totals!r}")
if not any(
    locus.get("status") == "warranted"
    and locus.get("ast_kind") == "EXPRESSION_STATEMENT"
    and "crc32.eq-walked" in locus.get("reason", "")
    for locus in crc_audit.get("loci", [])
):
    raise SystemExit("FAIL: crc update assignment was not warranted in source audit")
atom = vps[0]["inv"]["operands"][0]
if atom["name"] != "crc32.eq-walked":
    raise SystemExit("FAIL: value-pin atom is not crc32.eq-walked: " + atom["name"])
asserted = atom["args"][0]["value"] & 0xffffffff
# args[1] is a String const carrying the walked crc-FOL JSON payload.
walked = json.loads(atom["args"][1]["value"])

def ev(n):
    if n["kind"] == "const": return n["value"] & 0xffffffff
    if n["kind"] == "var":
        raise SystemExit("FAIL: walked crc-FOL contains a FREE VAR (not closed): " + n.get("name",""))
    nm, a = n["name"], n["args"]
    if nm == "bv32.and":  return (ev(a[0]) & ev(a[1])) & 0xffffffff
    if nm == "bv32.or":   return (ev(a[0]) | ev(a[1])) & 0xffffffff
    if nm == "bv32.xor":  return (ev(a[0]) ^ ev(a[1])) & 0xffffffff
    if nm == "bv32.add":  return (ev(a[0]) + ev(a[1])) & 0xffffffff
    if nm == "bv32.shl":  return (ev(a[0]) << (ev(a[1]) & 31)) & 0xffffffff
    if nm == "bv32.lshr": return (ev(a[0]) >> (ev(a[1]) & 31)) & 0xffffffff
    if nm == "bv32.ite":  return ev(a[1]) if evb(a[0]) else ev(a[2])
    raise SystemExit("FAIL: unhandled node " + nm)
def evb(n):
    nm, a = n["name"], n["args"]
    if nm == "bv32.ne": return ev(a[0]) != ev(a[1])
    if nm == "bv32.eq": return ev(a[0]) == ev(a[1])
    raise SystemExit("FAIL: unhandled bool " + nm)

folded = ev(walked)
if folded != 0xE3069283:
    raise SystemExit(f"FAIL: walked crc-FOL folds to {folded:#010x}, not the sworn 0xE3069283")
if asserted != 0xE3069283:
    raise SystemExit(f"FAIL: GOOD asserted value is {asserted:#010x}, not the sworn 0xE3069283")
# Confirm the FOL is genuinely the walked table+update: it must contain >= 9
# lshr-by-8 update shifts (one per input byte) — proof it walked the 9 update steps.
flat = json.dumps(walked)
nshift = flat.count('"bv32.lshr"')
if nshift < 9:
    raise SystemExit(f"FAIL: walked FOL has {nshift} lshr nodes; expected >= 9 (9 update steps)")
print(f"   value-pin contract emitted: crc32.eq-walked (1 closed bv32 equation).")
print(f"   walked crc-FOL = the vendor's static-init table + stateful update(int) over")
print(f"     \"123456789\" + getValue() inversion; NO free vars (genuinely closed).")
print(f"   constant-folds to {folded:#010x} == the vendor-sworn 0xE3069283 (the oath).")
print(f"   GOOD asserts {asserted:#010x} → DISCHARGES against the walked computation.")
print(
    "   source audit:",
    f"loci={totals['source_loci']}",
    f"warranted={totals['source_warranted']}",
    f"refused={totals['source_refused']}",
    f"unclassified={totals['unclassified_source']}",
)
for d in result.get("diagnostics", []):
    r = d.get("reason","") or ""
    if "value-pin refused" in r or "crc value-pin" in r:
        print("   NAMED:", r[:140])
PY
rm -f "$LIFT_JSON" 2>/dev/null || true

echo
echo "== prepare manifests and clean state =="
for suite in good bad; do
  mfin="$HERE/$suite/.sugar/lift/java-test-assertions/manifest.toml.in"
  mf="$HERE/$suite/.sugar/lift/java-test-assertions/manifest.toml"
  sed "s#@KIT_JAVA@#${KIT_JAVA}#g; s#@KIT_DIR@#${KIT_DIR}#g" "$mfin" > "$mf"
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" 2>/dev/null || true
  rm -f "$HERE/$suite"/.prove*.json "$HERE/$suite"/.verify*.json 2>/dev/null || true
done

pyget() { python3 -c "import sys,json; d=json.load(open(sys.argv[1])); print($2)" "$1"; }

run_suite() {
  local suite="$1" expect_consistency="$2"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite ===================="

  echo "-- mint: lift the CRC-32C value-pin contract(s) --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  # Verify the minted IR contains the value-pin contract (crc32.eq-walked).
  python3 - "$suite" "$dir" <<'PY'
import glob, sys
suite, dirp = sys.argv[1], sys.argv[2]
found = False
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    b = open(p, "rb").read()
    if b"crc-value-pin" in b and b"crc32.eq-walked" in b:
        found = True; break
if not found:
    raise SystemExit(f"FAIL[{suite}]: no crc32.eq-walked value-pin contract in any minted .proof")
print("   CRC-32C value-pin contract (crc32.eq-walked) present in minted .proof")
PY

  echo "-- prove: consistency rows --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json 2>/dev/null ) > "$prove_json" || true

  local consistency_status
  consistency_status="$(pyget "$prove_json" "
','.join([r.get('status') for r in d.get('rows', []) if (r.get('property', '') or '').startswith('consistency:')]) or 'MISSING'
")"
  echo "   prove consistency statuses: $consistency_status"

  if [ "$expect_consistency" = "DISCHARGE" ]; then
    if echo "$consistency_status" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected consistency discharged, got: $consistency_status"; exit 1
    fi
    if [ "$consistency_status" = "MISSING" ]; then
      echo "FAIL[$suite]: no consistency rows found"; exit 1
    fi
  else
    if ! echo "$consistency_status" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected consistency unsatisfied, got: $consistency_status"; exit 1
    fi
  fi

  echo "-- verify: durable artifact --"
  local verify_json="$dir/.verify.json"
  ( cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json 2>/dev/null ) > "$verify_json" || true

  python3 - "$suite" "$expect_consistency" "$verify_json" <<'PY'
import json, sys
suite, expect_consistency, path = sys.argv[1], sys.argv[2], sys.argv[3]
receipt = json.load(open(path, encoding="utf-8"))
rows = receipt.get("rows", [])
consistency = [r.get("status") for r in rows if (r.get("property") or "").startswith("consistency:")]
if not consistency:
    raise SystemExit(f"FAIL[{suite}]: durable verify has no consistency rows")
if expect_consistency == "DISCHARGE":
    if any(s != "discharged" for s in consistency):
        raise SystemExit(f"FAIL[{suite}]: expected all discharged, got {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (JDK-sworn 0xE3069283 DISCHARGED against the walked table+update crc-FOL)")
    print(f"   LOGO: OpenJDK's own CRC-32C check value, DERIVED from the vendor's real")
    print(f"         table-generation + stateful update by symbolic walk — the value, proven.")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (wrong CRC 0xE3069284 refuted UNSAT)")
    print(f"   the wrong CRC is refuted by the walked table+update computation, not a contradiction")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-crc32-valuepin showcase: PASS =="
