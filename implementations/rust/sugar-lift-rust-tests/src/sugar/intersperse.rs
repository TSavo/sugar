// SPDX-License-Identifier: Apache-2.0
//
// `intersperse` / `intersperse_with`: value-sequence adapters over a finite literal
// iterator. The receiver composes through the shared sequence-family builder; the
// separator is exact-or-bail. `intersperse_with` only evaluates zero-arg closures whose
// result is source-constructible, plus the closed counter-update shape used by coretests
// (`ctr *= 2; ctr`) when the counter has a literal initializer.

use std::collections::BTreeMap;

use syn::{BinOp, Expr, Stmt};
use tracing::debug;

use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::method_family;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    const_eval, simple_path_name, strip_refs_groups, ConstVal, Desugared, DesugaredElem, Outcome,
    Sugar, SugarCtx, SUGAR_SEQ_CAP,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite(
        "intersperse",
        crate::sugar::claim::SugarWitnesses::Pending,
        recognize_composite,
    );

pub(crate) fn recognize_composite(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.args.len() != 1 {
        return None;
    }
    let with = match call.method.to_string().as_str() {
        "intersperse" => false,
        "intersperse_with" => true,
        _ => return None,
    };
    let inner = SugarBody::from_node(method_family::build_literal_sequence_composite(
        &call.receiver,
        fcx,
    )?);
    let separator = if with {
        IntersperseSeparator::Generator(IntersperseGenerator::new(call.args[0].clone()))
    } else {
        IntersperseSeparator::Value(IntersperseValueSeparator::new(call.args[0].clone(), fcx))
    };
    Some(Box::new(IntersperseCallSugar { inner, separator }))
}

struct IntersperseCallSugar {
    inner: SugarBody<CompositeFloor>,
    separator: IntersperseSeparator,
}

enum IntersperseSeparator {
    Value(IntersperseValueSeparator),
    Generator(IntersperseGenerator),
}

pub(crate) struct IntersperseValueSeparator {
    source_expr: Expr,
    body: SugarBody<TermFloor>,
}

impl IntersperseValueSeparator {
    pub(crate) fn new(source_expr: Expr, fcx: &SugarBuildCtx) -> Self {
        let body = SugarBody::term(&source_expr, fcx);
        Self { source_expr, body }
    }

    fn elem(&self, ctx: &SugarCtx) -> Result<Option<DesugaredElem>, Outcome> {
        match self.body.reduce(ctx) {
            Outcome::Complete(d) => {
                d.into_term()
                    .unwrap_or_else(|| intersperse_gap("separator value reduced to non-term"));
            }
            Outcome::Incomplete(effect) => return Err(Outcome::Incomplete(effect)),
        }
        Ok(elem_from_source_expr(&self.source_expr, ctx))
    }
}

pub(crate) struct IntersperseGenerator {
    callback_source: Expr,
}

impl IntersperseGenerator {
    pub(crate) fn new(callback_source: Expr) -> Self {
        Self { callback_source }
    }
}

impl Sugar for IntersperseCallSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_intersperse_family(&self.inner, &self.separator, ctx)
    }
}

pub(crate) struct IntersperseSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) separator: IntersperseValueSeparator,
}

impl Sugar for IntersperseSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_intersperse(&self.inner, &self.separator, ctx)
            .map(|out| {
                Outcome::Complete(Desugared::Seq(out.unwrap_or_else(|| {
                    intersperse_gap("intersperse output did not materialize")
                })))
            })
            .unwrap_or_else(|outcome| outcome)
    }
}

pub(crate) struct IntersperseWithSugar {
    pub(crate) inner: SugarBody<CompositeFloor>,
    pub(crate) separator: IntersperseGenerator,
}

impl Sugar for IntersperseWithSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        reduce_intersperse_with(&self.inner, &self.separator, ctx)
            .map(|out| {
                Outcome::Complete(Desugared::Seq(out.unwrap_or_else(|| {
                    intersperse_gap("intersperse output did not materialize")
                })))
            })
            .unwrap_or_else(|outcome| outcome)
    }
}

