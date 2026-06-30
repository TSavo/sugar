// SPDX-License-Identifier: Apache-2.0
//
// `TermLiteralSugar`: the TERM-FLOOR LEAF for a scalar literal in term position --
// the constructive node mirror of the `Expr::Lit` arm of term dispatch:
//
//     Expr::Lit(lit) => term_literal::translate_lit(lit),
//
// `translate_lit` maps each `syn::Lit` to its keyed `Term`:
//   * `Lit::Int`  -> `num(value)` (no suffix) or a `Term::Const { value:
//                    ConstValue::Int, sort: <suffix> }` (width-keyed in the sort);
//   * `Lit::Float` -> `canonical_float_literal(f).map(real_const)`;
//   * `Lit::Str`  -> `str_const(s.value())`;
//   * `Lit::Char` -> `str_const(c.value().to_string())`;
//   * `Lit::Bool` -> `bool_const(b.value)`;
//   * `Lit::ByteStr` -> `bytes_literal_term_from_bytes(&bs.value())` (a content-
//                       keyed `Var`);
//   * `Lit::Byte` -> a `u8`-sorted `Term::Const { ConstValue::Int }` (byte value);
//   * any other -> `Err("only ... scalar constants are liftable, got ...")`.
//
// This is a LEAF: NO child `Sugar`. It produces the `Term` DIRECTLY from the
// stored `ScalarLit` (decoded from the `SourceFragment` at recognition time) --
// a literal is atomic, there is nothing to recurse into and `ctx` is unused.
//
// MIGRATION STATUS (Phase-3 ratchet -- FULLY MIGRATED).
//   * `recognize` uses ONLY `SourceFragment::scalar_lit()` -- no `as_expr()`
//     shim, no raw `Expr::` match.
//   * `TermLiteralSugar` holds `lit: ScalarLit` (host-native types only, NO
//     raw `syn` fields).
//   * `desugar` calls `scalar_lit_to_term(&self.lit)`, which is byte-identical
//     to `translate_lit` for every scalar variant.
//   * `translate_lit` is RETAINED for callers in `match_node.rs` (it takes a
//     `&ExprLit` and mirrors the shared arm); it is NOT called by `desugar` now.
//
// SIBLING TO `LiteralSugar`, NOT A COLLISION. A `LiteralSugar` ALREADY EXISTS
// in `src/sugar/literal.rs`; it is the SEQUENCE-floor node. `TermLiteralSugar`
// is the TERM-floor node. Same word ("literal"), DIFFERENT floor: `Seq` vs
// `Term`. They are SIBLINGS -- a sequence domain is not a scalar value and vice
// versa -- so this is a new file + a new type, never an edit to `literal.rs`.
//
// RECOGNIZER PREAMBLE. This Sugar's claim owns the scalar `Expr::Lit` TERM
// shape and news a `TermLiteralSugar` holding the decoded `ScalarLit`.
// `Expr::Array | Expr::Range` are separate sequence-floor claims (`LiteralSugar`);
// `CStr` literals return `None` from `scalar_lit()` and are not claimed here.

use std::rc::Rc;

