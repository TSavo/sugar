// SPDX-License-Identifier: Apache-2.0
//
// Literal slice/array search and split surfaces not owned by the broader iterator
// terminal family. Recognition is intentionally narrow: only source shapes whose
// receiver syntactically resolves to a literal array/slice are claimed here, so
// strings and ranges stay with their own domains.

use std::rc::Rc;

use sugar_ir_symbolic::{and_, atomic_, Term};
use syn::{BinOp, Expr, ExprClosure, ExprMacro, ExprMethodCall};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{CompositeFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::method_family;
use crate::sugar::monadic;
use crate::{
    callsite_assertion_name, const_eval_unary_closure, const_fold_int_term, const_int, num,
    parse_macro_args, repeat_count_in_scope, strip_refs_groups, AssertionFactKind, ConstVal,
    Desugared, DesugaredElem, Effect, Outcome, Sugar, SugarCtx, Warrant, SUGAR_SEQ_CAP,
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
    let kind = match recognize_search_kind(call)? {
        SearchKind::RPosition(pred) => {
            if !literal_int_slice_receiver(&call.receiver, fcx, 0) {
                return None;
            }
            SearchKind::RPosition(pred)
        }
        SearchKind::BinarySearch => {
            if !literal_int_slice_receiver(&call.receiver, fcx, 0) {
                return None;
            }
            if !unique_sorted_int_sequence(&call.receiver, fcx) {
                return None;
            }
            SearchKind::BinarySearch
        }
        SearchKind::BinarySearchBy { pred, .. } => SearchKind::BinarySearchBy {
            pred,
            len: literal_unit_repeat_len(&call.receiver, fcx, 0)?,
        },
    };
    let receiver = if matches!(kind, SearchKind::BinarySearchBy { .. }) {
        None
    } else {
        Some(SugarBody::from_node(
            method_family::build_literal_sequence_composite(&call.receiver, fcx)?,
        ))
    };
    let needle = if matches!(kind, SearchKind::BinarySearch) {
        Some(SugarBody::<TermFloor>::term(&call.args[0], fcx))
    } else {
        None
    };
    Some(Box::new(SliceSearchTermSugar {
        kind,
        receiver,
        needle,
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
        let expected = recognize_expected_option_tuple(rhs, fcx)?;
        return Some(Box::new(SliceSplitAssertionSugar { producer, expected }));
    }
    if let Some(producer) = recognize_tuple_option_producer(rhs, fcx) {
        let expected = recognize_expected_option_tuple(lhs, fcx)?;
        return Some(Box::new(SliceSplitAssertionSugar { producer, expected }));
    }
    None
}

#[derive(Clone)]
enum SearchKind {
    RPosition(ExprClosure),
    BinarySearch,
    BinarySearchBy { pred: ExprClosure, len: usize },
}

struct SliceSearchTermSugar {
    kind: SearchKind,
    receiver: Option<SugarBody<CompositeFloor>>,
    needle: Option<SugarBody<TermFloor>>,
}

impl Sugar for SliceSearchTermSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.eval(ctx) {
            Ok(term) => Outcome::Complete(Desugared::Term(term)),
            Err(effect) => Outcome::Incomplete(effect),
        }
    }
}

impl SliceSearchTermSugar {
    fn eval(&self, ctx: &SugarCtx) -> Result<Rc<Term>, Effect> {
        match &self.kind {
            SearchKind::RPosition(pred) => {
                let seq = literal_sequence_body(self.receiver_body(), ctx)?;
                for (idx, elem) in seq.iter().enumerate().rev() {
                    let value = elem
                        .value
                        .as_ref()
                        .unwrap_or_else(|| slice_search_gap("rposition element was not literal"));
                    let hit = const_eval_unary_closure(pred, value)
                        .and_then(|v| v.as_bool())
                        .unwrap_or_else(|| {
                            slice_search_gap("rposition predicate did not reduce to bool")
                        });
                    if hit {
                        return Ok(monadic::some_term(num(idx as i128)));
                    }
                }
                Ok(monadic::none_term())
            }
            SearchKind::BinarySearch => {
                let seq = literal_sequence_body(self.receiver_body(), ctx)?;
                let needle = self.needle_int(ctx)?;
                let elems = int_values(&seq);
                if !elems.windows(2).all(|pair| pair[0] <= pair[1]) {
                    slice_search_gap("binary_search receiver was not sorted");
                }
                match elems.binary_search(&needle) {
                    Ok(idx) => {
                        if elems.iter().filter(|&&elem| elem == needle).count() != 1 {
                            slice_search_gap("binary_search receiver had duplicate needle values");
                        }
                        Ok(monadic::ok_term(num(idx as i128)))
                    }
                    Err(idx) => Ok(monadic::err_term(num(idx as i128))),
                }
            }
            SearchKind::BinarySearchBy { pred, len } => {
                if *len != usize::MAX {
                    slice_search_gap("binary_search_by unit-repeat length was not usize::MAX");
                }
                match const_ordering_closure(pred)
                    .unwrap_or_else(|| slice_search_gap("binary_search_by closure was not const"))
                {
                    OrderingConst::Equal => {
                        let idx = len.checked_sub(1).unwrap_or_else(|| {
                            slice_search_gap("binary_search_by length underflow")
                        });
                        Ok(monadic::ok_term(num(idx as i128)))
                    }
                    OrderingConst::Greater => Ok(monadic::err_term(num(0))),
                    OrderingConst::Less => Ok(monadic::err_term(num(*len as i128))),
                }
            }
        }
    }

    fn receiver_body(&self) -> &SugarBody<CompositeFloor> {
        self.receiver
            .as_ref()
            .unwrap_or_else(|| slice_search_gap("slice search receiver body was not constructed"))
    }

    fn needle_int(&self, ctx: &SugarCtx) -> Result<i128, Effect> {
        let needle = self
            .needle
            .as_ref()
            .unwrap_or_else(|| slice_search_gap("binary_search needle body was not constructed"));
        let term = match needle.reduce(ctx) {
            Outcome::Complete(d) => d
                .into_term()
                .unwrap_or_else(|| slice_search_gap("binary_search needle reduced to non-term")),
            Outcome::Incomplete(effect) => return Err(effect),
        };
        Ok(const_fold_int_term(&term)
            .unwrap_or_else(|| slice_search_gap("binary_search needle was not literal int")))
    }
}

enum TupleOptionProducer {
    SplitFirst { receiver: SugarBody<CompositeFloor> },
    SplitLast { receiver: SugarBody<CompositeFloor> },
    EnumerateNext { receiver: SugarBody<CompositeFloor> },
}

enum ExpectedOptionTuple {
    Some(Vec<ExpectedTuplePart>),
    None,
}

enum ExpectedTuplePart {
    Scalar(SugarBody<TermFloor>),
    Seq(SugarBody<CompositeFloor>),
}

struct SliceSplitAssertionSugar {
    producer: TupleOptionProducer,
    expected: ExpectedOptionTuple,
}

impl Sugar for SliceSplitAssertionSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match self.constraints(ctx) {
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

impl SliceSplitAssertionSugar {
    fn constraints(
        &self,
        ctx: &SugarCtx,
    ) -> Result<(Rc<sugar_ir_symbolic::Formula>, Option<Rc<Term>>), Effect> {
        let actual = self.actual_parts(ctx)?;
        option_tuple_atoms(actual, &self.expected, ctx)
    }

    fn actual_parts(&self, ctx: &SugarCtx) -> Result<Option<Vec<ActualPart>>, Effect> {
        let (receiver, kind) = match &self.producer {
            TupleOptionProducer::SplitFirst { receiver } => (receiver, SplitKind::First),
            TupleOptionProducer::SplitLast { receiver } => (receiver, SplitKind::Last),
            TupleOptionProducer::EnumerateNext { receiver } => (receiver, SplitKind::EnumerateNext),
        };
        let seq = literal_sequence_body(receiver, ctx)?;
        match kind {
            SplitKind::First => {
                let Some((head, tail)) = seq.split_first() else {
                    return Ok(None);
                };
                Ok(Some(vec![
                    ActualPart::Scalar(elem_int(head)),
                    ActualPart::Seq(int_values(tail)),
                ]))
            }
            SplitKind::Last => {
                let Some((last, init)) = seq.split_last() else {
                    return Ok(None);
                };
                Ok(Some(vec![
                    ActualPart::Scalar(elem_int(last)),
                    ActualPart::Seq(int_values(init)),
                ]))
            }
            SplitKind::EnumerateNext => {
                let Some(first) = seq.first() else {
                    return Ok(None);
                };
                Ok(Some(vec![
                    ActualPart::Scalar(0),
                    ActualPart::Scalar(elem_int(first)),
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
        "binary_search_by" if call.args.len() == 1 => {
            let Expr::Closure(closure) = strip_refs_groups(&call.args[0]) else {
                return None;
            };
            SearchKind::BinarySearchBy {
                pred: closure.clone(),
                len: usize::MAX,
            }
        }
        _ => return None,
    })
}

#[derive(Clone, Copy)]
enum OrderingConst {
    Less,
    Equal,
    Greater,
}

fn const_ordering_closure(closure: &ExprClosure) -> Option<OrderingConst> {
    let Expr::Path(path) = strip_refs_groups(&closure.body) else {
        return None;
    };
    match path.path.segments.last()?.ident.to_string().as_str() {
        "Less" => Some(OrderingConst::Less),
        "Equal" => Some(OrderingConst::Equal),
        "Greater" => Some(OrderingConst::Greater),
        _ => None,
    }
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
                receiver: SugarBody::from_node(method_family::build_literal_sequence_composite(
                    &call.receiver,
                    fcx,
                )?),
            })
        }
        "split_last"
            if call.args.is_empty() && literal_int_slice_receiver(&call.receiver, fcx, 0) =>
        {
            Some(TupleOptionProducer::SplitLast {
                receiver: SugarBody::from_node(method_family::build_literal_sequence_composite(
                    &call.receiver,
                    fcx,
                )?),
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
        receiver: SugarBody::from_node(method_family::build_literal_sequence_composite(
            &enumerate.receiver,
            fcx,
        )?),
    })
}

fn recognize_expected_option_tuple(
    expr: &Expr,
    fcx: &SugarBuildCtx,
) -> Option<ExpectedOptionTuple> {
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
                tuple
                    .elems
                    .iter()
                    .map(|elem| expected_tuple_part(elem, fcx))
                    .collect(),
            ))
        }
        _ => None,
    }
}