fn reduce_intersperse_family(
    inner: &SugarBody<CompositeFloor>,
    separator: &IntersperseSeparator,
    ctx: &SugarCtx,
) -> Outcome {
    let reduced = match separator {
        IntersperseSeparator::Value(separator) => reduce_intersperse(inner, separator, ctx),
        IntersperseSeparator::Generator(generator) => {
            reduce_intersperse_with(inner, generator, ctx)
        }
    };
    let out = match reduced {
        Ok(Some(out)) => out,
        Ok(None) => intersperse_gap("intersperse output did not materialize"),
        Err(outcome) => return outcome,
    };
    Outcome::Complete(Desugared::Seq(out))
}

fn reduce_intersperse(
    inner: &SugarBody<CompositeFloor>,
    separator: &IntersperseValueSeparator,
    ctx: &SugarCtx,
) -> Result<Option<Vec<DesugaredElem>>, Outcome> {
    let Some(seq) = reduce_inner_seq(inner, ctx)? else {
        return Ok(None);
    };
    if seq.len() <= 1 {
        return Ok(Some(seq));
    }
    let Some(sep) = separator.elem(ctx)? else {
        return Ok(None);
    };
    let out = interleave(seq, || Some(sep.clone()));
    debug!(
        target: "sugar_lift_rust_tests::sugar::intersperse",
        len = out.as_ref().map_or(0, Vec::len),
        "literal intersperse reduced"
    );
    Ok(out)
}

fn reduce_intersperse_with(
    inner: &SugarBody<CompositeFloor>,
    separator: &IntersperseGenerator,
    ctx: &SugarCtx,
) -> Result<Option<Vec<DesugaredElem>>, Outcome> {
    let Some(seq) = reduce_inner_seq(inner, ctx)? else {
        return Ok(None);
    };
    if seq.len() <= 1 {
        return Ok(Some(seq));
    }
    let Some(closure) = resolve_zero_arg_closure(&separator.callback_source, ctx) else {
        return Ok(None);
    };
    let mut state = BTreeMap::new();
    let out = interleave(seq, || eval_separator_closure(closure, ctx, &mut state));
    debug!(
        target: "sugar_lift_rust_tests::sugar::intersperse",
        len = out.as_ref().map_or(0, Vec::len),
        "literal intersperse_with reduced"
    );
    Ok(out)
}

fn reduce_inner_seq(
    inner: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
) -> Result<Option<Vec<DesugaredElem>>, Outcome> {
    match inner.reduce(ctx) {
        Outcome::Complete(d) => Ok(d.into_seq()),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn interleave<F>(seq: Vec<DesugaredElem>, mut separator: F) -> Option<Vec<DesugaredElem>>
where
    F: FnMut() -> Option<DesugaredElem>,
{
    let out_len = seq.len().checked_mul(2)?.checked_sub(1)?;
    if out_len > SUGAR_SEQ_CAP as usize {
        return None;
    }
    let mut out = Vec::with_capacity(out_len);
    for (idx, elem) in seq.into_iter().enumerate() {
        if idx > 0 {
            out.push(separator()?);
        }
        out.push(elem);
    }
    Some(out)
}

fn intersperse_gap(reason: &str) -> ! {
    panic!("intersperse did not reach a lawful floor: {reason}")
}

fn elem_from_source_expr(expr: &Expr, ctx: &SugarCtx) -> Option<DesugaredElem> {
    let expr = resolve_stable_expr(expr, ctx, 0)?;
    Some(DesugaredElem {
        value: const_eval(&expr, &BTreeMap::new()),
        expr,
    })
}

fn resolve_stable_expr(expr: &Expr, ctx: &SugarCtx, depth: usize) -> Option<Expr> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            if let Some(current) = ctx.scope.temporal_rewrite_expr_for(&name) {
                return resolve_stable_expr(&current, ctx, depth + 1);
            }
            if let Some(init) = ctx.scope.stable_let_binding_for_term(&name) {
                return resolve_stable_expr(init, ctx, depth + 1);
            }
            Some(expr.clone())
        }
        other => Some(other.clone()),
    }
}

fn resolve_zero_arg_closure<'a>(expr: &'a Expr, ctx: &'a SugarCtx) -> Option<&'a syn::ExprClosure> {
    match strip_refs_groups(expr) {
        Expr::Closure(closure) if closure.inputs.is_empty() => Some(closure),
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = ctx.scope.stable_let_binding_for_term(&name)?;
            resolve_zero_arg_closure(init, ctx)
        }
        _ => None,
    }
}

