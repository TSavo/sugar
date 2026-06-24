// SPDX-License-Identifier: Apache-2.0
//
// `FunctionMapSugar`: the `.map(path_fn)` adaptor over a literal-derived sequence.
// Closure maps are owned by `MapSugar`; this node owns the stdlib shape where the
// transform is a visible source function such as `const fn doubler(x) { x * 2 }`.

use std::{collections::BTreeMap, rc::Rc};

use sugar_ir_symbolic::{ConstValue, Term};
use syn::Expr;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx};
use crate::sugar::method_family;
use crate::sugar::term_dispatch::literal_array_term_from_terms;
use crate::{
    const_eval, const_fold_int_term, const_val_term, resolve_value_call_inline, strip_refs_groups,
    ConstVal, Desugared, DesugaredElem, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("function_map", recognize_composite);
pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term("function_map_term", recognize_term);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    recognize_function_map(expr, fcx, SequenceKind::Any).map(|(receiver, func)| {
        Box::new(FunctionMapCallSugar {
            inner: SugarBody::composite(&receiver, fcx),
            func,
        }) as Box<dyn Sugar>
    })
}

pub(crate) fn recognize_term(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    recognize_function_map(expr, fcx, SequenceKind::ArrayOnly).map(|(receiver, func)| {
        Box::new(FunctionMapTermSugar {
            inner: SugarBody::composite(&receiver, fcx),
            func,
        }) as Box<dyn Sugar>
    })
}

#[derive(Clone, Copy)]
enum SequenceKind {
    Any,
    ArrayOnly,
}

fn recognize_function_map(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    sequence_kind: SequenceKind,
) -> Option<(Expr, Expr)> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method != "map" || call.args.len() != 1 {
        return None;
    }
    let func = strip_refs_groups(&call.args[0]);
    let name = simple_fn_name(func)?;
    if !fcx.scope().has_visible_fn(&name) {
        return None;
    }
    let receiver_is_literal = match sequence_kind {
        SequenceKind::Any => {
            method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits())
        }
        SequenceKind::ArrayOnly => {
            method_family::resolves_literal_array_sequence(&call.receiver, fcx.let_inits())
        }
    };
    if !receiver_is_literal {
        return None;
    }
    Some(((*call.receiver).clone(), func.clone()))
}

struct FunctionMapCallSugar {
    inner: SugarBody<CompositeFloor>,
    func: Expr,
}

impl Sugar for FunctionMapCallSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match reduce_function_map(&self.inner, &self.func, ctx) {
            Ok(seq) => Outcome::Complete(Desugared::Seq(seq)),
            Err(outcome) => outcome,
        }
    }
}

pub(crate) struct FunctionMapSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) func: Expr,
}

impl Sugar for FunctionMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match reduce_function_map(&self.inner, &self.func, ctx) {
            Ok(seq) => Outcome::Complete(Desugared::Seq(seq)),
            Err(outcome) => outcome,
        }
    }
}

pub(crate) struct FunctionMapTermSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) func: Expr,
}

impl Sugar for FunctionMapTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mapped = match reduce_function_map(&self.inner, &self.func, ctx) {
            Ok(mapped) => mapped,
            Err(outcome) => return outcome,
        };
        let terms = mapped
            .iter()
            .map(|elem| {
                elem.value
                    .as_ref()
                    .and_then(const_val_term)
                    .unwrap_or_else(|| {
                        function_map_gap("function map term element was not literal")
                    })
            })
            .collect::<Vec<_>>();
        Outcome::Complete(Desugared::Term(literal_array_term_from_terms(&terms)))
    }
}

fn reduce_function_map(
    inner: &SugarBody<CompositeFloor>,
    func: &Expr,
    ctx: &SugarCtx,
) -> Result<Vec<DesugaredElem>, Outcome> {
    let seq = match inner.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_seq()
            .unwrap_or_else(|| function_map_gap("function map receiver reduced to non-sequence")),
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    let mut out = Vec::with_capacity(seq.len());
    for elem in seq {
        let value = elem
            .value
            .as_ref()
            .unwrap_or_else(|| function_map_gap("function map element was not literal"));
        let arg = value
            .to_expr()
            .unwrap_or_else(|| function_map_gap("function map element could not materialize"));
        let mapped = eval_function_value(func, arg, ctx)
            .unwrap_or_else(|| function_map_gap("function map body did not reduce to a literal"));
        let expr = mapped
            .to_expr()
            .unwrap_or_else(|| function_map_gap("function map result could not materialize"));
        out.push(DesugaredElem {
            expr,
            value: Some(mapped),
        });
    }
    tracing::debug!(
        target: "sugar_lift_rust_tests::sugar::function_map",
        len = out.len(),
        func = %crate::token_key(func),
        "literal function map reduced"
    );
    Ok(out)
}

fn function_map_gap(reason: &str) -> ! {
    panic!("function_map did not reach a lawful floor: {reason}")
}

fn eval_function_value(func: &Expr, arg: Expr, ctx: &SugarCtx) -> Option<ConstVal> {
    if let Some(term) = ctx.try_inline_value_call(func, std::slice::from_ref(&arg)) {
        if let Some(value) = const_val_from_term(&term) {
            return Some(value);
        }
    }
    let resolved = resolve_value_call_inline(func, &[arg], ctx.scope, ctx.options)?;
    const_eval(&resolved, &BTreeMap::new())
}

fn const_val_from_term(term: &Rc<Term>) -> Option<ConstVal> {
    if let Some(n) = const_fold_int_term(term) {
        return Some(ConstVal::Int(n));
    }
    match term.as_ref() {
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } => Some(ConstVal::Bool(*value)),
        _ => None,
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
