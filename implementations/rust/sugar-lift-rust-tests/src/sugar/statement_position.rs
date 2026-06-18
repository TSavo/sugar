// SPDX-License-Identifier: Apache-2.0
//
// Shared detectors for statement-position effect sugars. This module owns no catalog claim:
// each semantic leaf lives in its own `statement_*` Sugar file.

use syn::{BinOp, Expr};

use crate::{
    closure_body_advances_iterator, count_asserts_in_expr, expr_contains_await,
    is_free_fn_block_on_async, reflection_scrutinee, strip_const_block,
};

pub(crate) fn carries_assert(expr: &Expr) -> bool {
    count_asserts_in_expr(expr) > 0
}

/// CONTINUATION detector: an `.await` anywhere, or a free-fn `block_on(async{..})`,
/// drives a future to completion via a runtime executor.
pub(crate) fn has_control_flow(expr: &Expr) -> bool {
    carries_assert(expr) && (expr_contains_await(expr) || is_free_fn_block_on_async(expr))
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
    if !carries_assert(expr) {
        return false;
    }
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
