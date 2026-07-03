// SPDX-License-Identifier: Apache-2.0
//
// `FunctionMapSugar`: the `.map(path_fn)` adaptor over a literal-derived sequence.
// Closure maps are owned by `MapSugar`; this node owns the stdlib shape where the
// transform is a visible source function such as `const fn doubler(x) { x * 2 }`.

use std::{collections::BTreeMap, rc::Rc};

use sugar_ir_symbolic::{ConstValue, Term};
use syn::Expr;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::method_family;
use crate::sugar::sequence_floor::{sequence_elem_term_floor, sequence_value_term_floor};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::term_dispatch::{literal_array_term_from_terms, CurryVisitor, TermFloorAccept};
use crate::{
    const_eval, const_fold_int_term, curry_param_name, curry_param_term, helper_param_names,
    resolve_value_call_inline, strip_refs_groups, value_body_tail_substituted, ConstVal, Desugared,
    DesugaredElem, Outcome, Sugar, SugarCtx,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "function_map",
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize_composite,
    );
pub(crate) const TERM_EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::term(
        "function_map_term",
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize_term,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    recognize_function_map(expr, fcx, SequenceKind::Any).map(|(receiver, func)| {
        let body = build_function_map_body_or_gap(func, fcx);
        Box::new(FunctionMapCallSugar {
            inner: SugarBody::composite(&receiver, fcx),
            body,
        }) as Box<dyn Sugar>
    })
}

pub(crate) fn recognize_term(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    recognize_function_map(expr, fcx, SequenceKind::ArrayOnly).map(|(receiver, func)| {
        let body = build_function_map_body_or_gap(func, fcx);
        Box::new(FunctionMapTermSugar {
            inner: SugarBody::composite(&receiver, fcx),
            body,
        }) as Box<dyn Sugar>
    })
}

fn build_function_map_body_or_gap(func: Expr, fcx: &SugarBuildCtx) -> FunctionMapBody {
    FunctionMapBody::build_result(func, fcx).unwrap_or_else(|reason| {
        panic!("function_map construction gap: {reason}");
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

pub(crate) struct FunctionMapBody {
    func: Expr,
    curry_params: Vec<String>,
    body: SugarBody<TermFloor>,
}

impl FunctionMapBody {
    pub(crate) fn build_result(func: Expr, fcx: &SugarBuildCtx) -> Result<Self, String> {
        let name = simple_fn_name(&func).ok_or_else(|| {
            format!(
                "mapper `{}` is not a simple visible fn path",
                crate::token_key(&func)
            )
        })?;
        let helper = fcx.scope().visible_fn(&name).ok_or_else(|| {
            format!("mapper `{name}` is not visible in the current temporal scope")
        })?;
        if helper.sig.asyncness.is_some() {
            return Err(format!("mapper `{name}` is async"));
        }
        if crate::count_asserts_in_stmts(&helper.block.stmts) != 0 {
            return Err(format!("mapper `{name}` contains assertions"));
        }
        let params = helper_param_names(&helper).map_err(|reason| {
            format!("mapper `{name}` parameter list is not curryable: {reason}")
        })?;
        let [param] = params.as_slice() else {
            return Err(format!(
                "mapper `{name}` has {} parameters, expected exactly one",
                params.len()
            ));
        };
        let curry_params = params
            .iter()
            .map(|param| curry_param_name(param))
            .collect::<Vec<_>>();
        let body_scope = fcx
            .scope()
            .fork_with_stable_term_binding(param, curry_param_term(param));
        let body_fcx = fcx.with_scope(&body_scope);
        let mut bindings = BTreeMap::new();
        let returned = value_body_tail_substituted(&helper.block, &mut bindings)
            .ok_or_else(|| format!("mapper `{name}` does not have a pure value tail"))?;
        let body = SugarBody::<TermFloor>::term(&returned, &body_fcx);
        Ok(Self {
            func,
            curry_params,
            body,
        })
    }
}

struct FunctionMapCallSugar {
    inner: SugarBody<CompositeFloor>,
    body: FunctionMapBody,
}

impl Sugar for FunctionMapCallSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match reduce_function_map(&self.inner, &self.body, ctx) {
            Ok(mapped) => Outcome::Complete(mapped.into_desugared()),
            Err(outcome) => outcome,
        }
    }
}

pub(crate) struct FunctionMapSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) body: FunctionMapBody,
}

impl Sugar for FunctionMapSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match reduce_function_map(&self.inner, &self.body, ctx) {
            Ok(mapped) => Outcome::Complete(mapped.into_desugared()),
            Err(outcome) => outcome,
        }
    }
}

pub(crate) struct FunctionMapTermSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) body: FunctionMapBody,
}

impl Sugar for FunctionMapTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mapped = match reduce_function_map(&self.inner, &self.body, ctx) {
            Ok(mapped) => mapped,
            Err(outcome) => return outcome,
        };
        Outcome::Complete(Desugared::Term(literal_array_term_from_terms(
            &mapped.into_terms(),
        )))
    }
}

