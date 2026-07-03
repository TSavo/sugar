#!/usr/bin/env bash
# java-codec-universe showcase: G1 — the universe walked from the vendor's source.
#
# THE THESIS: the test IS the spec. The vendor's point assertion is the sworn
# existential; the implementation body, WALKED through its own grammar, defines
# the valid universe of the output; we mint that universe as a contract; the
# vendor's own samples gate our reading; and a consumer's false claim about ANY
# input — including inputs the vendor never tested — is refuted by z3.
#
# WEAK TIER, CALLSITE-LEVEL: the universe is "every output character is a member
# of the static final encode table (∪ pad, when the vendor's own guard attributes
# it)". Every character traces to a LiteralTree node in vendor/commons-codec/
# (tag rel/commons-codec-1.16.1, sha256 in PROVENANCE.md). The table selection
# (urlSafe → URL_SAFE_ENCODE_TABLE) is walked by literal propagation through the
# vendor's own delegation chain — no table name, no method name, no default is
# hand-authored in the kit.
#
# GOOD suite:
#   The vendor's OWN sworn vector (Base64Test.java:878):
#     assertEquals("Zm9v", encodeBase64String(getBytesUtf8("foo")))
#   lifts an equality contract AND a str.chars-in-set universe contract under
#   the SAME #euf# name. Conjoined: SAT → discharged. The vendor's sample gates
#   our reading — a mis-walked universe would refute the vendor's own test.
#
# BAD suite:
#   A consumer's false claim about an input the vendor NEVER tested:
#     assertEquals("YmFy+/x=", encodeBase64URLSafeString(getBytesUtf8("bar")))
#   '+', '/', '=' are not members of the walked URL-safe table. The universe row
#   conjoins with the equality and z3's string theory refutes it: UNSAT →
#   unsatisfied. The refutation comes from the universe walked from their
#   source, gated by their samples — the vendor never tested this input.
#
# Runs real sugar mint -> sugar prove -> sugar verify and parses real JSON receipts.
set -euo pipefail

command -v javac >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java  >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"
KIT_JAVA="$(which java)"

echo "SCOPE: G1 universe-walk — output charset walked from the vendor's static final encode tables."
echo "SCOPE: table selection resolved by literal propagation through the vendor's delegation chain."
echo "SCOPE: GOOD: vendor's own Zm9v vector (Base64Test.java:878) + universe row; discharged."
echo "SCOPE: BAD: urlsafe confusion on an input the vendor NEVER tested; unsatisfied via z3 string theory."

