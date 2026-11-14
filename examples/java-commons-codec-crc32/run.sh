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
  ( cd "$dir" && PATH="$BIN_DIR:$PATH" "$SUGAR" prove . --json 2>/dev/null ) > "$verify_json" || true
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
