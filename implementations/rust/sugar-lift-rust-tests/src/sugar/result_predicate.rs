// SPDX-License-Identifier: Apache-2.0
//
// `ResultPredicateSugar`: `.is_ok()` / `.is_err()` over a grounded std `Result`
// constructor. The sibling of `option_predicate` (`is_some`/`is_none`): once the
// receiver bottoms out to `res:ok(_)` or `res:err(_)`, the predicate is a literal
// bool, replacing the opaque `method:is_ok` EUF var (no teeth).
//
// EXACT-OR-PANIC AT DESUGAR. We claim only when the receiver is known to ground
// to `res:ok`/`res:err`: integer `try_from(literal)`, Result constructors, or
// adaptors that preserve the Result floor. Runtime/effectful children propagate
// their own Effect; a constructed receiver that is not a Result floor is a factory
// construction bug and panics.
//
// TEETH. `u8::try_from(256u16).is_err()` grounds to `res:err` -> `Bool(true)`;
// `.is_ok()` -> `Bool(false)` (z3-UNSAT if asserted).

use std::rc::Rc;

use sugar_ir_symbolic::Term;
use syn::Expr;
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{MonadicFloorAccept, MonadicFloorVisitor};
use crate::{
    bool_const, const_fold_int_term, const_fold_u128_term, strip_refs_groups, Desugared, Outcome,
    Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "result_predicate",
    SugarRole::Term,
    crate::sugar::claim::SugarWitnesses::Pending,
    recognize,
);

// FULLY MIGRATED (Phase-3 ratchet): no as_expr(), no raw Expr:: / MethodCall field
// access in the recognize body. Uses call_method_key(), call_arg_count(),
// call_receiver(), and SugarBody::term_frag() exclusively. Helpers
// is_known_result_source_frag and layout_from_size_align_args_frag accept
// SourceFragment at the call site; raw syn stays inside those helpers and below.
fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let method = frag.call_method_key()?;
    if !matches!(method.as_str(), "is_ok" | "is_err") || frag.call_arg_count() != 0 {
        return None;
    }
    let receiver_frag = frag.call_receiver()?;
    if !is_known_result_source_frag(receiver_frag, fcx) {
        return None;
    }
    let layout =
        layout_from_size_align_args_frag(receiver_frag).map(|(size_frag, align_frag)| LayoutArgs {
            size: SugarBody::term_frag(&size_frag, fcx),
            align: SugarBody::term_frag(&align_frag, fcx),
        });
    Some(Box::new(ResultPredicateSugar {
        method,
        receiver: SugarBody::term_frag(&receiver_frag, fcx),
        layout,
    }))
}

struct ResultPredicateSugar {
    method: String,
    receiver: SugarBody<TermFloor>,
    layout: Option<LayoutArgs>,
}

struct LayoutArgs {
    size: SugarBody<TermFloor>,
    align: SugarBody<TermFloor>,
}

impl Sugar for ResultPredicateSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(layout) = &self.layout {
            let is_ok = match layout.is_ok(ctx) {
                Ok(value) => value,
                Err(outcome) => return outcome,
            };
            let value = if self.method == "is_ok" {
                is_ok
            } else {
                !is_ok
            };
            debug!(
                target: "sugar_lift_rust_tests::sugar::result_predicate",
                method = self.method.as_str(),
                value,
                "resolved Layout::from_size_align Result predicate compiler axiom"
            );
            return Outcome::Complete(Desugared::Term(bool_const(value)));
        }
        let receiver = match self.receiver.reduce(ctx) {
            Outcome::Complete(d) => d.into_term().unwrap_or_else(|| {
                panic!(
                    "Result predicate `{}` receiver reduced to non-term",
                    self.method
                )
            }),
            Outcome::Incomplete(e) => return Outcome::Incomplete(e),
        };
        receiver.accept_monadic_floor(ResultPresenceVisitor {
            method: &self.method,
        })
    }
}

impl LayoutArgs {
    fn is_ok(&self, ctx: &SugarCtx) -> Result<bool, Outcome> {
        let size = term_as_u128(&reduce_term_body(&self.size, ctx)?)
            .unwrap_or_else(|| panic!("Layout::from_size_align size did not reduce to integer"));
        let align = term_as_u128(&reduce_term_body(&self.align, ctx)?)
            .unwrap_or_else(|| panic!("Layout::from_size_align align did not reduce to integer"));
        if align == 0 || !align.is_power_of_two() {
            return Ok(false);
        }
        let rem = size % align;
        let rounded = if rem == 0 {
            size
        } else {
            let padding = align
                .checked_sub(rem)
                .unwrap_or_else(|| panic!("Layout::from_size_align align remainder underflowed"));
            let Some(rounded) = size.checked_add(padding) else {
                return Ok(false);
            };
            rounded
        };
        Ok(rounded <= isize::MAX as u128)
    }
}

fn reduce_term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("Layout::from_size_align argument reduced to non-term"))),
        Outcome::Incomplete(e) => Err(Outcome::Incomplete(e)),
    }
}

