#!/usr/bin/env bash
# rust-regex-membership showcase (RegexSugar): a rust regex-match assertion lifted
# to z3 regex theory.
#
# THE PRINCIPLE: a regex match is NOT runtime — it is first-order string theory.
#   re.is_match(s)   ⟺   str.in_re(s, R)
# where the pattern literal lowers to a z3 `RegLan` term. The kit LIFTS THE SHAPE;
# it never links or runs the `regex` crate. The pattern is a SOURCE LITERAL (the
# floor — an axiom), so the membership atom bottoms out at a written string.
#
# COMPOSITIONAL: the pattern operand of `Regex::new(<pattern>)` is an INNER Sugar,
# resolved by the SAME desugar walk as everything else — an inline literal, a
# `const`-string, and a `concat!` all flow through one path. A `format!(…)` pattern
# bails TODAY (no FormatSugar yet) and digs FOR FREE the instant that producer lands.
#
# SAME TERM AS JAVA @Pattern: the emitted ProofIR atom is byte-identical to the Java
# `@Pattern` universe pass — `str.in-regex(subject, <raw-regex-const>)` — so both
# languages meet at the SAME `RegLan` by CID. The single lowering authority
# (`regex_regln`) parses the raw regex at SMT-compile time into `(str.in_re subject
# <regln>)`, and is also the lift-time regularity oracle.
#
# GOOD suite:  matching subjects -> str.in_re SAT -> consistency DISCHARGED.
#              includes const-string and concat! patterns (composition proof).
# BAD suite:   a non-matching subject ("Alice!" vs ^[a-z][a-z0-9_]{2,15}$) ->
#              str.in_re UNSAT -> consistency REFUSED. THE TEETH (z3 membership).
# NONREGULAR:  a backreference / lookahead is not a regular language -> REFUSED BY
#              NAME at lift time; NO str.in-regex row (the floor stands), the lift
#              gap names the offending feature.
#
# Runs real sugar mint -> sugar prove and parses real JSON receipts.
set -euo pipefail

