// SPDX-License-Identifier: Apache-2.0
//
// HAND-MAINTAINED (NOT generated). This module is deliberately kept OUT of
// `generated.rs` so a future regeneration of the (vestigially "GENERATED")
// emitter file cannot silently revert the string/bool literal encoding and
// the cross-type distinctness axiom. `generated.rs` calls into here.
//
// ── What this module encodes, and why ────────────────────────────────────
//
// The pytest consistency pass conjoins a test's `assert`s into one `inv` and
// SAT-checks it: a satisfiable `inv` means the assertions are mutually
// CONSISTENT; an unsatisfiable one means they CONTRADICT. For that verdict to
// match Python `==` semantics, the SMT encoding of literal constants must
// honor Python's value identities and disjointness EXACTLY:
//
//   - Distinct string literals are unequal:        `"a" != "b"`
//   - A string literal is not any number:          `"5" != 5`
//   - A string literal is not None:                `"x" != None`
//   - None is not any number, not any string:      `None != 5`, `None != "x"`
//   - bool IS int:                                  `True == 1`, `False == 0`
//   - (float == int sometimes:                      `5.0 == 5` — see residual)
//
// Free vars (call results) are hardcoded to the SMT `Int` sort, so every
// literal must live in the Int universe. We split literals into two classes:
//
//   CONCRETE-VALUED literals — int (`n`) and bool (`True->1`, `False->0`) —
//     emit as their literal Int value. z3 then derives `5 != 6`, `True == 1`,
//     `True != 0`, etc. FOR FREE and CORRECTLY. They are NEVER placed in a
//     `distinct` axiom: asserting `bool != int` would be a FALSE fact and
//     would manufacture a spurious refusal (`True == 1` must stay consistent).
//
//   OPAQUE literals — string (`strlit_<hash>`) and None (`None`) — are
//     uninterpreted Int constants with no intrinsic value. z3 will otherwise
//     freely choose a model where `strlit == 5` or `None == strlit`, which is
//     a Python-false equality. To prevent that we emit ONE distinctness axiom
//     making the opaque constants distinct from EACH OTHER and from every
//     concrete Int value present in the formula.
//
// SOUNDNESS PRINCIPLE (the check against both falsePass and false-refusal):
//   Every pair we assert distinct is a Python-TRUE inequality. Asserting a
//   true fact can only ELIMINATE spurious models (catch contradictions); it
//   can never invent one. The only way to manufacture a false refusal is to
//   assert a FALSE distinctness — `bool != int` or `float != int` — so bool
//   is encoded concretely (never distinct) and non-integer floats are left
//   unasserted (residual; `5.0 == 5` is not modeled).
//
// BYTE-IDENTITY: the distinctness axiom is emitted ONLY when at least one
// OPAQUE literal (string or None) is present. String/None-free arithmetic
// formulas are byte-for-byte unchanged. A lone opaque const with no other
// constrained member emits nothing (a single `≠(x,None)` fact stays
// byte-identical to the pre-fix output; receipt-1 contracts are untouched).

use std::collections::BTreeSet;
use sugar_canonicalizer::blake3_512_of;
use sugar_ir_types::*;

/// Derive a deterministic, parse-safe SMT-LIB symbol name for a string
/// literal: `strlit_<24-hex-chars-of-blake3-of-utf8-bytes>`.
///
/// String literals cannot be emitted as `"..."` SMT string-theory values
/// here because (1) the free-var sort is `Int`, so a `String`-sort value is
/// ill-sorted, and (2) braces / backslashes / control chars / Unicode in the
/// raw text cause z3 PARSE ERRORS (an encoding bug, surfacing as UNDECIDABLE
/// and masking real verdicts). Encoding as a hash-named uninterpreted Int
/// constant excises escaping entirely (the name is `[0-9a-f]` only) and is
/// sort-compatible with the Int free var.
///
/// Soundness: same literal -> same name -> equal; different literals ->
/// different names (collision < 2^-96 for up to 2^32 formulas) -> made
/// distinct by the axiom below.
pub fn string_lit_name(s: &str) -> String {
    let full = blake3_512_of(s.as_bytes());
    // Strip the `blake3-512:` prefix (its colon is not a legal SMT simple-symbol
    // char); fall back to alphanumeric-only filtering if the format changes.
    let hex_part = full.strip_prefix("blake3-512:").unwrap_or(&full);
    let prefix: String = hex_part
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .take(24)
        .collect();
    format!("strlit_{}", prefix)
}