struct ResultPresenceVisitor<'a> {
    method: &'a str,
}

impl MonadicFloorVisitor for ResultPresenceVisitor<'_> {
    type Output = Outcome;

    fn visit_some(self, _inner: &Rc<Term>) -> Self::Output {
        panic!(
            "Result predicate `{}` received an Option::Some floor",
            self.method
        )
    }

    fn visit_none(self) -> Self::Output {
        panic!(
            "Result predicate `{}` received an Option::None floor",
            self.method
        )
    }

    fn visit_ok(self, _inner: &Rc<Term>) -> Self::Output {
        self.complete(true)
    }

    fn visit_err(self, _inner: &Rc<Term>) -> Self::Output {
        self.complete(false)
    }

    fn visit_non_monadic(self, _term: &Rc<Term>) -> Self::Output {
        panic!(
            "Result predicate `{}` receiver did not reduce to Result constructor",
            self.method
        )
    }
}

impl ResultPresenceVisitor<'_> {
    fn complete(self, is_ok: bool) -> Outcome {
        let value = if self.method == "is_ok" {
            is_ok
        } else {
            !is_ok
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::result_predicate",
            method = self.method,
            value,
            "resolved Result presence predicate stdlib axiom"
        );
        Outcome::Complete(Desugared::Term(bool_const(value)))
    }
}

/// SourceFragment entry point for `is_known_result_source` -- used in the migrated
/// recognize body so no raw `&Expr` appears at the recognize body call site.
/// The `as_expr()` call lives HERE (a helper, ratchet-excluded from the recognize body).
fn is_known_result_source_frag(frag: SourceFragment, fcx: &SugarBuildCtx) -> bool {
    let Some(expr) = frag.as_expr() else {
        return false;
    };
    is_known_result_source(expr, fcx)
}

/// SourceFragment entry point for `layout_from_size_align_args` -- returns the two
/// argument fragments (size, align) when the receiver fragment matches the
/// `Layout::from_size_align(size, align)` call shape. Used in the migrated recognize
/// body. Accesses `frag.node` directly (pub(crate) + Copy) so the `&'a Expr`
/// lifetime is preserved -- `as_expr(&self)` binds to the borrow of self, not to
/// `'a`, which would prevent returning a `SourceFragment<'a>`.
fn layout_from_size_align_args_frag<'a>(
    frag: SourceFragment<'a>,
) -> Option<(SourceFragment<'a>, SourceFragment<'a>)> {
    use crate::sugar::source_fragment::FragNode;
    let FragNode::Expr(expr) = frag.node else {
        return None;
    };
    layout_from_size_align_args(expr).map(|(size, align)| {
        (
            SourceFragment::expr(size, frag.file),
            SourceFragment::expr(align, frag.file),
        )
    })
}

/// A receiver that grounds to a `Result` ctor: an integer `try_from(literal)`,
/// a literal-payload `Ok(..)`/`Err(..)`, or a no-op `inspect`/`inspect_err` chain over
/// one of those stable sources.
///
/// EXACT-OR-NONE AT RECOGNIZE: broad or effectful `Ok(io())` and transforming adaptors
/// stay outside this predicate owner. `inspect`/`inspect_err` itself owns its method
/// shape before the generic method sugar, so non-no-op inspect callbacks become gaps
/// instead of opaque predicate terms.
fn is_known_result_source(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    receiver_resolves_result_source(strip_refs_groups(expr), fcx, 0)
}

fn receiver_resolves_result_source(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    if is_syntactic_result_ctor(expr)
        || layout_from_size_align_candidate(expr, fcx)
        || crate::sugar::inspect::is_stable_result_source(strip_refs_groups(expr), fcx)
    {
        return true;
    }
    match strip_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(|ident| ident.to_string()) else {
                return false;
            };
            if fcx.resolving_bound_path(&name) {
                return false;
            }
            let Some(init) = fcx.scope().stable_let_binding_for_term(&name) else {
                return false;
            };
            let child_fcx = fcx.with_bound_path(&name);
            receiver_resolves_result_source(init, &child_fcx, depth + 1)
        }
        Expr::MethodCall(call) if call.method == "ok_or" && call.args.len() == 1 => {
            crate::sugar::option_unwrap::receiver_resolves_monadic_source(
                &call.receiver,
                fcx,
                depth + 1,
            )
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "map" | "and_then" | "map_err"
            ) =>
        {
            receiver_resolves_result_source(&call.receiver, fcx, depth + 1)
        }
        Expr::Paren(paren) => receiver_resolves_result_source(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => receiver_resolves_result_source(&group.expr, fcx, depth + 1),
        _ => false,
    }
}

fn layout_from_size_align_candidate(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Some((size, align)) = layout_from_size_align_args(expr) else {
        return false;
    };
    crate::sugar::primitive_int::integer_receiver_can_ground(size, fcx, 0)
        && crate::sugar::primitive_int::integer_receiver_can_ground(align, fcx, 0)
}

