// SPDX-License-Identifier: Apache-2.0
//
// `peekable`: the `.peekable()` adaptor. `Iterator::peekable` yields the SAME items in
// the SAME order -- it only ADDS `peek`/`next_if` capability; it never alters the value
// stream. So over a finite literal sequence it is the IDENTITY adaptor, reusing
// `IdentitySugar` over the receiver's composite. This is the outermost-call recognizer
// (so `build_composite([..].iter().peekable())` resolves); `peel_fold_adaptors` carries
// the same identity treatment when `.peekable()` sits inside a longer adaptor chain
// (e.g. the `while let next_if` rewrite's `<seq>.iter().peekable().take_while(..)`).

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, num, Term};
use syn::{Expr, ExprCall, ExprMacro, ExprMethodCall};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::identity::IdentitySugar;
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::{
    callsite_assertion_name, parse_int_lit, parse_macro_args, simple_path_name, strip_refs_groups,
    AssertionFactKind, ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx,
    Warrant, STRUCTURAL_BACKSTOP_REASON,
};

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "peekable_runtime_assertion_surface",
    SugarRole::AssertionSurface,
    &[
        "assertion_surface_relation_macro",
        "assertion_surface_assert_macro",
    ],
    recognize_assertion_surface,
);

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::composite("peekable", recognize_composite);

pub(crate) fn recognize_composite(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.method == "peekable" && call.args.is_empty() {
        return Some(Box::new(IdentitySugar {
            inner: method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
        }));
    }
    None
}

fn recognize_assertion_surface(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    if mac.path.segments.last()?.ident != "assert_eq" {
        return None;
    }
    let args = parse_macro_args(mac.tokens.clone()).ok()?;
    if args.exprs.len() < 2 {
        return None;
    }
    build_assertion_surface(&args.exprs[0], &args.exprs[1], fcx)
        .or_else(|| build_assertion_surface(&args.exprs[1], &args.exprs[0], fcx))
}

fn build_assertion_surface(
    actual: &Expr,
    expected: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expected_kind = expected_option_kind(expected)?;
    let op = peekable_op(actual)?;
    let receiver = simple_path_name(&op.receiver);
    if let Some(name) = receiver.as_deref() {
        if runtime_peekable_binding(name, fcx) {
            return Some(Box::new(PeekableRuntimeRefusalSugar {
                receiver: name.to_string(),
            }));
        }
        if fcx.scope().is_consumed_iterator_local(name)
            || fcx
                .scope()
                .unknown_iterator_consumption_reason(name)
                .is_some()
        {
            return None;
        }
    }
    if matches!(expected_kind, ExpectedOptionKind::SomeOther) {
        return None;
    }
    if peekable_receiver_resolves_literal(&op.receiver, fcx, 0) {
        return Some(Box::new(PeekableLiteralAssertionSugar {
            op,
            expected: expected.clone(),
            let_inits: capture_let_inits(fcx),
        }));
    }
    None
}

fn peekable_op(expr: &Expr) -> Option<PeekableOp> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    let kind = peekable_op_kind(call)?;
    Some(PeekableOp {
        kind,
        receiver: call.receiver.as_ref().clone(),
    })
}

fn peekable_op_kind(call: &ExprMethodCall) -> Option<PeekableOpKind> {
    Some(match call.method.to_string().as_str() {
        "peek" if call.args.is_empty() => PeekableOpKind::Peek,
        "next" if call.args.is_empty() => PeekableOpKind::Next,
        "next_back" if call.args.is_empty() => PeekableOpKind::NextBack,
        "last" if call.args.is_empty() => PeekableOpKind::Last,
        "nth" if call.args.len() == 1 => {
            let Expr::Lit(syn::ExprLit {
                lit: syn::Lit::Int(k),
                ..
            }) = strip_refs_groups(&call.args[0])
            else {
                return None;
            };
            PeekableOpKind::Nth(usize::try_from(parse_int_lit(k).ok()?).ok()?)
        }
        _ => return None,
    })
}

enum ExpectedOptionKind {
    None,
    SomeScalarInt,
    SomeOther,
}