/// The SMT symbol the `None` nullary ctor lowers to (see `smt_quote("None")`,
/// which is a no-op for this plain identifier).
const NONE_SYMBOL: &str = "None";

/// The literal constants gathered from a formula, partitioned into the two
/// encoding classes.
#[derive(Debug, Default)]
pub struct LiteralConstants {
    /// Distinct opaque-literal SMT symbols (string-literal names + `None`),
    /// in stable sorted order.
    opaque_symbols: BTreeSet<String>,
    /// Distinct concrete Int values present (from Int consts AND bool consts,
    /// the latter mapped True->1 / False->0). Used as the right-hand side of
    /// the distinctness axiom so opaque constants are kept off these values.
    /// i128 carrier: a wide Int const (u64::MAX .. i128 range) must enter this
    /// set EXACTLY, or a refutation against an opaque symbol could be masked.
    concrete_ints: BTreeSet<i128>,
}

impl LiteralConstants {
    /// Walk a formula collecting every literal constant. Idempotent per value.
    #[cfg(test)]
    pub fn from_formula(formula: &Formula) -> Self {
        let mut lc = LiteralConstants::default();
        lc.collect_formula(formula);
        lc
    }

    /// Walk a formula collecting only literals that still use the legacy
    /// opaque-Int equality encoding. String-theory atoms render their string
    /// operands as real SMT `String` literals, so collecting those same
    /// operands here would add unused `strlit_*` declarations and distinctness
    /// axioms to otherwise pure string-theory scripts.
    pub fn from_formula_for_legacy_literals(formula: &Formula) -> Self {
        let mut lc = LiteralConstants::default();
        lc.collect_formula_for_legacy_literals(formula);
        lc
    }

    #[cfg(test)]
    fn collect_formula(&mut self, formula: &Formula) {
        match formula {
            Formula::Atomic { args, .. } => {
                for a in args {
                    self.collect_term(a);
                }
            }
            Formula::And { operands }
            | Formula::Or { operands }
            | Formula::Not { operands }
            | Formula::Implies { operands } => {
                for o in operands {
                    self.collect_formula(o);
                }
            }
            Formula::Forall { body, .. }
            | Formula::Exists { body, .. }
            | Formula::Choice { body, .. } => self.collect_formula(body),
            Formula::Substitute { .. } | Formula::Apply { .. } => {}
            Formula::DivergenceBetween { source, target } => {
                self.collect_formula(source);
                self.collect_formula(target);
            }
        }
    }

    fn collect_formula_for_legacy_literals(&mut self, formula: &Formula) {
        match formula {
            Formula::Atomic { name, args } => {
                if name == "identity" {
                    return;
                }
                if routes_to_string_theory(name, args) {
                    // The atom's TOP-LEVEL string consts render as real SMT
                    // String literals (no `strlit_*` declaration needed). But a
                    // ctor argument (e.g. a `callresult_*` subject) still has
                    // its OWN args rendered by the legacy `emit_term` path, so
                    // any string const nested inside it IS emitted as a
                    // `strlit_*` symbol and must be collected/declared here, or
                    // the script references an undeclared constant.
                    for a in args {
                        if !matches!(
                            a,
                            Term::Const {
                                value: serde_json::Value::String(_),
                                ..
                            }
                        ) {
                            self.collect_term_for_legacy_literals(a);
                        }
                    }
                    return;
                }
                // G2: BV32 atoms live in the bitvector sort — skip legacy Int
                // opaque-symbol collection entirely. The BV emitter handles them.
                if routes_to_bv32_theory(name) {
                    return;
                }
                for a in args {
                    self.collect_term_for_legacy_literals(a);
                }
            }
            Formula::And { operands }
            | Formula::Or { operands }
            | Formula::Not { operands }
            | Formula::Implies { operands } => {
                for o in operands {
                    self.collect_formula_for_legacy_literals(o);
                }
            }
            Formula::Forall { body, .. }
            | Formula::Exists { body, .. }
            | Formula::Choice { body, .. } => self.collect_formula_for_legacy_literals(body),
            Formula::Substitute { .. } | Formula::Apply { .. } => {}
            Formula::DivergenceBetween { source, target } => {
                self.collect_formula_for_legacy_literals(source);
                self.collect_formula_for_legacy_literals(target);
            }
        }
    }

