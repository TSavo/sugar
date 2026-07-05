// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `peekable`: the `.peekable()` adaptor. `Iterator::peekable` yields the SAME items in
// the SAME order -- it only ADDS `peek`/`next_if` capability; it never alters the value
// stream. So over a finite literal sequence it is the IDENTITY adaptor, reusing
// `IdentitySugar` over the receiver's composite. This is the outermost-call recognizer
// (so `build_composite([..].iter().peekable())` resolves); `peel_fold_adaptors` carries
// the same identity treatment when `.peekable()` sits inside a longer adaptor chain
// (e.g. the `while let next_if` rewrite's `<seq>.iter().peekable().take_while(..)`).

use std::rc::Rc;

use sugar_ir_symbolic::{and_, eq, num, Term};
use syn::{Expr, ExprCall, ExprMacro, ExprMethodCall};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::identity::IdentitySugar;
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    callsite_assertion_name, parse_int_lit, parse_macro_args, simple_path_name, strip_refs_groups,
    AssertionFactKind, ConstVal, Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx,
    Warrant,
};

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "peekable_runtime_assertion_surface",
    SugarRole::AssertionSurface,
    &[
        "assertion_surface_relation_macro",
        "assertion_surface_assert_macro",
    ],
    crate::sugar::claim::SugarWitnesses::temporal_campaign(
        "S5/S6 iterator state family: peekable assertion surface",
    ),
    recognize_assertion_surface,
);

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::composite(
    "peekable",
    crate::sugar::claim::SugarWitnesses::temporal_campaign(
        "S5/S6 iterator state family: peekable adaptor",
    ),
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
    if call.method == "peekable" && call.args.is_empty() {
        return Some(Box::new(IdentitySugar {
            inner: SugarBody::from_node(method_family::build_literal_sequence_composite(
                &call.receiver,
                fcx,
            )?),
        }));
    }
    None
}

fn recognize_assertion_surface(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
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
    if let Some(source) = peekable_source_expr(&op.receiver, fcx, 0)
        .filter(|source| literal_peekable_source(source, fcx, 0))
    {
        return Some(Box::new(PeekableLiteralAssertionSugar {
            kind: op.kind,
            source: literal_sequence_body(&source, fcx),
            expected: SugarBody::term(expected, fcx),
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
    kind: PeekableOpKind,
    source: SugarBody<CompositeFloor>,
    expected: SugarBody<TermFloor>,
}

impl Sugar for PeekableLiteralAssertionSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.constraint(ctx) {
            Ok((atom, anchor)) => Outcome::Complete(Desugared::Constraints {
                atom,
                n: 1,
                kind: AssertionFactKind::Warranted,
                warrant: Warrant {
                    name: anchor.as_ref().and_then(|term| {
                        callsite_assertion_name(term.as_ref(), ctx.scope.local_scope())
                    }),
                },
            }),
            Err(effect) => Outcome::Incomplete(effect),
        }
    }
}

impl PeekableLiteralAssertionSugar {
    fn constraint(
        &self,
        ctx: &SugarCtx,
    ) -> Result<(Rc<sugar_ir_symbolic::Formula>, Option<Rc<Term>>), Effect> {
        let seq = literal_sequence_from_body(&self.source, ctx)?;
        let actual = option_term_for_op(&self.kind, &seq);
        let expected = term_from_body(&self.expected, ctx)?;
        let atom = and_(vec![eq(Rc::clone(&actual), expected)]);
        Ok((atom, Some(actual)))
    }
}

fn option_term_for_op(kind: &PeekableOpKind, seq: &[DesugaredElem]) -> Rc<Term> {
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
                .unwrap_or_else(|| panic!("peekable literal sequence element is not an int floor"));
            monadic::some_term(num(n))
        }
        None => monadic::none_term(),
    }
}

fn literal_sequence_body(expr: &Expr, fcx: &SugarBuildCtx) -> SugarBody<CompositeFloor> {
    if let Some(arg) = non_fused_new_arg(expr) {
        return literal_sequence_body(arg, fcx);
    }
    SugarBody::from_node(
        method_family::build_literal_sequence_composite(expr, fcx).unwrap_or_else(|| {
            panic!(
                "peekable literal source did not construct as a sequence floor: `{}`",
                crate::token_key(expr)
            )
        }),
    )
}

fn literal_sequence_from_body(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
) -> Result<Vec<DesugaredElem>, Effect> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_seq()
            .unwrap_or_else(|| panic!("peekable source body completed as non-sequence floor"))),
        Outcome::Incomplete(effect) => Err(effect),
    }
}

fn term_from_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Effect> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| panic!("peekable expected body completed as non-term floor"))),
        Outcome::Incomplete(effect) => Err(effect),
    }
}
