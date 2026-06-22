// SPDX-License-Identifier: Apache-2.0
//
// `ConstraintRuntimeBoundarySugar`: relation operands that are not missing literal
// reducers, but proven runtime boundaries. The relation macro sugar asks this only
// after normal equality/inequality lowering fails, so already-liftable atomics and
// ordinary relations keep their existing contracts.

use crate::{token_key, SugarCtx};
use syn::{Expr, UnOp};

struct RuntimeTermBoundary {
    site: String,
    cause: &'static str,
}

impl RuntimeTermBoundary {
    fn reason(&self) -> String {
        format!(
            "unsupported term `{}`: effectful / raw-pointer / mutable-reference term \
             ({}) is not a constructible timeless value; refused",
            self.site, self.cause
        )
    }
}

pub(crate) fn relation_runtime_boundary_reason(
    lhs: &Expr,
    rhs: &Expr,
    ctx: &SugarCtx,
) -> Option<String> {
    nan_comparison_reason(lhs, rhs, ctx).or_else(|| {
        runtime_boundary_term(lhs, ctx, 0)
            .or_else(|| runtime_boundary_term(rhs, ctx, 0))
            .map(|boundary| boundary.reason())
    })
}

pub(crate) fn panic_payload_match_value_reason(
    m: &syn::ExprMatch,
    ctx: &SugarCtx,
) -> Option<String> {
    if !expr_is_catch_unwind_source(&m.expr, ctx, 0)
        || !m
            .arms
            .iter()
            .any(|arm| expr_downcasts_panic_payload(&arm.body))
    {
        return None;
    }
    Some(
        RuntimeTermBoundary {
            site: token_key(&Expr::Match(m.clone())),
            cause: "panic payload downcast reads runtime exception state",
        }
        .reason(),
    )
}

fn runtime_boundary_term(expr: &Expr, ctx: &SugarCtx, depth: usize) -> Option<RuntimeTermBoundary> {
    if depth > 16 {
        return None;
    }
    if let Some(boundary) = atomic_load_boundary(expr) {
        return Some(boundary);
    }
    match expr {
        Expr::Paren(paren) => runtime_boundary_term(&paren.expr, ctx, depth + 1),
        Expr::Group(group) => runtime_boundary_term(&group.expr, ctx, depth + 1),
        Expr::Reference(reference) => runtime_boundary_term(&reference.expr, ctx, depth + 1),
        Expr::Unary(unary) => panic_payload_deref_boundary(unary, ctx, depth + 1)
            .or_else(|| runtime_boundary_term(&unary.expr, ctx, depth + 1)),
        Expr::MethodCall(method) => runtime_boundary_term(&method.receiver, ctx, depth + 1)
            .or_else(|| {
                method
                    .args
                    .iter()
                    .find_map(|arg| runtime_boundary_term(arg, ctx, depth + 1))
            }),
        Expr::Field(field) => runtime_boundary_term(&field.base, ctx, depth + 1),
        Expr::Index(index) => runtime_boundary_term(&index.expr, ctx, depth + 1)
            .or_else(|| runtime_boundary_term(&index.index, ctx, depth + 1)),
        Expr::Call(call) => runtime_boundary_term(&call.func, ctx, depth + 1).or_else(|| {
            call.args
                .iter()
                .find_map(|arg| runtime_boundary_term(arg, ctx, depth + 1))
        }),
        Expr::Binary(binary) => runtime_boundary_term(&binary.left, ctx, depth + 1)
            .or_else(|| runtime_boundary_term(&binary.right, ctx, depth + 1)),
        Expr::Cast(cast) => runtime_boundary_term(&cast.expr, ctx, depth + 1),
        Expr::Array(array) => array
            .elems
            .iter()
            .find_map(|elem| runtime_boundary_term(elem, ctx, depth + 1)),
        Expr::Tuple(tuple) => tuple
            .elems
            .iter()
            .find_map(|elem| runtime_boundary_term(elem, ctx, depth + 1)),
        _ => None,
    }
}

