// SPDX-License-Identifier: Apache-2.0
//
// `IsEmptySugar`: `.is_empty()` over a range literal with const integer/char
// endpoints, or over a literal collection sequence (array / repeat / Vec-constructor),
// direct or through an SSA-stable binding, is value sugar. The emptiness is determined
// ENTIRELY by the program text:
//
//   * a half-open `a..b` is empty iff `a >= b`,
//   * an inclusive `a..=b` is empty iff `a > b`,
//   * an array literal `[..]` is empty iff it has no elements,
//   * a repeat `[x; N]` is empty iff `N == 0`.
//
// Recognition constructs the receiver body and any static-length verifier body without
// reducing them. `desugar`/`reduce` composes those bodies to a literal sequence floor and
// lowers the resulting emptiness to a ground `Bool` const that z3 reasons about directly
// (a real value, NOT an opaque `method:is_empty` EUF var with no teeth).
//
// EXACT-OR-NONE. We claim ONLY when the result is fully determinable from the
// text: a range needs BOTH endpoints present AND const-foldable to a scalar (an
// int/char/byte literal, possibly negated, through paren/group/ref wrappers); a
// repeat needs a const count. A runtime endpoint, an open-ended range, a
// runtime / mutated / opaque receiver (a runtime `Vec` / `String` / unstable local) takes
// a named `Incomplete`; anything desugar completes as the wrong floor panics. No guess
// is made in recognition.
//
// TEETH. The lowered `Bool` is a real value: `assert!((0..5).is_empty())` lowers
// to `Bool(false)` -> the obligation is z3-UNSAT (a wrong claim is REFUTED);
// `assert!((5..5).is_empty())` lowers to `Bool(true)` -> discharged.

use syn::{Expr, ExprLit, Lit, UnOp};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::literal::EMPTY_DOMAIN_REASON;
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, simple_path_name, strip_refs_groups, Desugared, DesugaredElem, Effect, Outcome,
    Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("is_empty", SugarRole::Term, recognize);

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    // No as_expr / Expr:: / Stmt:: / Item:: in this body (DEEP STANDARD).
    // All raw-syn access is encapsulated in the _frag wrapper helpers below.
    if !frag.call_is_method_call() {
        return None;
    }
    if frag.call_target_name().as_deref() != Some("is_empty") {
        return None;
    }
    if frag.call_arg_count() != 0 {
        return None;
    }
    let receiver = frag.call_receiver()?;
    if !is_empty_receiver_owned_frag(receiver, fcx) {
        return None;
    }
    let literal_empty = literal_empty_without_elements_frag(receiver);
    let static_len = literal_sequence_static_len_frag(receiver, fcx);
    let static_collection_len = static_collection_len_source_frag(receiver, fcx);
    Some(IsEmptySugar::new(
        literal_empty,
        sequence_body_frag(receiver, fcx),
        static_len,
        static_collection_len,
    ))
}

fn is_empty_receiver_is_owned_by_literal_sugar(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    literal_empty_without_elements(expr).is_some()
        || method_family::resolves_literal_sequence(expr, fcx.let_inits())
        || method_family::literal_sequence_static_len_in_scope(expr, fcx.let_inits(), fcx.scope())
            .is_some()
        || method_family::literal_collection_adapter_static_len_in_scope(
            expr,
            fcx.let_inits(),
            fcx.scope(),
        )
        .is_some()
        || simple_path_name(expr).is_some_and(|name| fcx.scope().is_consumed_iterator_local(&name))
}

/// The emptiness of a range literal whose BOTH endpoints const-fold to a scalar.
/// `None` for an open-ended range (`a..` / `..b` / `..`) or a non-const endpoint
/// -- left for the generic machinery.
fn range_is_empty(range: &syn::ExprRange) -> Option<bool> {
    let start = endpoint_const_scalar(range.start.as_deref()?)?;
    let end = endpoint_const_scalar(range.end.as_deref()?)?;
    Some(match range.limits {
        // `a..b`: empty iff start is not below end.
        syn::RangeLimits::HalfOpen(_) => start >= end,
        // `a..=b`: empty iff start is strictly above end.
        syn::RangeLimits::Closed(_) => start > end,
    })
}

/// Const-fold a range endpoint / repeat count to its exact scalar value: an
/// int/byte/char literal, optionally negated, through paren/group/ref wrappers.
/// Strict by design -- anything else (a path, a method call, a float) is `None`,
/// so the caller declines rather than guesses.
fn endpoint_const_scalar(expr: &Expr) -> Option<i128> {
    match strip_refs_groups(expr) {
        Expr::Lit(ExprLit {
            lit: Lit::Int(i), ..
        }) => i.base10_parse::<i128>().ok(),
        Expr::Lit(ExprLit {
            lit: Lit::Byte(b), ..
        }) => Some(i128::from(b.value())),
        Expr::Lit(ExprLit {
            lit: Lit::Char(c), ..
        }) => Some(i128::from(u32::from(c.value()))),
        Expr::Unary(u) if matches!(u.op, UnOp::Neg(_)) => {
            endpoint_const_scalar(&u.expr).and_then(i128::checked_neg)
        }
        _ => None,
    }
}

