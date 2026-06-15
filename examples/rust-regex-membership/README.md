# Rust Regex Membership (`RegexSugar`)

A rust regex-match assertion lifted to z3 regex theory. A regex match is **not
runtime** — it is first-order string theory:

```
re.is_match(s)   ⟺   str.in_re(s, R)
```

where the pattern literal compiles to a z3 `RegLan` term. The kit **lifts the
shape**; it never links or runs the `regex` crate. The pattern is a **source
literal** (the floor — an axiom), so the membership atom bottoms out at a written
string.

This is the rust sibling of `examples/java-pattern-regex` (Door 3, the JSR-380
`@Pattern` universe). Both emit the **identical** ProofIR atom —
`str.in-regex(subject, <raw-regex>)` — so the two languages meet at the same
`RegLan` by CID. The single regex→`RegLan` lowering authority
(`sugar-ir-compiler-smt-lib/src/regex_regln.rs`) parses the raw regex at
SMT-compile time into `(str.in_re subject <regln>)`, and is also the lift-time
regularity oracle.

## Compositional pattern operand

The `<pattern>` operand of `Regex::new(<pattern>)` is an **inner `Sugar`**, built
by the same walk as everything else and resolved by `desugar` — not a raw literal
matched in place. So the pattern is not required to *be* a `LitStr`; it must
*desugar to* one:

- an inline `"pat"` literal → a string-literal base case (digs now);
- a `const PAT: &str = "pat"` / `let p = "pat"` → resolved through the const/let
  resolver (digs now);
- a `concat!("a", "b")` of string literals → resolved through the concat resolver
  (digs now);
- a `format!(…)` pattern → bails **today** (no `FormatSugar` yet) and digs **for
  free** the instant that producer lands, with zero change to `RegexSugar`. This
  is the composition frontier: `Regex ∘ Format ∘ Literal`.

## Suites

- `good/`: matching subjects (inline, `const`-string, `concat!`, and
  `find(..).is_some()`) → `str.in_re` **SAT** → consistency **discharged**. The
  `const`/`concat!` cases prove the pattern came **through a child desugar**, not a
  hardcoded literal.
- `bad/`: a non-matching subject (`"Alice!"` vs `^[a-z][a-z0-9_]{2,15}$` —
  uppercase lead and a `!` body char) → `str.in_re` **UNSAT** → consistency
  **refused**. **The teeth**: the refutation is by membership in the walked regular
  language (z3 string/regex theory), not a within-test contradiction.
- `nonregular/`: a backreference (`(a)\1`) / lookahead (`foo(?=bar)`) is **not a
  regular language** → **refused by name** at lift time (mirroring the Java
  `PatternUniverseWalker`). No `str.in-regex` row is emitted — the language is
  never approximated, the weak floor stands, and the lift gap names the offending
  feature.

Run `bash run.sh` (requires `z3` and `python3` on PATH). It runs real
`sugar mint` → `sugar prove` and parses the JSON receipts.