fn expected_option_kind(expr: &Expr) -> Option<ExpectedOptionKind> {
    match strip_refs_groups(expr) {
        Expr::Path(path) => path
            .path
            .segments
            .last()
            .is_some_and(|seg| seg.ident == "None")
            .then_some(ExpectedOptionKind::None),
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return None;
            };
            if !path
                .path
                .segments
                .last()
                .is_some_and(|seg| seg.ident == "Some")
            {
                return None;
            }
            Some(if unreferenced_int_literal(&call.args[0]) {
                ExpectedOptionKind::SomeScalarInt
            } else {
                ExpectedOptionKind::SomeOther
            })
        }
        _ => None,
    }
}

fn unreferenced_int_literal(expr: &Expr) -> bool {
    match strip_groups(expr) {
        Expr::Lit(syn::ExprLit {
            lit: syn::Lit::Int(_),
            ..
        }) => true,
        Expr::Unary(unary) if matches!(unary.op, syn::UnOp::Neg(_)) => matches!(
            strip_groups(&unary.expr),
            Expr::Lit(syn::ExprLit {
                lit: syn::Lit::Int(_),
                ..
            })
        ),
        _ => false,
    }
}

fn strip_groups(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(p) => strip_groups(&p.expr),
        Expr::Group(g) => strip_groups(&g.expr),
        _ => expr,
    }
}

fn peekable_receiver_resolves_literal(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    let Some(source) = peekable_source_expr(expr, fcx, depth) else {
        return false;
    };
    literal_peekable_source(&source, fcx, depth + 1)
}

fn peekable_source_expr(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> Option<Expr> {
    if depth > 8 {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::MethodCall(call) if call.method == "peekable" && call.args.is_empty() => {
            Some(call.receiver.as_ref().clone())
        }
        Expr::Path(_) => {
            let name = simple_path_name(expr)?;
            if let Some(current) = fcx.scope().temporal_rewrite_expr_for(&name) {
                if let Some(source) = peekable_source_expr(&current, fcx, depth + 1) {
                    return Some(source);
                }
            }
            fcx.let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                .or_else(|| {
                    fcx.scope()
                        .let_bindings_iter()
                        .find_map(|(binding, init)| (binding == &name).then_some(init))
                })
                .and_then(|init| peekable_source_expr(init, fcx, depth + 1))
        }
        _ => None,
    }
}

fn runtime_peekable_binding(name: &str, fcx: &SugarBuildCtx) -> bool {
    let Some(init) = fcx
        .scope()
        .let_bindings_iter()
        .find_map(|(binding, init)| (binding == name).then_some(init))
    else {
        return false;
    };
    let Expr::MethodCall(call) = strip_refs_groups(init) else {
        return false;
    };
    call.method == "peekable"
        && call.args.is_empty()
        && !literal_peekable_source(&call.receiver, fcx, 0)
}

fn literal_peekable_source(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    if method_family::resolves_literal_sequence(expr, fcx.let_inits())
        || method_family::literal_sequence_static_len_in_scope(expr, fcx.let_inits(), fcx.scope())
            .is_some()
    {
        return true;
    }
    if let Some(arg) = non_fused_new_arg(expr) {
        return literal_peekable_source(arg, fcx, depth + 1);
    }
    let Some(name) = simple_path_name(expr) else {
        return false;
    };
    if let Some(current) = fcx.scope().temporal_rewrite_expr_for(&name) {
        return literal_peekable_source(&current, fcx, depth + 1);
    }
    fcx.let_inits()
        .get(&name)
        .copied()
        .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
        .or_else(|| {
            fcx.scope()
                .let_bindings_iter()
                .find_map(|(binding, init)| (binding == &name).then_some(init))
        })
        .is_some_and(|init| literal_peekable_source(init, fcx, depth + 1))
}

fn non_fused_new_arg(expr: &Expr) -> Option<&Expr> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    non_fused_new_call_arg(call)
}

fn non_fused_new_call_arg(call: &ExprCall) -> Option<&Expr> {
    if call.args.len() != 1 {
        return None;
    }
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    let mut saw_non_fused = false;
    let mut saw_new = false;
    for segment in &path.path.segments {
        if segment.ident == "NonFused" {
            saw_non_fused = true;
        }
        if segment.ident == "new" {
            saw_new = true;
        }
    }
    (saw_non_fused && saw_new)
        .then(|| call.args.first())
        .flatten()
}

#[derive(Clone)]
struct PeekableOp {
    kind: PeekableOpKind,
    receiver: Expr,
}

#[derive(Clone)]
enum PeekableOpKind {
    Peek,
    Next,
    NextBack,
    Last,
    Nth(usize),
}