use sugar_ir_symbolic::{num, real_const, str_const, ConstValue, Term};
use syn::{ExprLit, Lit};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::source_fragment::{ScalarLit, SourceFragment};
use crate::{
    bool_const, bytes_literal_term_from_bytes, canonical_float_literal, parse_int_lit,
    parse_u128_lit, token_key, u128_term, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("term_literal", recognize);

/// TERM recognizer for `Expr::Lit`: a scalar literal news a [`TermLiteralSugar`].
/// Uses ONLY `SourceFragment::scalar_lit()` -- no `as_expr()`, no raw `Expr::` access.
/// `CStr` is excluded by `scalar_lit()` returning `None` for it.
pub(crate) fn recognize(frag: &SourceFragment, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let lit = frag.scalar_lit()?;
    Some(Box::new(TermLiteralSugar { lit }))
}

/// The `syn`-level translator kept for external callers (`match_node.rs`).
/// Mirrors `Expr::Lit(lit) => translate_lit(lit)` byte-identically.
/// NOT called by `desugar` after the Phase-3 migration; `scalar_lit_to_term`
/// serves that role using the stored `ScalarLit`.
pub(crate) fn translate_lit(lit: &ExprLit) -> Result<Rc<Term>, String> {
    match &lit.lit {
        Lit::Int(i) => {
            // A CONCRETE Int const whose WIDTH (u8 ... i128 / usize / isize) is
            // carried in the const's SORT, never by opaquing the term. The proofir
            // compiler maps any non-{Int,Bool,Real,String} primitive sort -> Int
            // for SMT (emit_sort_with_reason), so the value stays concrete and
            // `2u8 + 3u8 == 6` is still REFUTED -- no arithmetic-masking falsePass.
            // The width rides in the canonical callsite KEY (canonical_term_sig
            // renders `i:{v}:{width}`), so `align_of_val(&1u8)=1` and `&1u64=8` get
            // DISTINCT obligations instead of collapsing onto `ref(i:1)`.
            let suffix = i.suffix();
            if suffix == "u128" {
                return Ok(u128_term(parse_u128_lit(i)?));
            }
            if suffix.is_empty() {
                match parse_int_lit(i) {
                    Ok(value) => Ok(num(value)),
                    Err(_) => Ok(u128_term(parse_u128_lit(i)?)),
                }
            } else {
                let value = parse_int_lit(i)?;
                Ok(Rc::new(Term::Const {
                    value: ConstValue::Int(value),
                    sort: sugar_ir_symbolic::Sort {
                        name: suffix.to_string(),
                    },
                }))
            }
        }
        Lit::Float(f) => canonical_float_literal(f).map(real_const),
        Lit::Str(s) => Ok(str_const(s.value())),
        Lit::Char(c) => Ok(str_const(c.value().to_string())),
        Lit::Bool(b) => Ok(bool_const(b.value)),
        Lit::ByteStr(bs) => Ok(bytes_literal_term_from_bytes(&bs.value())),
        // A byte literal `b'0'` is pure sugar for a `u8` constant (here 48): it
        // carries a fixed numeric value and rust types it `u8`. Dissolve it to the
        // same concrete-Int-with-u8-sort form a `48u8` literal lifts to, so a direct
        // byte operand (`assert_eq!(byte, b'0')`) is liftable and `b'0' != 49` is
        // REFUTED via the existing int path -- no new refutation logic, no masking.
        Lit::Byte(b) => Ok(Rc::new(Term::Const {
            value: ConstValue::Int(i128::from(b.value())),
            sort: sugar_ir_symbolic::Sort {
                name: "u8".to_string(),
            },
        })),
        other => Err(format!(
            "only integer/string/char/finite decimal float scalar constants are liftable, got `{}`",
            token_key(other)
        )),
    }
}

/// A scalar literal in TERM position (`42u8`, `3.14`, `"s"`, `'c'`, `true`,
/// `b"bytes"`, `b'0'`). LEAF: produces a single `Desugared::Term` directly from the
/// stored `ScalarLit` via `scalar_lit_to_term`, with NO child `Sugar` and no `ctx`
/// dependency. Sibling to the sequence-floor `LiteralSugar`; see the module header.
///
/// DEEP MIGRATION (Phase-3 ratchet). Holds `lit: ScalarLit` -- host-native types
/// only (String / char / bool / Vec<u8> / u8). No raw `syn` fields.
pub(crate) struct TermLiteralSugar {
    /// The decoded scalar literal. `desugar` lifts it through `scalar_lit_to_term`,
    /// which is byte-identical to `translate_lit` for every supported variant.
    pub(crate) lit: ScalarLit,
}

impl Sugar for TermLiteralSugar {
    /// LEAF term reduction: `scalar_lit_to_term(&self.lit)`. `Ok(term)` completes
    /// to `Desugared::Term(term)` (the width-keyed `Const` / `str_const` /
    /// `bool_const` / content-keyed bytes `Var` the arm produces); an `Err(reason)`
    /// is a scalar-leaf construction gap. `ctx` is unused: a literal's value is
    /// fixed by its tokens.
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        match scalar_lit_to_term(&self.lit) {
            Ok(term) => Outcome::Complete(Desugared::Term(term)),
            Err(reason) => term_literal_gap(&reason),
        }
    }
}

