// SPDX-License-Identifier: Apache-2.0
//
// Shared detectors for statement-position effect sugars. This module owns no catalog claim:
// each semantic leaf lives in its own `statement_*` Sugar file.

use std::collections::BTreeMap;

use syn::{BinOp, Expr};

use crate::sugar::factory::{has_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::{
    closure_body_advances_iterator, count_asserts_in_expr, count_asserts_in_stmts,
    expr_contains_await, reflection_scrutinee, strip_const_block, sugar_ctx_with_factory_audits,
    token_key, FactoryAuditLog, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, TemporalScope,
};

#[allow(clippy::too_many_arguments)]
pub(crate) fn desugar_composite_expr(
    expr: &Expr,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    let_inits: &BTreeMap<String, &Expr>,
    macro_depth: usize,
    factory_audits: Option<&FactoryAuditLog>,
) -> Outcome {
    let fcx = SugarBuildCtx::new(scope, options, let_inits);
    let body = SugarBody::composite(expr, &fcx);
    desugar_composite_body(
        &body,
        scope,
        options,
        reducer,
        float_widths,
        macro_depth,
        factory_audits,
    )
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn desugar_composite_body(
    body: &SugarBody<CompositeFloor>,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    macro_depth: usize,
    factory_audits: Option<&FactoryAuditLog>,
) -> Outcome {
    let ctx = sugar_ctx_with_factory_audits(
        scope,
        options,
        reducer,
        float_widths,
        macro_depth,
        factory_audits,
    );
    body.desugar(&ctx)
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn desugar_statement_composite(
    expr: &Expr,
    scope: &TemporalScope,
    options: &LiftOptions,
    reducer: &ReductionCtx<'_>,
    float_widths: &mut FloatWidthScope,
    let_inits: &BTreeMap<String, &Expr>,
    macro_depth: usize,
    factory_audits: Option<&FactoryAuditLog>,
) -> Option<Outcome> {
    let fcx = SugarBuildCtx::new(scope, options, let_inits);
    has_composite(expr, &fcx).then(|| {
        desugar_composite_expr(
            expr,
            scope,
            options,
            reducer,
            float_widths,
            let_inits,
            macro_depth,
            factory_audits,
        )
    })
}

pub(crate) fn carries_assert(expr: &Expr) -> bool {
    count_asserts_in_expr(expr) > 0
}

/// CONTINUATION detector: an `.await` in the expression being evaluated here.
/// Await inside a nested async future body is deliberately ignored by
/// `expr_contains_await`; that dormant future is owned by the future-handoff leaf.
pub(crate) fn has_control_flow(expr: &Expr) -> bool {
    carries_assert(expr) && expr_contains_await(expr)
}

/// FUTURE-HANDOFF detector: a call/method expression receives an assertion-bearing
/// async future. The callee spelling is irrelevant; the driver semantics must be
/// learned dynamically from visible source/proof before the async body can be lifted
/// as a point-wise fact.
pub(crate) fn future_handoff_boundary(expr: &Expr) -> Option<String> {
    let expr = strip_transparent(expr);
    let carries_asserting_future = match expr {
        Expr::Call(call) => call.args.iter().any(expr_contains_asserting_async),
        Expr::MethodCall(call) => {
            expr_contains_asserting_async(&call.receiver)
                || call.args.iter().any(expr_contains_asserting_async)
        }
        _ => false,
    };

    carries_asserting_future.then(|| token_key(expr))
}

/// REFLECTION detector: a `match <reflection> { .. }` whose scrutinee is `Type::of` /
/// `TypeId::of` / `.info()` after stripping const/transparent wrappers.
pub(crate) fn reflection_boundary(expr: &Expr) -> Option<String> {
    if !carries_assert(expr) {
        return None;
    }
    let Expr::Match(m) = expr else {
        return None;
    };
    reflection_scrutinee(strip_const_block(&m.expr))
}

fn strip_transparent(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => strip_transparent(&paren.expr),
        Expr::Group(group) => strip_transparent(&group.expr),
        _ => expr,
    }
}

fn expr_contains_asserting_async(expr: &Expr) -> bool {
    struct Scan {
        found: bool,
    }

    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_async(&mut self, async_expr: &'ast syn::ExprAsync) {
            if count_asserts_in_stmts(&async_expr.block.stmts) > 0 {
                self.found = true;
            }
        }
    }

    let mut scan = Scan { found: false };
    syn::visit::Visit::visit_expr(&mut scan, expr);
    scan.found
}

/// LOOP detector: a `loop { .. }` whose body advances a runtime iterator.
pub(crate) fn has_loop_advance(expr: &Expr) -> bool {
    if !carries_assert(expr) {
        return false;
    }
    let Expr::Loop(l) = expr else {
        return false;
    };
    let body = Expr::Block(syn::ExprBlock {
        attrs: Vec::new(),
        label: None,
        block: l.body.clone(),
    });
    loop_body_advances_runtime_iterator(&body)
}

/// RUNTIME expression-statement detector: a statement whose asserted value is read
/// through a `&mut` borrow or mutation.
pub(crate) fn has_runtime_expr(expr: &Expr) -> bool {
    carries_assert(expr) && has_runtime_boundary(expr)
}

/// Runtime mutation / mutable-borrow boundary, independent of whether the
/// expression also contains an assertion macro. Constraint-position callers use
/// this for visited callsites such as `*x.get_mut() += 1`, where the statement
/// itself is the panic-free surface but the value is not timeless.
pub(crate) fn has_runtime_boundary(expr: &Expr) -> bool {
    #[derive(Default)]
    struct Scan {
        runtime: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_reference(&mut self, r: &'ast syn::ExprReference) {
            if r.mutability.is_some() {
                self.runtime = true;
            }
            syn::visit::visit_expr_reference(self, r);
        }

        fn visit_expr_assign(&mut self, _: &'ast syn::ExprAssign) {
            self.runtime = true;
        }

        fn visit_expr_binary(&mut self, b: &'ast syn::ExprBinary) {
            if matches!(
                b.op,
                BinOp::AddAssign(_)
                    | BinOp::SubAssign(_)
                    | BinOp::MulAssign(_)
                    | BinOp::DivAssign(_)
                    | BinOp::RemAssign(_)
                    | BinOp::BitXorAssign(_)
                    | BinOp::BitAndAssign(_)
                    | BinOp::BitOrAssign(_)
                    | BinOp::ShlAssign(_)
                    | BinOp::ShrAssign(_)
            ) {
                self.runtime = true;
            }
            syn::visit::visit_expr_binary(self, b);
        }
    }
    let mut scan = Scan::default();
    syn::visit::Visit::visit_expr(&mut scan, expr);
    scan.runtime
}

/// Top-level mutation expression that can appear as a visited statement
/// surface. This deliberately does not recurse into enclosing `for` / `if` /
/// `match` bodies; those shapes have their own Sugar.
pub(crate) fn is_runtime_mutation_statement(expr: &Expr) -> bool {
    match expr {
        Expr::Assign(_) => true,
        Expr::Binary(binary) => matches!(
            binary.op,
            BinOp::AddAssign(_)
                | BinOp::SubAssign(_)
                | BinOp::MulAssign(_)
                | BinOp::DivAssign(_)
                | BinOp::RemAssign(_)
                | BinOp::BitXorAssign(_)
                | BinOp::BitAndAssign(_)
                | BinOp::BitOrAssign(_)
                | BinOp::ShlAssign(_)
                | BinOp::ShrAssign(_)
        ),
        Expr::Paren(paren) => is_runtime_mutation_statement(&paren.expr),
        Expr::Group(group) => is_runtime_mutation_statement(&group.expr),
        _ => false,
    }
}

/// True if a loop body advances a runtime iterator (`iter.next()` / `.size_hint()`).
fn loop_body_advances_runtime_iterator(body: &Expr) -> bool {
    if closure_body_advances_iterator(body) {
        return true;
    }
    struct Scan {
        found: bool,
    }
    impl<'ast> syn::visit::Visit<'ast> for Scan {
        fn visit_expr_method_call(&mut self, m: &'ast syn::ExprMethodCall) {
            if m.method == "size_hint" && m.args.is_empty() {
                self.found = true;
            }
            syn::visit::visit_expr_method_call(self, m);
        }
    }
    let mut s = Scan { found: false };
    syn::visit::Visit::visit_expr(&mut s, body);
    s.found
}