    #[cfg(test)]
    fn collect_term(&mut self, term: &Term) {
        match term {
            // CRITICAL: partition by VALUE, not by the declared sort label, so
            // the distinctness-target set can NEVER desync from what
            // `emit_const_value` renders into the body (which is also
            // value-based). A bool/int value carrying a mislabeled sort (e.g.
            // the `{value:true, sort:Int}` shape that exists in the wild and in
            // the byte-for-byte fixture) must still be collected as a concrete
            // int, or the body would emit `1` while the `(distinct ...)` omits
            // it -> sat -> falsePass. Soundness is value-driven here.
            Term::Const { value, sort } => {
                // Concrete-int FIRST (value-driven, now also recovering a wide
                // Int-sorted decimal string -- see `const_concrete_int`): such
                // a value enters the distinctness RHS, never the opaque set.
                if let Some(i) = const_concrete_int(value, sort) {
                    // Only integer-valued numerics/bools/wide-ints enter the RHS.
                    // A non-integer float is left out (residual): asserting
                    // `strlit != 5.0` would be ill-sorted, and `5.0 != 5` is
                    // Python-false (`5.0 == 5`).
                    self.concrete_ints.insert(i);
                } else if let serde_json::Value::String(s) = value {
                    // OPAQUE: hash-named uninterpreted Int const (see emit).
                    // (A wide Int-sorted string was already taken above.)
                    self.opaque_symbols.insert(string_lit_name(s));
                }
            }
            Term::Ctor { name, args } => {
                // None is an opaque literal (nullary `None` ctor). It is the
                // only ctor treated as a literal here; all other ctors are
                // uninterpreted functions handled by the ctor-decl pass.
                if name == "None" && args.is_empty() {
                    self.opaque_symbols.insert(NONE_SYMBOL.to_string());
                }
                for a in args {
                    self.collect_term(a);
                }
            }
            Term::Lambda { body, .. } => self.collect_term(body),
            Term::Let { bindings, body, .. } => {
                for b in bindings {
                    self.collect_term(&b.bound_term);
                }
                self.collect_term(body);
            }
            Term::Var { .. } => {}
        }
    }

    fn collect_term_for_legacy_literals(&mut self, term: &Term) {
        match term {
            Term::Ctor { name, .. }
                if name == "str.len"
                    || name == "str.++"
                    || name == "str.from_code"
                    || name == "str.table-select" => {}
            Term::Ctor { name, args } => {
                if name == "None" && args.is_empty() {
                    self.opaque_symbols.insert(NONE_SYMBOL.to_string());
                }
                for a in args {
                    self.collect_term_for_legacy_literals(a);
                }
            }
            Term::Lambda { body, .. } => self.collect_term_for_legacy_literals(body),
            Term::Let { bindings, body, .. } => {
                for b in bindings {
                    self.collect_term_for_legacy_literals(&b.bound_term);
                }
                self.collect_term_for_legacy_literals(body);
            }
            Term::Const { value, sort } => {
                if let Some(i) = const_concrete_int(value, sort) {
                    self.concrete_ints.insert(i);
                } else if let serde_json::Value::String(s) = value {
                    self.opaque_symbols.insert(string_lit_name(s));
                }
            }
            Term::Var { .. } => {}
        }
    }

