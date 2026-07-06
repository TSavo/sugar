#!/usr/bin/env bash
# java-pattern-regex showcase (Door 3): the @Pattern / regex validation universe.
#
# THE THESIS: validation is the densest false-confidence dark — code that FEELS
# safe ("the framework validates it") with unaccounted behaviour right next to it.
# A JSR-380 `@Pattern(regexp="…")` is a vendor-sworn SET: a regular language. We
# walk that regex literal from the annotation's AST into FOL (z3's native RegLan
# theory) so CHECK refutes a "valid(x)" claim about an input the pattern rejects —
# by MEMBERSHIP in the walked language, not a within-test contradiction.
#
# WE REFUTE, WE DO NOT SOLVE. Given the regex AND the input, decide match — the
# total, decidable, given-both check. No regex synthesis, no "find a matching
# string." The oath is the vendor's: the regex is the verbatim @Pattern literal
# walked from UserHandle.accept; the claim is the consumer's test.
#
# WALK OR SILENCE, CLOSE THE HOUSE. Every supported regex token lowers to an
# exact RegLan constructor (str.to_re / re.range / re.union / re.++ / re.* / re.+
# / re.opt / re.loop / re.comp). A non-regular feature (backreference, lookahead/
# behind, atomic/possessive group, inline flag, \b anchor) is REFUSED BY NAME at
# walk time — the language is NEVER approximated; the floor stands.
#
# GOOD suite:
#   A matching input's validity claim (PatternRegexGoodTest):
#     assertEquals("alice_01", accept("alice_01"))
#   lifts an equality contract AND a str.in-regex universe row under the SAME
#   #euf# name. Conjoined: "alice_01" ∈ L(@Pattern) → SAT → discharged.
#
# BAD suite:
#   A consumer's FALSE validity claim (PatternRegexBadTest):
#     assertEquals("Alice!", accept("Alice!"))
#   "Alice!" ∉ L("^[a-z][a-z0-9_]{2,15}$") — uppercase lead, '!' body. The regex
#   universe row conjoins with the equality and z3's string/regex theory refutes
#   it: UNSAT → unsatisfied. The refutation comes from the walked regular
#   language — there is no sworn vector to contradict.
#
# Runs real sugar mint -> sugar prove -> sugar verify and parses real JSON receipts.
set -euo pipefail

command -v javac >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java  >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
KIT_JAVA="$(which java)"

echo "SCOPE: Door 3 regex universe — the @Pattern(regexp=…) literal walked from the annotation AST."
echo "SCOPE: lowered to z3 native RegLan (str.in_re / re.range / re.union / re.++ / re.loop / re.comp)."
echo "SCOPE: supported regular subset only; non-regular features (backref, lookahead, atomic) refused by name."
echo "SCOPE: GOOD: a matching handle's validity claim + regex row; discharged."
echo "SCOPE: BAD: a non-matching input claimed valid; unsatisfied via z3 string/regex theory (membership)."

echo
echo "== resolve the sugar CLI via sugarbin =="
SUGAR="$("$REPO/bin/sugarbin" --profile debug)"
BIN_DIR="$(dirname "$SUGAR")"
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not at $SUGAR"; exit 1; }

echo
echo "== build the Java kit =="
bash "$KIT_DIR/build.sh" "$KIT_DIR/out" >/dev/null 2>&1
[ -f "$KIT_DIR/out/JavaTestAssertionsRpc.class" ] || { echo "FAIL: JavaTestAssertionsRpc.class not built"; exit 1; }

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

pyget() { python3 "$REPO/tools/showcase/json_get.py" "$1" "$2"; }

run_suite() {
  local suite="$1" expect_consistency="$2"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite ===================="

  echo "-- mint: lift assertions + walked @Pattern regex universe rows --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  # The regex universe row must actually be IN the minted proof: a str.in-regex
  # atom whose regex traces to the vendor's @Pattern annotation. No row = no teeth.
  python3 - "$suite" "$dir" <<'PY'
import glob, json, sys
suite, dirp = sys.argv[1], sys.argv[2]
found = False
for p in glob.glob(dirp + "/blake3-512_*.proof"):
    if b"str.in-regex" in open(p, "rb").read():
        found = True
        break
if not found:
    raise SystemExit(f"FAIL[{suite}]: no str.in-regex universe row in any minted .proof")
print(f"   regex universe row present in minted .proof")
PY

  echo "-- prove: consistency rows (equality ∧ regex universe conjoined per #euf# name) --"
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
    print(f"   durable: PASS (the matching handle is a member of the walked @Pattern language)")
else:
    if "unsatisfied" not in consistency:
        raise SystemExit(f"FAIL[{suite}]: expected unsatisfied in {consistency}")
    print(f"   durable consistency statuses: {','.join(consistency)}")
    print(f"   durable: PASS (false validity claim refuted — the input is NOT a member")
    print(f"            of the walked @Pattern regular language; the refutation is")
    print(f"            membership-driven, not a within-test contradiction)")
PY
}

run_suite good DISCHARGE
run_suite bad  REFUSE

echo
echo "== java-pattern-regex showcase: PASS =="