fn nan_comparison_reason(lhs: &Expr, rhs: &Expr, ctx: &SugarCtx) -> Option<String> {
    nan_value_site(lhs, ctx, 0)
        .or_else(|| nan_value_site(rhs, ctx, 0))
        .map(|site| {
            format!(
                "NaN comparison `{site}` uses Rust float PartialEq/PartialOrd semantics, \
                 not ordinary total-order/equality semantics; refused"
            )
        })
}

fn nan_value_site(expr: &Expr, ctx: &SugarCtx, depth: usize) -> Option<String> {
    if depth > 16 {
        return None;
    }
    match expr {
        Expr::Path(path) => {
            if path_is_float_nan(path) {
                return Some(token_key(expr));
            }
            path.path
                .get_ident()
                .and_then(|ident| ctx.scope.stable_let_binding_for_term(&ident.to_string()))
                .and_then(|init| nan_value_site(init, ctx, depth + 1))
        }
        Expr::Paren(paren) => nan_value_site(&paren.expr, ctx, depth + 1),
        Expr::Group(group) => nan_value_site(&group.expr, ctx, depth + 1),
        Expr::Reference(reference) => nan_value_site(&reference.expr, ctx, depth + 1),
        Expr::Unary(unary) => nan_value_site(&unary.expr, ctx, depth + 1),
        Expr::Cast(cast) => nan_value_site(&cast.expr, ctx, depth + 1),
        Expr::Array(array) => array
            .elems
            .iter()
            .find_map(|elem| nan_value_site(elem, ctx, depth + 1)),
        Expr::Tuple(tuple) => tuple
            .elems
            .iter()
            .find_map(|elem| nan_value_site(elem, ctx, depth + 1)),
        Expr::Repeat(repeat) => nan_value_site(&repeat.expr, ctx, depth + 1)
            .or_else(|| nan_value_site(&repeat.len, ctx, depth + 1)),
        Expr::Block(block) => block.block.stmts.iter().rev().find_map(|stmt| match stmt {
            syn::Stmt::Expr(expr, _) => nan_value_site(expr, ctx, depth + 1),
            syn::Stmt::Local(local) => local
                .init
                .as_ref()
                .and_then(|init| nan_value_site(&init.expr, ctx, depth + 1)),
            _ => None,
        }),
        _ => None,
    }
}

fn path_is_float_nan(path: &syn::ExprPath) -> bool {
    let segments: Vec<String> = path
        .path
        .segments
        .iter()
        .map(|segment| segment.ident.to_string())
        .collect();
    let names: Vec<&str> = segments.iter().map(String::as_str).collect();
    matches!(
        names.as_slice(),
        ["f32", "NAN"]
            | ["f64", "NAN"]
            | ["std", "f32", "NAN"]
            | ["std", "f64", "NAN"]
            | ["core", "f32", "NAN"]
            | ["core", "f64", "NAN"]
    )
}

fn atomic_load_boundary(expr: &Expr) -> Option<RuntimeTermBoundary> {
    let Expr::MethodCall(method) = expr else {
        return None;
    };
    if method.method != "load" || !method.args.iter().any(is_atomic_ordering_arg) {
        return None;
    }
    Some(RuntimeTermBoundary {
        site: token_key(expr),
        cause: "atomic load reads interior-mutable runtime state",
    })
}

fn is_atomic_ordering_arg(expr: &Expr) -> bool {
    let Expr::Path(path) = expr else {
        return false;
    };
    let mut saw_ordering_type = false;
    let mut saw_ordering_variant = false;
    for segment in &path.path.segments {
        match segment.ident.to_string().as_str() {
            "Ordering" => saw_ordering_type = true,
            "Relaxed" | "Acquire" | "Release" | "AcqRel" | "SeqCst" => {
                saw_ordering_variant = true;
            }
            _ => {}
        }
    }
    saw_ordering_type && saw_ordering_variant
}

