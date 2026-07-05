#!/usr/bin/env bash
# java-abs-model: z3.model derive showcase — the CHAIN IS CLOSED end to end.
#
# SCOPE: z3.model computes abs(MIN_VALUE) from the universe walked from Math.java.
# SCOPE: Derived, not executed, not asserted. The lift is the source of truth.
# SCOPE:
# SCOPE: The full chain, no hardcoded formula anywhere:
# SCOPE:   vendor source (Math.java) -> kit walk -> minted .proof
# SCOPE:     -> EXTRACT the int32.eq-bv-expr universe atom's bv_tree FROM the proof
# SCOPE:       -> z3.model derives abs(MIN_VALUE) from that lifted bv_tree.
# SCOPE:
# SCOPE: The JDK's own AbsTests.java (examples/java-abs-flagship) SWEARS the same
# SCOPE: value at line 110 ("// Strange but true"). Here the solver DERIVES it
# SCOPE: independently from the lifted universe. Two witnesses, same strange truth.
# SCOPE:
# SCOPE: GUARD: if the universe atom is deleted from the proof, `sugar derive
# SCOPE: --from-proof` has nothing to derive from and REFUSES — it never falls
# SCOPE: back to a built-in formula. That refusal is the proof the chain is real.
set -euo pipefail

command -v javac   >/dev/null 2>&1 || { echo "SKIP: no JDK on PATH"; exit 0; }
command -v java    >/dev/null 2>&1 || { echo "SKIP: no java on PATH"; exit 0; }
command -v z3      >/dev/null 2>&1 || { echo "SKIP: no z3 on PATH"; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: no python3 on PATH"; exit 0; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUST="$REPO/implementations/rust"
KIT_DIR="$REPO/implementations/java/sugar-lift-java-tests"
BIN_DIR="$RUST/target/debug"
SUGAR="$("$REPO/bin/sugarbin" --profile release)"
KIT_JAVA="$(which java)"

echo "SCOPE: java-abs-model — z3.model derive showcase, chain closed end to end."
echo "SCOPE: vendor Math.java -> kit walk -> minted .proof -> extract bv_tree -> z3.model derive."
echo "SCOPE: Walked body: (a < 0) ? -a : a  =>  bv32.ite(bv32.slt(a,0), bv32.neg(a), a)."
echo "SCOPE: Input: Integer.MIN_VALUE = -2147483648 = #x80000000."
echo "SCOPE: NO hardcoded formula: the bv_tree only ever comes from the lifted universe."
echo

# ── resolve sugar CLI + build Java kit ──────────────────────────────────────
echo "== resolve the sugar CLI =="
[ -x "$SUGAR" ] || { echo "FAIL: sugar binary not at $SUGAR"; exit 1; }
echo "   sugar binary: $SUGAR"

echo
echo "== build the Java kit =="
bash "$KIT_DIR/build.sh" "$KIT_DIR/out" >/dev/null 2>&1
[ -f "$KIT_DIR/out/JavaTestAssertionsRpc.class" ] || { echo "FAIL: JavaTestAssertionsRpc.class not built"; exit 1; }
echo "   kit class: $KIT_DIR/out/JavaTestAssertionsRpc.class"

echo
echo "== prepare manifest and clean state =="
DIR="$HERE/good"
mfin="$DIR/.sugar/lift/java-test-assertions/manifest.toml.in"
mf="$DIR/.sugar/lift/java-test-assertions/manifest.toml"
sed "s#@KIT_JAVA@#${KIT_JAVA}#g; s#@KIT_DIR@#${KIT_DIR}#g" "$mfin" > "$mf"
for p in "$DIR"/blake3-512_*.proof; do [ -e "$p" ] && rm -f "$p"; done
rm -rf "$DIR/.sugar/runs" 2>/dev/null || true
rm -f "$DIR/.dump.json" "$DIR/.bv-tree.json" "$DIR/no-universe.proof" 2>/dev/null || true
rm -f "$HERE/good-receipt.json" "$HERE/bad-receipt.json" "$HERE/no-universe-receipt.json" 2>/dev/null || true

# ── 1. MINT: walk Math.java -> the int32.eq-bv-expr universe atom ────────────
echo
echo "== 1. mint: lift Math.java -> int32.eq-bv-expr universe atom =="
( cd "$DIR" && "$SUGAR" mint --out . ) >/dev/null 2>&1 || { echo "FAIL: sugar mint failed"; exit 1; }

PROOF=""
for p in "$DIR"/blake3-512_*.proof; do [ -e "$p" ] && PROOF="$p"; done
[ -n "$PROOF" ] || { echo "FAIL: mint produced no .proof"; exit 1; }
echo "   minted: $(basename "$PROOF")"

# The universe row MUST be in the minted proof. No row = no teeth.
if ! grep -q 'int32.eq-bv-expr' "$PROOF"; then
  echo "FAIL: minted .proof carries no int32.eq-bv-expr universe atom"
  exit 1
fi
echo "   minted .proof carries the int32.eq-bv-expr universe row (walked from Math.java)."

# ── 2. EXTRACT the bv_tree FROM the minted artifact ─────────────────────────
echo
echo "== 2. extract: pull the bv_tree (universe atom args[1]) OUT of the minted .proof =="
"$SUGAR" dump "$PROOF" --json 2>/dev/null > "$DIR/.dump.json" || { echo "FAIL: sugar dump failed"; exit 1; }

# Extract args[1] of an int32.eq-bv-expr atom whose subject is abs(MIN_VALUE),
# straight out of the dumped proof. This is the ONLY source of the formula.
python3 - "$DIR/.dump.json" "$DIR/.bv-tree.json" <<'PY'
import json, sys
dump_path, out_path = sys.argv[1], sys.argv[2]
d = json.load(open(dump_path, encoding="utf-8"))

def find_universe_for_min(node):
    """Return args[1] (bv_tree) of an int32.eq-bv-expr atom whose subject
    is call:abs(-2147483648). Recursive — no hardcoded JSON path."""
    if isinstance(node, dict):
        if node.get("name") == "int32.eq-bv-expr":
            args = node.get("args", [])
            if len(args) == 2:
                subject = args[0]
                # subject ctor args carry the call-site int literal.
                subj_args = subject.get("args", []) if isinstance(subject, dict) else []
                vals = [a.get("value") for a in subj_args if isinstance(a, dict)]
                if -2147483648 in vals:
                    return args[1]
        for v in node.values():
            r = find_universe_for_min(v)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = find_universe_for_min(v)
            if r is not None:
                return r
    return None

tree = find_universe_for_min(d)
if tree is None:
    raise SystemExit("FAIL: no int32.eq-bv-expr universe atom for abs(MIN_VALUE) in the dumped proof")

# Guard: the extracted tree must be the walked body shape — not a literal we typed.
s = json.dumps(tree)
for op in ("bv32.ite", "bv32.slt", "bv32.neg"):
    if op not in s:
        raise SystemExit(f"FAIL: extracted bv_tree missing walked operator {op}: {s}")

json.dump(tree, open(out_path, "w", encoding="utf-8"))
print(f"   bv_tree extracted FROM the minted .proof (not typed into run.sh).")
print(f"   walked operators present: bv32.ite, bv32.slt, bv32.neg")
print(f"   bv_tree: {s}")
PY

EXTRACTED_BV_TREE="$(cat "$DIR/.bv-tree.json")"
[ -n "$EXTRACTED_BV_TREE" ] || { echo "FAIL: extraction yielded empty bv_tree"; exit 1; }

# ── 3. GOOD: derive abs(MIN_VALUE) from the EXTRACTED bv_tree ────────────────
echo
echo "== 3. GOOD: derive abs(MIN_VALUE) from the EXTRACTED lifted bv_tree =="
echo "   sugar derive --bv-expr <extracted-from-proof> --input=-2147483648"
"$SUGAR" derive \
  --bv-expr "$EXTRACTED_BV_TREE" \
  --input=-2147483648 \
  --receipt-out "$HERE/good-receipt.json" \
  --quiet 2>/dev/null || { echo "FAIL[good]: sugar derive exited non-zero"; exit 1; }

[ -f "$HERE/good-receipt.json" ] || { echo "FAIL[good]: receipt not written"; exit 1; }

python3 - "$HERE/good-receipt.json" <<'PY'
import json, sys
receipt = json.load(open(sys.argv[1], encoding="utf-8"))
derived = receipt.get("derived_value")
verdict = receipt.get("verdict")
model_line = receipt.get("model_line", "")
smt = receipt.get("smt_query", "")
src = receipt.get("bv_tree_source", "")
if verdict != "sat":
    raise SystemExit(f"FAIL[good]: z3 verdict must be 'sat', got {verdict!r}")
if derived != -2147483648:
    raise SystemExit(f"FAIL[good]: derived value must be -2147483648, got {derived!r}")
if "#x80000000" not in model_line:
    raise SystemExit(f"FAIL[good]: model line must contain #x80000000, got {model_line!r}")
if "(set-logic QF_BV)" not in smt or "(get-value (" not in smt:
    raise SystemExit("FAIL[good]: SMT query missing QF_BV / get-value shape")
# The result symbol is a fresh, collision-free token (not `r`); the universe
# definition binds it to the ite over the lifted arg `a`.
if "(ite (bvslt a #x00000000) (bvneg a) a)" not in smt:
    raise SystemExit("FAIL[good]: SMT missing symbolic universe definition (ite over a)")
print(f"   bv_tree source: {src}")
print(f"   z3 verdict    : {verdict}")
print(f"   z3 model      : {model_line}")
print(f"   derived value : {derived}")
print(f"   PASS[good]: z3.model derives abs(MIN_VALUE) = -2147483648 from the LIFTED bv_tree.")
print(f"              Derived, not executed. Two's complement truth.")
PY

# ── 3b. Also exercise --from-proof: the CLI reads the proof itself ──────────
echo
echo "== 3b. --from-proof: CLI reads the universe atom out of the minted .proof itself =="
"$SUGAR" derive \
  --from-proof "$PROOF" \
  --input=-2147483648 \
  --quiet 2>/dev/null | grep -q -- '-2147483648' \
  && echo "   PASS[from-proof]: derived -2147483648 reading directly from the minted .proof." \
  || { echo "FAIL[from-proof]: --from-proof did not derive -2147483648"; exit 1; }

# ── 4. BAD twin: the industry belief, refuted by the true computed value ────
echo
echo "== 4. BAD twin: industry belief abs(MIN) == MAX (2147483647) =="
echo "   The bad-twin is a FALSE claim. z3.model refutes it by computing the truth."
"$SUGAR" derive \
  --bv-expr "$EXTRACTED_BV_TREE" \
  --input=-2147483648 \
  --receipt-out "$HERE/bad-receipt.json" \
  --quiet 2>/dev/null || { echo "FAIL[bad-twin]: sugar derive exited non-zero"; exit 1; }

python3 - "$HERE/bad-receipt.json" <<'PY'
import json, sys
receipt = json.load(open(sys.argv[1], encoding="utf-8"))
derived = receipt.get("derived_value")
model_line = receipt.get("model_line", "")
industry_belief = 2147483647  # abs(x) >= 0 applied to MIN_VALUE
if derived == industry_belief:
    raise SystemExit(f"FAIL[bad-twin]: z3.model returned {derived}, validating the false claim")
if derived != -2147483648:
    raise SystemExit(f"FAIL[bad-twin]: z3.model returned unexpected value {derived}")
print(f"   z3.model response  : {model_line}")
print(f"   real derived value : {derived}")
print(f"   false claim (BAD)  : {industry_belief}")
print(f"   z3.model REFUTES the claim: {derived} != {industry_belief}")
print(f"   PASS[bad-twin]: the industry belief is false, refuted by the lifted body.")
PY

# ── 5. GUARD: delete the universe atom -> derive must REFUSE (no fallback) ───
echo
echo "== 5. GUARD: strip the universe atom from the proof -> --from-proof must REFUSE =="
echo "   If sugar derive fell back to a built-in abs formula, this would WRONGLY pass."
python3 - "$PROOF" "$DIR/no-universe.proof" <<'PY'
import sys
# Corrupt the universe atom name in the proof bytes so no int32.eq-bv-expr
# atom remains. We do a raw byte replace (the proof is CBOR with JCS-JSON
# member bodies); flipping the atom name is enough to make extraction find
# nothing. This is a deliberate negative: a universe-less proof.
src, dst = sys.argv[1], sys.argv[2]
data = open(src, "rb").read()
needle = b"int32.eq-bv-expr"
if needle not in data:
    raise SystemExit("FAIL[guard]: source proof has no universe atom to strip")
data = data.replace(needle, b"int32.eq-NOPE-expr")
open(dst, "wb").write(data)
print("   wrote a universe-less proof (int32.eq-bv-expr atom name flipped).")
PY

set +e
GUARD_OUT="$("$SUGAR" derive --from-proof "$DIR/no-universe.proof" --input=-2147483648 --quiet 2>&1)"
GUARD_RC=$?
set -e
if [ "$GUARD_RC" -eq 0 ]; then
  echo "FAIL[guard]: sugar derive SUCCEEDED on a universe-less proof — it must refuse!"
  echo "             (a built-in fallback would be a hollow chain.)"
  echo "$GUARD_OUT"
  exit 1
fi
if echo "$GUARD_OUT" | grep -qi 'refus\|nothing to derive\|no int32.eq-bv-expr'; then
  echo "   PASS[guard]: sugar derive REFUSED (rc=$GUARD_RC) — no universe atom, nothing to derive from."
  echo "               No built-in fallback. The chain is real."
else
  echo "FAIL[guard]: derive failed but not with a clear refusal message:"
  echo "$GUARD_OUT"
  exit 1
fi

echo
echo "== java-abs-model showcase: PASS =="
echo "   Chain closed: Math.java -> kit walk -> minted .proof -> extracted bv_tree -> z3.model."
echo "   GOOD: z3.model derives abs(MIN_VALUE) = -2147483648 from the LIFTED universe."
echo "   BAD : industry belief 2147483647 refuted by the true computed value."
echo "   GUARD: universe-less proof -> REFUSE (no built-in formula exists)."
echo "   The JDK's own AbsTests.java SWEARS the same value. Two independent witnesses."
