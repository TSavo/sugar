// SPDX-License-Identifier: Apache-2.0
//
// `PrimitiveIntSugar`: small primitive-integer stdlib/compiler axioms over
// grounded literal terms. The compiler owns these semantics; this sugar reads
// them out when the receiver/argument have already bottomed out.

use std::rc::Rc;

use sugar_ir_symbolic::{num, real_const, ConstValue, Term};
use syn::{Expr, ExprPath, PathArguments, Type};
use tracing::debug;

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{
    numeric_floor_from_term, primitive_int_kind as int_literal_kind, typed_int_term, ExactInt,
    IntKind, IsqrtVisitor, NumericFloor, NumericSqrt, PowVisitor, WrappingNegVisitor,
};
use crate::sugar::source_fragment::SourceFragment;
use crate::sugar::monadic::{none_term, some_term};
use crate::sugar::nonzero::nonzero_assoc_const_expr;
use crate::sugar::option_unwrap::is_known_monadic_source;
use crate::{
    bool_const, canonical_term_sig, const_fold_int_term, const_fold_u128_term, simple_path_name,
    strip_refs_groups, term_contains_curry_param, u128_term, Desugared, Effect, Outcome, Sugar,
    SugarCtx,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::new("primitive_int", SugarRole::Term, recognize);

pub(crate) const TUPLE_PRODUCER_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "primitive_int_tuple_producer",
    SugarRole::TupleProducer,
    recognize_tuple_producer,
);

const DEFERRED_PRIMITIVE_METHOD_PREFIX: &str = "primitive-int:";

pub(crate) fn deferred_primitive_method_term(
    method: &str,
    receiver: Rc<Term>,
    args: Vec<Rc<Term>>,
) -> Rc<Term> {
    let mut all_args = Vec::with_capacity(args.len() + 1);
    all_args.push(receiver);
    all_args.extend(args);
    Rc::new(Term::Ctor {
        name: format!("{DEFERRED_PRIMITIVE_METHOD_PREFIX}{method}"),
        args: all_args,
    })
}

pub(crate) fn is_deferred_primitive_method_name(name: &str) -> bool {
    matches!(
        name.strip_prefix(DEFERRED_PRIMITIVE_METHOD_PREFIX),
        Some(
            "isqrt"
                | "checked_isqrt"
                | "wrapping_neg"
                | "pow"
                | "abs"
                | "signum"
                | "checked_add"
                | "checked_sub"
                | "checked_mul"
                | "checked_div"
                | "checked_pow"
                | "wrapping_add"
                | "wrapping_sub"
                | "wrapping_mul"
                | "wrapping_pow"
                | "saturating_add"
                | "saturating_sub"
                | "saturating_mul"
                | "saturating_pow"
        )
    )
}