command -v z3 >/dev/null 2>&1 || { echo "SKIP: no z3 on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
BIN_DIR="$RUST/target/debug"
SUGAR="$BIN_DIR/sugar"

echo "SCOPE: RegexSugar — a rust regex-match assertion lifted to z3 regex theory (str.in_re)."
echo "SCOPE: re.is_match(s) ⟺ str.in_re(s, R); the pattern literal lowers to a z3 RegLan term."
echo "SCOPE: COMPOSITIONAL pattern operand (inline literal / const-string / concat!); format! bails as the frontier."
echo "SCOPE: SAME ProofIR atom as the Java @Pattern pass — str.in-regex(subject, raw-regex); meet by CID."
echo "SCOPE: GOOD: matching subjects -> str.in_re SAT -> discharged."
echo "SCOPE: BAD: a non-matching subject -> str.in_re UNSAT -> refused (membership teeth)."
echo "SCOPE: NONREGULAR: backref/lookahead refused BY NAME at lift time; no str.in-regex row, the floor stands."

echo
echo "== build the CLI + rust test-assertion lifter =="
if [ "${RUST_REGEX_MEMBERSHIP_SKIP_LOCAL_BUILD:-0}" != "1" ]; then
  cargo build --manifest-path "$RUST/Cargo.toml" \
    -p sugar-cli --bin sugar \
    -p sugar-lift-rust-tests --bin rust_test_assertions_rpc >/dev/null
fi
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not built at $SUGAR"; exit 1; }
[ -x "$BIN_DIR/rust_test_assertions_rpc" ] || { echo "FAIL: rust_test_assertions_rpc not built"; exit 1; }

for suite in good bad nonregular; do
  for p in "$HERE/$suite"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
  rm -rf "$HERE/$suite/.sugar/runs" "$HERE/$suite/target" 2>/dev/null || true
  rm -f "$HERE/$suite"/.prove*.json "$HERE/$suite"/.mint*.log "$HERE/$suite/Cargo.lock" 2>/dev/null || true
done

pyget() { python3 "$REPO/tools/showcase/json_get.py" "$1" "$2"; }

# A consistency row that is a TEST-assertion row (the regex membership), not the
# production self-contract (`consistency:rust-source::<fn>`, a trivially-SAT value
# self-pin the SourceOracle audit emits — see rust-test-assertion-consistency).
ROW_FILTER="(r.get('property','') or '').startswith('consistency:') and not (r.get('property','') or '').startswith('consistency:rust-source::')"

run_membership_suite() {
  local suite="$1" expect="$2"
  local dir="$HERE/$suite"
  echo
  echo "==================== suite: $suite (expect $expect) ===================="

  echo "-- mint: lift regex-match assertions -> str.in-regex membership rows --"
  ( cd "$dir" && "$SUGAR" mint --out . ) >/dev/null 2>&1

  local have_proof=0
  for p in "$dir"/blake3-512_*.proof; do [ -e "$p" ] && have_proof=1; done
  [ "$have_proof" = 1 ] || { echo "FAIL[$suite]: mint produced no .proof"; exit 1; }

  # The str.in-regex universe row must actually be IN the minted proof: a regex
  # membership atom whose pattern traces to the test's own Regex::new literal.
  python3 - "$suite" "$dir" <<'PY'
import glob, sys
suite, dirp = sys.argv[1], sys.argv[2]
found = any(b"str.in-regex" in open(p, "rb").read() for p in glob.glob(dirp + "/blake3-512_*.proof"))
if not found:
    raise SystemExit(f"FAIL[{suite}]: no str.in-regex membership row in any minted .proof")
print("   str.in-regex membership row present in minted .proof")
PY

  echo "-- prove: regex membership consistency (str.in_re over the walked RegLan) --"
  local prove_json="$dir/.prove.json"
  ( cd "$dir" && "$SUGAR" prove . --json 2>/dev/null ) > "$prove_json" || true

  local statuses
  statuses="$(pyget "$prove_json" "
','.join([r.get('status','?') for r in d.get('rows',[]) if $ROW_FILTER]) or 'MISSING'
")"
  echo "   membership consistency statuses: $statuses"

  if [ "$expect" = "DISCHARGE" ]; then
    if [ "$statuses" = "MISSING" ]; then
      echo "FAIL[$suite]: no membership consistency rows found"; exit 1
    fi
    if echo "$statuses" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected all membership rows discharged, got: $statuses"; exit 1
    fi
    echo "OK[$suite]: matching subjects are MEMBERS of the walked regular language -> discharged."
  else
    if ! echo "$statuses" | grep -q 'unsatisfied'; then
      echo "FAIL[$suite]: expected a refuted (unsatisfied) membership row, got: $statuses"; exit 1
    fi
    echo "OK[$suite]: a non-matching subject is REFUTED by membership (z3 str.in_re UNSAT) -> the teeth."
  fi
}

run_nonregular_suite() {
  local dir="$HERE/nonregular"
  echo
  echo "==================== suite: nonregular (expect REFUSED BY NAME) ===================="

  echo "-- mint: a non-regular pattern (backref/lookahead) is refused at lift time --"
  local mint_log="$dir/.mint.log"
  ( cd "$dir" && "$SUGAR" mint --out . ) > "$mint_log" 2>&1 || true

  # NO str.in-regex row may exist — the language is never approximated; the floor stands.
  python3 - "$dir" <<'PY'
import glob, sys
dirp = sys.argv[1]
bad = [p for p in glob.glob(dirp + "/blake3-512_*.proof") if b"str.in-regex" in open(p, "rb").read()]
if bad:
    raise SystemExit("FAIL[nonregular]: a non-regular pattern must NOT emit a str.in-regex row")
print("   no str.in-regex row emitted (the weak floor stands)")
PY

  # The refusal must NAME the offending non-regular feature.
  if ! grep -q "non-regular feature (backreference" "$mint_log"; then
    echo "FAIL[nonregular]: backreference refusal did not name the feature"; cat "$mint_log"; exit 1
  fi
  if ! grep -q "non-regular feature (lookahead" "$mint_log"; then
    echo "FAIL[nonregular]: lookahead refusal did not name the feature"; cat "$mint_log"; exit 1
  fi
  echo "   refusal names the feature:"
  grep "non-regular feature" "$mint_log" | sed 's/^.*assert!: /     /; s/ — not expressible.*$//'
  echo "OK[nonregular]: backreference / lookahead REFUSED BY NAME at lift time (no membership row)."
}

run_membership_suite good DISCHARGE
run_membership_suite bad  REFUSE
run_nonregular_suite

echo
echo "==================== rust-regex-membership showcase: PASS ===================="
echo "good/       : matching subjects are members of the walked regex language -> discharged"
echo "              (incl. const-string and concat! patterns — the pattern composes through a child desugar)."
echo "bad/        : a non-matching subject is refuted by z3 str.in_re membership -> the teeth."
echo "nonregular/ : a non-regular feature (backref/lookahead) is refused BY NAME -> no row, the floor stands."
