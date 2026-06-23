// SPDX-License-Identifier: Apache-2.0
//
// Literal slice/array search and split surfaces not owned by the broader iterator
// terminal family. Recognition is intentionally narrow: only source shapes whose
// receiver syntactically resolves to a literal array/slice are claimed here, so
// strings and ranges stay with their own domains.

use std::collections::BTreeMap;
use std::rc::Rc;

use sugar_ir_symbolic::{and_, atomic_, Term};
use syn::{BinOp, Expr, ExprClosure, ExprMacro, ExprMethodCall};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::format::stable_let_bindings;
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::{
    callsite_assertion_name, const_eval_unary_closure, const_fold_int_term, const_int, num,
    parse_macro_args, strip_refs_groups, AssertionFactKind, ConstVal, Desugared, DesugaredElem,
    Effect, Outcome, Sugar, SugarCtx, Warrant, STRUCTURAL_BACKSTOP_REASON, SUGAR_SEQ_CAP,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::term_before("slice_search", &["method"], recognize_term);

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "slice_search_assertion_surface",
    SugarRole::AssertionSurface,
    &[
        "assertion_surface_relation_macro",
        "assertion_surface_assert_macro",
    ],
    recognize_assertion_surface,
);

pub(crate) fn recognize_term(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    let kind = recognize_search_kind(call)?;
    if !literal_int_slice_receiver(&call.receiver, fcx, 0) {
        return None;
    }
    if matches!(kind, SearchKind::BinarySearch) && !unique_sorted_int_sequence(&call.receiver, fcx)
    {
        return None;
    }
    Some(Box::new(SliceSearchTermSugar {
        kind,
        receiver: call.receiver.as_ref().clone(),
        args: call.args.iter().cloned().collect(),
        let_inits: capture_let_inits(fcx),
    }))
}

fn recognize_assertion_surface(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match strip_refs_groups(expr) {
        Expr::Macro(expr_macro) => recognize_assert_eq_macro(expr_macro, fcx),
        Expr::Binary(binary) if matches!(binary.op, BinOp::Eq(_)) => {
            build_assertion_surface(&binary.left, &binary.right, fcx)
        }
        _ => None,
    }
}

fn recognize_assert_eq_macro(
    expr_macro: &ExprMacro,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    let name = expr_macro.mac.path.segments.last()?.ident.to_string();
    if !matches!(name.as_str(), "assert_eq" | "debug_assert_eq") {
        return None;
    }
    let args = parse_macro_args(expr_macro.mac.tokens.clone()).ok()?;
    if args.exprs.len() < 2 {
        return None;
    }
    build_assertion_surface(&args.exprs[0], &args.exprs[1], fcx)
}

fn build_assertion_surface(lhs: &Expr, rhs: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if let Some(producer) = recognize_tuple_option_producer(lhs, fcx) {
        let expected = recognize_expected_option_tuple(rhs)?;
        return Some(Box::new(SliceSplitAssertionSugar {
            producer,
            expected,
            let_inits: capture_let_inits(fcx),
        }));
    }
    if let Some(producer) = recognize_tuple_option_producer(rhs, fcx) {
        let expected = recognize_expected_option_tuple(lhs)?;
        return Some(Box::new(SliceSplitAssertionSugar {
            producer,
            expected,
            let_inits: capture_let_inits(fcx),
        }));
    }
    None
}

#[derive(Clone)]
enum SearchKind {
    RPosition(ExprClosure),
    BinarySearch,
}

struct SliceSearchTermSugar {
    kind: SearchKind,
    receiver: Expr,
    args: Vec<Expr>,
    let_inits: BTreeMap<String, Expr>,
}

impl Sugar for SliceSearchTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.eval(ctx) {
            Ok(term) => Outcome::Dug(Desugared::Term(term)),
            Err(effect) => Outcome::Hit(effect),
        }
    }
}

impl SliceSearchTermSugar {
    fn eval(&self, ctx: &SugarCtx) -> Result<Rc<Term>, Effect> {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let seq = literal_sequence(&self.receiver, &fcx, ctx)?;
        match &self.kind {
            SearchKind::RPosition(pred) => {
                for (idx, elem) in seq.iter().enumerate().rev() {
                    let value = elem.value.as_ref().ok_or_else(structural_effect)?;
                    let hit = const_eval_unary_closure(pred, value)
                        .and_then(|v| v.as_bool())
                        .ok_or_else(structural_effect)?;
                    if hit {
                        return Ok(monadic::some_term(num(idx as i128)));
                    }
                }
                Ok(monadic::none_term())
            }
            SearchKind::BinarySearch => {
                let needle = self.int_arg(0, &fcx, ctx)?;
                let elems = int_values(&seq)?;
                if !elems.windows(2).all(|pair| pair[0] <= pair[1]) {
                    return Err(structural_effect());
                }
                match elems.binary_search(&needle) {
                    Ok(idx) => {
                        if elems.iter().filter(|&&elem| elem == needle).count() != 1 {
                            return Err(structural_effect());
                        }
                        Ok(monadic::ok_term(num(idx as i128)))
                    }
                    Err(idx) => Ok(monadic::err_term(num(idx as i128))),
                }
            }
        }
    }

