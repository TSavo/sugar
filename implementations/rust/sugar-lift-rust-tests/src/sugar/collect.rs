// SPDX-License-Identifier: Apache-2.0
//
// `CollectSugar`: `collect::<Option<Vec<_>>>()` / `collect::<Result<Vec<_>, _>>()`
// over a finite literal sequence whose final `.map` closure constructs `Some`/`None`
// or `Ok`/`Err`. This is stdlib short-circuit sugar over a source-constructed domain:
// all `Some` -> `Some(Vec(..))`, first `None` -> `None`; all `Ok` -> `Ok(Vec(..))`,
// first `Err(e)` -> `Err(e)`.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, num, str_const, ConstValue, Sort, Term};
use syn::{Expr, ExprClosure};
use tracing::debug;

use crate::sugar::factory::{build_composite, SugarBuildCtx};
use crate::sugar::method;
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::sugar::unit_path::unit_path_literal_name;
use crate::{
    canonical_term_sig, closure_single_param_ident, const_eval, const_fold_int_term,
    primitive_int_term, strip_refs_groups, term_as_int, u128_term, BoundedDomain, ConstVal,
    Desugared, DesugaredElem, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("collect", recognize);

pub(crate) fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "collect" || !call.args.is_empty() {
        return None;
    }
    if !method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits()) {
        return None;
    }
    let Some(plan) = CollectPlan::from_receiver(&call.receiver, fcx) else {
        return None;
    };
    let fallback = method::recognize(expr, fcx)?;
    debug!(
        target: "sugar_lift_rust_tests::sugar::collect",
        receiver = %crate::token_key(&call.receiver),
        "recognized literal monadic collect"
    );
    Some(Box::new(CollectSugar { plan, fallback }))
}

struct CollectSugar {
    plan: CollectPlan,
    fallback: Box<dyn Sugar>,
}

enum CollectPlan {
    MapMonadic {
        base: Box<dyn Sugar>,
        base_expr: Expr,
        closure: ExprClosure,
        kind: CollectKind,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CollectKind {
    Option,
    Result,
}

enum MonadicValue {
    Option(Option<Rc<Term>>),
    Result(Result<Rc<Term>, Rc<Term>>),
}

impl CollectPlan {
    fn from_receiver(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Self> {
        let Expr::MethodCall(call) = strip_refs_groups(expr) else {
            return None;
        };
        if call.method != "map" || call.args.len() != 1 {
            return None;
        }
        let Expr::Closure(closure) = strip_refs_groups(&call.args[0]) else {
            return None;
        };
        let kind = monadic_kind_of_closure(closure)?;
        Some(Self::MapMonadic {
            base: build_composite(&call.receiver, fcx),
            base_expr: (*call.receiver).clone(),
            closure: closure.clone(),
            kind,
        })
    }

    fn reduce(&self, ctx: &SugarCtx) -> Option<Rc<Term>> {
        match self {
            CollectPlan::MapMonadic {
                base,
                base_expr,
                closure,
                kind,
            } => {
                let seq = match base.desugar(ctx) {
                    Outcome::Dug(d) => d.into_seq()?,
                    Outcome::Hit(_) => empty_literal_sequence(base_expr, ctx)?,
                };
                let mut collected = Vec::with_capacity(seq.len());
                for elem in seq {
                    let value = elem.value.as_ref()?;
                    match (*kind, eval_monadic_closure(closure, value)?) {
                        (CollectKind::Option, MonadicValue::Option(Some(term))) => {
                            collected.push(term)
                        }
                        (CollectKind::Option, MonadicValue::Option(None)) => {
                            debug!(
                                target: "sugar_lift_rust_tests::sugar::collect",
                                "literal Option collect short-circuited to None"
                            );
                            return Some(monadic::none_term());
                        }
                        (CollectKind::Result, MonadicValue::Result(Ok(term))) => {
                            collected.push(term)
                        }
                        (CollectKind::Result, MonadicValue::Result(Err(term))) => {
                            debug!(
                                target: "sugar_lift_rust_tests::sugar::collect",
                                "literal Result collect short-circuited to Err"
                            );
                            return Some(monadic::err_term(term));
                        }
                        _ => return None,
                    }
                }
                let vec = literal_vec_term(&collected);
                debug!(
                    target: "sugar_lift_rust_tests::sugar::collect",
                    len = collected.len(),
                    kind = ?kind,
                    "literal monadic collect reduced"
                );
                Some(match kind {
                    CollectKind::Option => monadic::some_term(vec),
                    CollectKind::Result => monadic::ok_term(vec),
                })
            }
        }
    }
}

fn empty_literal_sequence(expr: &Expr, ctx: &SugarCtx) -> Option<Vec<DesugaredElem>> {
    match strip_refs_groups(expr) {
        Expr::Array(arr) if arr.elems.is_empty() => Some(Vec::new()),
        Expr::Range(_) => {
            let BoundedDomain::Range {
                start,
                end,
                inclusive,
            } = crate::bounded_domain_from_expr(expr, ctx.scope)?
            else {
                return None;
            };
            let s = term_as_int(&start).or_else(|| const_fold_int_term(&start))?;
            let e = term_as_int(&end).or_else(|| const_fold_int_term(&end))?;
            let end_exclusive = if inclusive { e.checked_add(1)? } else { e };
            (end_exclusive <= s).then(Vec::new)
        }
        _ => None,
    }
}

impl Sugar for CollectSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.plan.reduce(ctx) {
            Some(term) => Outcome::Dug(Desugared::Term(term)),
            None => self.fallback.desugar(ctx),
        }
    }
}

fn monadic_kind_of_closure(closure: &ExprClosure) -> Option<CollectKind> {
    let body = closure_body_expr(closure)?;
    monadic_kind_of_expr(body)
}

fn monadic_kind_of_expr(expr: &Expr) -> Option<CollectKind> {
    match strip_refs_groups(expr) {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(expr, None)] => monadic_kind_of_expr(expr),
            _ => None,
        },
        Expr::Path(path) if path_ends_with(&path.path, "None") => Some(CollectKind::Option),
        Expr::Call(call) => {
            let Expr::Path(func) = strip_refs_groups(&call.func) else {
                return None;
            };
            if call.args.len() != 1 {
                return None;
            }
            if path_ends_with(&func.path, "Some") {
                Some(CollectKind::Option)
            } else if path_ends_with(&func.path, "Ok") || path_ends_with(&func.path, "Err") {
                Some(CollectKind::Result)
            } else {
                None
            }
        }
        Expr::If(if_expr) => {
            let then_kind = match if_expr.then_branch.stmts.as_slice() {
                [syn::Stmt::Expr(expr, None)] => monadic_kind_of_expr(expr)?,
                _ => return None,
            };
            let else_kind = if_expr
                .else_branch
                .as_ref()
                .and_then(|(_, expr)| monadic_kind_of_expr(expr))?;
            (then_kind == else_kind).then_some(then_kind)
        }
        _ => None,
    }
}