fn expected_tuple_part(expr: &Expr, fcx: &SugarBuildCtx) -> ExpectedTuplePart {
    if let Some(seq) = method_family::build_literal_sequence_composite(strip_refs_groups(expr), fcx)
    {
        ExpectedTuplePart::Seq(SugarBody::from_node(seq))
    } else {
        ExpectedTuplePart::Scalar(SugarBody::term(strip_refs_groups(expr), fcx))
    }
}

fn option_tuple_atoms(
    actual: Option<Vec<ActualPart>>,
    expected: &ExpectedOptionTuple,
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
            for (actual_part, expected_part) in actual.into_iter().zip(expected) {
                match (actual_part, expected_part) {
                    (ActualPart::Scalar(value), ExpectedTuplePart::Scalar(expected_body)) => {
                        let lhs = num(value);
                        let rhs = term_body(expected_body, ctx)?;
                        if anchor.is_none() {
                            anchor = Some(Rc::clone(&lhs));
                        }
                        atoms.push(atomic_("=".to_string(), vec![lhs, rhs]));
                    }
                    (ActualPart::Seq(values), ExpectedTuplePart::Seq(expected_body)) => {
                        let expected_values =
                            int_values(&literal_sequence_body(expected_body, ctx)?);
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
                    (ActualPart::Scalar(_), ExpectedTuplePart::Seq(_)) => {
                        slice_search_gap("expected scalar tuple part was constructed as sequence")
                    }
                    (ActualPart::Seq(_), ExpectedTuplePart::Scalar(_)) => {
                        slice_search_gap("expected sequence tuple part was constructed as scalar")
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

fn literal_unit_repeat_len(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> Option<usize> {
    const MAX_DEPTH: usize = 8;
    if depth > MAX_DEPTH {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Repeat(repeat) if unit_expr(&repeat.expr) => {
            repeat_count_in_scope(&repeat.len, fcx.scope())
        }
        Expr::Path(path) if path.qself.is_none() => {
            let name = path.path.get_ident()?.to_string();
            let init = fcx
                .let_inits()
                .get(&name)
                .copied()
                .or_else(|| fcx.scope().stable_let_binding_for_term(&name))?;
            literal_unit_repeat_len(init, fcx, depth + 1)
        }
        _ => None,
    }
}

fn unit_expr(expr: &Expr) -> bool {
    matches!(strip_refs_groups(expr), Expr::Tuple(tuple) if tuple.elems.is_empty())
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

fn term_body(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Effect> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_term()
            .unwrap_or_else(|| slice_search_gap("expected scalar reduced to non-term"))),
        Outcome::Incomplete(effect) => Err(effect),
    }
}

fn literal_sequence_body(
    body: &SugarBody<CompositeFloor>,
    ctx: &SugarCtx,
) -> Result<Vec<DesugaredElem>, Effect> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => Ok(d
            .into_seq()
            .unwrap_or_else(|| slice_search_gap("slice search receiver reduced to non-sequence"))),
        Outcome::Incomplete(effect) => Err(effect),
    }
}

fn int_values(seq: &[DesugaredElem]) -> Vec<i128> {
    seq.iter().map(elem_int).collect()
}

fn elem_int(elem: &DesugaredElem) -> i128 {
    elem.value
        .as_ref()
        .and_then(ConstVal::as_int)
        .unwrap_or_else(|| slice_search_gap("slice search element was not a literal int"))
}

fn path_ends_with(path: &syn::ExprPath, name: &str) -> bool {
    path.path
        .segments
        .last()
        .is_some_and(|seg| seg.ident == name)
}

fn slice_search_gap(reason: &str) -> ! {
    panic!("slice_search did not reach a lawful floor: {reason}")
}