// ---------------------------------------------------------------------------
// `scalar_lit_to_term` -- the fragment-derived twin of `translate_lit`
// ---------------------------------------------------------------------------

/// Lift a `ScalarLit` to a `Term`, byte-identical to what `translate_lit` would
/// produce for the same source literal. All syn is gone; only native types remain.
fn scalar_lit_to_term(lit: &ScalarLit) -> Result<Rc<Term>, String> {
    match lit {
        ScalarLit::Int { token_text, suffix } => {
            // Mirrors the `Lit::Int(i)` arm of `translate_lit` exactly:
            //   suffix == "u128"  -> u128_term(parse_u128_lit)
            //   suffix empty      -> num(parse_int_lit) with u128 fallback
            //   any other suffix  -> Const { Int(parse_int_lit), sort: suffix }
            if suffix == "u128" {
                return Ok(u128_term(decode_u128(token_text, suffix)?));
            }
            if suffix.is_empty() {
                match decode_i128(token_text, suffix) {
                    Ok(value) => Ok(num(value)),
                    Err(_) => Ok(u128_term(decode_u128(token_text, suffix)?)),
                }
            } else {
                let value = decode_i128(token_text, suffix)?;
                Ok(Rc::new(Term::Const {
                    value: ConstValue::Int(value),
                    sort: sugar_ir_symbolic::Sort {
                        name: suffix.clone(),
                    },
                }))
            }
        }
        ScalarLit::Float { base10_digits } => {
            // Mirrors `Lit::Float(f) => canonical_float_literal(f).map(real_const)`.
            canonical_float_from_digits(base10_digits).map(real_const)
        }
        ScalarLit::Str(s) => Ok(str_const(s.clone())),
        ScalarLit::Char(c) => Ok(str_const(c.to_string())),
        ScalarLit::Bool(b) => Ok(bool_const(*b)),
        ScalarLit::ByteStr(bytes) => Ok(bytes_literal_term_from_bytes(bytes)),
        ScalarLit::Byte(b) => Ok(Rc::new(Term::Const {
            value: ConstValue::Int(i128::from(*b)),
            sort: sugar_ir_symbolic::Sort {
                name: "u8".to_string(),
            },
        })),
        // Verbatim or any other non-exhaustive syn::Lit variant captured at
        // recognition time. Mirrors `other => Err(format!(...))` in translate_lit.
        ScalarLit::Other(token) => Err(format!(
            "only integer/string/char/finite decimal float scalar constants are liftable, got `{token}`",
        )),
    }
}

// ---------------------------------------------------------------------------
// Integer helpers -- mirrors of `int_lit_radix_digits` / `parse_int_lit` /
// `parse_u128_lit` from the crate root, operating on the stored token_text and
// suffix strings instead of `&syn::LitInt`.
// ---------------------------------------------------------------------------