fn eval_separator_closure(
    closure: &syn::ExprClosure,
    ctx: &SugarCtx,
    state: &mut BTreeMap<String, ConstVal>,
) -> Option<DesugaredElem> {
    if !closure.inputs.is_empty() {
        return None;
    }
    match strip_refs_groups(&closure.body) {
        Expr::Block(block) => eval_separator_block(&block.block.stmts, ctx, state),
        expr => elem_from_closure_expr(expr, state),
    }
}

fn eval_separator_block(
    stmts: &[Stmt],
    ctx: &SugarCtx,
    state: &mut BTreeMap<String, ConstVal>,
) -> Option<DesugaredElem> {
    match stmts {
        [Stmt::Expr(expr, None)] => elem_from_closure_expr(expr, state),
        [assign_stmt, Stmt::Expr(tail, None)] => {
            replay_counter_assignment(assign_stmt, ctx, state)?;
            elem_from_closure_expr(tail, state)
        }
        _ => None,
    }
}

fn elem_from_closure_expr(
    expr: &Expr,
    state: &BTreeMap<String, ConstVal>,
) -> Option<DesugaredElem> {
    let value = const_eval(expr, state);
    let expr = match value.as_ref().and_then(ConstVal::to_expr) {
        Some(expr) => expr,
        None => expr.clone(),
    };
    Some(DesugaredElem { expr, value })
}

fn replay_counter_assignment(
    stmt: &Stmt,
    ctx: &SugarCtx,
    state: &mut BTreeMap<String, ConstVal>,
) -> Option<()> {
    let Stmt::Expr(expr, _) = stmt else {
        return None;
    };
    match strip_refs_groups(expr) {
        Expr::Binary(binary) if assignment_op(&binary.op).is_some() => {
            let name = simple_path_name(&binary.left)?;
            let rhs = const_eval(&binary.right, state)?;
            apply_counter_assignment(&name, assignment_op(&binary.op)?, rhs, ctx, state)
        }
        Expr::Assign(assign) => {
            let name = simple_path_name(&assign.left)?;
            let Expr::Binary(rhs) = strip_refs_groups(&assign.right) else {
                return None;
            };
            let lhs_name = simple_path_name(&rhs.left)?;
            if lhs_name != name {
                return None;
            }
            let op = binary_op(&rhs.op)?;
            let rhs = const_eval(&rhs.right, state)?;
            apply_counter_assignment(&name, op, rhs, ctx, state)
        }
        _ => None,
    }
}

#[derive(Clone, Copy)]
enum CounterOp {
    Add,
    Sub,
    Mul,
}

fn assignment_op(op: &BinOp) -> Option<CounterOp> {
    match op {
        BinOp::AddAssign(_) => Some(CounterOp::Add),
        BinOp::SubAssign(_) => Some(CounterOp::Sub),
        BinOp::MulAssign(_) => Some(CounterOp::Mul),
        _ => None,
    }
}

fn binary_op(op: &BinOp) -> Option<CounterOp> {
    match op {
        BinOp::Add(_) => Some(CounterOp::Add),
        BinOp::Sub(_) => Some(CounterOp::Sub),
        BinOp::Mul(_) => Some(CounterOp::Mul),
        _ => None,
    }
}

fn apply_counter_assignment(
    name: &str,
    op: CounterOp,
    rhs: ConstVal,
    ctx: &SugarCtx,
    state: &mut BTreeMap<String, ConstVal>,
) -> Option<()> {
    let old = match state.get(name) {
        Some(value) => value.clone(),
        None => {
            let init = ctx
                .scope
                .temporal_rewrite_expr_for(name)
                .or_else(|| ctx.scope.stable_let_binding_for_term(name).cloned())?;
            let value = const_eval(&init, &BTreeMap::new())?;
            state.insert(name.to_string(), value.clone());
            value
        }
    };
    let old = old.as_int()?;
    let rhs = rhs.as_int()?;
    let next = match op {
        CounterOp::Add => old.checked_add(rhs)?,
        CounterOp::Sub => old.checked_sub(rhs)?,
        CounterOp::Mul => old.checked_mul(rhs)?,
    };
    state.insert(name.to_string(), ConstVal::Int(next));
    Some(())
}