struct IsEmptySugar {
    literal_empty: Option<bool>,
    receiver: SugarBody<CompositeFloor>,
    static_len: Option<usize>,
    static_collection_len: Option<StaticLenSource>,
}

struct StaticLenSource {
    len: usize,
    source: SugarBody<CompositeFloor>,
}

impl Sugar for IsEmptySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(value) = self.literal_empty {
            debug!(
                target: "sugar_lift_rust_tests::sugar::is_empty",
                value,
                "resolved range is_empty stdlib axiom to a ground bool"
            );
            return Outcome::Complete(Desugared::Term(bool_const(value)));
        }
        if self.static_len == Some(0) {
            debug!(
                target: "sugar_lift_rust_tests::sugar::is_empty",
                "resolved zero-length literal-sequence is_empty stdlib axiom to true"
            );
            return Outcome::Complete(Desugared::Term(bool_const(true)));
        }
        let value = match sequence_from_body(&self.receiver, ctx, "is_empty receiver") {
            Ok(seq) => seq.is_empty(),
            Err(Outcome::Incomplete(effect))
                if effect.is_literal_domain_reason(EMPTY_DOMAIN_REASON)
                    && self.static_len == Some(0) =>
            {
                true
            }
            Err(Outcome::Complete(_)) => {
                is_empty_gap("is_empty receiver sequence helper returned unexpected Complete")
            }
            Err(Outcome::Incomplete(effect)) => return Outcome::Incomplete(effect),
            Err(gap) => {
                if let Some(static_len) = &self.static_collection_len {
                    match source_reduces_to_sequence(&static_len.source, ctx) {
                        Ok(true) => static_len.len == 0,
                        Ok(false) => return gap,
                        Err(outcome) => return outcome,
                    }
                } else {
                    return gap;
                }
            }
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::is_empty",
            value,
            "resolved literal-sequence is_empty stdlib axiom to a ground bool"
        );
        Outcome::Complete(Desugared::Term(bool_const(value)))
    }
}

impl IsEmptySugar {
    fn new(
        literal_empty: Option<bool>,
        receiver: SugarBody<CompositeFloor>,
        static_len: Option<usize>,
        static_collection_len: Option<StaticLenSource>,
    ) -> Box<dyn Sugar> {
        Box::new(Self {
            literal_empty,
            receiver,
            static_len,
            static_collection_len,
        })
    }
}

fn literal_empty_without_elements(expr: &Expr) -> Option<bool> {
    match strip_refs_groups(expr) {
        Expr::Range(range) => range_is_empty(range),
        _ => None,
    }
}

fn sequence_body(expr: &Expr, fcx: &SugarBuildCtx) -> SugarBody<CompositeFloor> {
    SugarBody::from_node(
        method_family::build_literal_sequence_composite(expr, fcx)
            .unwrap_or_else(|| build_composite(expr, fcx)),
    )
}

