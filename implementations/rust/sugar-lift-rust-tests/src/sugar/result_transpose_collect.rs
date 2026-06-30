// SPDX-License-Identifier: Apache-2.0
//
// `ResultTransposeCollectSugar`: stdlib
// `.map(|x| -> Result<Option<T>, E> { ... }).filter_map(Result::transpose).collect()`
// over a finite literal sequence. This is the Result/Option transpose pipeline:
// `Ok(Some(v))` contributes `Ok(v)`, `Ok(None)` contributes no element, and the first
// `Err(e)` short-circuits the final `collect::<Result<Vec<_>, _>>()` to `Err(e)`.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{make_var, num, str_const, ConstValue, Sort, Term};
use syn::{Expr, ExprClosure, Pat, Stmt};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::collect::literal_vec_term;
use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::sugar::unit_path::unit_path_literal_name;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    const_eval, primitive_int_term, resolve_value_call_inline, strip_refs_groups, u128_term,
    ConstVal, Desugared, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("result_transpose_collect", SugarRole::Term, recognize);

pub(crate) fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(collect) = expr else {
        return None;
    };
    if collect.method != "collect" || !collect.args.is_empty() {
        return None;
    }

    let Expr::MethodCall(filter_map) = strip_refs_groups(&collect.receiver) else {
        return None;
    };
    if filter_map.method != "filter_map" || filter_map.args.len() != 1 {
        return None;
    }
    if !is_result_transpose(&filter_map.args[0]) {
        return None;
    }

    let Expr::MethodCall(map) = strip_refs_groups(&filter_map.receiver) else {
        return None;
    };
    if map.method != "map" || map.args.len() != 1 {
        return None;
    }
    let Expr::Closure(closure) = strip_refs_groups(&map.args[0]) else {
        return None;
    };
    if !method_family::resolves_literal_sequence(&map.receiver, fcx.let_inits()) {
        return None;
    }

    Some(Box::new(ResultTransposeCollectSugar {
        base: SugarBody::from_node(method_family::build_literal_sequence_composite(
            &map.receiver,
            fcx,
        )?),
        mapper: ResultTransposeClosure {
            raw: closure.clone(),
        },
    }))
}

struct ResultTransposeCollectSugar {
    base: SugarBody<CompositeFloor>,
    mapper: ResultTransposeClosure,
}

struct ResultTransposeClosure {
    raw: ExprClosure,
}

impl Sugar for ResultTransposeCollectSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let seq = match self.base.reduce(ctx) {
            Outcome::Complete(desugared) => desugared
                .into_seq()
                .unwrap_or_else(|| result_transpose_collect_gap("base completed as non-sequence")),
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let mut kept = Vec::new();
        for (index, elem) in seq.into_iter().enumerate() {
            let Some(value) = elem.value.as_ref() else {
                result_transpose_collect_gap("sequence element did not carry a literal value");
            };
            match eval_result_option_closure(&self.mapper.raw, value, ctx) {
                Some(ResultOptionValue::Ok(Some(value))) => {
                    let Some(term) = value_term(&value) else {
                        result_transpose_collect_gap("closure value did not reduce to a term");
                    };
                    kept.push(term);
                }
                Some(ResultOptionValue::Ok(None)) => {}
                Some(ResultOptionValue::Err(err)) => {
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::result_transpose_collect",
                        index,
                        "Result transpose/filter_map collect short-circuited to Err"
                    );
                    return Outcome::Complete(Desugared::Term(monadic::err_term(err)));
                }
                None => result_transpose_collect_gap(
                    "recognized transpose/filter_map closure did not reduce to a literal result",
                ),
            }
        }
        debug!(
            target: "sugar_lift_rust_tests::sugar::result_transpose_collect",
            len = kept.len(),
            "Result transpose/filter_map collect reduced to Ok(Vec)"
        );
        Outcome::Complete(Desugared::Term(monadic::ok_term(literal_vec_term(&kept))))
    }
}

fn result_transpose_collect_gap(reason: &str) -> ! {
    panic!("result_transpose_collect did not reach a lawful literal floor: {reason}")
}

enum ResultOptionValue {
    Ok(Option<ConstVal>),
    Err(Rc<Term>),
}

enum ResultValue {
    Ok(ConstVal),
    Err(Rc<Term>),
}

fn eval_result_option_closure(
    closure: &ExprClosure,
    arg: &ConstVal,
    ctx: &SugarCtx,
) -> Option<ResultOptionValue> {
    if closure.inputs.len() != 1 {
        return None;
    }
    let mut env = BTreeMap::new();
    bind_arg(closure.inputs.first()?, arg, &mut env)?;
    match &*closure.body {
        Expr::Block(block) => eval_result_option_block(&block.block.stmts, &mut env, ctx),
        expr => eval_result_option_expr(expr, &env, ctx),
    }
}

fn eval_result_option_block(
    stmts: &[Stmt],
    env: &mut BTreeMap<String, ConstVal>,
    ctx: &SugarCtx,
) -> Option<ResultOptionValue> {
    let (tail, leading) = stmts.split_last()?;
    for stmt in leading {
        let Stmt::Local(local) = stmt else {
            return None;
        };
        let name = simple_pat_name(&local.pat)?;
        let init = local.init.as_ref()?;
        if init.diverge.is_some() {
            return None;
        }
        let value = match strip_refs_groups(&init.expr) {
            Expr::Try(try_expr) => match eval_result_value_expr(&try_expr.expr, env, ctx)? {
                ResultValue::Ok(value) => value,
                ResultValue::Err(err) => return Some(ResultOptionValue::Err(err)),
            },
            expr => const_eval(expr, env)?,
        };
        env.insert(name, value);
    }

    match tail {
        Stmt::Expr(expr, None) => eval_result_option_expr(expr, env, ctx),
        _ => None,
    }
}