    /// Emit the preamble lines that declare string-literal constants and the
    /// cross-type distinctness axiom.
    ///
    /// Lines produced (in order):
    ///   - `(declare-const strlit_<hash> Int)` for each distinct string lit.
    ///     (`None` is declared by the existing ctor-decl pass, not here, so we
    ///      do not redeclare it.)
    ///   - `(assert (distinct <opaque...> <concrete-ints...>))` ONLY when at
    ///     least one OPAQUE literal is present AND the total distinct-member
    ///     count is >= 2. Emitting `distinct` over a single member is a no-op
    ///     z3 rejects; emitting it with no opaque member would needlessly
    ///     decorate pure-arithmetic formulas and break byte-identity.
    pub fn preamble(&self) -> String {
        let mut out = String::new();

        // Declare string-literal constants (skip `None`, declared elsewhere).
        for sym in &self.opaque_symbols {
            if sym != NONE_SYMBOL {
                out.push_str(&format!("(declare-const {sym} Int)\n"));
            }
        }

        // Gate: distinctness axiom requires at least one opaque literal.
        if self.opaque_symbols.is_empty() {
            return out;
        }

        // Build the distinct-member list: all opaque symbols, then all
        // concrete int values (rendered as SMT numerals; negatives as `(- n)`).
        let mut members: Vec<String> = self.opaque_symbols.iter().cloned().collect();
        for &i in &self.concrete_ints {
            members.push(render_int(i));
        }

        // A `distinct` over fewer than two members is meaningless; skip it.
        if members.len() < 2 {
            return out;
        }

        out.push_str(&format!("(assert (distinct {}))\n", members.join(" ")));
        out
    }
}

// True iff this atom is emitted through the z3 STRING-THEORY path (real
// `String`-sorted operands, real `"..."` literals) instead of the legacy
// opaque-Int regime.
//
// Two cases:
//   1. A named string-theory predicate (`contains`, `str.chars-in-set`, ...).
//   2. STRING-ROUTED EQUALITY: `=` whose one side is a String-sorted string
//      const and whose other side is a non-`None` ctor (a `callresult_*`
//      subject) or another string const. This is the G1 conjoin shape: the
//      universe row `str.chars-in-set(call, set)` forces the subject term to
//      the SMT `String` sort, so the sworn equality over the SAME subject
//      must also live in string theory or the two rows are ill-sorted
//      against each other and z3 errors instead of refuting.
//
// DELIBERATE EXCLUSIONS (the legacy Python regime is preserved bit-for-bit):
//   - `=` over an untainted free VAR (`r == "a"`) stays opaque-Int: the
//     Python kit's cross-type consistency (`r == "a" ∧ r == 1` -> UNSAT via
//     distinctness) depends on every literal living in the Int universe.
//     A VAR already forced into string theory by a sibling string predicate
//     (`str.eq-bv-blocks(out, ...)`, charset, regex, ...) is routable, because
//     its sworn equality must meet the same `String`-sorted subject.
//   - `=` against the `None` ctor stays opaque-Int: `None != "x"` is enforced
//     by the distinctness axiom, which string theory cannot express over an
//     uninterpreted String const (it would freely model `None == "x"`).
//   - `=` between a string const and an int/bool const stays opaque-Int
//     (cross-type distinctness is Python-semantics-critical).
thread_local! {
    // Ctor subjects that appear in a string-theory PREDICATE atom (chars-in-set,
    // contains, prefix-of, ...) -- i.e. genuinely forced to the String sort.
    // Set per-compile. A ctor-subject `=` against a string const string-routes
    // ONLY when its subject is tainted; otherwise it stays in the sound
    // opaque-Int regime (so the same ctor used in BOTH a string `=` and an
    // Int-regime atom -- e.g. `member` -- does not ill-sort the function
    // declaration, the werkzeug subscript cross-sort). Restricting routing is
    // strictly more conservative: it never adds string theory where the legacy
    // Int regime sufficed, so it cannot introduce a falsePass.
    static STRING_TAINTED: std::cell::RefCell<Vec<Term>> = const { std::cell::RefCell::new(Vec::new()) };
}

pub(crate) fn set_string_tainted(subjects: Vec<Term>) {
    STRING_TAINTED.with(|t| *t.borrow_mut() = subjects);
}

fn ctor_subject_is_tainted(t: &Term) -> bool {
    STRING_TAINTED.with(|set| set.borrow().contains(t))
}