    fn int_arg(&self, idx: usize, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Result<i128, Effect> {
        let arg = self.args.get(idx).ok_or_else(structural_effect)?;
        let term = term_for(strip_refs_groups(arg), fcx, ctx)?;
        const_fold_int_term(&term).ok_or_else(structural_effect)
    }
}

#[derive(Clone)]
enum TupleOptionProducer {
    SplitFirst { receiver: Expr },
    SplitLast { receiver: Expr },
    EnumerateNext { receiver: Expr },
}

#[derive(Clone)]
enum ExpectedOptionTuple {
    Some(Vec<Expr>),
    None,
}

struct SliceSplitAssertionSugar {
    producer: TupleOptionProducer,
    expected: ExpectedOptionTuple,
    let_inits: BTreeMap<String, Expr>,
}

impl Sugar for SliceSplitAssertionSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.constraints(ctx) {
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

impl SliceSplitAssertionSugar {
    fn constraints(
        &self,
        ctx: &SugarCtx,
    ) -> Result<(Rc<sugar_ir_symbolic::Formula>, Option<Rc<Term>>), Effect> {
        let stable = stable_let_bindings(ctx.scope);
        let let_inits = merge_let_inits(&stable, &self.let_inits);
        let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &let_inits);
        let actual = self.actual_parts(&fcx, ctx)?;
        option_tuple_atoms(actual, &self.expected, &fcx, ctx)
    }

