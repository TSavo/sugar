// SPDX-License-Identifier: Apache-2.0
//
// `TermLiteralSugar`: the TERM-FLOOR LEAF for a scalar literal in term position --
// the constructive node mirror of the `Expr::Lit` arm of `translate_term_in_scope`:
//
//     Expr::Lit(lit) => translate_lit(lit),
//
// `translate_lit` (in `lib.rs`) maps each `syn::Lit` to its keyed `Term`:
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
// This is a LEAF: NO child `Sugar`. It produces the `Term` DIRECTLY from the held
// `ExprLit` -- a literal is atomic, there is nothing to recurse into and `ctx` is
// unused (a literal's value is fixed by its tokens, not by scope). To mirror the
// arm BYTE-IDENTICALLY and avoid ANY drift, the node CALLS the shared `translate_lit`
// helper (imported from `crate::`) rather than re-transcribing its width-keyed body:
// the arm IS `translate_lit(lit)`, so the node is too. `Ok(term)` completes to
// `Desugared::Term(term)`; an `Err(reason)` -- a non-scalar literal (e.g. a
// `Lit::Verbatim`) -- returns Incomplete `Effect::Unsupported { reason }`, carrying the verbatim
// reason the arm's `Err` propagated, so the wire format (CID + counts) is conserved.
//
// SIBLING TO `LiteralSugar`, NOT A COLLISION (the naming + purpose split). A
// `LiteralSugar` ALREADY EXISTS in `src/sugar/literal.rs`; it is the SEQUENCE-floor
// node -- it desugars a finite literal DOMAIN (a literal array `[e0, e1, ...]` or a
// closed integer range `a..b`) to a `Desugared::Seq` of elements, for the sequence
// adaptors (`MapSugar`/`FilterSugar`/...) to consume. `TermLiteralSugar` is the
// TERM-floor node -- it desugars a SCALAR literal to a single `Desugared::Term`, for
// the term composites (`UnarySugar`/`CompareSugar`/...) to consume. Same word
// ("literal"), DIFFERENT floor: `Seq` vs `Term`. They are SIBLINGS, not extensions of
// one another -- a sequence domain is not a scalar value and vice versa -- so this
// is a new file + a new type, never an edit to `literal.rs` (which would conflate the
// two floors). The shared `Lit`-decoding lives in `translate_lit`, called by this
// node; `LiteralSugar` never touches a scalar `Lit`, so there is no overlap to unify.
//
// RECOGNIZER PREAMBLE. This Sugar's claim owns the scalar `Expr::Lit` TERM shape and
// news a `TermLiteralSugar` holding the `ExprLit`. `Expr::Array | Expr::Range` are
// separate sequence-floor claims (`LiteralSugar`); scalar literals stay here via
// `translate_lit`.

use syn::{Expr, ExprLit, Lit};

use crate::sugar::factory::SugarBuildCtx;
use crate::{translate_lit, Desugared, Effect, Outcome, Sugar, SugarCtx};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("term_literal", recognize);

/// TERM recognizer for `Expr::Lit`: a scalar literal news a [`TermLiteralSugar`].
/// Byte-identical to the `Expr::Lit(lit) => translate_lit(lit)` arm.
pub(crate) fn recognize(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Lit(lit) if !matches!(lit.lit, Lit::CStr(_)) => {
            Some(Box::new(TermLiteralSugar { lit: lit.clone() }))
        }
        _ => None,
    }
}

/// A scalar literal in TERM position (`42u8`, `3.14`, `"s"`, `'c'`, `true`,
/// `b"bytes"`, `b'0'`). LEAF: produces a single `Desugared::Term` directly from the
/// held `ExprLit` via the shared `translate_lit`, with NO child `Sugar` and no `ctx`
/// dependency. Sibling to the sequence-floor `LiteralSugar`; see the module header.
pub(crate) struct TermLiteralSugar {
    /// The source scalar literal this node lifts. `desugar` lifts it through
    /// `translate_lit(&self.lit)` -- byte-identical to the `Expr::Lit(lit) =>
    /// translate_lit(lit)` arm.
    pub(crate) lit: ExprLit,
}

impl Sugar for TermLiteralSugar {
    /// LEAF term reduction: `translate_lit(&self.lit)`. `Ok(term)` completes to
    /// `Desugared::Term(term)` (the width-keyed `Const` / `str_const` / `bool_const`
    /// / content-keyed bytes `Var` the arm produced); an `Err(reason)` -- a
    /// non-scalar literal -- returns Incomplete `Effect::Unsupported { reason }`, the verbatim
    /// reason the arm's `Err` carried. `ctx` is unused: a literal is atomic, its
    /// value fixed by its tokens.
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        match translate_lit(&self.lit) {
            Ok(term) => Outcome::Complete(Desugared::Term(term)),
            Err(reason) => Outcome::Incomplete(Effect::Unsupported { reason }),
        }
    }
}

#[cfg(test)]
mod tests {
    // `TermLiteralSugar::desugar` does NOT read `ctx` (a literal's value is fixed by
    // its tokens), but the trait signature still requires a `&SugarCtx`. Rather than
    // build the lifetime-heavy `SugarCtx` (documented impractical in `bound.rs`), we
    // assert the byte-identical term output by comparing the node's reduction
    // SEAM against the shared helper it mirrors: `desugar` is `translate_lit(&lit)`
    // wrapped, so `translate_lit(&lit)` IS the ground truth for the produced term,
    // and we verify the exact `Term` shape `translate_lit` yields for each scalar
    // kind here (the same shapes `desugar` completes). The end-to-end byte-identity is
    // exercised through `tests/assertion_lift.rs` once the factory routes the scalar
    // `Expr::Lit` term arm here (the wiring slice).
    use super::*;
    use sugar_ir_symbolic::{ConstValue, Term};
    use syn::parse_quote;

    /// The node holds the `ExprLit` it will lift, unchanged.
    #[test]
    fn holds_the_source_literal() {
        let lit: ExprLit = parse_quote!(42u8);
        let node = TermLiteralSugar { lit: lit.clone() };
        assert_eq!(
            quote::ToTokens::to_token_stream(&node.lit).to_string(),
            quote::ToTokens::to_token_stream(&lit).to_string(),
        );
    }

    /// An UNSUFFIXED int lifts to a plain `num` (`Const { Int, sort: int }`) -- the
    /// exact term `desugar` completes (`translate_lit` -> `num(value)`).
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
}