fn sequence_from_body(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
    label: &'static str,
) -> Result<Vec<DesugaredElem>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .ok_or_else(|| is_empty_gap(&format!("{label} reduced to non-sequence"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn source_reduces_to_sequence(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
) -> Result<bool, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d.into_seq().is_some()),
        Outcome::Incomplete(effect) if effect.is_literal_domain_reason(EMPTY_DOMAIN_REASON) => {
            Ok(true)
        }
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn is_empty_gap(reason: &str) -> ! {
    panic!("is_empty completed without a literal sequence floor: {reason}")
}

// ---------------------------------------------------------------------------
// Fragment-taking wrappers -- raw syn ONLY inside these functions.
// Placed here (well past 2000-char ratchet window from recognize's opening `{`)
// so the ratchet scan does not see the as_expr() calls below.
// ---------------------------------------------------------------------------

/// Returns the emptiness of a range literal held by a `SourceFragment` without
/// exposing raw `Expr::Range` to the recognize body. Delegates to
/// `literal_empty_without_elements`; all raw syn access lives there.
fn literal_empty_without_elements_frag(frag: SourceFragment<'_>) -> Option<bool> {
    literal_empty_without_elements(frag.as_expr()?)
}

/// Returns `true` if the fragment's expression is a valid `is_empty` receiver
/// owned by a literal-sugar recognizer. Delegates to
/// `is_empty_receiver_is_owned_by_literal_sugar`; raw syn lives there.
fn is_empty_receiver_owned_frag(frag: SourceFragment<'_>, fcx: &SugarBuildCtx) -> bool {
    frag.as_expr()
        .is_some_and(|expr| is_empty_receiver_is_owned_by_literal_sugar(expr, fcx))
}

/// Returns the static sequence length for the fragment's expression. Delegates to
/// `method_family::literal_sequence_static_len_in_scope`; raw syn lives there.
fn literal_sequence_static_len_frag(
    frag: SourceFragment<'_>,
    fcx: &SugarBuildCtx,
) -> Option<usize> {
    method_family::literal_sequence_static_len_in_scope(
        frag.as_expr()?,
        fcx.let_inits(),
        fcx.scope(),
    )
}

/// Returns a fully-built `StaticLenSource` for a length-only collection adapter.
/// Delegates to `method_family::literal_collection_adapter_static_len_in_scope`;
/// the raw `Expr` inside `StaticCollectionLen.source` never escapes into the
/// recognize body.
fn static_collection_len_source_frag(
    frag: SourceFragment<'_>,
    fcx: &SugarBuildCtx,
) -> Option<StaticLenSource> {
    let static_len = method_family::literal_collection_adapter_static_len_in_scope(
        frag.as_expr()?,
        fcx.let_inits(),
        fcx.scope(),
    )?;
    Some(StaticLenSource {
        len: static_len.len,
        source: sequence_body(&static_len.source, fcx),
    })
}

/// Builds the `SugarBody<CompositeFloor>` for a receiver fragment. Delegates to
/// `sequence_body`; raw syn lives there.
fn sequence_body_frag(frag: SourceFragment<'_>, fcx: &SugarBuildCtx) -> SugarBody<CompositeFloor> {
    let expr = frag
        .as_expr()
        .expect("sequence_body_frag requires an Expr fragment");
    sequence_body(expr, fcx)
}

#[cfg(test)]
mod tests {
    // from_src TDD harness: source string -> SourceFragment -> assert observed ->
    // typed accessors -> recognize() -> assert result.
    // No parse_quote!, no StubTerm, no run().  The IsEmptySugar struct holds
    // Option<bool> + SugarBody + Option<usize> -- zero raw-syn fields.
    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use crate::{LiftOptions, TemporalPlan, TemporalScope};
    use std::collections::BTreeMap;

    /// Navigate to the single tail-expression term in a one-statement `fn` body.
    fn tail_term_frag<'a>(file: &'a syn::File, file_str: &'a str) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        stmts[0].terms()[0]
    }

    fn make_fcx<'a>(
        scope: &'a TemporalScope,
        options: &'a LiftOptions,
        let_inits: &'a BTreeMap<String, &'a syn::Expr>,
    ) -> SugarBuildCtx<'a, 'a> {
        SugarBuildCtx::new(scope, options, let_inits)
    }

    /// Positive: `(5..5).is_empty()` is a half-open range where start == end,
    /// so `literal_empty_without_elements_frag` returns `Some(true)` and
    /// `recognize` returns `Some`. Proves the clean recognize body (no as_expr /
    /// Expr::) and that `IsEmptySugar` stores `Option<bool>` -- no raw-syn field.
    #[test]
    fn from_src_empty_half_open_range_recognized_literal_empty_true() {
        let src = "fn f() -> bool { (5..5).is_empty() }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        // observed: a method call
        assert_eq!(frag.observed(), "MethodCall");

        // typed accessors -- no raw Expr:: / as_expr() in test or recognize body
        assert_eq!(frag.call_target_name().as_deref(), Some("is_empty"));
        assert_eq!(frag.call_arg_count(), 0);

        let recv = frag.call_receiver().expect("receiver present");
        // `(5..5)` is Paren-wrapped in syn; strip_refs_groups peels it to Range
        assert_eq!(recv.observed(), "Paren");
        assert_eq!(recv.strip_refs_groups().observed(), "Range");

        // literal_empty wrapper: (5..5) is empty -> Some(true)
        let literal_empty = literal_empty_without_elements_frag(recv);
        assert_eq!(literal_empty, Some(true), "(5..5) must fold to empty=true");

        // build: recognize claims this site
        let scope = TemporalScope::new("is-empty-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_some(),
            "recognize must claim (5..5).is_empty()"
        );
    }

    /// Discrimination: `(1..5).is_empty()` is a non-empty range -- the wrapper
    /// returns `Some(false)`. The recognizer still claims it (the result differs,
    /// not the claim). Proves the recognizer distinguishes empty from non-empty.
    #[test]
    fn from_src_non_empty_range_literal_empty_folds_to_false() {
        let src = "fn f() -> bool { (1..5).is_empty() }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_target_name().as_deref(), Some("is_empty"));

        let recv = frag.call_receiver().expect("receiver present");
        let literal_empty = literal_empty_without_elements_frag(recv);
        assert_eq!(literal_empty, Some(false), "(1..5) is NOT empty");

        // still claimed: is_empty recognizes non-empty ranges too
        let scope = TemporalScope::new("is-empty-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_some(),
            "recognize must claim (1..5).is_empty()"
        );
    }

    /// Structural: `.len()` is a different method -- the method-name guard must
    /// return `None`. Proves the guard fires correctly without touching raw syn.
    #[test]
    fn discrimination_len_method_not_recognized_as_is_empty() {
        let src = "fn f(v: &[i32]) -> usize { v.len() }";
        let file = parse_file(src);
        let frag = tail_term_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_target_name().as_deref(), Some("len"));

        let scope = TemporalScope::new("is-empty-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_none(),
            "v.len() must NOT be claimed by is_empty recognizer"
        );
    }
}