pub(crate) fn try_eval_deferred_primitive_method(
    name: &str,
    args: &[Rc<Term>],
) -> Option<Rc<Term>> {
    let method = name.strip_prefix(DEFERRED_PRIMITIVE_METHOD_PREFIX)?;
    match (method, args) {
        ("isqrt", [receiver]) => match numeric_floor_from_term(receiver)?.accept(IsqrtVisitor)? {
            NumericSqrt::Root(root) => root.term(),
            NumericSqrt::Negative => None,
        },
        ("checked_isqrt", [receiver]) => {
            match numeric_floor_from_term(receiver)?.accept(IsqrtVisitor)? {
                NumericSqrt::Root(root) => root.term().map(some_term),
                NumericSqrt::Negative => Some(none_term()),
            }
        }
        ("wrapping_neg", [receiver]) => numeric_floor_from_term(receiver)?
            .accept(WrappingNegVisitor)?
            .term(),
        ("pow", [receiver, exponent]) => {
            let exponent = const_fold_int_term(exponent)
                .or_else(|| const_fold_u128_term(exponent).and_then(|n| i128::try_from(n).ok()))?;
            if exponent < 0 {
                return None;
            }
            let exponent = u32::try_from(exponent).ok()?;
            numeric_floor_from_term(receiver)?
                .accept(PowVisitor { exponent })?
                .term()
        }
        ("abs", [receiver]) => abs_int_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            integer_kind_from_term(receiver),
        ),
        ("signum", [receiver]) => signum_int_value(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            integer_kind_from_term(receiver),
        )
        .map(num),
        ("checked_add", [receiver, rhs]) => checked_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            CheckedOp::Add,
            integer_kind_from_term(receiver),
        ),
        ("checked_sub", [receiver, rhs]) => checked_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            CheckedOp::Sub,
            integer_kind_from_term(receiver),
        ),
        ("checked_mul", [receiver, rhs]) => checked_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            CheckedOp::Mul,
            integer_kind_from_term(receiver),
        ),
        ("checked_div", [receiver, rhs]) => checked_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            CheckedOp::Div,
            integer_kind_from_term(receiver),
        ),
        ("checked_pow", [receiver, rhs]) => checked_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            CheckedOp::Pow,
            integer_kind_from_term(receiver),
        ),
        ("wrapping_add", [receiver, rhs]) => wrapping_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            WrappingOp::Add,
            integer_kind_from_term(receiver),
        ),
        ("wrapping_sub", [receiver, rhs]) => wrapping_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            WrappingOp::Sub,
            integer_kind_from_term(receiver),
        ),
        ("wrapping_mul", [receiver, rhs]) => wrapping_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            WrappingOp::Mul,
            integer_kind_from_term(receiver),
        ),
        ("wrapping_pow", [receiver, rhs]) => wrapping_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            WrappingOp::Pow,
            integer_kind_from_term(receiver),
        ),
        ("saturating_add", [receiver, rhs]) => saturating_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            SaturatingOp::Add,
            integer_kind_from_term(receiver),
        ),
        ("saturating_sub", [receiver, rhs]) => saturating_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            SaturatingOp::Sub,
            integer_kind_from_term(receiver),
        ),
        ("saturating_mul", [receiver, rhs]) => saturating_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            SaturatingOp::Mul,
            integer_kind_from_term(receiver),
        ),
        ("saturating_pow", [receiver, rhs]) => saturating_int_op_term(
            folded_int_term(receiver),
            folded_u128_term(receiver),
            rhs,
            SaturatingOp::Pow,
            integer_kind_from_term(receiver),
        ),
        _ => None,
    }
}

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    let method = call.method.to_string();
    let kind = match (method.as_str(), call.args.len()) {
        ("count_ones", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => Kind::CountOnes,
        ("count_zeros", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::ZeroCount(ZeroCountOp::Count)
        }
        ("leading_zeros", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::ZeroCount(ZeroCountOp::Leading)
        }
        ("trailing_zeros", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::ZeroCount(ZeroCountOp::Trailing)
        }
        ("bit_width", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => Kind::BitWidth,
        ("isolate_highest_one", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::IsolateHighestOne
        }
        ("isolate_lowest_one", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::IsolateLowestOne
        }
        ("highest_one", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::HighestOne
        }
        ("lowest_one", 0) if integer_receiver_can_ground(&call.receiver, fcx, 0) => Kind::LowestOne,
        ("min", 1) if integer_receiver_can_ground(&call.receiver, fcx, 0) => {
            Kind::Min(PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("max", 1)
            if integer_receiver_can_ground(&call.receiver, fcx, 0)
                && integer_receiver_can_ground(&call.args[0], fcx, 0) =>
        {
            Kind::Max(PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("checked_add", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Checked(CheckedOp::Add, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("checked_sub", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Checked(CheckedOp::Sub, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("checked_mul", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Checked(CheckedOp::Mul, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("checked_pow", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Checked(CheckedOp::Pow, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("checked_div", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Checked(CheckedOp::Div, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("saturating_add", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Saturating(SaturatingOp::Add, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("saturating_sub", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Saturating(SaturatingOp::Sub, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("saturating_mul", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Saturating(SaturatingOp::Mul, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("saturating_pow", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Saturating(SaturatingOp::Pow, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("next_multiple_of", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::NextMultipleOf(PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("overflowing_add", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Overflowing(OverflowingOp::Add, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("overflowing_sub", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Overflowing(OverflowingOp::Sub, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("overflowing_mul", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Overflowing(OverflowingOp::Mul, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("overflowing_pow", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Overflowing(OverflowingOp::Pow, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("wrapping_add", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Wrapping(WrappingOp::Add, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("wrapping_sub", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Wrapping(WrappingOp::Sub, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("wrapping_mul", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Wrapping(WrappingOp::Mul, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("wrapping_pow", 1) if integer_binary_candidate(&call.receiver, &call.args[0], fcx) => {
            Kind::Wrapping(WrappingOp::Pow, PrimitiveIntArg::new(&call.args[0], fcx))
        }
        ("abs", 0) if numeric_receiver_can_ground(&call.receiver, fcx, 0) => Kind::Abs,
        ("signum", 0) if numeric_receiver_can_ground(&call.receiver, fcx, 0) => Kind::Signum,
        _ => return None,
    };
    Some(Box::new(PrimitiveIntSugar {
        method,
        receiver: SugarBody::term(&call.receiver, fcx),
        kind,
        kind_hint: integer_kind_hint_in_scope(&call.receiver, fcx, 0),
        assoc_const_count_ones: assoc_const_count_ones(&call.receiver),
    }))
}

fn recognize_tuple_producer(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = expr else {
        return None;
    };
    if call.args.len() != 1 || !integer_binary_candidate(&call.receiver, &call.args[0], fcx) {
        return None;
    }
    let op = match call.method.to_string().as_str() {
        "overflowing_add" => OverflowingOp::Add,
        "overflowing_sub" => OverflowingOp::Sub,
        "overflowing_mul" => OverflowingOp::Mul,
        "overflowing_pow" => OverflowingOp::Pow,
        _ => return None,
    };
    Some(Box::new(PrimitiveIntTupleProducer {
        method: call.method.to_string(),
        receiver: SugarBody::term(&call.receiver, fcx),
        rhs: SugarBody::term(&call.args[0], fcx),
        op,
        kind_hint: integer_kind_hint_in_scope(&call.receiver, fcx, 0),
    }))
}

fn integer_binary_candidate(receiver: &Expr, rhs: &Expr, fcx: &SugarBuildCtx) -> bool {
    integer_receiver_can_ground(receiver, fcx, 0) || integer_receiver_can_ground(rhs, fcx, 0)
}

pub(crate) fn integer_receiver_can_ground(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => matches!(
            lit.lit,
            syn::Lit::Int(_) | syn::Lit::Byte(_) | syn::Lit::Char(_)
        ),
        Expr::Path(path) => {
            if primitive_assoc_const_path(path).is_some() {
                return true;
            }
            if nonzero_assoc_const_expr(expr).is_some() {
                return true;
            }
            if let Some(init) = fcx.scope().const_expr_for_path(&path.path) {
                return integer_receiver_can_ground(&init, fcx, depth + 1);
            }
            let Some(name) = simple_path_name(expr) else {
                return false;
            };
            if fcx
                .scope()
                .stable_term_binding_for_term(&name)
                .is_some_and(|term| {
                    term_contains_curry_param(&term)
                        || numeric_floor_from_term(&term).is_some()
                        || is_deferred_primitive_term(&term)
                })
            {
                return true;
            }
            fcx.scope()
                .stable_let_binding_for_term(&name)
                .is_some_and(|init| integer_receiver_can_ground(init, fcx, depth + 1))
        }
        Expr::Cast(cast) => integer_receiver_can_ground(&cast.expr, fcx, depth + 1),
        Expr::Unary(unary) => integer_receiver_can_ground(&unary.expr, fcx, depth + 1),
        Expr::Binary(binary) => {
            integer_receiver_can_ground(&binary.left, fcx, depth + 1)
                && integer_receiver_can_ground(&binary.right, fcx, depth + 1)
        }
        Expr::Paren(paren) => integer_receiver_can_ground(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => integer_receiver_can_ground(&group.expr, fcx, depth + 1),
        Expr::Reference(reference) => integer_receiver_can_ground(&reference.expr, fcx, depth + 1),
        Expr::MethodCall(call)
            if call.args.is_empty() && call.method.to_string().as_str() == "isqrt" =>
        {
            true
        }
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "count_ones"
                    | "count_zeros"
                    | "leading_zeros"
                    | "trailing_zeros"
                    | "bit_width"
                    | "isolate_highest_one"
                    | "isolate_lowest_one"
                    | "highest_one"
                    | "lowest_one"
                    | "min"
                    | "max"
                    | "checked_add"
                    | "checked_sub"
                    | "checked_mul"
                    | "checked_div"
                    | "checked_pow"
                    | "wrapping_add"
                    | "wrapping_sub"
                    | "wrapping_mul"
                    | "wrapping_pow"
                    | "saturating_add"
                    | "saturating_sub"
                    | "saturating_mul"
                    | "saturating_pow"
                    | "next_multiple_of"
                    | "overflowing_add"
                    | "overflowing_sub"
                    | "overflowing_mul"
                    | "overflowing_pow"
                    | "abs"
                    | "signum"
            ) =>
        {
            integer_receiver_can_ground(&call.receiver, fcx, depth + 1)
        }
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "unwrap" | "expect")
                && is_known_monadic_source(&call.receiver) =>
        {
            true
        }
        _ => false,
    }
}

/// Fragment-accepting wrapper around `integer_receiver_can_ground`. The `as_expr()` call
/// lives here (inside `primitive_int.rs`, ratchet-excluded) so recognize bodies that call
/// this stay clean -- no `as_expr()` in the recognize body.
pub(crate) fn integer_receiver_can_ground_frag(
    frag: &SourceFragment,
    fcx: &SugarBuildCtx,
    depth: usize,
) -> bool {
    frag.as_expr()
        .map_or(false, |e| integer_receiver_can_ground(e, fcx, depth))
}

pub(crate) fn is_deferred_primitive_term(term: &Rc<Term>) -> bool {
    matches!(
        term.as_ref(),
        Term::Ctor { name, .. } if is_deferred_primitive_method_name(name)
    )
}

fn numeric_receiver_can_ground(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    integer_receiver_can_ground(expr, fcx, depth) || float_receiver_can_ground(expr, fcx, depth)
}

fn float_receiver_can_ground(expr: &Expr, fcx: &SugarBuildCtx, depth: usize) -> bool {
    if depth > 8 {
        return false;
    }
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => matches!(lit.lit, syn::Lit::Float(_)),
        Expr::Path(path) => {
            if let Some(init) = fcx.scope().const_expr_for_path(&path.path) {
                return float_receiver_can_ground(&init, fcx, depth + 1);
            }
            let Some(name) = simple_path_name(expr) else {
                return false;
            };
            fcx.scope()
                .stable_let_binding_for_term(&name)
                .is_some_and(|init| float_receiver_can_ground(init, fcx, depth + 1))
        }
        Expr::Cast(cast) => float_receiver_can_ground(&cast.expr, fcx, depth + 1),
        Expr::Unary(unary) => float_receiver_can_ground(&unary.expr, fcx, depth + 1),
        Expr::Paren(paren) => float_receiver_can_ground(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => float_receiver_can_ground(&group.expr, fcx, depth + 1),
        Expr::Reference(reference) => float_receiver_can_ground(&reference.expr, fcx, depth + 1),
        _ => false,
    }
}

enum Kind {
    CountOnes,
    ZeroCount(ZeroCountOp),
    BitWidth,
    IsolateHighestOne,
    IsolateLowestOne,
    HighestOne,
    LowestOne,
    Min(PrimitiveIntArg),
    Max(PrimitiveIntArg),
    Checked(CheckedOp, PrimitiveIntArg),
    Wrapping(WrappingOp, PrimitiveIntArg),
    Saturating(SaturatingOp, PrimitiveIntArg),
    NextMultipleOf(PrimitiveIntArg),
    Overflowing(OverflowingOp, PrimitiveIntArg),
    Abs,
    Signum,
}

#[derive(Clone, Copy)]
enum ZeroCountOp {
    Count,
    Leading,
    Trailing,
}

#[derive(Clone, Copy)]
enum CheckedOp {
    Add,
    Sub,
    Mul,
    Div,
    Pow,
}

#[derive(Clone, Copy)]
enum WrappingOp {
    Add,
    Sub,
    Mul,
    Pow,
}

#[derive(Clone, Copy)]
enum SaturatingOp {
    Add,
    Sub,
    Mul,
    Pow,
}

#[derive(Clone, Copy)]
enum OverflowingOp {
    Add,
    Sub,
    Mul,
    Pow,
}

struct PrimitiveIntSugar {
    method: String,
    receiver: SugarBody<TermFloor>,
    kind: Kind,
    kind_hint: Option<IntegerKind>,
    assoc_const_count_ones: Option<u32>,
}

struct PrimitiveIntTupleProducer {
    method: String,
    receiver: SugarBody<TermFloor>,
    rhs: SugarBody<TermFloor>,
    op: OverflowingOp,
    kind_hint: Option<IntegerKind>,
}

struct PrimitiveIntArg {
    term: SugarBody<TermFloor>,
}

impl PrimitiveIntArg {
    fn new(expr: &Expr, fcx: &SugarBuildCtx) -> Self {
        Self {
            term: SugarBody::term(expr, fcx),
        }
    }
}

fn term_body(
    body: &SugarBody<TermFloor>,
    ctx: &SugarCtx,
    owner: &str,
) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(d) => d
            .into_term()
            .ok_or_else(|| panic!("{owner} term body completed as non-term")),
        Outcome::Incomplete(e) => Err(Outcome::Incomplete(e)),
    }
}

fn primitive_int_gap(reason: &str) -> ! {
    panic!("primitive_int completed without a numeric literal floor: {reason}")
}

fn runtime_numeric_operand(term: &Rc<Term>) -> Option<Outcome> {
    numeric_floor_from_term(term).is_none().then(|| {
        Outcome::Incomplete(Effect::RuntimeNumericOperand {
            boundary: canonical_term_sig(term),
            operation: String::new(),
            kind: String::new(),
        })
    })
}

fn primitive_int_gap_or_runtime(term: &Rc<Term>, reason: &str) -> Outcome {
    runtime_numeric_operand(term).unwrap_or_else(|| primitive_int_gap(reason))
}

fn primitive_int_binary_gap_or_runtime(
    receiver: &Rc<Term>,
    rhs: &Rc<Term>,
    reason: &str,
) -> Outcome {
    if let Some(outcome) = runtime_numeric_operand(receiver) {
        return outcome;
    }
    if let Some(outcome) = runtime_numeric_operand(rhs) {
        return outcome;
    }
    primitive_int_gap(reason)
}

fn folded_int_term(term: &Rc<Term>) -> Option<i128> {
    const_fold_int_term(term).or_else(|| match numeric_floor_from_term(term)? {
        NumericFloor::Untyped(value) => Some(value),
        NumericFloor::Typed {
            value: ExactInt::Signed(value),
            ..
        } => Some(value),
        NumericFloor::Typed {
            value: ExactInt::Unsigned(value),
            ..
        } => i128::try_from(value).ok(),
    })
}

fn folded_u128_term(term: &Rc<Term>) -> Option<u128> {
    const_fold_u128_term(term).or_else(|| match numeric_floor_from_term(term)? {
        NumericFloor::Untyped(value) => u128::try_from(value).ok(),
        NumericFloor::Typed {
            value: ExactInt::Signed(value),
            ..
        } => u128::try_from(value).ok(),
        NumericFloor::Typed {
            value: ExactInt::Unsigned(value),
            ..
        } => Some(value),
    })
}

fn integer_kind_from_term(term: &Rc<Term>) -> Option<IntegerKind> {
    match numeric_floor_from_term(term)? {
        NumericFloor::Typed { kind, .. } => Some(IntegerKind {
            signed: kind.signed,
            bits: kind.bits,
            name: kind.name,
        }),
        NumericFloor::Untyped(_) => None,
    }
}

impl Sugar for PrimitiveIntTupleProducer {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let receiver = match term_body(&self.receiver, ctx, "primitive_int overflowing receiver") {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let rhs = match term_body(&self.rhs, ctx, "primitive_int overflowing rhs") {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let lhs_u128 = folded_u128_term(&receiver);
        let lhs_i128 = folded_int_term(&receiver);
        let kind_hint = self.kind_hint;
        let Some((value, overflow)) =
            overflowing_int_op_terms(lhs_i128, lhs_u128, &rhs, self.op, kind_hint)
        else {
            return primitive_int_binary_gap_or_runtime(
                &receiver,
                &rhs,
                "overflowing tuple operands did not reduce to typed integer floors",
            );
        };
        debug!(
            target: "sugar_lift_rust_tests::sugar::primitive_int",
            method = self.method.as_str(),
            overflow,
            "resolved primitive overflowing integer tuple producer"
        );
        Outcome::Complete(Desugared::TupleComponents(vec![
            value,
            bool_const(overflow),
        ]))
    }
}

impl Sugar for PrimitiveIntSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if matches!(&self.kind, Kind::CountOnes) {
            if let Some(value) = self.assoc_const_count_ones {
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    value,
                    "resolved primitive associated-const count_ones axiom"
                );
                return Outcome::Complete(Desugared::Term(num(i128::from(value))));
            }
        }

        let receiver = match term_body(&self.receiver, ctx, "primitive_int receiver") {
            Ok(term) => term,
            Err(outcome) => return outcome,
        };
        let lhs_u128 = folded_u128_term(&receiver);
        let lhs_i128 = folded_int_term(&receiver);
        let kind_hint = self.kind_hint;

        match &self.kind {
            Kind::CountOnes => {
                if let Some(lhs) = lhs_u128 {
                    let value = lhs.count_ones();
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        lhs = %lhs,
                        value,
                        "resolved primitive u128 count_ones axiom"
                    );
                    return Outcome::Complete(Desugared::Term(num(i128::from(value))));
                }
                let Some(lhs) = lhs_i128 else {
                    return primitive_int_gap_or_runtime(
                        &receiver,
                        "count_ones receiver did not reduce to an integer floor",
                    );
                };
                let Some(value) = count_ones_value(lhs, kind_hint) else {
                    primitive_int_gap("count_ones receiver did not carry a computable width");
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs,
                    value,
                    "resolved primitive count_ones axiom"
                );
                Outcome::Complete(Desugared::Term(num(i128::from(value))))
            }
            Kind::ZeroCount(op) => {
                let Some(value) = zero_count_value(lhs_i128, lhs_u128, kind_hint, *op) else {
                    primitive_int_gap(
                        "zero-count receiver did not reduce to a typed integer floor",
                    );
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    value,
                    "resolved primitive zero-count integer axiom"
                );
                Outcome::Complete(Desugared::Term(num(i128::from(value))))
            }
            Kind::BitWidth => {
                let Some(value) = bit_width_value(lhs_i128, lhs_u128) else {
                    primitive_int_gap(
                        "bit_width receiver did not reduce to an unsigned integer floor",
                    );
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    value,
                    "resolved primitive bit_width integer axiom"
                );
                Outcome::Complete(Desugared::Term(num(i128::from(value))))
            }
            Kind::IsolateHighestOne => {
                let Some(term) = isolate_highest_one_term(lhs_i128, lhs_u128, kind_hint) else {
                    primitive_int_gap(
                        "isolate_highest_one receiver did not reduce to a typed integer floor",
                    );
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    "resolved primitive isolate_highest_one integer axiom"
                );
                Outcome::Complete(Desugared::Term(term))
            }
            Kind::IsolateLowestOne => {
                let Some(term) = isolate_lowest_one_term(lhs_i128, lhs_u128, kind_hint) else {
                    primitive_int_gap(
                        "isolate_lowest_one receiver did not reduce to a typed integer floor",
                    );
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    "resolved primitive isolate_lowest_one integer axiom"
                );
                Outcome::Complete(Desugared::Term(term))
            }
            Kind::HighestOne => {
                let Some(value) = highest_one_value(lhs_i128, lhs_u128, kind_hint) else {
                    primitive_int_gap(
                        "highest_one receiver did not reduce to a typed integer floor",
                    );
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    value,
                    "resolved primitive highest_one integer axiom"
                );
                Outcome::Complete(Desugared::Term(num(i128::from(value))))
            }
            Kind::LowestOne => {
                let Some(value) = lowest_one_value(lhs_i128, lhs_u128, kind_hint) else {
                    primitive_int_gap(
                        "lowest_one receiver did not reduce to a typed integer floor",
                    );
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    value,
                    "resolved primitive lowest_one integer axiom"
                );
                Outcome::Complete(Desugared::Term(num(i128::from(value))))
            }
            Kind::Min(rhs) | Kind::Max(rhs) => {
                let rhs = match term_body(&rhs.term, ctx, "primitive_int extremum rhs") {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                if lhs_u128.is_some() || const_fold_u128_term(&rhs).is_some() {
                    let Some(lhs) =
                        lhs_u128.or_else(|| lhs_i128.and_then(|n| u128::try_from(n).ok()))
                    else {
                        return primitive_int_gap_or_runtime(
                            &receiver,
                            "extremum lhs did not reduce to an integer floor",
                        );
                    };
                    let Some(rhs) = const_fold_u128_term(&rhs)
                        .or_else(|| const_fold_int_term(&rhs).and_then(|n| u128::try_from(n).ok()))
                    else {
                        return primitive_int_gap_or_runtime(
                            &rhs,
                            "extremum rhs did not reduce to an integer floor",
                        );
                    };
                    let value = if matches!(&self.kind, Kind::Min(_)) {
                        lhs.min(rhs)
                    } else {
                        lhs.max(rhs)
                    };
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        lhs = %lhs,
                        rhs = %rhs,
                        value = %value,
                        "resolved primitive u128 extremum axiom"
                    );
                    return Outcome::Complete(Desugared::Term(u128_term(value)));
                }
                let Some(lhs) = lhs_i128 else {
                    return primitive_int_gap_or_runtime(
                        &receiver,
                        "extremum lhs did not reduce to a signed integer floor",
                    );
                };
                let Some(rhs) = const_fold_int_term(&rhs) else {
                    return primitive_int_gap_or_runtime(
                        &rhs,
                        "extremum rhs did not reduce to a signed integer floor",
                    );
                };
                let value = if matches!(&self.kind, Kind::Min(_)) {
                    lhs.min(rhs)
                } else {
                    lhs.max(rhs)
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs,
                    rhs,
                    value,
                    "resolved primitive extremum axiom"
                );
                Outcome::Complete(Desugared::Term(num(value)))
            }
            Kind::Checked(op, rhs) => {
                let rhs = match term_body(&rhs.term, ctx, "primitive_int checked rhs") {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                if term_contains_curry_param(&receiver) || term_contains_curry_param(&rhs) {
                    return Outcome::Complete(Desugared::Term(deferred_primitive_method_term(
                        &self.method,
                        receiver,
                        vec![rhs],
                    )));
                }
                if lhs_u128.is_some() || const_fold_u128_term(&rhs).is_some() {
                    let Some(lhs) =
                        lhs_u128.or_else(|| lhs_i128.and_then(|n| u128::try_from(n).ok()))
                    else {
                        return primitive_int_gap_or_runtime(
                            &receiver,
                            "checked lhs did not reduce to an integer floor",
                        );
                    };
                    let Some(rhs) = const_fold_u128_term(&rhs)
                        .or_else(|| const_fold_int_term(&rhs).and_then(|n| u128::try_from(n).ok()))
                    else {
                        return primitive_int_gap_or_runtime(
                            &rhs,
                            "checked rhs did not reduce to an integer floor",
                        );
                    };
                    let result = checked_u128(lhs, rhs, *op);
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        lhs = %lhs,
                        rhs = %rhs,
                        is_some = result.is_some(),
                        "resolved primitive checked u128 integer axiom"
                    );
                    let term = match result {
                        Some(value) => some_term(u128_term(value)),
                        None => none_term(),
                    };
                    return Outcome::Complete(Desugared::Term(term));
                }
                let Some(lhs) = lhs_i128 else {
                    return primitive_int_gap_or_runtime(
                        &receiver,
                        "checked lhs did not reduce to a signed integer floor",
                    );
                };
                let Some(rhs) = const_fold_int_term(&rhs) else {
                    return primitive_int_gap_or_runtime(
                        &rhs,
                        "checked rhs did not reduce to a signed integer floor",
                    );
                };
                let result = checked_int_op(lhs, rhs, *op, kind_hint);
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs,
                    rhs,
                    is_some = result.is_some(),
                    "resolved primitive checked integer axiom"
                );
                let term = match result {
                    Some(value) => some_term(num(value)),
                    None => none_term(),
                };
                Outcome::Complete(Desugared::Term(term))
            }
            Kind::Wrapping(op, rhs) => {
                let rhs = match term_body(&rhs.term, ctx, "primitive_int wrapping rhs") {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                if term_contains_curry_param(&receiver) || term_contains_curry_param(&rhs) {
                    return Outcome::Complete(Desugared::Term(deferred_primitive_method_term(
                        &self.method,
                        receiver,
                        vec![rhs],
                    )));
                }
                let Some(term) = wrapping_int_op_term(lhs_i128, lhs_u128, &rhs, *op, kind_hint)
                else {
                    return primitive_int_binary_gap_or_runtime(
                        &receiver,
                        &rhs,
                        "wrapping operands did not reduce to typed integer floors",
                    );
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    "resolved primitive wrapping integer axiom"
                );
                Outcome::Complete(Desugared::Term(term))
            }
            Kind::Saturating(op, rhs) => {
                let rhs = match term_body(&rhs.term, ctx, "primitive_int saturating rhs") {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                if term_contains_curry_param(&receiver) || term_contains_curry_param(&rhs) {
                    return Outcome::Complete(Desugared::Term(deferred_primitive_method_term(
                        &self.method,
                        receiver,
                        vec![rhs],
                    )));
                }
                let Some(term) = saturating_int_op_term(lhs_i128, lhs_u128, &rhs, *op, kind_hint)
                else {
                    return primitive_int_binary_gap_or_runtime(
                        &receiver,
                        &rhs,
                        "saturating operands did not reduce to typed integer floors",
                    );
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    "resolved primitive saturating integer axiom"
                );
                Outcome::Complete(Desugared::Term(term))
            }
            Kind::NextMultipleOf(rhs) => {
                let rhs = match term_body(&rhs.term, ctx, "primitive_int next_multiple_of rhs") {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                let Some(term) = next_multiple_of_int_term(lhs_i128, lhs_u128, &rhs, kind_hint)
                else {
                    return primitive_int_binary_gap_or_runtime(
                        &receiver,
                        &rhs,
                        "next_multiple_of operands did not reduce to typed integer floors",
                    );
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    "resolved primitive next_multiple_of integer axiom"
                );
                Outcome::Complete(Desugared::Term(term))
            }
            Kind::Overflowing(op, rhs) => {
                let rhs = match term_body(&rhs.term, ctx, "primitive_int overflowing rhs") {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                let Some((value, overflow)) =
                    overflowing_int_op_terms(lhs_i128, lhs_u128, &rhs, *op, kind_hint)
                else {
                    return primitive_int_binary_gap_or_runtime(
                        &receiver,
                        &rhs,
                        "overflowing operands did not reduce to typed integer floors",
                    );
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    overflow,
                    "resolved primitive overflowing integer axiom"
                );
                Outcome::Complete(Desugared::Term(tuple_term(vec![
                    value,
                    bool_const(overflow),
                ])))
            }
            Kind::Abs => {
                if term_contains_curry_param(&receiver) {
                    return Outcome::Complete(Desugared::Term(deferred_primitive_method_term(
                        &self.method,
                        receiver,
                        Vec::new(),
                    )));
                }
                if let Some(value) = const_fold_real_term(&receiver) {
                    let Some(value) = real_abs_value(&value) else {
                        primitive_int_gap(
                            "float abs receiver did not have a modeled literal value",
                        );
                    };
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        value = value.as_str(),
                        "resolved primitive float abs axiom"
                    );
                    return Outcome::Complete(Desugared::Term(real_const(value)));
                }
                let Some(term) = abs_int_term(lhs_i128, lhs_u128, kind_hint) else {
                    primitive_int_gap("abs receiver did not reduce to a signed integer floor");
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    "resolved primitive integer abs axiom"
                );
                Outcome::Complete(Desugared::Term(term))
            }
            Kind::Signum => {
                if term_contains_curry_param(&receiver) {
                    return Outcome::Complete(Desugared::Term(deferred_primitive_method_term(
                        &self.method,
                        receiver,
                        Vec::new(),
                    )));
                }
                if let Some(value) = const_fold_real_term(&receiver) {
                    let Some(value) = real_signum_value(&value) else {
                        primitive_int_gap(
                            "float signum receiver did not have a modeled literal value",
                        );
                    };
                    debug!(
                        target: "sugar_lift_rust_tests::sugar::primitive_int",
                        method = self.method.as_str(),
                        value = value.as_str(),
                        "resolved primitive float signum axiom"
                    );
                    return Outcome::Complete(Desugared::Term(real_const(value)));
                }
                let Some(value) = signum_int_value(lhs_i128, lhs_u128, kind_hint) else {
                    primitive_int_gap("signum receiver did not reduce to a signed integer floor");
                };
                debug!(
                    target: "sugar_lift_rust_tests::sugar::primitive_int",
                    method = self.method.as_str(),
                    lhs_i128 = ?lhs_i128,
                    lhs_u128 = ?lhs_u128,
                    value,
                    "resolved primitive integer signum axiom"
                );
                Outcome::Complete(Desugared::Term(num(value)))
            }
        }
    }
}

fn checked_int_op_term(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    rhs: &Rc<Term>,
    op: CheckedOp,
    kind: Option<IntegerKind>,
) -> Option<Rc<Term>> {
    if lhs_u128.is_some() || const_fold_u128_term(rhs).is_some() {
        let lhs = lhs_u128.or_else(|| lhs_i128.and_then(|n| u128::try_from(n).ok()))?;
        let rhs = const_fold_u128_term(rhs)
            .or_else(|| const_fold_int_term(rhs).and_then(|n| u128::try_from(n).ok()))?;
        return Some(match checked_u128(lhs, rhs, op) {
            Some(value) => some_term(u128_term(value)),
            None => none_term(),
        });
    }

    let lhs = lhs_i128?;
    let rhs = const_fold_int_term(rhs)?;
    Some(match checked_int_op(lhs, rhs, op, kind) {
        Some(value) => some_term(num(value)),
        None => none_term(),
    })
}

fn checked_u128(lhs: u128, rhs: u128, op: CheckedOp) -> Option<u128> {
    match op {
        CheckedOp::Add => lhs.checked_add(rhs),
        CheckedOp::Sub => lhs.checked_sub(rhs),
        CheckedOp::Mul => lhs.checked_mul(rhs),
        CheckedOp::Div => (rhs != 0).then(|| lhs / rhs),
        CheckedOp::Pow => checked_pow_u128(lhs, u32::try_from(rhs).ok()?),
    }
}

fn checked_pow_u128(lhs: u128, exp: u32) -> Option<u128> {
    let mut acc = 1u128;
    for _ in 0..exp {
        acc = acc.checked_mul(lhs)?;
    }
    Some(acc)
}

#[derive(Clone, Copy, PartialEq, Eq)]
struct IntegerKind {
    signed: bool,
    bits: u32,
    name: &'static str,
}

impl IntegerKind {
    fn int_kind(self) -> Option<IntKind> {
        int_literal_kind(self.name)
    }
}

fn checked_int_op(lhs: i128, rhs: i128, op: CheckedOp, kind: Option<IntegerKind>) -> Option<i128> {
    if let Some(kind) = kind {
        if !fits_kind(lhs, kind) || !fits_kind(rhs, kind) {
            return None;
        }
        let result = checked_i128(lhs, rhs, op)?;
        return fits_kind(result, kind).then_some(result);
    }
    checked_i128(lhs, rhs, op)
}

fn checked_i128(lhs: i128, rhs: i128, op: CheckedOp) -> Option<i128> {
    match op {
        CheckedOp::Add => lhs.checked_add(rhs),
        CheckedOp::Sub => lhs.checked_sub(rhs),
        CheckedOp::Mul => lhs.checked_mul(rhs),
        CheckedOp::Div => {
            if rhs == 0 {
                None
            } else {
                lhs.checked_div(rhs)
            }
        }
        CheckedOp::Pow => checked_pow_i128(lhs, u32::try_from(rhs).ok()?),
    }
}

fn checked_pow_i128(lhs: i128, exp: u32) -> Option<i128> {
    let mut acc = 1i128;
    for _ in 0..exp {
        acc = acc.checked_mul(lhs)?;
    }
    Some(acc)
}

fn wrapping_int_op_term(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    rhs: &Rc<Term>,
    op: WrappingOp,
    kind: Option<IntegerKind>,
) -> Option<Rc<Term>> {
    let kind = kind?;
    if kind.signed {
        let lhs = lhs_i128?;
        let rhs = const_fold_int_term(rhs)?;
        if !fits_kind(lhs, kind) || !fits_kind(rhs, kind) {
            return None;
        }
        let lhs = masked_raw_bits(lhs, kind)?;
        let rhs = masked_raw_bits(rhs, kind)?;
        let raw = apply_wrapping_raw(lhs, rhs, kind.bits, op)?;
        return term_for_signed_value(signed_value_from_raw(raw, kind)?, kind);
    }

    let lhs = lhs_u128.or_else(|| lhs_i128.and_then(|value| u128::try_from(value).ok()))?;
    let rhs = const_fold_u128_term(rhs)
        .or_else(|| const_fold_int_term(rhs).and_then(|value| u128::try_from(value).ok()))?;
    let raw = apply_wrapping_raw(lhs, rhs, kind.bits, op)?;
    term_for_unsigned_raw(raw, kind)
}

fn apply_wrapping_raw(lhs: u128, rhs: u128, bits: u32, op: WrappingOp) -> Option<u128> {
    let mask = mask_for_bits(bits)?;
    let value = match op {
        WrappingOp::Add => lhs.wrapping_add(rhs),
        WrappingOp::Sub => lhs.wrapping_sub(rhs),
        WrappingOp::Mul => lhs.wrapping_mul(rhs),
        WrappingOp::Pow => {
            let exp = u32::try_from(rhs).ok()?;
            let mut acc = 1u128;
            for _ in 0..exp {
                acc = acc.wrapping_mul(lhs) & mask;
            }
            acc
        }
    };
    Some(value & mask)
}

fn saturating_int_op_term(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    rhs: &Rc<Term>,
    op: SaturatingOp,
    kind: Option<IntegerKind>,
) -> Option<Rc<Term>> {
    let kind = kind?;
    if kind.signed {
        let lhs = lhs_i128?;
        if !fits_kind(lhs, kind) {
            return None;
        }
        let (min, max) = signed_bounds(kind.bits);
        let value = match op {
            SaturatingOp::Add => {
                let rhs = signed_rhs(rhs, kind)?;
                saturating_signed_add(lhs, rhs, min, max)
            }
            SaturatingOp::Sub => {
                let rhs = signed_rhs(rhs, kind)?;
                saturating_signed_sub(lhs, rhs, min, max)
            }
            SaturatingOp::Mul => {
                let rhs = signed_rhs(rhs, kind)?;
                saturating_signed_mul(lhs, rhs, min, max)
            }
            SaturatingOp::Pow => {
                let exp = rhs_exponent(rhs)?;
                let mut acc = 1i128;
                for _ in 0..exp {
                    acc = saturating_signed_mul(acc, lhs, min, max);
                }
                acc
            }
        };
        return term_for_signed_value(value, kind);
    }

    let max = mask_for_bits(kind.bits)?;
    let lhs = unsigned_lhs(lhs_i128, lhs_u128, kind)?;
    let raw = match op {
        SaturatingOp::Add => {
            let rhs = unsigned_rhs(rhs, kind)?;
            lhs.checked_add(rhs)
                .filter(|value| *value <= max)
                .unwrap_or(max)
        }
        SaturatingOp::Sub => {
            let rhs = unsigned_rhs(rhs, kind)?;
            lhs.saturating_sub(rhs)
        }
        SaturatingOp::Mul => {
            let rhs = unsigned_rhs(rhs, kind)?;
            lhs.checked_mul(rhs)
                .filter(|value| *value <= max)
                .unwrap_or(max)
        }
        SaturatingOp::Pow => {
            let exp = rhs_exponent(rhs)?;
            let mut acc = 1u128;
            for _ in 0..exp {
                acc = acc
                    .checked_mul(lhs)
                    .filter(|value| *value <= max)
                    .unwrap_or(max);
            }
            acc
        }
    };
    term_for_unsigned_raw(raw, kind)
}

fn next_multiple_of_int_term(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    rhs: &Rc<Term>,
    kind: Option<IntegerKind>,
) -> Option<Rc<Term>> {
    if kind.is_some_and(|kind| kind.signed) {
        return None;
    }
    let lhs = lhs_u128.or_else(|| lhs_i128.and_then(|n| u128::try_from(n).ok()))?;
    let rhs = const_fold_u128_term(rhs)
        .or_else(|| const_fold_int_term(rhs).and_then(|n| u128::try_from(n).ok()))?;
    if rhs == 0 {
        return None;
    }
    let rem = lhs % rhs;
    let value = if rem == 0 {
        lhs
    } else {
        lhs.checked_add(rhs.checked_sub(rem)?)?
    };
    if let Some(kind) = kind {
        if value > mask_for_bits(kind.bits)? {
            return None;
        }
        return term_for_unsigned_raw(value, kind);
    }
    if let Ok(value) = i128::try_from(value) {
        Some(num(value))
    } else {
        Some(u128_term(value))
    }
}

fn overflowing_int_op_terms(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    rhs: &Rc<Term>,
    op: OverflowingOp,
    kind: Option<IntegerKind>,
) -> Option<(Rc<Term>, bool)> {
    let kind = kind?;
    if kind.signed {
        let lhs = lhs_i128?;
        if !fits_kind(lhs, kind) {
            return None;
        }
        let (value, overflow) = match op {
            OverflowingOp::Add => {
                let rhs = signed_rhs(rhs, kind)?;
                overflowing_signed_add(lhs, rhs, kind)?
            }
            OverflowingOp::Sub => {
                let rhs = signed_rhs(rhs, kind)?;
                overflowing_signed_sub(lhs, rhs, kind)?
            }
            OverflowingOp::Mul => {
                let rhs = signed_rhs(rhs, kind)?;
                overflowing_signed_mul(lhs, rhs, kind)?
            }
            OverflowingOp::Pow => {
                let exp = rhs_exponent(rhs)?;
                let mut acc = 1i128;
                let mut overflow = false;
                for _ in 0..exp {
                    let (next, step_overflow) = overflowing_signed_mul(acc, lhs, kind)?;
                    acc = next;
                    overflow |= step_overflow;
                }
                (acc, overflow)
            }
        };
        return Some((term_for_signed_value(value, kind)?, overflow));
    }

    let lhs = unsigned_lhs(lhs_i128, lhs_u128, kind)?;
    let (raw, overflow) = match op {
        OverflowingOp::Add => {
            let rhs = unsigned_rhs(rhs, kind)?;
            overflowing_unsigned_add(lhs, rhs, kind)?
        }
        OverflowingOp::Sub => {
            let rhs = unsigned_rhs(rhs, kind)?;
            overflowing_unsigned_sub(lhs, rhs, kind)?
        }
        OverflowingOp::Mul => {
            let rhs = unsigned_rhs(rhs, kind)?;
            overflowing_unsigned_mul(lhs, rhs, kind)?
        }
        OverflowingOp::Pow => {
            let exp = rhs_exponent(rhs)?;
            let mut acc = 1u128;
            let mut overflow = false;
            for _ in 0..exp {
                let (next, step_overflow) = overflowing_unsigned_mul(acc, lhs, kind)?;
                acc = next;
                overflow |= step_overflow;
            }
            (acc, overflow)
        }
    };
    Some((term_for_unsigned_raw(raw, kind)?, overflow))
}

fn signed_rhs(rhs: &Rc<Term>, kind: IntegerKind) -> Option<i128> {
    let rhs = const_fold_int_term(rhs)?;
    fits_kind(rhs, kind).then_some(rhs)
}

fn unsigned_lhs(lhs_i128: Option<i128>, lhs_u128: Option<u128>, kind: IntegerKind) -> Option<u128> {
    let value = lhs_u128.or_else(|| lhs_i128.and_then(|n| u128::try_from(n).ok()))?;
    (value <= mask_for_bits(kind.bits)?).then_some(value)
}

fn unsigned_rhs(rhs: &Rc<Term>, kind: IntegerKind) -> Option<u128> {
    let value = const_fold_u128_term(rhs)
        .or_else(|| const_fold_int_term(rhs).and_then(|n| u128::try_from(n).ok()))?;
    (value <= mask_for_bits(kind.bits)?).then_some(value)
}

fn rhs_exponent(rhs: &Rc<Term>) -> Option<u32> {
    const_fold_u128_term(rhs)
        .or_else(|| const_fold_int_term(rhs).and_then(|n| u128::try_from(n).ok()))
        .and_then(|n| u32::try_from(n).ok())
}

fn term_for_unsigned_raw(raw: u128, kind: IntegerKind) -> Option<Rc<Term>> {
    let raw = raw & mask_for_bits(kind.bits)?;
    typed_int_term(ExactInt::Unsigned(raw), kind.int_kind()?)
}

fn term_for_signed_value(value: i128, kind: IntegerKind) -> Option<Rc<Term>> {
    typed_int_term(ExactInt::Signed(value), kind.int_kind()?)
}

fn saturating_signed_add(lhs: i128, rhs: i128, min: i128, max: i128) -> i128 {
    lhs.checked_add(rhs)
        .map(|value| value.clamp(min, max))
        .unwrap_or_else(|| if rhs >= 0 { max } else { min })
}

fn saturating_signed_sub(lhs: i128, rhs: i128, min: i128, max: i128) -> i128 {
    lhs.checked_sub(rhs)
        .map(|value| value.clamp(min, max))
        .unwrap_or_else(|| if rhs >= 0 { min } else { max })
}

fn saturating_signed_mul(lhs: i128, rhs: i128, min: i128, max: i128) -> i128 {
    lhs.checked_mul(rhs)
        .map(|value| value.clamp(min, max))
        .unwrap_or_else(|| if (lhs < 0) ^ (rhs < 0) { min } else { max })
}

fn overflowing_signed_add(lhs: i128, rhs: i128, kind: IntegerKind) -> Option<(i128, bool)> {
    let raw = apply_wrapping_raw(
        masked_raw_bits(lhs, kind)?,
        masked_raw_bits(rhs, kind)?,
        kind.bits,
        WrappingOp::Add,
    )?;
    let value = signed_value_from_raw(raw, kind)?;
    let overflow = lhs
        .checked_add(rhs)
        .is_none_or(|value| !fits_kind(value, kind));
    Some((value, overflow))
}

fn overflowing_signed_sub(lhs: i128, rhs: i128, kind: IntegerKind) -> Option<(i128, bool)> {
    let raw = apply_wrapping_raw(
        masked_raw_bits(lhs, kind)?,
        masked_raw_bits(rhs, kind)?,
        kind.bits,
        WrappingOp::Sub,
    )?;
    let value = signed_value_from_raw(raw, kind)?;
    let overflow = lhs
        .checked_sub(rhs)
        .is_none_or(|value| !fits_kind(value, kind));
    Some((value, overflow))
}

fn overflowing_signed_mul(lhs: i128, rhs: i128, kind: IntegerKind) -> Option<(i128, bool)> {
    let raw = apply_wrapping_raw(
        masked_raw_bits(lhs, kind)?,
        masked_raw_bits(rhs, kind)?,
        kind.bits,
        WrappingOp::Mul,
    )?;
    let value = signed_value_from_raw(raw, kind)?;
    let overflow = lhs
        .checked_mul(rhs)
        .is_none_or(|value| !fits_kind(value, kind));
    Some((value, overflow))
}

fn overflowing_unsigned_add(lhs: u128, rhs: u128, kind: IntegerKind) -> Option<(u128, bool)> {
    let max = mask_for_bits(kind.bits)?;
    let raw = apply_wrapping_raw(lhs, rhs, kind.bits, WrappingOp::Add)?;
    let overflow = lhs.checked_add(rhs).is_none_or(|value| value > max);
    Some((raw, overflow))
}

fn overflowing_unsigned_sub(lhs: u128, rhs: u128, kind: IntegerKind) -> Option<(u128, bool)> {
    let raw = apply_wrapping_raw(lhs, rhs, kind.bits, WrappingOp::Sub)?;
    Some((raw, lhs < rhs))
}

fn overflowing_unsigned_mul(lhs: u128, rhs: u128, kind: IntegerKind) -> Option<(u128, bool)> {
    let max = mask_for_bits(kind.bits)?;
    let raw = apply_wrapping_raw(lhs, rhs, kind.bits, WrappingOp::Mul)?;
    let overflow = lhs.checked_mul(rhs).is_none_or(|value| value > max);
    Some((raw, overflow))
}

fn tuple_term(parts: Vec<Rc<Term>>) -> Rc<Term> {
    let inner = parts
        .iter()
        .map(|part| canonical_term_sig(part))
        .collect::<Vec<_>>()
        .join(",");
    Rc::new(Term::Var {
        name: format!("literal:Tuple({inner})"),
    })
}

fn mask_for_bits(bits: u32) -> Option<u128> {
    if bits == 128 {
        Some(u128::MAX)
    } else {
        (1u128.checked_shl(bits)?).checked_sub(1)
    }
}

fn signed_value_from_raw(raw: u128, kind: IntegerKind) -> Option<i128> {
    if kind.bits == 128 {
        return Some(raw as i128);
    }
    let sign_bit = 1u128.checked_shl(kind.bits - 1)?;
    if raw & sign_bit == 0 {
        i128::try_from(raw).ok()
    } else {
        let modulus = 1i128.checked_shl(kind.bits)?;
        i128::try_from(raw).ok()?.checked_sub(modulus)
    }
}

fn abs_int_term(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
) -> Option<Rc<Term>> {
    if lhs_u128.is_some() || kind.is_some_and(|kind| !kind.signed) {
        return None;
    }
    let lhs = lhs_i128?;
    if let Some(kind) = kind {
        if !kind.signed || !fits_kind(lhs, kind) {
            return None;
        }
        let (min, _) = signed_bounds(kind.bits);
        if lhs == min {
            return None;
        }
        return term_for_signed_value(lhs.checked_abs()?, kind);
    }
    lhs.checked_abs().map(num)
}

fn signum_int_value(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
) -> Option<i128> {
    if lhs_u128.is_some() || kind.is_some_and(|kind| !kind.signed) {
        return None;
    }
    let lhs = lhs_i128?;
    if let Some(kind) = kind {
        if !kind.signed || !fits_kind(lhs, kind) {
            return None;
        }
    }
    Some(lhs.signum())
}

fn const_fold_real_term(term: &Rc<Term>) -> Option<String> {
    match term.as_ref() {
        Term::Const {
            value: ConstValue::Real(value),
            ..
        } => Some(value.clone()),
        Term::Ctor { name, args } if name == "ref" && args.len() == 1 => {
            const_fold_real_term(&args[0])
        }
        _ => None,
    }
}

fn real_abs_value(value: &str) -> Option<String> {
    if real_literal_is_zero_text(value) {
        return None;
    }
    Some(value.strip_prefix('-').unwrap_or(value).to_string())
}

fn real_signum_value(value: &str) -> Option<String> {
    if real_literal_is_zero_text(value) {
        return None;
    }
    if value.starts_with('-') {
        Some("-1".to_string())
    } else {
        Some("1".to_string())
    }
}

fn real_literal_is_zero_text(text: &str) -> bool {
    let text = text.strip_prefix('-').unwrap_or(text);
    let mut saw_digit = false;
    for ch in text.chars() {
        if ch == '.' {
            continue;
        }
        saw_digit = true;
        if ch != '0' {
            return false;
        }
    }
    saw_digit
}

fn count_ones_value(value: i128, kind: Option<IntegerKind>) -> Option<u32> {
    let Some(kind) = kind else {
        let value = u128::try_from(value).ok()?;
        return Some(value.count_ones());
    };
    let raw = raw_bits(value, kind)?;
    if kind.bits == 128 {
        Some(raw.count_ones())
    } else {
        let mask = (1u128.checked_shl(kind.bits)?).checked_sub(1)?;
        Some((raw & mask).count_ones())
    }
}

fn zero_count_value(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
    op: ZeroCountOp,
) -> Option<u32> {
    if let Some(kind) = kind {
        let raw = if let Some(value) = lhs_u128 {
            if kind.bits == 128 {
                value
            } else {
                let mask = (1u128.checked_shl(kind.bits)?).checked_sub(1)?;
                value & mask
            }
        } else {
            let value = lhs_i128.or_else(|| lhs_u128.and_then(|n| i128::try_from(n).ok()))?;
            masked_raw_bits(value, kind)?
        };
        return Some(apply_zero_count(raw, kind.bits, op));
    }
    if let Some(value) = lhs_u128 {
        return Some(apply_zero_count(value, 128, op));
    }
    let value = u128::try_from(lhs_i128?).ok()?;
    match op {
        ZeroCountOp::Count => None,
        ZeroCountOp::Leading => None,
        ZeroCountOp::Trailing => (value != 0).then_some(value.trailing_zeros()),
    }
}

/// `uint_bit_width` (`bit_width`): the number of bits required to represent the
/// value = highest-set-bit position + 1, with `0.bit_width() == 0`. This is
/// VALUE-determined, independent of the integer type's width: for a `T`-typed
/// unsigned value, `T::BITS - leading_zeros()` equals `128 - leading_zeros()` of
/// the same magnitude widened to `u128` (the leading-zero count grows by exactly
/// `128 - T::BITS`, which cancels). So we never need the receiver's type width.
/// A negative receiver (not a real `bit_width` site — the method is unsigned-only)
/// cannot be widened to `u128` and DECLINES rather than fabricate a value.
fn bit_width_value(lhs_i128: Option<i128>, lhs_u128: Option<u128>) -> Option<u32> {
    let value = lhs_u128.or_else(|| lhs_i128.and_then(|n| u128::try_from(n).ok()))?;
    Some(if value == 0 {
        0
    } else {
        u128::BITS - value.leading_zeros()
    })
}

fn isolate_highest_one_term(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
) -> Option<Rc<Term>> {
    if let Some(kind) = kind {
        let raw = if let Some(value) = lhs_u128 {
            value & mask_for_bits(kind.bits)?
        } else {
            masked_raw_bits(lhs_i128?, kind)?
        };
        let isolated = isolate_highest_raw(raw, kind.bits)?;
        return if kind.signed {
            term_for_signed_value(signed_value_from_raw(isolated, kind)?, kind)
        } else {
            term_for_unsigned_raw(isolated, kind)
        };
    }

    if let Some(value) = lhs_u128 {
        return Some(u128_term(isolate_highest_raw(value, 128)?));
    }
    let value = u128::try_from(lhs_i128?).ok()?;
    Some(num(i128::try_from(isolate_highest_raw(value, 128)?).ok()?))
}

fn isolate_highest_raw(value: u128, bits: u32) -> Option<u128> {
    if value == 0 {
        return Some(0);
    }
    let leading = apply_zero_count(value, bits, ZeroCountOp::Leading);
    1u128.checked_shl(bits.checked_sub(1)?.checked_sub(leading)?)
}

fn isolate_lowest_one_term(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
) -> Option<Rc<Term>> {
    if let Some(kind) = kind {
        let raw = if let Some(value) = lhs_u128 {
            value & mask_for_bits(kind.bits)?
        } else {
            masked_raw_bits(lhs_i128?, kind)?
        };
        let isolated = isolate_lowest_raw(raw, kind.bits)?;
        return if kind.signed {
            term_for_signed_value(signed_value_from_raw(isolated, kind)?, kind)
        } else {
            term_for_unsigned_raw(isolated, kind)
        };
    }

    if let Some(value) = lhs_u128 {
        return Some(u128_term(isolate_lowest_raw(value, 128)?));
    }
    let value = u128::try_from(lhs_i128?).ok()?;
    Some(num(i128::try_from(isolate_lowest_raw(value, 128)?).ok()?))
}

fn isolate_lowest_raw(value: u128, bits: u32) -> Option<u128> {
    let mask = mask_for_bits(bits)?;
    let value = value & mask;
    Some(value & value.wrapping_neg() & mask)
}

fn highest_one_value(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
) -> Option<u32> {
    let kind = kind?;
    let raw = if let Some(value) = lhs_u128 {
        value & mask_for_bits(kind.bits)?
    } else {
        masked_raw_bits(lhs_i128?, kind)?
    };
    (raw != 0).then(|| kind.bits - 1 - apply_zero_count(raw, kind.bits, ZeroCountOp::Leading))
}

fn lowest_one_value(
    lhs_i128: Option<i128>,
    lhs_u128: Option<u128>,
    kind: Option<IntegerKind>,
) -> Option<u32> {
    let kind = kind?;
    let raw = if let Some(value) = lhs_u128 {
        value & mask_for_bits(kind.bits)?
    } else {
        masked_raw_bits(lhs_i128?, kind)?
    };
    (raw != 0).then(|| apply_zero_count(raw, kind.bits, ZeroCountOp::Trailing))
}

fn apply_zero_count(raw: u128, bits: u32, op: ZeroCountOp) -> u32 {
    match op {
        ZeroCountOp::Count => bits - raw.count_ones(),
        ZeroCountOp::Leading => {
            if bits == 128 {
                raw.leading_zeros()
            } else {
                (raw << (128 - bits)).leading_zeros()
            }
        }
        ZeroCountOp::Trailing => {
            if raw == 0 {
                bits
            } else {
                raw.trailing_zeros().min(bits)
            }
        }
    }
}

fn assoc_const_count_ones(expr: &Expr) -> Option<u32> {
    let (kind, konst) = primitive_assoc_const(expr)?;
    match (kind.signed, kind.bits, konst.as_str()) {
        (_, _, "MIN") if !kind.signed => Some(0),
        (_, _, "MAX") if !kind.signed => Some(kind.bits),
        (_, _, "MIN") => Some(1),
        (_, _, "MAX") => Some(kind.bits.saturating_sub(1)),
        _ => None,
    }
}

fn integer_kind_hint_in_scope(
    expr: &Expr,
    fcx: &SugarBuildCtx,
    depth: usize,
) -> Option<IntegerKind> {
    if depth > 8 {
        return None;
    }
    match strip_refs_groups(expr) {
        Expr::Lit(lit) => match &lit.lit {
            syn::Lit::Int(i) => primitive_integer_kind(i.suffix()),
            _ => None,
        },
        Expr::Cast(cast) => integer_kind_from_type(&cast.ty),
        Expr::Path(path) => {
            if let Some((kind, _)) = primitive_assoc_const_path(path) {
                return Some(kind);
            }
            if let Some((kind, _)) = nonzero_assoc_const_expr(expr) {
                return Some(IntegerKind {
                    signed: kind.signed,
                    bits: kind.bits,
                    name: kind.name,
                });
            }
            if let Some(init) = fcx.scope().const_expr_for_path(&path.path) {
                return integer_kind_hint_in_scope(&init, fcx, depth + 1);
            }
            let name = simple_path_name(expr)?;
            fcx.scope()
                .stable_let_binding_for_term(&name)
                .and_then(|init| integer_kind_hint_in_scope(init, fcx, depth + 1))
        }
        Expr::Unary(unary) => integer_kind_hint_in_scope(&unary.expr, fcx, depth + 1),
        Expr::Binary(binary) => {
            let left = integer_kind_hint_in_scope(&binary.left, fcx, depth + 1);
            let right = integer_kind_hint_in_scope(&binary.right, fcx, depth + 1);
            match (left, right) {
                (Some(left), Some(right)) if left == right => Some(left),
                (Some(kind), None) | (None, Some(kind)) => Some(kind),
                _ => None,
            }
        }
        Expr::Paren(paren) => integer_kind_hint_in_scope(&paren.expr, fcx, depth + 1),
        Expr::Group(group) => integer_kind_hint_in_scope(&group.expr, fcx, depth + 1),
        Expr::MethodCall(call)
            if matches!(call.method.to_string().as_str(), "unwrap" | "expect")
                && is_known_monadic_source(&call.receiver) =>
        {
            nonzero_new_integer_kind(&call.receiver)
                .or_else(|| integer_kind_hint_in_scope(&call.receiver, fcx, depth + 1))
        }
        _ => None,
    }
}

fn nonzero_new_integer_kind(expr: &Expr) -> Option<IntegerKind> {
    let Expr::Call(call) = strip_refs_groups(expr) else {
        return None;
    };
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    if path.qself.is_some() || path.path.segments.len() < 2 {
        return None;
    }
    let mut segments = path.path.segments.iter().rev();
    let method = segments.next()?;
    let ty = segments.next()?;
    if method.ident != "new" {
        return None;
    }
    let ty_name = ty.ident.to_string();
    if ty_name == "NonZero" {
        let PathArguments::AngleBracketed(args) = &ty.arguments else {
            return None;
        };
        return args.args.iter().find_map(|arg| match arg {
            syn::GenericArgument::Type(ty) => integer_kind_from_type(&ty),
            _ => None,
        });
    }
    ty_name
        .strip_prefix("NonZero")
        .map(|suffix| suffix.to_ascii_lowercase())
        .and_then(|suffix| primitive_integer_kind(&suffix))
}

fn primitive_assoc_const(expr: &Expr) -> Option<(IntegerKind, String)> {
    let Expr::Path(path) = strip_refs_groups(expr) else {
        return None;
    };
    primitive_assoc_const_path(path)
}

fn primitive_assoc_const_path(path: &ExprPath) -> Option<(IntegerKind, String)> {
    if let Some(qself) = &path.qself {
        let kind = integer_kind_from_type(&qself.ty)?;
        let konst = path.path.segments.last()?.ident.to_string();
        return Some((kind, konst));
    }
    if path.path.segments.len() != 2 {
        return None;
    }
    if path
        .path
        .segments
        .iter()
        .any(|segment| !matches!(segment.arguments, PathArguments::None))
    {
        return None;
    }
    let ty = path.path.segments[0].ident.to_string();
    let kind = primitive_integer_kind(&ty)?;
    let konst = path.path.segments[1].ident.to_string();
    Some((kind, konst))
}

fn integer_kind_from_type(ty: &Type) -> Option<IntegerKind> {
    let Type::Path(path) = ty else {
        return None;
    };
    primitive_integer_kind(&path.path.segments.last()?.ident.to_string())
}

fn primitive_integer_kind(name: &str) -> Option<IntegerKind> {
    let kind = int_literal_kind(name)?;
    Some(IntegerKind {
        signed: kind.signed,
        bits: kind.bits,
        name: kind.name,
    })
}

fn raw_bits(value: i128, kind: IntegerKind) -> Option<u128> {
    if !fits_kind(value, kind) {
        if !kind.signed && kind.bits == 128 {
            return Some(value as u128);
        }
        if kind.signed && value >= 0 && kind.bits < 128 {
            let raw = u128::try_from(value).ok()?;
            let max = (1u128.checked_shl(kind.bits)?).checked_sub(1)?;
            return (raw <= max).then_some(raw);
        }
        return None;
    }
    if value >= 0 {
        return u128::try_from(value).ok();
    }
    if kind.bits == 128 {
        return Some(value as u128);
    }
    let modulus = 1i128.checked_shl(kind.bits)?;
    u128::try_from(modulus.checked_add(value)?).ok()
}

fn masked_raw_bits(value: i128, kind: IntegerKind) -> Option<u128> {
    let raw = raw_bits(value, kind)?;
    if kind.bits == 128 {
        Some(raw)
    } else {
        let mask = (1u128.checked_shl(kind.bits)?).checked_sub(1)?;
        Some(raw & mask)
    }
}

fn fits_kind(value: i128, kind: IntegerKind) -> bool {
    if kind.signed {
        let (min, max) = signed_bounds(kind.bits);
        (min..=max).contains(&value)
    } else if kind.bits == 128 {
        value >= 0
    } else {
        let max = (1i128 << kind.bits) - 1;
        (0..=max).contains(&value)
    }
}

fn signed_bounds(bits: u32) -> (i128, i128) {
    if bits == 128 {
        (i128::MIN, i128::MAX)
    } else {
        let sign = 1i128 << (bits - 1);
        (-sign, sign - 1)
    }
}