/// Extract (radix, digits_string) from an integer token text and suffix.
/// Mirrors `int_lit_radix_digits(lit)` exactly, substituting `i.to_string()`
/// -> `token_text` and `i.suffix()` -> `suffix`.
fn int_radix_digits(token_text: &str, suffix: &str) -> (u32, String) {
    let mut text = token_text.to_string();
    if !suffix.is_empty() && text.ends_with(suffix) {
        text.truncate(text.len() - suffix.len());
    }
    let text = text.replace('_', "");
    if let Some(rest) = text.strip_prefix("0x").or_else(|| text.strip_prefix("0X")) {
        (16, rest.to_string())
    } else if let Some(rest) = text.strip_prefix("0o").or_else(|| text.strip_prefix("0O")) {
        (8, rest.to_string())
    } else if let Some(rest) = text.strip_prefix("0b").or_else(|| text.strip_prefix("0B")) {
        (2, rest.to_string())
    } else {
        (10, text)
    }
}

/// Parse `token_text`/`suffix` as `i128`. Mirrors `parse_int_lit`.
fn decode_i128(token_text: &str, suffix: &str) -> Result<i128, String> {
    let (radix, digits) = int_radix_digits(token_text, suffix);
    i128::from_str_radix(&digits, radix)
        .map_err(|e| format!("int literal `{token_text}`: {e}"))
}

/// Parse `token_text`/`suffix` as `u128`. Mirrors `parse_u128_lit`.
fn decode_u128(token_text: &str, suffix: &str) -> Result<u128, String> {
    let (radix, digits) = int_radix_digits(token_text, suffix);
    u128::from_str_radix(&digits, radix)
        .map_err(|e| format!("int literal `{token_text}`: {e}"))
}

// ---------------------------------------------------------------------------
// Float helper -- mirrors `canonical_float_literal` from the crate root,
// operating on `ScalarLit::Float { base10_digits }` (already `base10_digits()`
// from `syn::LitFloat`) instead of `&syn::LitFloat`.
// ---------------------------------------------------------------------------

/// Canonicalise a float literal from its `base10_digits` string.
/// Mirrors `canonical_float_literal(lit)` where `lit.base10_digits()` equals
/// `base10_digits`. Calls `crate::normalize_decimal_exponent_literal` for the
/// exponent-containing case, exactly as `canonical_float_literal` does.
fn canonical_float_from_digits(base10_digits: &str) -> Result<String, String> {
    let digits = base10_digits.replace('_', "");
    if digits.is_empty() {
        return Err("empty float literal".to_string());
    }
    if digits.contains('e') || digits.contains('E') {
        return crate::normalize_decimal_exponent_literal(&digits).map_err(|e| {
            format!(
                "float literal with exponent is not exact decimal syntax `{}`: {e}",
                base10_digits
            )
        });
    }
    Ok(digits)
}

fn term_literal_gap(reason: &str) -> ! {
    panic!("term_literal did not reach a lawful scalar floor: {reason}")
}

#[cfg(test)]
mod tests {
    // Phase-3 TDD harness: source string -> SourceFragment -> scalar_lit() ->
    // scalar_lit_to_term() -> assert Term shape.  No parse_quote!, no StubTerm,
    // no run().  The from_src tests validate the full recognizer/floor path via
    // the typed accessor door only.
    //
    // `translate_lit` tests are retained because `translate_lit` is still the
    // external API consumed by `match_node.rs`; they verify the shared-helper
    // seam remains byte-identical to the Sugar's output.
    use super::*;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use sugar_ir_symbolic::{ConstValue, Term};
    use syn::parse_quote;

    // -----------------------------------------------------------------------
    // from_src: source string -> SourceFragment -> observed -> build -> floor
    // -----------------------------------------------------------------------