pub(crate) fn term_is_string_tainted(t: &Term) -> bool {
    STRING_TAINTED.with(|set| set.borrow().contains(t))
}

pub(crate) fn routes_to_string_theory(name: &str, args: &[Term]) -> bool {
    if is_string_theory_atomic_predicate(name) {
        return true;
    }
    if name != "=" || args.len() != 2 {
        return false;
    }
    let is_string_const = |t: &Term| {
        matches!(
            t,
            Term::Const {
                value: serde_json::Value::String(_),
                sort: Sort::Primitive { name },
            } if name == "String"
        )
    };
    // python:bytes(<String const>) is the Python kit's ASCII-gated bytes
    // literal: kind-distinct from a bare str at the EUF/term layer (the kit
    // refuses literal-vs-literal cross-kind comparisons), but its CONTENT
    // must live in string theory so a sworn bytes equality conjoins with a
    // charset universe over the same subject instead of ill-sorting.
    let is_bytes_wrapped_string_const = |t: &Term| {
        matches!(
            t,
            Term::Ctor { name, args } if name == "python:bytes"
                && args.len() == 1
                && is_string_const(&args[0])
        )
    };
    let is_string_like_const = |t: &Term| is_string_const(t) || is_bytes_wrapped_string_const(t);
    let is_routable_subject = |t: &Term| {
        // A string const is always a String. A CTOR or VAR subject string-routes
        // only when it is string-tainted (appears in a string-theory predicate);
        // otherwise it stays opaque-Int, consistent with its other uses.
        is_string_const(t)
            // String-building ctors are inherently String-sorted: str.++ always
            // returns String, str.from_code returns a one-char String.  Route them
            // through string theory unconditionally without requiring taint tracking.
            // Sound: these SMT operators always return String, never opaque-Int.
            || matches!(t, Term::Ctor { name, .. } if name == "str.++" || name == "str.from_code")
            || matches!(t, Term::Ctor { name, args }
                if !(name == "None" && args.is_empty()) && ctor_subject_is_tainted(t))
            || matches!(t, Term::Var { .. } if term_is_string_tainted(t))
    };
    (is_string_like_const(&args[0]) && is_routable_subject(&args[1]))
        || (is_string_like_const(&args[1]) && is_routable_subject(&args[0]))
}

/// Route atoms for the bitvector-32 theory arm.
///
/// G2: `int32.eq-bv-expr` carries a BV expression tree walked from the vendor's
/// source. The SMT emitter renders it as `(bvslt ...)` / `(bvneg ...)` / `(ite ...)`
/// over a `(_ BitVec 32)` sort. These atoms must NOT be collected for the
/// legacy opaque-Int regime, and must NOT be mixed with string-theory atoms
/// over the same EUF subject (mixed-sort STOP).
pub(crate) fn routes_to_bv32_theory(name: &str) -> bool {
    is_bv32_atomic_predicate(name)
}

fn is_bv32_atomic_predicate(name: &str) -> bool {
    // `int32.eq-const` is the synthetic atom produced by the bv32-contagion
    // pre-pass: a sibling sworn equality `=(call:abs, IntConst)` promoted to
    // the bv32 sort because its subject also appears in an `int32.eq-bv-expr`
    // universe atom. See `apply_bv32_contagion` in generated.rs.
    //
    // `int32.{lt,lte,gt,gte}-const` are the G2b comparison-bound synthetic atoms:
    // a sibling `<`/`<=`/`>`/`>=` atom promoted to bv32 by the same contagion pass.
    // They render as `bvs{lt,le,gt,ge}` over the bv32-promoted subject.
    matches!(
        name,
        "int32.eq-bv-expr"
            | "int32.in-range"
            | "int32.eq-const"
            | "int32.lt-const"
            | "int32.lte-const"
            | "int32.gt-const"
            | "int32.gte-const"
            // CRC value-pin (paper 26): a self-contained bv32 equality between the
            // test's asserted CRC value and the WALKED closed crc-FOL.
            | "crc32.eq-walked"
            // MT seeding value-pin (paper 26 — inter-procedural seed-state walk):
            // a self-contained bv32 equality between the test's asserted reference
            // value and the WALKED closed MT recurrence (the 624-word seeding chain
            // + twist), carried as an SSA `let`-chain payload so the deep recurrence
            // shares sub-terms (no exponential tree blowup).
            | "mt32.eq-seeded"
    )
}

