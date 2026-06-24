// SPDX-License-Identifier: Apache-2.0
//
// `TryFromFnSugar`: std/core `array::try_from_fn::<_, N, _>(path_fn)` where
// the const length is literal and the source function returns an exact `Option`.
// This owns the literal stdlib constructor surface; non-literal lengths,
// closures, and non-Option bodies stay unclaimed so accounting reports the next
// real gap.

use std::collections::BTreeMap;

use syn::{Expr, GenericArgument, Path, PathArguments};

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::monadic;
use crate::{
    const_eval, const_path_key, literal_aggregate_term_in_scope, parse_int_lit,
    resolve_value_call_inline, strip_refs_groups, ConstVal, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("try_from_fn", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Call(call) = expr else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    if path.qself.is_some() || !is_array_try_from_fn_path(&path.path) {
        return None;
    }
    let len = literal_array_len(&path.path)?;
    let func = strip_refs_groups(&call.args[0]);
    let name = simple_fn_name(func)?;
    if !fcx.scope().has_visible_fn(&name) {
        return None;
    }
    Some(Box::new(TryFromFnSugar {
        source_site: TryFromFnSource::new(expr.clone()),
        len,
        func: func.clone(),
    }))
}

struct TryFromFnSource {
    expr: Expr,
}

impl TryFromFnSource {
    fn new(expr: Expr) -> Self {
        Self { expr }
    }
}

struct TryFromFnSugar {
    source_site: TryFromFnSource,
    len: usize,
    func: Expr,
}

impl Sugar for TryFromFnSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::Complete(
            reduce_try_from_fn(&self.source_site.expr, self.len, &self.func, ctx)
                .unwrap_or_else(|| try_from_fn_gap("try_from_fn did not reduce to a monadic term")),
        )
    }
}

fn reduce_try_from_fn(source: &Expr, len: usize, func: &Expr, ctx: &SugarCtx) -> Option<Desugared> {
    let mut mapped = Vec::with_capacity(len);
    for index in 0..len {
        let arg = ConstVal::Int(i128::try_from(index).ok()?).to_expr()?;
        match eval_option_function(func, arg, ctx)? {
            Some(value) => mapped.push(value.to_expr()?),
            None => {
                tracing::debug!(
                    target: "sugar_lift_rust_tests::sugar::try_from_fn",
                    func = %crate::token_key(func),
                    index,
                    "literal array try_from_fn short-circuited to None"
                );
                return Some(Desugared::Term(monadic::none_term()));
            }
        }
    }
    let array_term =
        literal_aggregate_term_in_scope("Array", mapped.iter(), source, ctx.scope).ok()?;
    tracing::debug!(
        target: "sugar_lift_rust_tests::sugar::try_from_fn",
        len,
        func = %crate::token_key(func),
        "literal array try_from_fn reduced to Some(array)"
    );
    Some(Desugared::Term(monadic::some_term(array_term)))
}

fn try_from_fn_gap(reason: &str) -> ! {
    panic!("{reason}")
}

fn eval_option_function(func: &Expr, arg: Expr, ctx: &SugarCtx) -> Option<Option<ConstVal>> {
    let resolved = resolve_value_call_inline(func, &[arg], ctx.scope, ctx.options)?;
    eval_option_expr(&resolved, &BTreeMap::new())
}

fn eval_option_expr(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<Option<ConstVal>> {
    match expr {
        Expr::Paren(p) => eval_option_expr(&p.expr, env),
        Expr::Group(g) => eval_option_expr(&g.expr, env),
        Expr::Reference(r) => eval_option_expr(&r.expr, env),
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(expr, None)] => eval_option_expr(expr, env),
            _ => None,
        },
        Expr::Path(path) if path.path.segments.last()?.ident == "None" => Some(None),
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = &*call.func else {
                return None;
            };
            if path.path.segments.last()?.ident != "Some" {
                return None;
            }
            Some(Some(const_value_expr_with_env(&call.args[0], env)?))
        }
        Expr::MethodCall(call) if call.method == "checked_mul" && call.args.len() == 1 => {
            checked_mul_usize(
                const_value_expr_with_env(&call.receiver, env)?.as_int()?,
                const_value_expr_with_env(&call.args[0], env)?.as_int()?,
            )
        }
        _ => None,
    }
}

fn checked_mul_usize(lhs: i128, rhs: i128) -> Option<Option<ConstVal>> {
    let lhs = usize_domain(lhs)?;
    let rhs = usize_domain(rhs)?;
    let product = lhs.checked_mul(rhs)?;
    if product > usize::MAX as u128 {
        Some(None)
    } else {
        Some(Some(ConstVal::Int(product as i128)))
    }
}

fn usize_domain(value: i128) -> Option<u128> {
    if value < 0 || value > usize::MAX as i128 {
        return None;
    }
    Some(value as u128)
}

fn const_value_expr_with_env(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<ConstVal> {
    match expr {
        Expr::Path(path) => match const_path_key(&path.path)?.as_str() {
            "usize::MAX" => Some(ConstVal::Int(usize::MAX as i128)),
            name => env.get(name).cloned(),
        },
        Expr::Paren(p) => const_value_expr_with_env(&p.expr, env),
        Expr::Group(g) => const_value_expr_with_env(&g.expr, env),
        Expr::Reference(r) => const_value_expr_with_env(&r.expr, env),
        other => const_eval(other, env),
    }
}

fn is_array_try_from_fn_path(path: &Path) -> bool {
    let mut segments = path.segments.iter().rev();
    let Some(last) = segments.next() else {
        return false;
    };
    if last.ident != "try_from_fn" {
        return false;
    }
    matches!(segments.next(), Some(segment) if segment.ident == "array")
}

fn literal_array_len(path: &Path) -> Option<usize> {
    let last = path.segments.last()?;
    let PathArguments::AngleBracketed(args) = &last.arguments else {
        return None;
    };
    let mut len = None;
    for arg in &args.args {
        let GenericArgument::Const(Expr::Lit(lit)) = arg else {
            continue;
        };
        let syn::Lit::Int(int) = &lit.lit else {
            continue;
        };
        let value = parse_int_lit(int).ok()?;
        if value < 0 {
            return None;
        }
        if len.replace(usize::try_from(value).ok()?).is_some() {
            return None;
        }
    }
    len
}

fn simple_fn_name(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = expr else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    path.path.get_ident().map(ToString::to_string)
}
