// SPDX-License-Identifier: Apache-2.0
//
// `TryMapSugar`: std `array::try_map(path_fn)` over a literal array when the
// source function returns an exact `Option` value. This owns the literal
// stdlib surface; closure/ZST/non-Option forms stay unclaimed so the accounting
// report keeps surfacing the next honest gap.

use std::{collections::BTreeMap, rc::Rc};

use sugar_ir_symbolic::{make_var, num, str_const, ConstValue, Sort, Term};
use syn::{Expr, ExprClosure};

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::monadic;
use crate::sugar::unit_path::unit_path_literal_name;
use crate::{
    canonical_term_sig, const_eval, const_eval_option_closure, const_path_key, primitive_int_term,
    repeat_count_literal, resolve_value_call_inline, strip_refs_groups, u128_term, ConstVal,
    Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("try_map", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "try_map" || call.args.len() != 1 {
        return None;
    }
    if !is_literal_array_receiver(&call.receiver) {
        return None;
    }
    let func = TryMapFunc::from_arg(strip_refs_groups(&call.args[0]), fcx)?;
    Some(Box::new(TryMapSugar {
        receiver: SugarBody::composite(&call.receiver, fcx),
        func,
    }))
}

struct TryMapSugar {
    receiver: SugarBody<CompositeFloor>,
    func: TryMapFunc,
}

#[derive(Clone)]
enum TryMapFunc {
    Path(Expr),
    Closure(ExprClosure),
}

impl TryMapFunc {
    fn from_arg(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Self> {
        if let Some(name) = simple_fn_name(expr) {
            if fcx.scope().has_visible_fn(&name) {
                return Some(Self::Path(expr.clone()));
            }
        }
        if let Expr::Closure(closure) = expr {
            return Some(Self::Closure(closure.clone()));
        }
        None
    }

    fn token(&self) -> String {
        match self {
            Self::Path(expr) => crate::token_key(expr),
            Self::Closure(closure) => crate::token_key(&Expr::Closure(closure.clone())),
        }
    }
}

impl Sugar for TryMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_try_map(&self.receiver, &self.func, ctx)
    }
}

fn reduce_try_map(
    receiver: &SugarBody<CompositeFloor>,
    func: &TryMapFunc,
    ctx: &SugarCtx,
) -> Outcome {
    let seq = match receiver.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .unwrap_or_else(|| try_map_gap("try_map receiver reduced to non-sequence")),
        Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
    };
    let values = seq
        .iter()
        .map(|elem| {
            elem.value
                .clone()
                .unwrap_or_else(|| try_map_gap("try_map receiver element was not literal"))
        })
        .collect::<Vec<_>>();
    let mut mapped = Vec::with_capacity(values.len());
    for (index, value) in values.iter().enumerate() {
        match eval_option_function(func, value, ctx)
            .unwrap_or_else(|| try_map_gap("try_map function did not reduce to Option"))
        {
            Some(value) => mapped.push(value),
            None => {
                tracing::debug!(
                    target: "sugar_lift_rust_tests::sugar::try_map",
                    func = %func.token(),
                    index,
                    "literal array try_map short-circuited to None"
                );
                return Outcome::Complete(Desugared::Term(monadic::none_term()));
            }
        }
    }
    let array_term = literal_array_term_from_values(&mapped)
        .unwrap_or_else(|| try_map_gap("try_map result did not materialize as literal array"));
    tracing::debug!(
        target: "sugar_lift_rust_tests::sugar::try_map",
        len = mapped.len(),
        func = %func.token(),
        "literal array try_map reduced to Some(array)"
    );
    Outcome::Complete(Desugared::Term(monadic::some_term(array_term)))
}

fn try_map_gap(reason: &str) -> ! {
    panic!("try_map did not reach a lawful floor: {reason}")
}

fn is_literal_array_receiver(expr: &Expr) -> bool {
    match strip_refs_groups(expr) {
        Expr::Array(_) => true,
        Expr::Repeat(repeat) => repeat_count_literal(&repeat.len).is_some(),
        _ => false,
    }
}

fn literal_receiver_values(expr: &Expr) -> Option<Vec<ConstVal>> {
    match strip_refs_groups(expr) {
        Expr::Array(array) => array.elems.iter().map(const_value_expr).collect(),
        Expr::Repeat(repeat) => {
            let count = repeat_count_literal(&repeat.len)?;
            const MAX_REPEAT: usize = 4096;
            if count > MAX_REPEAT {
                return None;
            }
            let value = const_value_expr(&repeat.expr)?;
            Some(std::iter::repeat_n(value, count).collect())
        }
        _ => None,
    }
}

fn literal_array_term_from_values(values: &[ConstVal]) -> Option<Rc<Term>> {
    let terms = values
        .iter()
        .map(const_val_term)
        .collect::<Option<Vec<_>>>()?;
    let inner = terms
        .iter()
        .map(|term| canonical_term_sig(term))
        .collect::<Vec<_>>()
        .join(",");
    Some(make_var(format!("literal:Array({inner})")))
}

fn const_val_term(value: &ConstVal) -> Option<Rc<Term>> {
    match value {
        ConstVal::Int(n) => Some(num(*n)),
        ConstVal::PrimitiveInt { raw, kind } => primitive_int_term(*raw, *kind),
        ConstVal::UInt128(n) => Some(u128_term(*n)),
        ConstVal::Bool(b) => Some(Rc::new(Term::Const {
            value: ConstValue::Bool(*b),
            sort: Sort::bool(),
        })),
        ConstVal::Char(c) => Some(str_const(c.to_string())),
        ConstVal::UnitPath(path) => Some(make_var(unit_path_literal_name(path))),
        ConstVal::Tuple(parts) => {
            let terms = parts
                .iter()
                .map(const_val_term)
                .collect::<Option<Vec<_>>>()?;
            let inner = terms
                .iter()
                .map(|term| canonical_term_sig(term))
                .collect::<Vec<_>>()
                .join(",");
            Some(make_var(format!("literal:Tuple({inner})")))
        }
    }
}

fn eval_option_function(
    func: &TryMapFunc,
    arg: &ConstVal,
    ctx: &SugarCtx,
) -> Option<Option<ConstVal>> {
    match func {
        TryMapFunc::Path(func) => {
            let resolved =
                resolve_value_call_inline(func, &[arg.to_expr()?], ctx.scope, ctx.options)?;
            eval_option_expr(&resolved, &BTreeMap::new())
        }
        TryMapFunc::Closure(closure) => const_eval_option_closure(closure, arg),
    }
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

fn const_value_expr(expr: &Expr) -> Option<ConstVal> {
    const_value_expr_with_env(expr, &BTreeMap::new())
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

fn simple_fn_name(expr: &Expr) -> Option<String> {
    let Expr::Path(path) = expr else {
        return None;
    };
    if path.qself.is_some() {
        return None;
    }
    path.path.get_ident().map(ToString::to_string)
}