fn eval_result_option_expr(
    expr: &Expr,
    env: &BTreeMap<String, ConstVal>,
    ctx: &SugarCtx,
) -> Option<ResultOptionValue> {
    match strip_refs_groups(expr) {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [Stmt::Expr(expr, None)] => eval_result_option_expr(expr, env, ctx),
            _ => None,
        },
        Expr::If(if_expr) => {
            let cond = const_eval(&if_expr.cond, env)?.as_bool()?;
            if cond {
                match if_expr.then_branch.stmts.as_slice() {
                    [Stmt::Expr(expr, None)] => eval_result_option_expr(expr, env, ctx),
                    _ => None,
                }
            } else {
                let (_, else_expr) = if_expr.else_branch.as_ref()?;
                eval_result_option_expr(else_expr, env, ctx)
            }
        }
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return None;
            };
            if path_ends_with(&path.path, "Ok") {
                Some(ResultOptionValue::Ok(eval_option_expr(&call.args[0], env)?))
            } else if path_ends_with(&path.path, "Err") {
                let err = value_term(&const_eval(&call.args[0], env)?)?;
                Some(ResultOptionValue::Err(err))
            } else {
                None
            }
        }
        _ => None,
    }
}

fn eval_result_value_expr(
    expr: &Expr,
    env: &BTreeMap<String, ConstVal>,
    ctx: &SugarCtx,
) -> Option<ResultValue> {
    match strip_refs_groups(expr) {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [Stmt::Expr(expr, None)] => eval_result_value_expr(expr, env, ctx),
            _ => None,
        },
        Expr::If(if_expr) => {
            let cond = const_eval(&if_expr.cond, env)?.as_bool()?;
            if cond {
                match if_expr.then_branch.stmts.as_slice() {
                    [Stmt::Expr(expr, None)] => eval_result_value_expr(expr, env, ctx),
                    _ => None,
                }
            } else {
                let (_, else_expr) = if_expr.else_branch.as_ref()?;
                eval_result_value_expr(else_expr, env, ctx)
            }
        }
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return None;
            };
            if path_ends_with(&path.path, "Ok") {
                Some(ResultValue::Ok(const_eval(&call.args[0], env)?))
            } else if path_ends_with(&path.path, "Err") {
                let err = value_term(&const_eval(&call.args[0], env)?)?;
                Some(ResultValue::Err(err))
            } else {
                let args = call
                    .args
                    .iter()
                    .map(|arg| const_eval(arg, env)?.to_expr())
                    .collect::<Option<Vec<_>>>()?;
                let resolved =
                    resolve_value_call_inline(&call.func, &args, ctx.scope, ctx.options)?;
                eval_result_value_expr(&resolved, env, ctx)
            }
        }
        _ => None,
    }
}

fn eval_option_expr(expr: &Expr, env: &BTreeMap<String, ConstVal>) -> Option<Option<ConstVal>> {
    match strip_refs_groups(expr) {
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [Stmt::Expr(expr, None)] => eval_option_expr(expr, env),
            _ => None,
        },
        Expr::Path(path) if path_ends_with(&path.path, "None") => Some(None),
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return None;
            };
            if path_ends_with(&path.path, "Some") {
                Some(Some(const_eval(&call.args[0], env)?))
            } else {
                None
            }
        }
        Expr::If(if_expr) => {
            let cond = const_eval(&if_expr.cond, env)?.as_bool()?;
            if cond {
                match if_expr.then_branch.stmts.as_slice() {
                    [Stmt::Expr(expr, None)] => eval_option_expr(expr, env),
                    _ => None,
                }
            } else {
                let (_, else_expr) = if_expr.else_branch.as_ref()?;
                eval_option_expr(else_expr, env)
            }
        }
        _ => None,
    }
}

fn bind_arg(pat: &Pat, arg: &ConstVal, env: &mut BTreeMap<String, ConstVal>) -> Option<()> {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => {
            env.insert(ident.ident.to_string(), arg.clone());
            Some(())
        }
        Pat::Reference(reference) if reference.mutability.is_none() => {
            bind_arg(&reference.pat, arg, env)
        }
        Pat::Type(typed) => bind_arg(&typed.pat, arg, env),
        Pat::Paren(paren) => bind_arg(&paren.pat, arg, env),
        Pat::Wild(_) => Some(()),
        _ => None,
    }
}

fn simple_pat_name(pat: &Pat) -> Option<String> {
    match pat {
        Pat::Ident(ident) if ident.subpat.is_none() => Some(ident.ident.to_string()),
        Pat::Type(typed) => simple_pat_name(&typed.pat),
        Pat::Paren(paren) => simple_pat_name(&paren.pat),
        _ => None,
    }
}

fn value_term(value: &ConstVal) -> Option<Rc<Term>> {
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
        ConstVal::Tuple(_) => None,
        ConstVal::Array(_) => None,
        ConstVal::Struct { .. } => None,
    }
}

fn is_result_transpose(expr: &Expr) -> bool {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return false;
    };
    path.qself.is_none()
        && path.path.segments.len() >= 2
        && path_ends_with(&path.path, "transpose")
        && path
            .path
            .segments
            .iter()
            .any(|segment| segment.ident == "Result")
}

fn path_ends_with(path: &syn::Path, name: &str) -> bool {
    path.segments
        .last()
        .is_some_and(|segment| segment.ident == name)
}