/// A string-theory PREDICATE that forces its operands to the String sort
/// (every named string predicate except the routed `=`, which is what we are
/// deciding). Used to compute the string-tainted subject set.
pub(crate) fn forces_string_sort(name: &str) -> bool {
    name != "=" && is_string_theory_atomic_predicate(name)
}

fn is_string_theory_atomic_predicate(name: &str) -> bool {
    matches!(
        name,
        "contains"
            | "prefix-of"
            | "suffix-of"
            | "str.is_ascii"
            | "str.is_ascii_alphabetic"
            | "str.is_ascii_alphanumeric"
            | "str.is_ascii_digit"
            | "str.is_ascii_octdigit"
            | "str.is_ascii_lowercase"
            | "str.is_ascii_uppercase"
            | "str.is_ascii_hexdigit"
            | "str.is_ascii_punctuation"
            | "str.is_ascii_graphic"
            | "str.is_ascii_whitespace"
            | "str.is_ascii_control"
            | "str.chars-in-set"
            | "str.chars-not-in-set"
            | "str.eq-bv-blocks"
            | "str.in-regex"
    )
}

/// Render an i128 as an SMT-LIB v2.6 numeral. Non-negative -> bare digits;
/// negative -> `(- n)` (SMT-LIB has no negative numeral literal token). The
/// i128 carrier holds wide Int consts (u64::MAX .. i128 range) exactly.
fn render_int(i: i128) -> String {
    if i < 0 {
        format!("(- {})", i.unsigned_abs())
    } else {
        i.to_string()
    }
}

/// Read a const term's EXACT concrete integer value, if it has one.
///
/// Returns `Some(i128)` for: a JSON Number within i64/u64 range; a bool
/// (True->1, False->0, since bool IS int); and a wide `Int`-sorted const
/// carried as a decimal STRING (value > u64::MAX, within i128 -- see
/// `sugar_ir_symbolic::convert::int_to_json`). Returns `None` for a genuine
/// opaque string literal (a String-sorted const), `None`, and non-integer
/// numerics (floats). The distinctness-target set is value-driven, so a wide
/// Int MUST be recovered here or a refutation against an opaque symbol could
/// be masked (a falsePass).
fn const_concrete_int(value: &serde_json::Value, sort: &sugar_ir_types::Sort) -> Option<i128> {
    let sort_is_int = matches!(sort, sugar_ir_types::Sort::Primitive { name } if name == "Int");
    match value {
        serde_json::Value::Bool(b) => Some(if *b { 1 } else { 0 }),
        serde_json::Value::Number(_) => value
            .as_i64()
            .map(i128::from)
            .or_else(|| value.as_u64().map(i128::from)),
        // A wide Int is a decimal string under an Int sort; a String-sorted
        // const of the same shape is an opaque literal, NOT an integer.
        serde_json::Value::String(s) if sort_is_int => s.parse::<i128>().ok(),
        _ => None,
    }
}

