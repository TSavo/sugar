#!/usr/bin/env bash
# java-commons-codec-crc32 showcase: Apache Commons Codec PureJavaCrc32,
# source-accounted through the vendor-tested byte-array update path.
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
BIN_DIR="$RUST/target/debug"
SUGAR="$("$REPO/bin/sugarbin" --profile release)"
KIT_JAVA="$(which java)"

echo "SCOPE: java-commons-codec-crc32 — PureJavaCrc32 from Apache Commons Codec rel/commons-codec-1.16.1."
echo "SCOPE: Vendor test warrant: PureJavaCrc32Test compares PureJavaCrc32 to java.util.zip.CRC32."
echo "SCOPE: GOOD: CRC32(\"123456789\") == 0xCBF43926."
echo "SCOPE: BAD:  CRC32(\"123456789\") == 0xCBF43927 is refuted by the walked slicing-by-8 table relation."

echo
echo "== resolve the sugar CLI =="
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not at $SUGAR"; exit 1; }

echo
echo "== build the Java kit =="
bash "$KIT_DIR/build.sh" "$KIT_DIR/out" >/dev/null 2>&1
[ -f "$KIT_DIR/out/JavaTestAssertionsRpc.class" ] || { echo "FAIL: kit not built"; exit 1; }

echo
echo "== prepare manifests =="
for suite in good bad; do
  mfin="$HERE/$suite/.sugar/lift/java-test-assertions/manifest.toml.in"
  mf="$HERE/$suite/.sugar/lift/java-test-assertions/manifest.toml"
  sed "s#@KIT_JAVA@#${KIT_JAVA}#g; s#@KIT_DIR@#${KIT_DIR}#g" "$mfin" > "$mf"
done

echo
echo "== source audit: sugar lift --report Commons Codec PureJavaCrc32.update(byte[], int, int) =="
LIFT_REPORT_JSON="$HERE/.lift-report.json"
( cd "$HERE/good" && "$SUGAR" lift --report --json . ) > "$LIFT_REPORT_JSON"
LIFT_JSON="$HERE/.lift.json"
( cd "$HERE/good" && "$SUGAR" lift . ) > "$LIFT_JSON"

python3 - "$LIFT_REPORT_JSON" "$LIFT_JSON" <<'PY'
import json, sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
result = json.load(open(sys.argv[2], encoding="utf-8"))
pins = [c for c in result.get("ir", []) if c["name"].endswith("::crc-value-pin")]
if len(pins) != 1:
    raise SystemExit(f"FAIL: expected one crc-value-pin, got {len(pins)}")
mementos = result.get("sourceMementos") or []
roles = {m.get("role") for m in mementos}
if not {"java.test-fact", "java.crc-value-pin"} <= roles:
    raise SystemExit(f"FAIL: raw lift missing crc source mementos: roles={sorted(str(r) for r in roles)}")
report_mementos = report.get("sourceMementos") or []
report_roles = {m.get("role") for m in report_mementos}
if not {"java.test-fact", "java.crc-value-pin"} <= report_roles:
    raise SystemExit(f"FAIL: lift report missing crc source mementos: roles={sorted(str(r) for r in report_roles)}")
fact = next(m for m in report_mementos if m.get("role") == "java.test-fact")
if not fact.get("claimName", "").endswith("::assertion") or not fact.get("contractName", "").endswith("::assertion"):
    raise SystemExit(f"FAIL: test fact memento does not link to assertion contract: {fact!r}")
if "bodyText" in fact or "body_text" in fact or "templateJson" in fact or "ast_template" in fact:
    raise SystemExit(f"FAIL: test fact memento carried inline source: {fact!r}")
warrant = pins[0].get("sourceWarrants", [None])[0]
if not warrant or not warrant["file"].endswith("vendor/commons-codec/org/apache/commons/codec/digest/PureJavaCrc32.java"):
    raise SystemExit(f"FAIL: wrong source warrant: {warrant!r}")
if warrant["span"]["start_line"] != 598 or warrant["span"]["end_line"] != 637:
    raise SystemExit(f"FAIL: expected bulk update span 598-637, got {warrant['span']!r}")
audits = [a for a in report.get("sourceAudits", []) if a.get("role") == "java.crc-value-pin"]
if len(audits) != 1:
    raise SystemExit(f"FAIL: expected one crc source audit, got {len(audits)}")
audit = audits[0]
totals = audit["totals"]
if totals.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: unclassified source remains: {totals!r}")
by_line = {locus["line"]: locus for locus in audit["loci"]}
for line in [605, 606, 607, 609, 610, 611, 612]:
    locus = by_line.get(line)
    if not locus or locus["status"] != "warranted" or "slicing-by-8" not in locus["reason"]:
        raise SystemExit(f"FAIL: line {line} not warranted as slicing-by-8: {locus!r}")