fn panic_payload_deref_boundary(
    unary: &syn::ExprUnary,
    ctx: &SugarCtx,
    depth: usize,
) -> Option<RuntimeTermBoundary> {
    if !matches!(unary.op, UnOp::Deref(_)) {
        return None;
    }
    let name = expr_path_ident(&unary.expr)?;
    let init = ctx.scope.stable_let_binding_for_term(&name)?;
    if !expr_is_catch_unwind_payload(init, ctx, depth + 1) {
        return None;
    }
    Some(RuntimeTermBoundary {
        site: token_key(&Expr::Unary(unary.clone())),
        cause: "panic payload downcast reads runtime exception state",
    })
}

fn expr_path_ident(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(path) => path.path.get_ident().map(ToString::to_string),
        Expr::Paren(paren) => expr_path_ident(&paren.expr),
        Expr::Group(group) => expr_path_ident(&group.expr),
        _ => None,
    }
}

fn expr_is_catch_unwind_payload(expr: &Expr, ctx: &SugarCtx, depth: usize) -> bool {
    if depth > 16 {
        return false;
    }
    match expr {
        Expr::Match(match_expr) => {
            expr_is_catch_unwind_source(&match_expr.expr, ctx, depth + 1)
                && match_expr
                    .arms
                    .iter()
                    .any(|arm| expr_downcasts_panic_payload(&arm.body))
        }
        Expr::Path(path) => path
            .path
            .get_ident()
            .and_then(|ident| ctx.scope.stable_let_binding_for_term(&ident.to_string()))
            .is_some_and(|init| expr_is_catch_unwind_payload(init, ctx, depth + 1)),
        Expr::Paren(paren) => expr_is_catch_unwind_payload(&paren.expr, ctx, depth + 1),
        Expr::Group(group) => expr_is_catch_unwind_payload(&group.expr, ctx, depth + 1),
        _ => false,
    }
}

fn expr_is_catch_unwind_source(expr: &Expr, ctx: &SugarCtx, depth: usize) -> bool {
    if depth > 16 {
        return false;
    }
    match expr {
        Expr::Call(call) => expr_path_last_ident(&call.func).as_deref() == Some("catch_unwind"),
        Expr::Path(path) => path
            .path
            .get_ident()
            .and_then(|ident| ctx.scope.stable_let_binding_for_term(&ident.to_string()))
            .is_some_and(|init| expr_is_catch_unwind_source(init, ctx, depth + 1)),
        Expr::Paren(paren) => expr_is_catch_unwind_source(&paren.expr, ctx, depth + 1),
        Expr::Group(group) => expr_is_catch_unwind_source(&group.expr, ctx, depth + 1),
        _ => false,
    }
}

fn expr_path_last_ident(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = expr else {
        return None;
    };
    path.path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
}

fn expr_downcasts_panic_payload(expr: &Expr) -> bool {
    match expr {
        Expr::MethodCall(method) => {
            let name = method.method.to_string();
            name.starts_with("downcast")
                || (name == "unwrap" && expr_downcasts_panic_payload(&method.receiver))
                || method.args.iter().any(expr_downcasts_panic_payload)
        }
        Expr::Block(block) => block
            .block
            .stmts
            .last()
            .is_some_and(stmt_downcasts_panic_payload),
        Expr::Unsafe(unsafe_expr) => unsafe_expr
            .block
            .stmts
            .last()
            .is_some_and(stmt_downcasts_panic_payload),
        Expr::Paren(paren) => expr_downcasts_panic_payload(&paren.expr),
        Expr::Group(group) => expr_downcasts_panic_payload(&group.expr),
        Expr::Reference(reference) => expr_downcasts_panic_payload(&reference.expr),
        Expr::Call(call) => {
            expr_downcasts_panic_payload(&call.func)
                || call.args.iter().any(expr_downcasts_panic_payload)
        }
        _ => false,
    }
}

fn stmt_downcasts_panic_payload(stmt: &syn::Stmt) -> bool {
    match stmt {
        syn::Stmt::Expr(expr, _) => expr_downcasts_panic_payload(expr),
        _ => false,
    }
}