    fn actual_parts(
        &self,
        fcx: &SugarBuildCtx,
        ctx: &SugarCtx,
    ) -> Result<Option<Vec<ActualPart>>, Effect> {
        let (receiver, kind) = match &self.producer {
            TupleOptionProducer::SplitFirst { receiver } => (receiver, SplitKind::First),
            TupleOptionProducer::SplitLast { receiver } => (receiver, SplitKind::Last),
            TupleOptionProducer::EnumerateNext { receiver } => (receiver, SplitKind::EnumerateNext),
        };
        let seq = literal_sequence(receiver, fcx, ctx)?;
        match kind {
            SplitKind::First => {
                let Some((head, tail)) = seq.split_first() else {
                    return Ok(None);
                };
                Ok(Some(vec![
                    ActualPart::Scalar(elem_int(head)?),
                    ActualPart::Seq(int_values(tail)?),
                ]))
            }
            SplitKind::Last => {
                let Some((last, init)) = seq.split_last() else {
                    return Ok(None);
                };
                Ok(Some(vec![
                    ActualPart::Scalar(elem_int(last)?),
                    ActualPart::Seq(int_values(init)?),
                ]))
            }
            SplitKind::EnumerateNext => {
                let Some(first) = seq.first() else {
                    return Ok(None);
                };
                Ok(Some(vec![
                    ActualPart::Scalar(0),
                    ActualPart::Scalar(elem_int(first)?),
                ]))
            }
        }
    }
}

#[derive(Clone, Copy)]
enum SplitKind {
    First,
    Last,
    EnumerateNext,
}

enum ActualPart {
    Scalar(i128),
    Seq(Vec<i128>),
}

fn recognize_search_kind(call: &ExprMethodCall) -> Option<SearchKind> {
    Some(match call.method.to_string().as_str() {
        "rposition" if call.args.len() == 1 => {
            let Expr::Closure(closure) = strip_refs_groups(&call.args[0]) else {
                return None;
            };
            SearchKind::RPosition(closure.clone())
        }
        "binary_search" if call.args.len() == 1 => SearchKind::BinarySearch,
        _ => return None,
    })
}

fn recognize_tuple_option_producer(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<TupleOptionProducer> {
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    match call.method.to_string().as_str() {
        "split_first"
            if call.args.is_empty() && literal_int_slice_receiver(&call.receiver, fcx, 0) =>
        {
            Some(TupleOptionProducer::SplitFirst {
                receiver: call.receiver.as_ref().clone(),
            })
        }
        "split_last"
            if call.args.is_empty() && literal_int_slice_receiver(&call.receiver, fcx, 0) =>
        {
            Some(TupleOptionProducer::SplitLast {
                receiver: call.receiver.as_ref().clone(),
            })
        }
        "next" if call.args.is_empty() => recognize_enumerate_next_receiver(&call.receiver, fcx),
        _ => None,
    }
}

fn recognize_enumerate_next_receiver(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<TupleOptionProducer> {
    let Expr::MethodCall(enumerate) = strip_refs_groups(expr) else {
        return None;
    };
    if enumerate.method != "enumerate"
        || !enumerate.args.is_empty()
        || !literal_int_slice_receiver(&enumerate.receiver, fcx, 0)
    {
        return None;
    }
    Some(TupleOptionProducer::EnumerateNext {
        receiver: enumerate.receiver.as_ref().clone(),
    })
}

fn recognize_expected_option_tuple(expr: &Expr) -> Option<ExpectedOptionTuple> {
    match strip_refs_groups(expr) {
        Expr::Path(path) if path_ends_with(path, "None") => Some(ExpectedOptionTuple::None),
        Expr::Call(call) if call.args.len() == 1 => {
            let Expr::Path(path) = strip_refs_groups(&call.func) else {
                return None;
            };
            if !path_ends_with(path, "Some") {
                return None;
            }
            let Expr::Tuple(tuple) = strip_refs_groups(&call.args[0]) else {
                return None;
            };
            Some(ExpectedOptionTuple::Some(
                tuple.elems.iter().cloned().collect(),
            ))
        }
        _ => None,
    }
}

fn option_tuple_atoms(
    actual: Option<Vec<ActualPart>>,
    expected: &ExpectedOptionTuple,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> Result<(Rc<sugar_ir_symbolic::Formula>, Option<Rc<Term>>), Effect> {
    let mut atoms = Vec::new();
    let mut anchor = None;
    match (actual, expected) {
        (Some(actual), ExpectedOptionTuple::Some(expected)) => {
            if actual.len() != expected.len() {
                atoms.push(atomic_(
                    "=".to_string(),
                    vec![num(actual.len() as i128), num(expected.len() as i128)],
                ));
            }
            for (actual_part, expected_expr) in actual.into_iter().zip(expected) {
                match actual_part {
                    ActualPart::Scalar(value) => {
                        let lhs = num(value);
                        let rhs = term_for(strip_refs_groups(expected_expr), fcx, ctx)?;
                        if anchor.is_none() {
                            anchor = Some(Rc::clone(&lhs));
                        }
                        atoms.push(atomic_("=".to_string(), vec![lhs, rhs]));
                    }
                    ActualPart::Seq(values) => {
                        let expected_values =
                            literal_int_sequence_arg(strip_refs_groups(expected_expr), fcx, ctx)?;
                        if values.len() != expected_values.len() {
                            atoms.push(atomic_(
                                "=".to_string(),
                                vec![
                                    num(values.len() as i128),
                                    num(expected_values.len() as i128),
                                ],
                            ));
                        }
                        for (lhs_value, rhs_value) in values.into_iter().zip(expected_values) {
                            let lhs = num(lhs_value);
                            if anchor.is_none() {
                                anchor = Some(Rc::clone(&lhs));
                            }
                            atoms.push(atomic_("=".to_string(), vec![lhs, num(rhs_value)]));
                        }
                    }
                }
            }
        }
        (None, ExpectedOptionTuple::None) => {
            let lhs = monadic::none_term();
            let rhs = monadic::none_term();
            anchor = Some(Rc::clone(&lhs));
            atoms.push(atomic_("=".to_string(), vec![lhs, rhs]));
        }
        (Some(actual), ExpectedOptionTuple::None) => {
            let value = actual.iter().find_map(|part| match part {
                ActualPart::Scalar(value) => Some(*value),
                ActualPart::Seq(values) => values.first().copied(),
            });
            let lhs = value
                .map(|value| monadic::some_term(num(value)))
                .unwrap_or_else(|| monadic::some_term(num(0)));
            let rhs = monadic::none_term();
            anchor = Some(Rc::clone(&lhs));
            atoms.push(atomic_("=".to_string(), vec![lhs, rhs]));
        }
        (None, ExpectedOptionTuple::Some(_)) => {
            let lhs = monadic::none_term();
            let rhs = monadic::some_term(num(0));
            anchor = Some(Rc::clone(&lhs));
            atoms.push(atomic_("=".to_string(), vec![lhs, rhs]));
        }
    }
    Ok((and_(atoms), anchor))
}

fn literal_int_slice_receiver(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Array(array) => array.elems.iter().all(syntactic_int_expr),
        Expr::Repeat(repeat) => {
            syntactic_int_expr(&repeat.expr)
                && method_family::literal_sequence_static_len_in_scope(
                    expr,
                    fcx.let_inits(),
                    fcx.scope(),
                )
                .is_some_and(|len| len <= SUGAR_SEQ_CAP as usize)
        }
        Expr::Index(index) => {
            literal_int_slice_receiver(&index.expr, fcx, depth + 1)
                && method_family::literal_sequence_static_len_in_scope(
                    expr,
                    fcx.let_inits(),
                    fcx.scope(),
                )
                .is_some()
        }
        Expr::Path(path) if path.qself.is_none() => {
            let Some(name) = path.path.get_ident().map(ToString::to_string) else {
                return false;
            };
            fcx.let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))
                .is_some_and(|init| literal_int_slice_receiver(init, fcx, depth + 1))
        }
        Expr::MethodCall(call) if call.args.is_empty() => {
            matches!(
                call.method.to_string().as_str(),
                "iter"
                    | "into_iter"
                    | "cloned"
                    | "copied"
                    | "fuse"
                    | "as_slice"
                    | "to_vec"
                    | "to_owned"
                    | "into_vec"
            ) && literal_int_slice_receiver(&call.receiver, fcx, depth + 1)
        }
        other => crate::sugar::collection_literal::collection_literal_array(other)
            .is_some_and(|array| literal_int_slice_receiver(&array, fcx, depth + 1)),
    }
}

fn syntactic_int_expr(expr: &Expr) -> bool {
    const_int(strip_refs_groups(expr)).is_some()
}

fn unique_sorted_int_sequence(expr: &Expr, fcx: &SugarBuildCtx) -> bool {
    let Some(values) = literal_int_values_syntax(expr, fcx, 0) else {
        return false;
    };
    values.windows(2).all(|pair| pair[0] < pair[1])
}

fn literal_int_values_syntax(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> Option<Vec<i128>> {
    if depth > 8 {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Array(array) => {
            if array.elems.len() > SUGAR_SEQ_CAP as usize {
                return None;
            }
            array
                .elems
                .iter()
                .map(|elem| const_int(strip_refs_groups(elem)))
                .collect()
        }
        Expr::Repeat(repeat) => {
            let value = const_int(strip_refs_groups(&repeat.expr))?;
            let len = method_family::literal_sequence_static_len_in_scope(
                expr,
                fcx.let_inits(),
                fcx.scope(),
            )?;
            if len > SUGAR_SEQ_CAP as usize {
                return None;
            }
            Some(vec![value; len])
        }
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = fcx
                .let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))?;
            literal_int_values_syntax(init, fcx, depth + 1)
        }
        Expr::MethodCall(call) if call.args.is_empty() => {
            if matches!(
                call.method.to_string().as_str(),
                "iter"
                    | "into_iter"
                    | "cloned"
                    | "copied"
                    | "fuse"
                    | "as_slice"
                    | "to_vec"
                    | "to_owned"
                    | "into_vec"
            ) {
                literal_int_values_syntax(&call.receiver, fcx, depth + 1)
            } else {
                None
            }
        }
        other => crate::sugar::collection_literal::collection_literal_array(other)
            .and_then(|array| literal_int_values_syntax(&array, fcx, depth + 1)),
    }
}