fn eval_monadic_closure(closure: &ExprClosure, arg: &ConstVal) -> Option<MonadicValue> {
    if closure.inputs.len() != 1 {
        return None;
    }
    let param = closure_single_param_ident(&closure.inputs[0])?;
    let mut env = BTreeMap::new();
    env.insert(param, arg.clone());
    let body = closure_body_expr(closure)?;
    eval_monadic_expr(body, &env)
}

fn eval_monadic_expr(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<MonadicValue> {
    match strip_refs_groups(expr) {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(expr, None)] => eval_monadic_expr(expr, env),
            _ => None,
        },
        Expr::Path(path) if path_ends_with(&path.path, "None") => Some(MonadicValue::Option(None)),
        Expr::Call(call) => {
            let Expr::Path(func) = strip_refs_groups(&call.func) else {
                return None;
            };
            if call.args.len() != 1 {
                return None;
            }
            let inner = const_val_term(&const_eval(&call.args[0], env)?)?;
            if path_ends_with(&func.path, "Some") {
                Some(MonadicValue::Option(Some(inner)))
            } else if path_ends_with(&func.path, "Ok") {
                Some(MonadicValue::Result(Ok(inner)))
            } else if path_ends_with(&func.path, "Err") {
                Some(MonadicValue::Result(Err(inner)))
            } else {
                None
            }
        }
        Expr::If(if_expr) => {
            let cond = const_eval(&if_expr.cond, env)?.as_bool()?;
            if cond {
                match if_expr.then_branch.stmts.as_slice() {
                    [syn::Stmt::Expr(expr, None)] => eval_monadic_expr(expr, env),
                    _ => None,
                }
            } else {
                let else_branch = if_expr.else_branch.as_ref()?;
                eval_monadic_expr(&else_branch.1, env)
            }
        }
        _ => None,
    }
}

fn closure_body_expr(closure: &ExprClosure) -> Option<&Expr> {
    match &*closure.body {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(expr, None)] => Some(expr),
            _ => None,
        },
        other => Some(other),
    }
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

pub(crate) fn literal_vec_term(elems: &[Rc<Term>]) -> Rc<Term> {
    let inner = elems
        .iter()
        .map(|term| canonical_term_sig(term))
        .collect::<Vec<_>>()
        .join(",");
    make_var(format!("literal:Vec({inner})"))
}

fn path_ends_with(path: &syn::Path, name: &str) -> bool {
    path.segments.last().is_some_and(|seg| seg.ident == name)
}