echo
echo "== build the sugar CLI =="
if [ "${JAVA_ASSERT_SHOWCASE_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
  cargo build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar >/dev/null
fi
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not at $SUGAR"; exit 1; }

echo
echo "== build the Java kit =="
bash "$KIT_DIR/build.sh" "$KIT_DIR/out" >/dev/null 2>&1
[ -f "$KIT_DIR/out/JavaTestAssertionsRpc.class" ] || { echo "FAIL: JavaTestAssertionsRpc.class not built"; exit 1; }

echo
echo "== prepare manifests =="
for suite in good bad; do
  mfin="$HERE/$suite/.sugar/lift/java-test-assertions/manifest.toml.in"
  mf="$HERE/$suite/.sugar/lift/java-test-assertions/manifest.toml"
  sed "s#@KIT_JAVA@#${KIT_JAVA}#g; s#@KIT_DIR@#${KIT_DIR}#g" "$mfin" > "$mf"
done

echo
echo "== source audit: sugar lift --report Commons Codec Base64.encodeBase64String =="
LIFT_REPORT_JSON="$HERE/.lift-report.json"
( cd "$HERE/good" && "$SUGAR" lift --report --json . ) > "$LIFT_REPORT_JSON"
python3 - "$LIFT_REPORT_JSON" <<'PY'
import json, sys
result = json.load(open(sys.argv[1], encoding="utf-8"))
ledger = result.get("sourceLedger") or {}
if ledger.get("unclassified_source") != 0:
    raise SystemExit(f"FAIL: Base64 source audit has unclassified source: {ledger!r}")
audits = result.get("sourceAudits") or []
weak = [a for a in audits if a.get("role") == "java.weak-universe"]
strong = [a for a in audits if a.get("role") == "java.strong-universe"]
if len(weak) != 1 or len(strong) != 1:
    raise SystemExit(f"FAIL: expected weak+strong Base64 audits, got roles={[a.get('role') for a in audits]}")
if weak[0]["totals"]["unclassified_source"] != 0 or strong[0]["totals"]["unclassified_source"] != 0:
    raise SystemExit(f"FAIL: Base64 audit unclassified totals: weak={weak[0]['totals']} strong={strong[0]['totals']}")
if not any(locus.get("line") == 780 and locus.get("status") == "warranted" for locus in strong[0]["loci"]):
    raise SystemExit("FAIL: Base64 full-block extraction line 780 was not warranted")
mementos = result.get("sourceMementos") or []
roles = {m.get("role") for m in mementos}
if not {"java.test-fact", "java.weak-universe", "java.strong-universe"} <= roles:
    raise SystemExit(f"FAIL: lift report missing source mementos: roles={sorted(str(r) for r in roles)}")
fact = next(m for m in mementos if m.get("role") == "java.test-fact")
if not fact.get("claimName", "").endswith("::assertion") or not fact.get("contractName", "").endswith("::assertion"):
    raise SystemExit(f"FAIL: test fact memento does not link to assertion contract: {fact!r}")
if "bodyText" in fact or "body_text" in fact or "templateJson" in fact or "ast_template" in fact:
    raise SystemExit(f"FAIL: test fact memento carried inline source: {fact!r}")
print(
    "   source audit:",
    f"loci={ledger['source_loci']}",
    f"warranted={ledger['source_warranted']}",
    f"refused={ledger['source_refused']}",
    f"inactive={ledger['source_inactive']}",
    f"unclassified={ledger['unclassified_source']}",
)
print("   Base64 full-block line 780 warranted; EOF tail switch accounted inactive")
PY
rm -f "$LIFT_REPORT_JSON"

echo
echo "== clean state =="
for suite in good bad; do
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" 2>/dev/null || true
  rm -f "$HERE/$suite"/.prove*.json "$HERE/$suite"/.verify*.json 2>/dev/null || true
done

pyget() { python3 "$REPO/tools/showcase/json_get.py" "$1" "$2"; }

run_suite() {
  local suite="$1" expect_consistency="$2"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite ===================="

  echo "-- mint: lift assertions + walked universe rows --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  # The universe row must actually be IN the minted proof: a str.chars-in-set
  # atom whose charset traces to the vendor's tables. No row = no teeth.
  python3 - "$suite" "$dir" <<'PY'
import glob, json, sys
suite, dirp = sys.argv[1], sys.argv[2]
found = False
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    if b"str.chars-in-set" in open(p, "rb").read():
        found = True
        break
if not found:
    raise SystemExit(f"FAIL[{suite}]: no str.chars-in-set universe row in any minted .proof")
print(f"   universe row present in minted .proof")
PY

  echo "-- prove: consistency rows (equality ∧ universe conjoined per #euf# name) --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json 2>/dev/null ) > "$prove_json" || true

  local consistency_status
  consistency_status="$(pyget "$prove_json" "
','.join([r.get('status') for r in d.get('rows', []) if (r.get('property', '') or '').startswith('consistency:')]) or 'MISSING'
")"
  echo "   prove consistency statuses: $consistency_status"

  if [ "$expect_consistency" = "DISCHARGE" ]; then
    if echo "$consistency_status" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected consistency discharged, got: $consistency_status"
      exit 1
    fi
    if [ "$consistency_status" = "MISSING" ]; then
      echo "FAIL[$suite]: no consistency rows found"
      exit 1
    fi
  else
    if ! echo "$consistency_status" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected consistency unsatisfied, got: $consistency_status"
      exit 1
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
consistency = [
    r.get("status")
    for r in rows
    if (r.get("property") or "").startswith("consistency:")
]
if not consistency:
    raise SystemExit(f"FAIL[{suite}]: durable verify has no consistency rows")
if expect_consistency == "DISCHARGE":
    if any(s != "discharged" for s in consistency):
        raise SystemExit(f"FAIL[{suite}]: expected all discharged, got {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (vendor's own sample consistent with the walked universe)")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (false claim refuted — the vendor never tested this input;")
    print(f"            the refutation comes from the universe walked from their source,")
    print(f"            gated by their samples)")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-codec-universe showcase: PASS =="
