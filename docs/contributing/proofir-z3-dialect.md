<!--
  The ProofIR dialect as the z3/SMT-LIB backend actually supports it. Grounded in
  implementations/rust/sugar-ir-compiler-smt-lib/src/{lib.rs,generated.rs,literal_encoding.rs,
  isinstance_encoding.rs,regex_regln.rs,derive_query.rs}. One level below lifting-vocabulary.md:
  that page names the parts; this page is the exact subset the z3 compiler accepts and
  the SMT-LIB it emits. The compiler is authoritative; if this drifts, read it, not this.
-->
# The ProofIR dialect the z3 compiler supports

[lifting-vocabulary](lifting-vocabulary.md) names the parts of ProofIR. This page is the
**exact subset the SMT-LIB / z3 backend (`sugar-ir-compiler-smt-lib`) accepts**, and the
SMT-LIB2 it lowers each form to. If you emit IR outside this dialect, the backend either
refuses (soundly) or errors — it never guesses. The compiler source is authoritative; this
is a map of it.

## The shape of a compile

A `Formula` goes in; SMT-LIB2 comes out as a **preamble** (`declare-const` / `declare-fun` /
axioms) plus a **body** of `(assert …)`. Discharge is two queries over that:

- **consistency:** `(assert φ) (check-sat)` — `unsat` means the lifted facts are
  self-contradictory → **refused**; `sat` means consistent.
- **teeth (the bad-twin):** assert the *wrong* literal alongside; it must come back `unsat`.
  A contract whose bad-twin stays `sat` has no teeth (see [lifting-rules §5, §9](lifting-rules.md)).

## Formula forms

Supported `IrFormula` (lowered by `generated.rs`):

| ProofIR | SMT-LIB |
|---|---|
| `Atomic { name, args }` | `(<name> arg…)` — see the predicate vocabulary below |
| `And` / `Or` / `Not` / `Implies` | `(and …)` / `(or …)` / `(not …)` / `(=> …)` |
| `Forall` / `Exists` / `Choice` | quantifiers over sorted bound vars |

**Must be reduced before the backend** (reaching it is an error, not a refusal):

- `Substitute` / `Apply` — these are `wp_rule` schema nodes; `libsugar::wp` must eliminate
  them before solving.
- `DivergenceBetween` — a platform-divergence formula; the stage-4 lowering must resolve it
  before solving.

## Term forms

`IrTerm`: `Var`, `Const { value, sort }`, `Ctor { name, args }` (an operation applied to
args), `Lambda`, `Let`. Lambdas and lets are walked through to their bodies; constants carry
their own sort.

## Sorts

The backend maps to a small set of SMT sorts:

- **`Int`**, **`Bool`**, **`String`** — the supported primitives.
- **int-width sorts** (`i32`, `u64`, …) collapse to `Int` (width is a refinement, not a
  separate solver sort), *except* under `sugar derive`, which uses **`(_ BitVec 32)`** so it
  can compute exact two's-complement results (the `abs(Integer.MIN_VALUE)` flagship).
- an **unknown / unsupported sort** is declared opaque.

### Strings have two regimes

A `String`-typed value lowers to SMT **`String` theory**; a string value that does **not**
carry the `String` sort (e.g. an opaque method-call *receiver* whose only `String` is the
call *result*) lowers to an **opaque `strlit_<hash>` `Int`** — distinct integers asserted
`(distinct …)` only when an opaque literal is compared against a concrete one. The hard rule:
**one symbol cannot be both `Int` and `String`.** `check_mixed_sort_conjunction` rejects a
conjunction that would force that — a *sound refuse*, not a crash. (Getting the receiver-vs-result
sort wrong is the classic `unknown constant method:to_string (String)` regression.)

## Unknown ctors are uninterpreted (EUF)

This is the heart of the dialect. A `Ctor { name, args }` the backend doesn't special-case
becomes an **uninterpreted function**: `(declare-fun <name> (<arg-sorts>) <ret-sort>)` plus
`(<name> arg…)`. The function is opaque — z3 knows nothing about what it computes. What gives
it teeth is the **universe of literal facts** asserted around it: `encodeBase64("abc") == "xyz"`
is `(assert (= (encodeBase64 "abc") "xyz"))` over an uninterpreted `encodeBase64`, and the
bad-twin `(assert (= (encodeBase64 "abc") "WRONG"))` is `unsat` against it. The vendor's stated
fact pins the opaque call; the literal anchor is what makes the dig real (this is exactly why an
[EUF dig needs teeth](lifting-rules.md)).

## Predicate vocabulary (`Atomic.name` → SMT-LIB)

The backend special-cases these names; everything else is an uninterpreted application.

| `Atomic.name` | lowers to |
|---|---|
| `=` | `(= a b)` (Int/Bool, or String theory when string-routed) |
| `str.len` | `(str.len s)` |
| `str.contains` / `str.prefixof` / `str.suffixof` | the matching SMT string op |
| `str.is_ascii`, `str.is_ascii_alphabetic`, `str.is_ascii_digit`, `str.is_ascii_hexdigit`, `str.is_ascii_punctuation`, … | `(str.in_re s <re>)` built from `re.range` / `re.union` / `re.*` |
| `str.chars-in-set` | `(str.in_re s (re.* (re.union (str.to_re "c1") …)))` |
| `isinstance` | `(declare-fun isinstance (Int Int) Bool)` + a `(not (and (isinstance s A) (isinstance s B)))` disjointness axiom per incompatible type pair |
| a lifted regex | a RegLan term (`re.*`, `re.range`, `re.union`, `str.to_re`, `str.in_re`) |
| bitvec ops (`derive` only) | `bvslt`, `bvneg`, `ite`, `#x…` hex literals over `(_ BitVec 32)` |

The friendly lifter-facing names in
[`writing-a-lift-adapter` §canonical-predicate-vocabulary](writing-a-lift-adapter/03-emit-canonical-IR.md)
(`eq`, `starts_with`, `length_ge`, `is_some`, …) are aliases that resolve to these — emit
those when you can; this table is what they bottom out as.

## What "supported" means for you

- Emit a formula built only from the forms above and the backend compiles it.
- Emit an unknown **ctor** and it becomes an honest uninterpreted function — sound, and
  given teeth by your literal universe.
- Emit an unknown **sort** or a mixed Int/String symbol and you get a **loud refuse**, not a
  silent wrong answer.
- Emit a `substitute`/`apply`/`divergence` node and you get an **error** — those must be
  lowered upstream first.

That asymmetry is the point: the dialect is small, total, and refuses rather than guesses, so
a kit can extend ProofIR coverage by adding *facts and sorts*, never by teaching z3 a
language.

---

Authoritative source: `implementations/rust/sugar-ir-compiler-smt-lib/src/` (`lib.rs`,
`generated.rs`, `literal_encoding.rs`, `isinstance_encoding.rs`, `regex_regln.rs`,
`derive_query.rs`). See also: [lifting-vocabulary](lifting-vocabulary.md) ·
[the ProofIR grammar (CDDL)](../../protocol/sugar-ir.cddl) · [lifting-rules](lifting-rules.md).
