// SPDX-License-Identifier: Apache-2.0
//
// `CollectSugar`: `collect::<Vec<_>>()`, plus `collect::<Option<Vec<_>>>()` /
// `collect::<Result<Vec<_>, _>>()` over a finite literal sequence whose final `.map`
// closure constructs `Some`/`None` or `Ok`/`Err`. This is stdlib collection sugar over
// a source-constructed domain: plain `Vec` materializes every element; `Option` /
// `Result` short-circuit on the first `None` / `Err`.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, num, str_const, ConstValue, Sort, Term};
use syn::{Expr, ExprClosure, GenericArgument, Type};
use tracing::debug;

use crate::sugar::factory::{build_composite, CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::sugar::unit_path::unit_path_literal_name;
use crate::{
    canonical_term_sig, closure_single_param_ident, const_eval, primitive_int_term,
    strip_refs_groups, u128_term, ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar,
    SugarCtx,
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
    if let Some(plan) = CollectPlan::runtime_callable_from_receiver(&call.receiver, fcx) {
        return Some(Box::new(CollectSugar { plan }));
    }
    if !crate::resolves_literal_sequence_in_scope(&call.receiver, fcx) {
        return None;
    }
    let map_plan = CollectPlan::from_receiver(&call.receiver, fcx);
    let plan = if collects_vec(call) && map_plan.is_none() {
        CollectPlan::PlainVec {
            base: sequence_body(&call.receiver, fcx),
        }
    } else if let Some(plan) = map_plan {
        plan
    } else {
        CollectPlan::runtime_callable_from_receiver(&call.receiver, fcx)?
    };
    debug!(
        target: "sugar_lift_rust_tests::sugar::collect",
        receiver = %crate::token_key(&call.receiver),
        "recognized collect"
    );
    Some(Box::new(CollectSugar { plan }))
}

struct CollectSugar {
    plan: CollectPlan,
}

enum CollectPlan {
    PlainVec {
        base: SugarBody<CompositeFloor>,
    },
    MapMonadic {
        base: SugarBody<CompositeFloor>,
        closure: ExprClosure,
        kind: CollectKind,
    },
    RuntimeCallableMap {
        boundary: String,
        reason: String,
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
            base: sequence_body(&call.receiver, fcx),
            closure: closure.clone(),
            kind,
        })
    }

    fn runtime_callable_from_receiver(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Self> {
        let kind = expected_collect_kind(fcx)?;
        let Expr::MethodCall(call) = strip_refs_groups(expr) else {
            return None;
        };
        if call.method != "map" || call.args.len() != 1 {
            return None;
        }
        method_family::literal_sequence_static_len_in_scope(
            &call.receiver,
            fcx.let_inits(),
            fcx.scope(),
        )?;
        let Expr::Closure(_) = strip_refs_groups(&call.args[0]) else {
            return None;
        };
        if !crate::closure_body_calls_through_param(&call.args[0]) {
            return None;
        }
        let domain = crate::token_key(&call.receiver);
        let boundary = crate::token_key(expr);
        let kind = match kind {
            CollectKind::Option => "Option",
            CollectKind::Result => "Result",
        };
        Some(Self::RuntimeCallableMap {
            boundary,
            reason: format!(
                "iterator/option adaptor `.map(|..| ..).collect::<{kind}<Vec<_>>` over {domain} whose closure body \
                 performs a runtime call through closure body parameter (bin-2: dynamic \
                 callable element, not constructed from source literals); refused"
            ),
        })
    }

    fn reduce(&self, ctx: &SugarCtx) -> Result<Option<Rc<Term>>, Effect> {
        match self {
            CollectPlan::PlainVec { base } => {
                let seq = sequence_from_body(base, ctx)?;
                let collected = seq.iter().map(elem_term).collect::<Vec<_>>();
                debug!(
                    target: "sugar_lift_rust_tests::sugar::collect",
                    len = collected.len(),
                    "literal Vec collect reduced"
                );
                Ok(Some(literal_vec_term(&collected)))
            }
            CollectPlan::MapMonadic {
                base,
                closure,
                kind,
            } => {
                let seq = sequence_from_body(base, ctx)?;
                let mut collected = Vec::with_capacity(seq.len());
                for elem in seq {
                    let Some(value) = elem.value.as_ref() else {
                        return Ok(None);
                    };
                    let Some(monadic_value) = eval_monadic_closure(closure, value) else {
                        return Ok(None);
                    };
                    match (*kind, monadic_value) {
                        (CollectKind::Option, MonadicValue::Option(Some(term))) => {
                            collected.push(term)
                        }
                        (CollectKind::Option, MonadicValue::Option(None)) => {
                            debug!(
                                target: "sugar_lift_rust_tests::sugar::collect",
                                "literal Option collect short-circuited to None"
                            );
                            return Ok(Some(monadic::none_term()));
                        }
                        (CollectKind::Result, MonadicValue::Result(Ok(term))) => {
                            collected.push(term)
                        }
                        (CollectKind::Result, MonadicValue::Result(Err(term))) => {
                            debug!(
                                target: "sugar_lift_rust_tests::sugar::collect",
                                "literal Result collect short-circuited to Err"
                            );
                            return Ok(Some(monadic::err_term(term)));
                        }
                        _ => return Ok(None),
                    }
                }
                let vec = literal_vec_term(&collected);
                debug!(
                    target: "sugar_lift_rust_tests::sugar::collect",
                    len = collected.len(),
                    kind = ?kind,
                    "literal monadic collect reduced"
                );
                Ok(Some(match kind {
                    CollectKind::Option => monadic::some_term(vec),
                    CollectKind::Result => monadic::ok_term(vec),
                }))
            }
            CollectPlan::RuntimeCallableMap { boundary, reason } => {
                Err(Effect::RuntimeCallableElement {
                    boundary: boundary.clone(),
                    reason: reason.clone(),
                })
            }
        }
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
) -> Result<Vec<DesugaredElem>, Effect> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d.into_seq().unwrap_or_else(|| {
            collect_gap("recognized collect receiver reduced to a non-sequence floor")
        })),
        Outcome::Incomplete(effect) => Err(effect),
    }
}