struct PeekableLiteralAssertionSugar {
    op: PeekableOp,
    expected: Expr,
    let_inits: BTreeMap<String, Expr>,
}

struct PeekableRuntimeRefusalSugar {
    receiver: String,
}

impl Sugar for PeekableLiteralAssertionSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.constraint(ctx) {
            Ok((atom, anchor)) => Outcome::Dug(Desugared::Constraints {
                atom,
                n: 1,
                kind: AssertionFactKind::Warranted,
                warrant: Warrant {
                    name: anchor.as_ref().and_then(|term| {
                        callsite_assertion_name(term.as_ref(), ctx.scope.local_scope())
                    }),
                },
            }),
            Err(effect) => Outcome::Hit(effect),
        }
    }
}

impl PeekableLiteralAssertionSugar {
    fn constraint(
        &self,
        ctx: &SugarCtx,
    ) -> Result<(Rc<sugar_ir_symbolic::Formula>, Option<Rc<Term>>), Effect> {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        if let Some(name) = simple_path_name(&self.op.receiver) {
            if let Some(reason) = ctx.scope.unknown_iterator_consumption_reason(&name) {
                return Err(Effect::Unsupported { reason });
            }
            if ctx.scope.is_consumed_iterator_local(&name)
                && ctx.scope.temporal_rewrite_expr_for(&name).is_none()
            {
                return Err(structural_effect());
            }
        }
        let source =
            peekable_source_expr(&self.op.receiver, &fcx, 0).ok_or_else(structural_effect)?;
        let seq = literal_sequence(&source, &fcx, ctx)?;
        let actual = option_term_for_op(&self.op.kind, &seq)?;
        let expected = term_for(&self.expected, &fcx, ctx)?;
        let atom = and_(vec![eq(Rc::clone(&actual), expected)]);
        Ok((atom, Some(actual)))
    }
}

impl Sugar for PeekableRuntimeRefusalSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        Outcome::Hit(Effect::Unsupported {
            reason: format!("runtime slice source, not literal `{}`", self.receiver),
        })
    }
}

fn option_term_for_op(kind: &PeekableOpKind, seq: &[DesugaredElem]) -> Result<Rc<Term>, Effect> {
    let idx = match kind {
        PeekableOpKind::Peek | PeekableOpKind::Next => Some(0usize),
        PeekableOpKind::NextBack | PeekableOpKind::Last => seq.len().checked_sub(1),
        PeekableOpKind::Nth(k) => Some(*k),
    };
    match idx.and_then(|idx| seq.get(idx)) {
        Some(elem) => {
            let n = elem
                .value
                .as_ref()
                .and_then(ConstVal::as_int)
                .ok_or_else(structural_effect)?;
            Ok(monadic::some_term(num(n)))
        }
        None => Ok(monadic::none_term()),
    }
}

fn literal_sequence(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> Result<Vec<DesugaredElem>, Effect> {
    if let Some(arg) = non_fused_new_arg(expr) {
        return literal_sequence(arg, fcx, ctx);
    }
    let node =
        method_family::build_literal_sequence_composite(expr, fcx).ok_or_else(structural_effect)?;
    match node.desugar(ctx) {
        Outcome::Dug(d) => d.into_seq().ok_or_else(structural_effect),
        Outcome::Hit(effect) => Err(effect),
    }
}

fn term_for(expr: &Expr, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Result<Rc<Term>, Effect> {
    match build_term(expr, fcx).desugar(ctx) {
        Outcome::Dug(d) => d.into_term().ok_or_else(structural_effect),
        Outcome::Hit(effect) => Err(effect),
    }
}

fn structural_effect() -> Effect {
    Effect::Unsupported {
        reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
    }
}

fn capture_let_inits(fcx: &SugarBuildCtx) -> BTreeMap<String, Expr> {
    fcx.let_inits()
        .iter()
        .map(|(name, init)| (name.clone(), (**init).clone()))
        .collect()
}

fn merge_let_inits<'a>(
    stable: &'a BTreeMap<String, Expr>,
    captured: &'a BTreeMap<String, Expr>,
) -> BTreeMap<String, &'a Expr> {
    stable
        .iter()
        .map(|(name, init)| (name.clone(), init))
        .chain(captured.iter().map(|(name, init)| (name.clone(), init)))
        .collect()
}
