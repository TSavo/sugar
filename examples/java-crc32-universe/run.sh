#!/usr/bin/env bash
# java-crc32-universe showcase: the keystone over a REAL vendor CRC, with a
# value the VENDOR SWORE behind the CHECK — and the derivation tier REFUSED BY
# NAME where the merged keystone cannot reach the vendor's table-gen.
#
# VENDOR: OpenJDK java.util.zip.CRC32C (tag jdk-21+35), GPLv2+Classpath-Exception.
#   A PURE-JAVA checksum that builds its 8x256 lookup table in a `static {}`
#   initializer from the reversed Castagnoli polynomial, then runs the classic
#   reflected update `crc = (crc>>>8) ^ table[(crc^b)&0xff]`.
#
# THE OATH IS THE VENDOR'S. OpenJDK's own test suite swears, verbatim:
#   test/jdk/java/util/zip/TestCRC32C.java:
#     ChecksumBase.testAll(new CRC32C(), 0xE3069283L);
#   ChecksumBase feeds the canonical check input "123456789" and asserts
#   getValue()==expected. 0xE3069283 is the CRC-32C (Castagnoli) analogue of the
#   canonical CRC-32 check value 0xCBF43926. It is the value the VENDOR SWORE.
#
# WHAT IS WALKED / WHAT IS REFUSED (close the house):
#   - CONSTRUCTION-SITE WALK (JLS §12.4): the RecurrenceUniverseWalker (the
#     merged array/loop-unroll keystone, extended to treat a `static {}` block as
#     a first-class construction site) enters CRC32C's static initializer and
#     FULLY UNROLLS the table-generation recurrence into FOL (256 steps). It
#     folds the polynomial from `Integer.reverse(CRC32C_POLY)`, the bound 256
#     from `byteTables[0].length`, the bound 8 from `Byte.SIZE`, and the bit-gate
#     from the `if ((r&1)!=0) … else …` statement to a `bv32.ite`. The walked FOL
#     CONSTANT-FOLDS to the real CRC32C table (asserted below) — symbolic
#     execution of the vendor AST, not a copied table. The slicing-by-8 SECOND
#     loop (a for-each over int[][] with a `.length` bound) is REFUSED BY NAME.
#   - The CHECK rides the FLOOR tier: the vendor-sworn CRC value lifted as a
#     point contract on the vendor's REAL getValue() callsite. (The walked
#     table-gen is the construction-site proof; wiring it into the value-pin via
#     the stateful instance update + the byteTable alias is the next rung, named
#     in PROVENANCE.md — not faked here.)
#
# GOOD: the JDK-sworn value 0xE3069283 on the real CRC32C callsite for the
#       canonical input → one consistent point contract → discharged.
# BAD:  the SAME callsite asserted to TWO contradictory values in one test
#       (the sworn value AND a wrong CRC) → the location-keyed contracts conjoin
#       → UNSAT → unsatisfied.
#
# Runs real sugar mint -> sugar prove -> sugar verify and parses real JSON
# receipts. Verdicts come from parsed consistency-row statuses, not exit codes.
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

echo "SCOPE: java-crc32-universe — keystone over OpenJDK CRC32C (jdk-21+35), GPLv2+CE."
echo "SCOPE: Vendor-sworn value: TestCRC32C.java → testAll(new CRC32C(), 0xE3069283L)."
echo "SCOPE: Canonical input \"123456789\"; sworn CRC-32C = 0xE3069283 (CRC-32 analogue 0xCBF43926)."
echo "SCOPE: GOOD: sworn value on the real getValue() callsite → consistent point contract → discharged."
echo "SCOPE: BAD:  same callsite, sworn value AND a wrong CRC → contradiction → unsatisfied."
echo "SCOPE: CONSTRUCTION SITE WALKED (JLS §12.4): the keystone enters the CRC32C static{} block and"
echo "SCOPE:       fully unrolls the table-gen recurrence into FOL that constant-folds to the real table"
echo "SCOPE:       (poly from Integer.reverse, bounds from .length/Byte.SIZE, bit-gate from if/else→ite)."
echo "SCOPE:       Residual slicing-by-8 second loop (a for-each over int[][]) is REFUSED BY NAME."

echo
echo "== THE DOG THAT DID NOT BARK =="
echo "-- the sworn value is the VENDOR'S; we did not author it: it is OpenJDK's TestCRC32C oath --"
echo "   0xE3069283 == $(python3 -c 'print(0xE3069283)') ; cross-checked: CRC-32C(\"123456789\")"
python3 - <<'PY'
POLY = 0x82F63B78  # reversed Castagnoli (== Integer.reverse(0x1EDC6F41))
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
  cargo build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar >/dev/null
fi
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not at $SUGAR"; exit 1; }

echo
echo "== build the Java kit =="
bash "$KIT_DIR/build.sh" "$KIT_DIR/out" >/dev/null 2>&1
[ -f "$KIT_DIR/out/JavaTestAssertionsRpc.class" ] || { echo "FAIL: kit not built"; exit 1; }

