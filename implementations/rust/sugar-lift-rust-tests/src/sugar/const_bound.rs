// SPDX-License-Identifier: Apache-2.0
//
// ConstBoundSugar: assertion-shaped expressions whose operands are compiler-known
// const terms (const generics, associated consts, literals, arithmetic/comparison
// over those terms). These can be lifted out of otherwise runtime method bodies:
// the assertion does not read `self` or mutable state, so the impl/trait receiver
// boundary is not the owner of this semantics.

use crate::{
    lower_assert_condition, lower_assert_eq, lower_assert_ne, parse_macro_args,
    scalar_cast_type_key, AssertionEntry, FactoryAuditLog, FloatWidthScope, TemporalScope,
};
use syn::{BinOp, Expr, ExprMacro, Type, UnOp};

pub(crate) fn is_const_bound_assertion(expr: &Expr) -> bool {
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return false;
    };
    let Some(name) = mac.path.segments.last().map(|seg| seg.ident.to_string()) else {
        return false;
    };
    let Ok(args) = parse_macro_args(mac.tokens.clone()) else {
        return false;
    };
    match name.as_str() {
        "assert" => args
            .exprs
            .first()
            .is_some_and(|expr| is_const_bound_expr(expr)),
        "assert_eq" | "assert_ne" => {
            args.exprs.len() >= 2
                && is_const_bound_expr(&args.exprs[0])
                && is_const_bound_expr(&args.exprs[1])
        }
        _ => false,
    }
}

pub(crate) fn lift_const_bound_assertion(
    expr: &Expr,
    scope: &TemporalScope,
    factory_audits: Option<&FactoryAuditLog>,
) -> Option<AssertionEntry> {
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    let name = mac.path.segments.last()?.ident.to_string();
    let args = parse_macro_args(mac.tokens.clone()).ok()?;
    let floats = FloatWidthScope::new();
    match name.as_str() {
        "assert" => {
            let expr = args.exprs.first()?;
            is_const_bound_expr(expr)
                .then(|| lower_assert_condition(expr, scope, &floats, factory_audits).ok())?
        }
        "assert_eq" if args.exprs.len() >= 2 => (is_const_bound_expr(&args.exprs[0])
            && is_const_bound_expr(&args.exprs[1]))
        .then(|| {
            lower_assert_eq(
                &args.exprs[0],
                &args.exprs[1],
                scope,
                &floats,
                factory_audits,
            )
            .ok()
        })?,
        "assert_ne" if args.exprs.len() >= 2 => (is_const_bound_expr(&args.exprs[0])
            && is_const_bound_expr(&args.exprs[1]))
        .then(|| lower_assert_ne(&args.exprs[0], &args.exprs[1], scope, factory_audits).ok())?,
        _ => None,
    }
}

fn is_const_bound_expr(expr: &Expr) -> bool {
    match expr {
        Expr::Paren(paren) => is_const_bound_expr(&paren.expr),
        Expr::Group(group) => is_const_bound_expr(&group.expr),
        Expr::Lit(_) => true,
        Expr::Path(path) => path.qself.is_none() && is_const_bound_path(&path.path),
        Expr::Binary(binary) => {
            is_const_bound_binop(&binary.op)
                && is_const_bound_expr(&binary.left)
                && is_const_bound_expr(&binary.right)
        }
        Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_) | UnOp::Neg(_)) => {
            is_const_bound_expr(&unary.expr)
        }
        Expr::Cast(cast) => {
            is_const_bound_expr(&cast.expr)
                && (matches!(cast.ty.as_ref(), Type::Infer(_))
                    || scalar_cast_type_key(&cast.ty).is_some())
        }
        Expr::Const(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(tail, None)] => is_const_bound_expr(tail),
            _ => false,
        },
        _ => false,
    }
}

fn is_const_bound_binop(op: &BinOp) -> bool {
    matches!(
        op,
        BinOp::Add(_)
            | BinOp::Sub(_)
            | BinOp::Mul(_)
            | BinOp::Div(_)
            | BinOp::Rem(_)
            | BinOp::BitAnd(_)
            | BinOp::BitOr(_)
            | BinOp::BitXor(_)
            | BinOp::Shl(_)
            | BinOp::Shr(_)
            | BinOp::Eq(_)
            | BinOp::Ne(_)
            | BinOp::Lt(_)
            | BinOp::Le(_)
            | BinOp::Gt(_)
            | BinOp::Ge(_)
            | BinOp::And(_)
            | BinOp::Or(_)
    )
}

fn is_const_bound_path(path: &syn::Path) -> bool {
    if path.segments.is_empty() {
        return false;
    }
    let mut segments = path.segments.iter();
    let first = segments.next().expect("non-empty path");
    if first.ident == "Self" && path.segments.len() > 1 {
        return path.segments.last().is_some_and(|seg| {
            matches!(seg.arguments, syn::PathArguments::None) && is_const_like_ident(&seg.ident)
        });
    }
    path.segments.iter().all(|seg| {
        matches!(seg.arguments, syn::PathArguments::None)
            && (is_const_like_ident(&seg.ident) || primitive_namespace(&seg.ident))
    }) && path
        .segments
        .last()
        .is_some_and(|seg| is_const_like_ident(&seg.ident))
}

fn primitive_namespace(ident: &syn::Ident) -> bool {
    matches!(
        ident.to_string().as_str(),
        "usize"
            | "isize"
            | "u8"
            | "u16"
            | "u32"
            | "u64"
            | "u128"
            | "i8"
            | "i16"
            | "i32"
            | "i64"
            | "i128"
            | "bool"
            | "char"
    )
}

fn is_const_like_ident(ident: &syn::Ident) -> bool {
    let ident = ident.to_string();
    ident.chars().any(|ch| ch.is_ascii_uppercase())
        && ident
            .chars()
            .all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit() || ch == '_')
}