/// Emit a single literal constant's term-position SMT rendering.
///
/// CONCRETE-VALUED: int -> its numeral; bool -> `1`/`0` (bool IS int in
/// Python, so a bool literal compared against an Int free var must be its
/// integer value, not the SMT `Bool` literal `true`/`false` which would be
/// ill-sorted against Int and break `r == True ∧ r == 1` consistency).
/// OPAQUE: string -> `strlit_<hash>` (declared + made distinct in `preamble`).
/// Other JSON shapes fall back to `0` (unchanged legacy behavior).
pub fn emit_const_value(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.to_string()
            } else if let Some(u) = n.as_u64() {
                u.to_string()
            } else {
                n.to_string()
            }
        }
        // bool IS int: True -> 1, False -> 0 (Python `True == 1`, `False == 0`).
        serde_json::Value::Bool(b) => {
            if *b {
                "1".to_string()
            } else {
                "0".to_string()
            }
        }
        serde_json::Value::String(s) => string_lit_name(s),
        _ => "0".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn str_c(s: &str) -> Term {
        serde_json::from_value(
            json!({"kind":"const","value":s,"sort":{"kind":"primitive","name":"String"}}),
        )
        .unwrap()
    }
    fn int_c(n: i64) -> Term {
        serde_json::from_value(
            json!({"kind":"const","value":n,"sort":{"kind":"primitive","name":"Int"}}),
        )
        .unwrap()
    }
    fn bool_c(b: bool) -> Term {
        serde_json::from_value(
            json!({"kind":"const","value":b,"sort":{"kind":"primitive","name":"Bool"}}),
        )
        .unwrap()
    }
    fn none_c() -> Term {
        serde_json::from_value(json!({"kind":"ctor","name":"None","args":[]})).unwrap()
    }
    fn atomic_eq(a: Term, b: Term) -> Formula {
        Formula::Atomic {
            name: "=".to_string(),
            args: vec![a, b],
        }
    }
    fn and(a: Formula, b: Formula) -> Formula {
        Formula::And {
            operands: vec![a, b],
        }
    }
    fn var(n: &str) -> Term {
        serde_json::from_value(json!({"kind":"var","name":n})).unwrap()
    }

    #[test]
    fn bool_emits_concrete_int_not_smt_bool() {
        assert_eq!(emit_const_value(&json!(true)), "1");
        assert_eq!(emit_const_value(&json!(false)), "0");
    }

    #[test]
    fn string_lit_name_is_parse_safe_and_stable() {
        let a = string_lit_name(r#"{"a":1}"#);
        let b = string_lit_name(r#"{"a":1}"#);
        assert_eq!(a, b, "same literal -> same name");
        assert!(a.starts_with("strlit_"));
        assert!(a[7..].chars().all(|c| c.is_ascii_alphanumeric()));
        assert_ne!(string_lit_name("a"), string_lit_name("b"));
    }

    #[test]
    fn no_distinct_when_no_opaque_literal() {
        // Pure arithmetic: two int literals, no string/None -> no distinct line.
        let f = and(atomic_eq(var("r"), int_c(5)), atomic_eq(var("r"), int_c(6)));
        let lc = LiteralConstants::from_formula(&f);
        assert_eq!(
            lc.preamble(),
            "",
            "no opaque literal -> byte-identical (empty)"
        );
    }

    #[test]
    fn lone_none_emits_no_distinct() {
        // Single `≠(x, None)` style: one opaque, no other member -> no axiom.
        let f = atomic_eq(var("x"), none_c());
        let lc = LiteralConstants::from_formula(&f);
        assert_eq!(
            lc.preamble(),
            "",
            "lone None -> no distinctness axiom (byte-identical)"
        );
    }

    #[test]
    fn lone_string_declares_const_but_no_distinct() {
        let f = atomic_eq(var("r"), str_c("a"));
        let lc = LiteralConstants::from_formula(&f);
        let p = lc.preamble();
        assert!(
            p.contains("(declare-const strlit_"),
            "declares the strlit const: {p}"
        );
        assert!(
            !p.contains("(assert (distinct"),
            "no distinct for a lone string: {p}"
        );
    }

    #[test]
    fn str_and_int_get_distinctness() {
        let f = and(
            atomic_eq(var("r"), str_c("5")),
            atomic_eq(var("r"), int_c(5)),
        );
        let p = LiteralConstants::from_formula(&f).preamble();
        assert!(
            p.contains("(assert (distinct strlit_"),
            "str vs int -> distinct: {p}"
        );
        assert!(p.contains(" 5)"), "distinct includes the int value 5: {p}");
    }

    #[test]
    fn none_and_bool_false_get_distinctness_over_zero() {
        // None vs False(=0): the opaque None must be distinct from concrete 0.
        let f = and(
            atomic_eq(var("r"), none_c()),
            atomic_eq(var("r"), bool_c(false)),
        );
        let p = LiteralConstants::from_formula(&f).preamble();
        assert!(
            p.contains("(assert (distinct None 0))"),
            "None distinct from 0: {p}"
        );
    }

    #[test]
    fn bool_true_int_one_no_distinct_member_collision() {
        // True(=1) and int 1: both concrete, no opaque -> no distinct, and the
        // concrete set coalesces 1 (so they remain EQUAL -> consistent).
        let f = and(
            atomic_eq(var("r"), bool_c(true)),
            atomic_eq(var("r"), int_c(1)),
        );
        let lc = LiteralConstants::from_formula(&f);
        assert_eq!(
            lc.preamble(),
            "",
            "bool+int both concrete, no opaque -> no axiom"
        );
    }

    #[test]
    fn negative_int_rendered_as_smt_neg() {
        let f = and(
            atomic_eq(var("r"), str_c("x")),
            atomic_eq(var("r"), int_c(-3)),
        );
        let p = LiteralConstants::from_formula(&f).preamble();
        assert!(p.contains("(- 3)"), "negative int rendered as (- 3): {p}");
    }

    #[test]
    fn float_literal_excluded_from_distinctness_set() {
        // RESIDUAL: a non-integer float must NOT enter the distinct RHS
        // (would be ill-sorted `(distinct strlit 5.0)` and falsely assert
        // `5.0 != 5`). With a string present and only a 5.0 float, the
        // distinctness set has one member (the strlit) -> no axiom emitted.
        let float_c: Term = serde_json::from_value(
            json!({"kind":"const","value":5.0,"sort":{"kind":"primitive","name":"Real"}}),
        )
        .unwrap();
        let f = and(
            atomic_eq(var("r"), str_c("x")),
            atomic_eq(var("r"), float_c),
        );
        let p = LiteralConstants::from_formula(&f).preamble();
        assert!(
            p.contains("(declare-const strlit_"),
            "string const still declared: {p}"
        );
        assert!(
            !p.contains("(assert (distinct"),
            "float must not pull a distinctness axiom (residual): {p}"
        );
        assert!(
            !p.contains("5.0"),
            "float value must not appear in preamble: {p}"
        );
    }

    #[test]
    fn bool_value_with_mislabeled_int_sort_still_collected_as_concrete() {
        // DESYNC GUARD: `emit_const_value` is VALUE-based (a bool value renders
        // as 1/0 regardless of sort). The collector must match: a
        // `{value:true, sort:Int}` const (the byte-for-byte fixture #9 shape,
        // and a possible cross-language emission) must enter concrete_ints as 1,
        // or the body emits `1` while the distinctness axiom omits it -> sat ->
        // falsePass. Pair it with a string so a distinct axiom is emitted.
        let bool_int: Term = serde_json::from_value(
            json!({"kind":"const","value":true,"sort":{"kind":"primitive","name":"Int"}}),
        )
        .unwrap();
        let f = and(
            atomic_eq(var("r"), str_c("x")),
            atomic_eq(var("r"), bool_int),
        );
        let p = LiteralConstants::from_formula(&f).preamble();
        assert!(
            p.contains("(assert (distinct strlit_") && p.trim_end().ends_with(" 1))"),
            "mislabeled bool(true)/Int must be collected as concrete 1 in the \
             distinctness set (value-based, not sort-based): {p}"
        );
    }

    #[test]
    fn integer_valued_float_5_0_not_treated_as_int_5() {
        // `5.0` serializes as an f64 JSON number; as_i64() is None, so it is
        // NOT added to the concrete-int set. Pair it with None: no `distinct`
        // over `0`/`5` is produced from the float -> None stays unconstrained
        // vs the float (residual), but None vs a *real* int still works.
        let float_c: Term = serde_json::from_value(
            json!({"kind":"const","value":5.0,"sort":{"kind":"primitive","name":"Real"}}),
        )
        .unwrap();
        let f = and(atomic_eq(var("r"), none_c()), atomic_eq(var("r"), float_c));
        let p = LiteralConstants::from_formula(&f).preamble();
        assert!(
            !p.contains("(assert (distinct"),
            "None vs float-5.0 must not assert distinctness (residual): {p}"
        );
    }
}