fn layout_from_size_align_args(expr: &Expr) -> Option<(&Expr, &Expr)> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    if call.args.len() != 2 {
        return None;
    }
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    let mut segments = path.path.segments.iter().rev();
    let method = segments.next()?;
    let ty = segments.next()?;
    if method.ident != "from_size_align" || ty.ident != "Layout" {
        return None;
    }
    Some((&call.args[0], &call.args[1]))
}

fn term_as_u128(term: &Rc<Term>) -> Option<u128> {
    const_fold_u128_term(term)
        .or_else(|| const_fold_int_term(term).and_then(|value| u128::try_from(value).ok()))
}

fn is_syntactic_result_ctor(expr: &Expr) -> bool {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return false;
    };
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return false;
    };
    call.args.len() == 1
        && path
            .path
            .segments
            .last()
            .is_some_and(|seg| matches!(seg.ident.to_string().as_str(), "Ok" | "Err"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::factory::SugarBuildCtx;
    use crate::sugar::source_fragment::{parse_file, FragNode, SourceFragment};
    use crate::{LiftOptions, TemporalPlan, TemporalScope};

    fn result_predicate_expr_frag<'a>(
        file: &'a syn::File,
        file_str: &'a str,
    ) -> SourceFragment<'a> {
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), file_str);
        let body = frag.function_body().expect("fn has a body");
        let stmts = body.statements();
        // The tail expression statement; `terms()` yields the single method-call child.
        let terms = stmts[0].terms();
        terms[0]
    }

    fn make_fcx<'a>(
        scope: &'a TemporalScope,
        options: &'a LiftOptions,
        let_inits: &'a std::collections::BTreeMap<String, &'a syn::Expr>,
    ) -> SugarBuildCtx<'a, 'a> {
        SugarBuildCtx::new(scope, options, let_inits)
    }

    /// Positive: `Ok::<u8,()>(1u8).is_ok()` is classified as `"MethodCall"`,
    /// `call_method_key()` returns `"is_ok"`, `call_arg_count()` is 0,
    /// `call_receiver()` yields a `"Call"` fragment (the `Ok(1u8)` constructor).
    /// `recognize()` returns `Some` -- the sugar claims this site.
    /// No as_expr / Expr:: / MethodCall field access in this test body.
    #[test]
    fn from_src_is_ok_observed_method_key_and_receiver() {
        let file = parse_file("fn f() -> bool { Ok::<u8, ()>(1u8).is_ok() }");
        let frag = result_predicate_expr_frag(&file, "f.rs");

        // observed: method call shape
        assert_eq!(frag.observed(), "MethodCall");

        // method key via typed accessor -- no raw Expr:: access
        assert_eq!(frag.call_method_key().as_deref(), Some("is_ok"));

        // arg count: zero (is_ok takes no explicit args)
        assert_eq!(frag.call_arg_count(), 0);

        // receiver: Ok(1u8) is a Call fragment
        let recv = frag.call_receiver().expect("receiver present");
        assert_eq!(recv.observed(), "Call");

        // build: recognize claims this site
        let scope = TemporalScope::new("result-predicate-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_some(),
            "recognize should claim Ok(...).is_ok()"
        );
    }

    /// Discrimination: `Err::<(),u8>(42u8).is_err()` has method key `"is_err"` and
    /// `recognize` claims it -- proves method key discriminates is_err from is_ok.
    #[test]
    fn discrimination_is_err_decodes_from_err_receiver() {
        let file = parse_file("fn f() -> bool { Err::<(), u8>(42u8).is_err() }");
        let frag = result_predicate_expr_frag(&file, "f.rs");

        assert_eq!(frag.observed(), "MethodCall");
        assert_eq!(frag.call_method_key().as_deref(), Some("is_err"));
        assert_eq!(frag.call_arg_count(), 0);

        let recv = frag.call_receiver().expect("receiver present");
        assert_eq!(recv.observed(), "Call");

        let scope = TemporalScope::new("result-predicate-test", TemporalPlan::default());
        let options = LiftOptions::default();
        let let_inits = std::collections::BTreeMap::new();
        let fcx = make_fcx(&scope, &options, &let_inits);
        assert!(
            recognize(&frag, &fcx).is_some(),
            "recognize should claim Err(...).is_err()"
        );
    }

    /// Structural: a `BinOp` fragment returns `None` from `call_method_key()` and
    /// `call_receiver()` -- accessors are shape-specific and do not bleed across kinds.
    #[test]
    fn structural_binop_returns_none_from_call_method_accessors() {
        let file = parse_file("fn f(a: i32, b: i32) -> i32 { a + b }");
        let item = &file.items[0];
        let frag = SourceFragment::from_node(FragNode::Item(item), "f.rs");
        let body = frag.function_body().unwrap();
        let stmts = body.statements();
        let terms = stmts[0].terms();
        let binop_frag = &terms[0];

        assert_eq!(binop_frag.observed(), "BinOp");
        assert_eq!(binop_frag.call_method_key(), None);
        assert!(binop_frag.call_receiver().is_none());
        // call_arg_count() returns 0 for non-call shapes (empty vec fallback)
        assert_eq!(binop_frag.call_arg_count(), 0);
    }
}