enum FunctionMapSequence {
    Values(Vec<DesugaredElem>),
    Terms(Vec<Rc<Term>>),
}

enum FunctionMapReceiverSequence {
    Values(Vec<DesugaredElem>),
    Terms(Vec<Rc<Term>>),
}

impl FunctionMapSequence {
    fn into_desugared(self) -> Desugared {
        match self {
            FunctionMapSequence::Values(values) => Desugared::Seq(values),
            FunctionMapSequence::Terms(terms) => Desugared::TermSeq(terms),
        }
    }

    fn into_terms(self) -> Vec<Rc<Term>> {
        match self {
            FunctionMapSequence::Values(values) => values
                .iter()
                .map(|elem| {
                    elem.value
                        .as_ref()
                        .and_then(sequence_value_term_floor)
                        .unwrap_or_else(|| {
                            function_map_gap("literal function_map value did not reify to a term")
                        })
                })
                .collect(),
            FunctionMapSequence::Terms(terms) => terms,
        }
    }
}

fn reduce_function_map(
    inner: &SugarBody<CompositeFloor>,
    body: &FunctionMapBody,
    ctx: &SugarCtx,
) -> Result<FunctionMapSequence, Outcome> {
    let seq = match inner.reduce(ctx) {
        Outcome::Complete(Desugared::Seq(seq)) => FunctionMapReceiverSequence::Values(seq),
        Outcome::Complete(Desugared::TermSeq(terms)) => FunctionMapReceiverSequence::Terms(terms),
        Outcome::Complete(_) => function_map_gap("function map receiver reduced to non-sequence"),
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    reduce_function_map_sequence(seq, body, ctx)
}

fn reduce_function_map_sequence(
    seq: FunctionMapReceiverSequence,
    body: &FunctionMapBody,
    ctx: &SugarCtx,
) -> Result<FunctionMapSequence, Outcome> {
    match seq {
        FunctionMapReceiverSequence::Values(seq) => {
            if let Some(values) = reduce_function_map_sequence_to_values(&seq, body, ctx)? {
                tracing::debug!(
                    target: "sugar_lift_rust_tests::sugar::function_map",
                    len = values.len(),
                    func = %crate::token_key(&body.func),
                    "literal function map reduced"
                );
                return Ok(FunctionMapSequence::Values(values));
            }
            let terms = seq
                .iter()
                .map(|elem| sequence_elem_term_floor(elem, "function_map"))
                .collect::<Vec<_>>();
            Ok(FunctionMapSequence::Terms(curry_function_map_terms(
                terms, body, ctx,
            )?))
        }
        FunctionMapReceiverSequence::Terms(terms) => Ok(FunctionMapSequence::Terms(
            curry_function_map_terms(terms, body, ctx)?,
        )),
    }
}

fn reduce_function_map_sequence_to_values(
    seq: &[DesugaredElem],
    body: &FunctionMapBody,
    ctx: &SugarCtx,
) -> Result<Option<Vec<DesugaredElem>>, Outcome> {
    let mut out = Vec::with_capacity(seq.len());
    for elem in seq {
        let Some(value) = elem.value.as_ref() else {
            return Ok(None);
        };
        let Some(arg) = value.to_expr() else {
            return Ok(None);
        };
        let Some(mapped) = eval_function_value(&body.func, arg, ctx)? else {
            return Ok(None);
        };
        let Some(expr) = mapped.to_expr() else {
            return Ok(None);
        };
        out.push(DesugaredElem {
            expr,
            value: Some(mapped),
        });
    }
    Ok(Some(out))
}

fn curry_function_map_terms(
    terms: Vec<Rc<Term>>,
    body: &FunctionMapBody,
    ctx: &SugarCtx,
) -> Result<Vec<Rc<Term>>, Outcome> {
    let body_term = match body.body.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_term()
            .unwrap_or_else(|| function_map_gap("function map body reduced to non-Term floor")),
        Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
    };
    let [curry_param] = body.curry_params.as_slice() else {
        function_map_gap("function map body carried non-unary curry params");
    };
    Ok(terms
        .into_iter()
        .enumerate()
        .map(|(ordinal, elem_term)| {
            body_term.accept_term_floor(CurryVisitor {
                param: curry_param,
                arg: &elem_term,
                occurrence: ctx.scope.temporal_curry_occurrence("function_map", ordinal),
            })
        })
        .collect())
}

fn function_map_gap(reason: &str) -> ! {
    panic!("function_map did not reach a lawful floor: {reason}")
}

fn eval_function_value(
    func: &Expr,
    arg: Expr,
    ctx: &SugarCtx,
) -> Result<Option<ConstVal>, Outcome> {
    if let Some(term) = ctx
        .try_inline_value_call(func, std::slice::from_ref(&arg))
        .map_err(Outcome::Incomplete)?
    {
        if let Some(value) = const_val_from_term(&term) {
            return Ok(Some(value));
        }
    }
    let Some(resolved) = resolve_value_call_inline(func, &[arg], ctx.scope, ctx.options) else {
        return Ok(None);
    };
    Ok(const_eval(&resolved, &BTreeMap::new()))
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