    /// Navigate to the first expression in the tail position of a one-liner fn.
    fn tail_term_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("body");
        let stmts = body.statements();
        // Tail expr statement -> its single term child
        let terms = stmts[0].terms();
        terms[0]
    }

    /// A suffixed integer (`42u8`) is classified as `PrimitiveLiteral`, decodes
    /// to `ScalarLit::Int { suffix: "u8" }`, and lifts to a width-keyed u8 const.
    #[test]
    fn from_src_suffixed_u8_to_width_keyed_int_const() {
        let src = "fn f() -> u8 { 42u8 }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        // observed
        assert_eq!(frag.observed(), "PrimitiveLiteral");

        // build: scalar_lit() extracts without any as_expr / raw Expr:: access
        let lit = frag.scalar_lit().expect("42u8 yields ScalarLit");
        match &lit {
            ScalarLit::Int { token_text, suffix } => {
                assert_eq!(token_text.as_str(), "42u8");
                assert_eq!(suffix.as_str(), "u8");
            }
            other => panic!("expected ScalarLit::Int, got {other:?}"),
        }

        // floor: identical term to translate_lit
        let term = scalar_lit_to_term(&lit).expect("42u8 lifts");
        match &*term {
            Term::Const { value: ConstValue::Int(v), sort } => {
                assert_eq!(*v, 42);
                assert_eq!(sort.name, "u8");
            }
            other => panic!("expected u8 Int const, got {other:?}"),
        }
    }

    /// An unsuffixed integer (`7`) decodes to `ScalarLit::Int { suffix: "" }` and
    /// lifts to a plain `num` (untyped `Const { Int, sort: int }`).
    #[test]
    fn from_src_unsuffixed_int_to_plain_num() {
        let src = "fn f() -> i32 { 7 }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "PrimitiveLiteral");

        let lit = frag.scalar_lit().expect("7 yields ScalarLit");
        let term = scalar_lit_to_term(&lit).expect("7 lifts");
        match &*term {
            Term::Const {
                value: ConstValue::Int(v),
                ..
            } => assert_eq!(*v, 7),
            other => panic!("expected Int const, got {other:?}"),
        }
    }

    /// A string literal (`"hi"`) decodes to `ScalarLit::Str` and lifts to a
    /// `str_const`.
    #[test]
    fn from_src_str_to_string_const() {
        let src = r#"fn f() -> &'static str { "hi" }"#;
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "PrimitiveLiteral");

        let lit = frag.scalar_lit().expect("\"hi\" yields ScalarLit");
        let term = scalar_lit_to_term(&lit).expect("\"hi\" lifts");
        match &*term {
            Term::Const {
                value: ConstValue::String(s),
                ..
            } => assert_eq!(s, "hi"),
            other => panic!("expected String const, got {other:?}"),
        }
    }

    /// A bool literal (`true`) decodes to `ScalarLit::Bool(true)` and lifts to
    /// a `bool_const`.
    #[test]
    fn from_src_bool_to_bool_const() {
        let src = "fn f() -> bool { true }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "PrimitiveLiteral");

        let lit = frag.scalar_lit().expect("true yields ScalarLit");
        let term = scalar_lit_to_term(&lit).expect("true lifts");
        match &*term {
            Term::Const {
                value: ConstValue::Bool(b),
                ..
            } => assert!(*b),
            other => panic!("expected Bool const, got {other:?}"),
        }
    }

    // -----------------------------------------------------------------------
    // translate_lit tests (retained: external API used by match_node.rs)
    // -----------------------------------------------------------------------

    /// An UNSUFFIXED int lifts to a plain `num` (`Const { Int, sort: int }`) --
    /// the exact term `desugar` completes (`translate_lit` -> `num(value)`).
    #[test]
    fn unsuffixed_int_is_plain_int_const() {
        let lit: ExprLit = parse_quote!(7);
        let term = translate_lit(&lit).expect("an int literal lifts");
        match &*term {
            Term::Const {
                value: ConstValue::Int(v),
                ..
            } => assert_eq!(*v, 7),
            other => panic!("expected an Int const, got {other:?}"),
        }
    }

    /// A SUFFIXED int carries its width in the `sort` name (`42u8` -> sort "u8") --
    /// the width-keyed `Const` `desugar` completes.
    #[test]
    fn suffixed_int_carries_width_in_sort() {
        let lit: ExprLit = parse_quote!(42u8);
        let term = translate_lit(&lit).expect("a suffixed int lifts");
        match &*term {
            Term::Const {
                value: ConstValue::Int(v),
                sort,
            } => {
                assert_eq!(*v, 42);
                assert_eq!(sort.name, "u8");
            }
            other => panic!("expected a width-keyed Int const, got {other:?}"),
        }
    }

    /// A string literal lifts to a `str_const` (`Const { String }`).
    #[test]
    fn str_is_string_const() {
        let lit: ExprLit = parse_quote!("hi");
        let term = translate_lit(&lit).expect("a str literal lifts");
        match &*term {
            Term::Const {
                value: ConstValue::String(s),
                ..
            } => assert_eq!(s, "hi"),
            other => panic!("expected a String const, got {other:?}"),
        }
    }

    /// A bool literal lifts to a `bool_const` (`Const { Bool }`).
    #[test]
    fn bool_is_bool_const() {
        let lit: ExprLit = parse_quote!(true);
        let term = translate_lit(&lit).expect("a bool literal lifts");
        match &*term {
            Term::Const {
                value: ConstValue::Bool(b),
                ..
            } => assert!(*b),
            other => panic!("expected a Bool const, got {other:?}"),
        }
    }

    /// A byte literal `b'0'` lifts to the same `u8`-sorted Int const as `48u8`.
    #[test]
    fn byte_lit_is_u8_int_const() {
        let lit: ExprLit = parse_quote!(b'0');
        let term = translate_lit(&lit).expect("a byte literal lifts");
        match &*term {
            Term::Const {
                value: ConstValue::Int(v),
                sort,
            } => {
                assert_eq!(*v, 48);
                assert_eq!(sort.name, "u8");
            }
            other => panic!("expected a u8 Int const, got {other:?}"),
        }
    }

    // -----------------------------------------------------------------------
    // Parity: scalar_lit_to_term agrees with translate_lit for every scalar kind
    // -----------------------------------------------------------------------

    /// `scalar_lit_to_term` agrees with `translate_lit` for a suffixed int.
    #[test]
    fn scalar_lit_to_term_agrees_with_translate_lit_int() {
        let src = "fn f() -> u8 { 42u8 }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");
        let scalar = frag.scalar_lit().unwrap();
        let via_scalar = scalar_lit_to_term(&scalar).expect("lifts via ScalarLit");

        let lit: ExprLit = parse_quote!(42u8);
        let via_translate = translate_lit(&lit).expect("lifts via translate_lit");

        // Same Term shape and values (compare via debug repr as simplest stable check)
        assert_eq!(format!("{via_scalar:?}"), format!("{via_translate:?}"));
    }

    /// `scalar_lit_to_term` agrees with `translate_lit` for a string literal.
    #[test]
    fn scalar_lit_to_term_agrees_with_translate_lit_str() {
        let src = r#"fn f() -> &'static str { "hello" }"#;
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");
        let scalar = frag.scalar_lit().unwrap();
        let via_scalar = scalar_lit_to_term(&scalar).expect("lifts via ScalarLit");

        let lit: ExprLit = parse_quote!("hello");
        let via_translate = translate_lit(&lit).expect("lifts via translate_lit");

        assert_eq!(format!("{via_scalar:?}"), format!("{via_translate:?}"));
    }

    /// `scalar_lit_to_term` agrees with `translate_lit` for a bool literal.
    #[test]
    fn scalar_lit_to_term_agrees_with_translate_lit_bool() {
        let src = "fn f() -> bool { true }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");
        let scalar = frag.scalar_lit().unwrap();
        let via_scalar = scalar_lit_to_term(&scalar).expect("lifts via ScalarLit");

        let lit: ExprLit = parse_quote!(true);
        let via_translate = translate_lit(&lit).expect("lifts via translate_lit");

        assert_eq!(format!("{via_scalar:?}"), format!("{via_translate:?}"));
    }
}