fn literal_sequence(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> Result<Vec<DesugaredElem>, Effect> {
    let node =
        method_family::build_literal_sequence_composite(expr, fcx).ok_or_else(structural_effect)?;
    match node.desugar(ctx) {
        Outcome::Dug(d) => d.into_seq().ok_or_else(structural_effect),
        Outcome::Hit(effect) => Err(effect),
    }
}

fn literal_int_sequence_arg(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    ctx: &SugarCtx,
) -> Result<Vec<i128>, Effect> {
    int_values(&literal_sequence(strip_refs_groups(expr), fcx, ctx)?)
}

fn term_for(expr: &Expr, fcx: &SugarBuildCtx, ctx: &SugarCtx) -> Result<Rc<Term>, Effect> {
    match build_term(expr, fcx).desugar(ctx) {
        Outcome::Dug(d) => d.into_term().ok_or_else(structural_effect),
        Outcome::Hit(effect) => Err(effect),
    }
}

fn int_values(seq: &[DesugaredElem]) -> Result<Vec<i128>, Effect> {
    seq.iter().map(elem_int).collect()
}

fn elem_int(elem: &DesugaredElem) -> Result<i128, Effect> {
    elem.value
        .as_ref()
        .and_then(ConstVal::as_int)
        .ok_or_else(structural_effect)
}

fn path_ends_with(path: &syn::ExprPath, name: &str) -> bool {
    path.path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == name)
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