for line in [617, 618, 619, 620, 621, 622, 623, 624, 625, 626, 627, 628]:
    locus = by_line.get(line)
    if not locus or locus["status"] != "inactive":
        raise SystemExit(f"FAIL: line {line} not inactive tail residue: {locus!r}")
for line in [629, 630, 636]:
    locus = by_line.get(line)
    if not locus or locus["status"] != "warranted":
        raise SystemExit(f"FAIL: line {line} not warranted: {locus!r}")

atom = pins[0]["inv"]["operands"][0]
asserted = atom["args"][0]["value"] & 0xffffffff
walked = json.loads(atom["args"][1]["value"])
def ev(node):
    if node["kind"] == "const":
        return node["value"] & 0xffffffff
    if node["kind"] == "var":
        raise SystemExit("FAIL: walked crc-FOL contains free var " + node.get("name", ""))
    name, args = node["name"], node["args"]
    if name == "bv32.xor":
        return (ev(args[0]) ^ ev(args[1])) & 0xffffffff
    if name == "bv32.lshr":
        return (ev(args[0]) >> (ev(args[1]) & 31)) & 0xffffffff
    raise SystemExit("FAIL: unhandled bv node " + name)
folded = ev(walked)
if asserted != 0xCBF43926 or folded != 0xCBF43926:
    raise SystemExit(f"FAIL: asserted/folded mismatch asserted={asserted:#010x} folded={folded:#010x}")
print(
    "   source audit:",
    f"loci={totals['source_loci']}",
    f"warranted={totals['source_warranted']}",
    f"inactive={totals['source_inactive']}",
    f"refused={totals['source_refused']}",
    f"unclassified={totals['unclassified_source']}",
)
print("   lines 605-612: slicing-by-8 input/table relation warranted")
print("   walked crc-FOL folds to 0xcbf43926")
PY
rm -f "$LIFT_REPORT_JSON" "$LIFT_JSON"

echo
echo "== clean state =="
for suite in good bad; do
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" "$HERE/$suite/.sugar/witnesses" 2>/dev/null || true
  rm -f "$HERE/$suite"/.prove*.json "$HERE/$suite"/.verify*.json 2>/dev/null || true
done

pyget() { python3 "$REPO/tools/showcase/json_get.py" "$1" "$2"; }

run_suite() {
  local suite="$1" expect="$2"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite ===================="
  echo "-- mint: lift the Commons CRC32 value-pin contract(s) --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1
  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  python3 - "$suite" "$dir" <<'PY'
import glob, sys
suite, dirp = sys.argv[1], sys.argv[2]
found = any(b"crc32.eq-walked" in open(path, "rb").read()
            for path in glob.glob(dirp + "/blake3-512_*.proof"))
if not found:
    raise SystemExit(f"FAIL[{suite}]: no crc32.eq-walked value-pin in minted .proof")
print("   crc32.eq-walked value-pin present in minted .proof")
PY

  echo "-- prove: consistency rows --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json 2>/dev/null ) > "$prove_json" || true
  local statuses
  statuses="$(pyget "$prove_json" "','.join([r.get('status') for r in d.get('rows', []) if (r.get('property','') or '').startswith('consistency:')]) or 'MISSING'")"
  echo "   prove consistency statuses: $statuses"
  if [ "$expect" = "DISCHARGE" ]; then
    if echo "$statuses" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected discharged, got: $statuses"; exit 1
    fi
    [ "$statuses" != "MISSING" ] || { echo "FAIL[$suite]: missing consistency rows"; exit 1; }
  else
    if ! echo "$statuses" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected unsatisfied, got: $statuses"; exit 1
    fi
  fi

  echo "-- verify: durable artifact --"
  local verify_json="$dir/.verify.json"
  ( cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" verify --project . --json 2>/dev/null ) > "$verify_json" || true
  python3 - "$suite" "$expect" "$verify_json" <<'PY'
import json, sys
suite, expect, path = sys.argv[1], sys.argv[2], sys.argv[3]
receipt = json.load(open(path, encoding="utf-8"))
statuses = [
    row.get("status")
    for row in receipt.get("rows", [])
    if (row.get("property") or "").startswith("consistency:")
]
if not statuses:
    raise SystemExit(f"FAIL[{suite}]: durable verify has no consistency rows")
if expect == "DISCHARGE":
    if any(status != "discharged" for status in statuses):
        raise SystemExit(f"FAIL[{suite}]: expected discharged rows, got {statuses}")
    print(f"   durable consistency statuses: {','.join(statuses)}")
else:
    if "unsatisfied" not in statuses:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {statuses}")
    print(f"   durable consistency statuses: {','.join(statuses)}")
PY
}

run_suite good DISCHARGE
run_suite bad REFUSE

echo
echo "== java-commons-codec-crc32 showcase: PASS =="