impl Sugar for CollectSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.plan.reduce(ctx) {
            Ok(Some(term)) => Outcome::Complete(Desugared::Term(term)),
            Ok(None) => collect_gap("recognized collect chain did not reduce to a literal floor"),
            Err(effect) => Outcome::Incomplete(effect),
        }
    }
}

fn collect_gap(reason: &str) -> ! {
    panic!("collect did not reach a lawful sequence floor: {reason}")
}

pub(crate) fn collects_vec(call: &syn::ExprMethodCall) -> bool {
    let Some(turbofish) = &call.turbofish else {
        return false;
    };
    if turbofish.args.len() != 1 {
        return false;
    }
    matches!(
        turbofish.args.first(),
        Some(GenericArgument::Type(Type::Path(path)))
            if path.qself.is_none()
                && path.path.segments.iter().any(|seg| seg.ident == "Vec")
    )
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

fn expected_collect_kind(fcx: &SugarBuildCtx) -> Option<CollectKind> {
    let ty = fcx.expected_type()?;
    if ty.starts_with("Option") && ty.contains("Vec") {
        Some(CollectKind::Option)
    } else if ty.starts_with("Result") && ty.contains("Vec") {
        Some(CollectKind::Result)
    } else {
        None
    }
}

fn elem_term(elem: &DesugaredElem) -> Rc<Term> {
    elem.value
        .as_ref()
        .and_then(const_val_term)
        .unwrap_or_else(|| {
            panic!("collect sequence element did not dispatch to a literal term floor")
        })
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
        ConstVal::Array(parts) => {
            let terms = parts
                .iter()
                .map(const_val_term)
                .collect::<Option<Vec<_>>>()?;
            Some(literal_vec_term(&terms))
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
