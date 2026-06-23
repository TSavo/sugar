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

use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::method_family;
use crate::{
    const_eval, simple_path_name, strip_refs_groups, ConstVal, Desugared, DesugaredElem, Outcome,
    Sugar, SugarCtx, SUGAR_SEQ_CAP,
};

pub(crate) const EXPR_SUGAR: crate::sugar::claim::ExprSugarClaim =
    crate::sugar::claim::ExprSugarClaim::composite("intersperse", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
    method_family::resolves_literal_sequence(&call.receiver, fcx.let_inits()).then(|| {
        Box::new(IntersperseCallSugar {
            receiver: (*call.receiver).clone(),
            separator: call.args[0].clone(),
            with,
            let_inits: capture_let_inits(fcx),
        }) as Box<dyn Sugar>
    })
}

struct IntersperseCallSugar {
    receiver: Expr,
    separator: Expr,
    with: bool,
    let_inits: BTreeMap<String, Expr>,
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

impl Sugar for IntersperseCallSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt((|| {
            let stable = crate::sugar::format::stable_let_bindings(ctx.scope);
            let let_inits: BTreeMap<String, &Expr> = stable
                .iter()
                .map(|(name, init)| (name.clone(), init))
                .chain(
                    self.let_inits
                        .iter()
                        .map(|(name, init)| (name.clone(), init)),
                )
                .collect();
            let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
            let inner = method_family::build_literal_sequence_composite(&self.receiver, &fcx)?;
            if self.with {
                reduce_intersperse_with(inner.as_ref(), &self.separator, ctx)
            } else {
                reduce_intersperse(inner.as_ref(), &self.separator, ctx)
            }
            .map(Desugared::Seq)
        })())
    }
}

pub(crate) struct IntersperseSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) separator: Expr,
}

impl Sugar for IntersperseSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt(
            reduce_intersperse(self.inner.as_ref(), &self.separator, ctx).map(Desugared::Seq),
        )
    }
}

pub(crate) struct IntersperseWithSugar {
    pub(crate) inner: Box<dyn Sugar>,
    pub(crate) separator: Expr,
}

impl Sugar for IntersperseWithSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        Outcome::from_opt(
            reduce_intersperse_with(self.inner.as_ref(), &self.separator, ctx).map(Desugared::Seq),
        )
    }
}

fn reduce_intersperse(
    inner: &dyn Sugar,
    separator: &Expr,
    ctx: &SugarCtx,
) -> Option<Vec<DesugaredElem>> {
    let seq = inner.desugar(ctx).dug()?.into_seq()?;
    if seq.len() <= 1 {
        return Some(seq);
    }
    let sep = elem_from_expr(separator, ctx)?;
    let out = interleave(seq, || Some(sep.clone()))?;
    debug!(
        target: "sugar_lift_rust_tests::sugar::intersperse",
        len = out.len(),
        "literal intersperse reduced"
    );
    Some(out)
}

fn reduce_intersperse_with(
    inner: &dyn Sugar,
    separator: &Expr,
    ctx: &SugarCtx,
) -> Option<Vec<DesugaredElem>> {
    let seq = inner.desugar(ctx).dug()?.into_seq()?;
    if seq.len() <= 1 {
        return Some(seq);
    }
    let closure = resolve_zero_arg_closure(separator, ctx)?;
    let mut state = BTreeMap::new();
    let out = interleave(seq, || eval_separator_closure(closure, ctx, &mut state))?;
    debug!(
        target: "sugar_lift_rust_tests::sugar::intersperse",
        len = out.len(),
        "literal intersperse_with reduced"
    );
    Some(out)
}

fn interleave<F>(seq: Vec<DesugaredElem>, mut separator: F) -> Option<Vec<DesugaredElem>>
where
    F: FnMut() -> Option<DesugaredElem>,
{
    let out_len = seq.len().checked_mul(2)?.checked_sub(1)?;
    if out_len as i64 > SUGAR_SEQ_CAP {
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

fn elem_from_expr(expr: &Expr, ctx: &SugarCtx) -> Option<DesugaredElem> {
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