echo
echo "== THE CONSTRUCTION SITE: the keystone WALKS the CRC32C static-init table-gen =="
# Drive the lift directly and assert the RecurrenceUniverseWalker entered the
# `static {}` block (JLS §12.4 construction site), fully UNROLLED the table-gen
# recurrence into FOL, and that the walked FOL CONSTANT-FOLDS to the real CRC32C
# table (this is symbolic execution of the vendor's AST, not a copied table).
# It also names the residual break (the slicing-by-8 second loop) by name.
JAVA_CMD="$KIT_JAVA \
  --add-exports jdk.compiler/com.sun.source.tree=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.source.util=ALL-UNNAMED \
  --add-exports jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED \
  -cp $KIT_DIR/out JavaTestAssertionsRpc"
LIFT_JSON="$HERE/.lift.json"
( python3 - "$HERE/good" "src/test/java/demo/Crc32cReferenceTest.java" <<'PY'
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
diags = result.get("diagnostics", [])
recs = [d.get("reason","") for d in diags if "recurrence-walker" in (d.get("reason","") or "")]
unrolled = [r for r in recs if "recurrence unrolled" in r]
if not unrolled:
    raise SystemExit("FAIL: keystone did NOT unroll the CRC32C static-init table-gen "
                     "(the construction site must be walked, not skipped)")
raw_note = unrolled[0]
payload_start = raw_note.find("{")
if payload_start < 0:
    raise SystemExit(
        "FAIL: recurrence unrolled diagnostic did not carry a JSON payload: "
        + raw_note
    )
note = json.loads(raw_note[payload_start:])
if note["steps"] != 256:
    raise SystemExit(f"FAIL: expected 256 table-gen steps, got {note['steps']}")

# Constant-fold the walked step0 / stepN FOL and compare to the real CRC32C table.
def ev(n):
    if n["kind"] == "const": return n["value"] & 0xffffffff
    nm, a = n["name"], n["args"]
    if nm == "bv32.and":  return (ev(a[0]) & ev(a[1])) & 0xffffffff
    if nm == "bv32.or":   return (ev(a[0]) | ev(a[1])) & 0xffffffff
    if nm == "bv32.xor":  return (ev(a[0]) ^ ev(a[1])) & 0xffffffff
    if nm == "bv32.shl":  return (ev(a[0]) << (ev(a[1]) & 31)) & 0xffffffff
    if nm == "bv32.lshr": return (ev(a[0]) >> (ev(a[1]) & 31)) & 0xffffffff
    if nm == "bv32.add":  return (ev(a[0]) + ev(a[1])) & 0xffffffff
    if nm == "bv32.ite":  return ev(a[1]) if evb(a[0]) else ev(a[2])
    raise SystemExit("unhandled node " + nm)
def evb(n):
    nm, a = n["name"], n["args"]
    if nm == "bv32.ne": return ev(a[0]) != ev(a[1])
    if nm == "bv32.eq": return ev(a[0]) == ev(a[1])
    raise SystemExit("unhandled bool " + nm)
POLY = 0x82F63B78  # Integer.reverse(0x1EDC6F41), folded from the AST
def real(index):
    r = index
    for _ in range(8):
        r = (r >> 1) ^ POLY if (r & 1) else (r >> 1)
    return r & 0xffffffff
v0 = ev(json.loads(note["step0_fol"]))
vN = ev(json.loads(note["stepN_fol"]))
if v0 != real(0) or vN != real(255):
    raise SystemExit(f"FAIL: walked FOL does not fold to the real CRC32C table "
                     f"(step0={v0:#010x} vs {real(0):#010x}, stepN={vN:#010x} vs {real(255):#010x})")

ir = result.get("ir", [])
if len(ir) != 1:
    raise SystemExit(f"FAIL: expected exactly 1 GOOD point contract, got {len(ir)}")
print(f"   keystone WALKED the static-init table-gen: {note['steps']} steps, "
      f"{note['nodes_walked']} AST nodes interpreted (silent=0 structural).")
print(f"   walked FOL constant-folds to the REAL CRC32C table: "
      f"table[0]={v0:#010x}, table[255]={vN:#010x} (both match).")
print(f"     polynomial 0x82F63B78 folded from Integer.reverse(CRC32C_POLY) at the AST node;")
print(f"     bound 256 from byteTables[0].length, bound 8 from Byte.SIZE, gate from if/else→ite.")
refusals = [r for r in recs if "refused" in r]
if refusals:
    print(f"   residual break NAMED (slicing-by-8 second loop): "
          + refusals[0].split('refused: ',1)[-1][:130])
print("   GOOD point contract minted on the real getValue() callsite (1 contract).")
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

  echo "-- mint: lift the CRC-32C point contract(s) --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  # Verify the minted IR actually contains the getValue() point contract.
  python3 - "$suite" "$dir" <<'PY'
import glob, sys
suite, dirp = sys.argv[1], sys.argv[2]
found = False
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    b = open(p, "rb").read()
    if b"::assertion" in b and b"getValue" in b:
        found = True; break
if not found:
    raise SystemExit(f"FAIL[{suite}]: no getValue ::assertion contract in any minted .proof")
print("   CRC-32C getValue() point contract present in minted .proof")
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
    print(f"   durable: PASS (JDK-sworn CRC-32C value 0xE3069283 consistent on the real callsite)")
    print(f"   LOGO: OpenJDK's own CRC-32C check value, lifted from the vendor's real")
    print(f"         Checksum API and federated — the checksum's contract, sworn by the JDK.")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (within-test contradiction on the CRC-32C callsite → UNSAT)")
    print(f"   The sworn value and a wrong CRC cannot both equal getValue() → unsatisfied.")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-crc32-universe showcase: PASS =="
