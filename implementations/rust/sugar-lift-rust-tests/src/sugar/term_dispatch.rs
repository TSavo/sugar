// SPDX-License-Identifier: Apache-2.0

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, str_const, ConstValue, LetBinding, Term};
use syn::{Expr, Item};

use crate::sugar::block_term::translate_expression_only_block_in_scope_with_audits;
use crate::sugar::factory::SugarBuildCtx;
use crate::sugar::factory_gap_info::CoverageGapInfo;
use crate::sugar::int_literal::{numeric_floor_from_term, NumericFloor};
use crate::sugar::ip_addr::{literal_ip_from_term, LiteralIp};
use crate::sugar::monadic::{OPT_NONE, OPT_SOME, RES_ERR, RES_OK};
use crate::sugar::predicate_value::PredicateValue;
use crate::sugar::primitive_int::{
    is_deferred_primitive_method_name, try_eval_deferred_primitive_method,
};
use crate::sugar::symbolic_value::SymbolicValue;
use crate::sugar::temporal_floor::CurryOccurrence;
use crate::{
    bool_const, canonical_term_sig, const_fold_int_term, const_fold_u128_term, num,
    scope_const_block_locals, sugar_ctx_with_factory_audits, token_key, Desugared, Effect,
    FactoryAuditLog, FloatWidthScope, LiftOptions, Outcome, ReductionCtx, Sugar, TemporalScope,
};

pub(crate) const VALUE_IF_TERM: &str = "value:if";

pub(crate) fn value_if_term(cond: Rc<Term>, then_term: Rc<Term>, else_term: Rc<Term>) -> Rc<Term> {
    if let Some(value) = literal_predicate_bool(&cond) {
        return if value { then_term } else { else_term };
    }
    Rc::new(Term::Ctor {
        name: VALUE_IF_TERM.to_string(),
        args: vec![cond, then_term, else_term],
    })
}

/// Thin adapter over the term factory. The term factory owns recognition; this
/// helper exists only as the old external API for callers that already have a
/// `TemporalScope`.
pub(crate) fn translate_term_in_scope(
    expr: &Expr,
    scope: &TemporalScope,
) -> Result<Rc<Term>, Effect> {
    translate_term_in_scope_with_audits(expr, scope, None)
}

pub(crate) fn translate_term_in_scope_with_audits(
    expr: &Expr,
    scope: &TemporalScope,
    factory_audits: Option<&FactoryAuditLog>,
) -> Result<Rc<Term>, Effect> {
    let options = LiftOptions::default();
    let let_inits = std::collections::BTreeMap::new();
    let fcx = SugarBuildCtx::new(scope, &options, &let_inits);
    let node = crate::sugar::factory::build_term(expr, &fcx);
    let items: Vec<Item> = Vec::new();
    let reducer = ReductionCtx::from_items_with_imports(&items, scope.macro_registry());
    let mut float_widths = FloatWidthScope::new();
    let ctx = sugar_ctx_with_factory_audits(
        scope,
        &options,
        &reducer,
        &mut float_widths,
        0,
        factory_audits,
    );
    match node.desugar(&ctx) {
        Outcome::Complete(d) => {
            term_floor_dispatch(d, "rust.term_dispatch", token_key(expr)).into_result()
        }
        Outcome::Incomplete(effect) => Err(effect),
    }
}

pub(crate) fn translate_assertion_term_in_scope_with_audits(
    expr: &Expr,
    scope: &TemporalScope,
    factory_audits: Option<&FactoryAuditLog>,
) -> Result<Rc<Term>, Effect> {
    match expr {
        Expr::Const(const_block) => {
            let term = translate_expression_only_block_in_scope_with_audits(
                &const_block.block,
                "const",
                scope,
                factory_audits,
            )?;
            Ok(scope_const_block_locals(term, scope.local_scope()))
        }
        Expr::Path(path)
            if path
                .path
                .segments
                .last()
                .is_some_and(|seg| seg.ident == "None") =>
        {
            Ok(Rc::new(Term::Ctor {
                name: OPT_NONE.to_string(),
                args: Vec::new(),
            }))
        }
        Expr::Paren(paren) => {
            translate_assertion_term_in_scope_with_audits(&paren.expr, scope, factory_audits)
        }
        Expr::Group(group) => {
            translate_assertion_term_in_scope_with_audits(&group.expr, scope, factory_audits)
        }
        _ => translate_term_in_scope_with_audits(expr, scope, factory_audits),
    }
}

pub(crate) enum FloorDispatch<T> {
    Dispatched(T),
    Gap(CoverageGapInfo),
}

impl<T> FloorDispatch<T> {
    pub(crate) fn into_result(self) -> Result<T, Effect> {
        match self {
            Self::Dispatched(value) => Ok(value),
            Self::Gap(gap) => Err(floor_dispatch_gap_effect(gap)),
        }
    }
}

pub(crate) fn term_floor_dispatch(
    floor: Desugared,
    owner: impl Into<String>,
    blame: impl Into<String>,
) -> FloorDispatch<Rc<Term>> {
    match floor {
        Desugared::Term(term) => FloorDispatch::Dispatched(term),
        Desugared::TermSeq(terms) => {
            FloorDispatch::Dispatched(literal_array_term_from_terms(&terms))
        }
        other => FloorDispatch::Gap(floor_dispatch_gap_info(
            owner,
            blame,
            desugared_floor_name(&other),
            "TermFloor",
        )),
    }
}

fn floor_dispatch_gap_info(
    owner: impl Into<String>,
    blame: impl Into<String>,
    observed: impl Into<String>,
    requested: impl Into<String>,
) -> CoverageGapInfo {
    CoverageGapInfo {
        owner: owner.into(),
        blame: blame.into(),
        observed: observed.into(),
        requested: requested.into(),
        fix: "sugar::term_dispatch".to_string(),
        gap_kind: "FloorDispatch".to_string(),
        gap_locus: "TermFloor".to_string(),
    }
}

fn floor_dispatch_gap_effect(gap: CoverageGapInfo) -> Effect {
    Effect::CoverageGap {
        boundary: gap.observed.clone(),
        reason: gap.message(),
    }
}

pub(crate) trait TermFloorVisitor {
    type Output;

    fn visit_term(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait TermFloorAccept {
    fn accept_term_floor<V: TermFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl TermFloorAccept for Rc<Term> {
    fn accept_term_floor<V: TermFloorVisitor>(&self, visitor: V) -> V::Output {
        visitor.visit_term(self)
    }
}

pub(crate) trait SymbolicValueFloorVisitor {
    type Output;

    fn visit_symbolic_value(self, value: SymbolicValue) -> Self::Output;
    fn visit_non_symbolic(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait SymbolicValueFloorAccept {
    fn accept_symbolic_value_floor<V: SymbolicValueFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl SymbolicValueFloorAccept for Rc<Term> {
    fn accept_symbolic_value_floor<V: SymbolicValueFloorVisitor>(&self, visitor: V) -> V::Output {
        match SymbolicValue::from_term(Rc::clone(self)) {
            Some(value) => visitor.visit_symbolic_value(value),
            None => visitor.visit_non_symbolic(self),
        }
    }
}

pub(crate) trait BoolFloorVisitor {
    type Output;

    fn visit_bool(self, value: bool) -> Self::Output;
    fn visit_non_bool(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait BoolFloorAccept {
    fn accept_bool_floor<V: BoolFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl BoolFloorAccept for Rc<Term> {
    fn accept_bool_floor<V: BoolFloorVisitor>(&self, visitor: V) -> V::Output {
        match self.as_ref() {
            Term::Const {
                value: ConstValue::Bool(value),
                ..
            } => visitor.visit_bool(*value),
            _ => visitor.visit_non_bool(self),
        }
    }
}

pub(crate) struct RequiredBoolVisitor<'a> {
    pub(crate) owner: &'a str,
}

impl BoolFloorVisitor for RequiredBoolVisitor<'_> {
    type Output = bool;

    fn visit_bool(self, value: bool) -> Self::Output {
        value
    }

    fn visit_non_bool(self, term: &Rc<Term>) -> Self::Output {
        panic!(
            "{} did not dispatch to BoolLiteral: {}",
            self.owner,
            canonical_term_sig(term)
        )
    }
}

pub(crate) trait PredicateValueFloorVisitor {
    type Output;

    fn visit_predicate_value(self, value: PredicateValue) -> Self::Output;
    fn visit_non_predicate(self, floor: Desugared) -> Self::Output;
}

pub(crate) trait PredicateValueFloorAccept {
    fn accept_predicate_value_floor<V: PredicateValueFloorVisitor>(self, visitor: V) -> V::Output;
}

impl PredicateValueFloorAccept for Desugared {
    fn accept_predicate_value_floor<V: PredicateValueFloorVisitor>(self, visitor: V) -> V::Output {
        match self {
            Desugared::PredicateValue(value) => visitor.visit_predicate_value(value),
            floor => visitor.visit_non_predicate(floor),
        }
    }
}

pub(crate) struct RequiredPredicateValueVisitor<'a> {
    pub(crate) owner: &'a str,
}

impl PredicateValueFloorVisitor for RequiredPredicateValueVisitor<'_> {
    type Output = PredicateValue;

    fn visit_predicate_value(self, value: PredicateValue) -> Self::Output {
        value
    }

    fn visit_non_predicate(self, floor: Desugared) -> Self::Output {
        panic!(
            "{} completed {} floor where a PredicateValue floor was required",
            self.owner,
            desugared_floor_name(&floor)
        )
    }
}

fn desugared_floor_name(floor: &Desugared) -> &'static str {
    match floor {
        Desugared::Seq(_) => "Seq",
        Desugared::TermSeq(_) => "TermSeq",
        Desugared::Constraints { .. } => "Constraints",
        Desugared::Term(_) => "Term",
        Desugared::LiteralString(_) => "LiteralString",
        Desugared::LiteralCStr(_) => "LiteralCStr",
        Desugared::FormatValue(_) => "FormatValue",
        Desugared::TupleComponents(_) => "TupleComponents",
        Desugared::ObjectValue(_) => "ObjectValue",
        Desugared::PredicateValue(_) => "PredicateValue",
        Desugared::StmtSupport => "StmtSupport",
        Desugared::StmtBound(_) => "StmtBound",
        Desugared::StmtReturn(_) => "StmtReturn",
        Desugared::StmtGuarded(_) => "StmtGuarded",
        Desugared::StmtRaise(_) => "StmtRaise",
        Desugared::StmtGuardedRaise(_) => "StmtGuardedRaise",
        Desugared::StmtBlock { .. } => "StmtBlock",
    }
}

pub(crate) struct LiteralPredicateBoolVisitor;

impl TermFloorVisitor for LiteralPredicateBoolVisitor {
    type Output = Option<bool>;

    fn visit_term(self, term: &Rc<Term>) -> Self::Output {
        literal_predicate_bool(term)
    }
}

pub(crate) fn literal_predicate_bool_or_runtime_effect(
    term: &Rc<Term>,
) -> Result<Option<bool>, Effect> {
    if let Some(value) = literal_predicate_bool(term) {
        return Ok(Some(value));
    }
    if let Some(boundary) = runtime_occurrence_boundary(term) {
        return Err(Effect::OpaqueRuntime {
            boundary,
            accessor: false,
        });
    }
    Ok(None)
}

pub(crate) trait ScalarFloorVisitor {
    type Output;

    fn visit_numeric(self, floor: NumericFloor) -> Self::Output;
    fn visit_bool(self, value: bool) -> Self::Output;
    fn visit_char(self, value: char) -> Self::Output;
    fn visit_ip(self, term: &Rc<Term>, ip: LiteralIp) -> Self::Output
    where
        Self: Sized,
    {
        let _ = ip;
        self.visit_runtime(term)
    }
    fn visit_runtime(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait ScalarFloorAccept {
    fn accept_scalar_floor<V: ScalarFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl ScalarFloorAccept for Rc<Term> {
    fn accept_scalar_floor<V: ScalarFloorVisitor>(&self, visitor: V) -> V::Output {
        if let Some(floor) = numeric_floor_from_term(self) {
            return visitor.visit_numeric(floor);
        }
        if let Some(ip) = literal_ip_from_term(self) {
            return visitor.visit_ip(self, ip);
        }
        match self.as_ref() {
            Term::Const {
                value: ConstValue::Bool(value),
                ..
            } => visitor.visit_bool(*value),
            Term::Const {
                value: ConstValue::String(value),
                ..
            } => {
                let mut chars = value.chars();
                let Some(ch) = chars.next() else {
                    return visitor.visit_runtime(self);
                };
                if chars.next().is_some() {
                    visitor.visit_runtime(self)
                } else {
                    visitor.visit_char(ch)
                }
            }
            _ => visitor.visit_runtime(self),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Bv32UnaryOp {
    Neg,
}

impl Bv32UnaryOp {
    pub(crate) fn ctor_name(self) -> &'static str {
        match self {
            Self::Neg => "bv32.neg",
        }
    }

    fn from_ctor_name(name: &str) -> Option<Self> {
        match name {
            "bv32.neg" => Some(Self::Neg),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Bv32BinaryOp {
    Shl,
    Lshr,
    And,
    Or,
    Xor,
    Add,
    Sub,
    Mul,
}

impl Bv32BinaryOp {
    pub(crate) fn ctor_name(self) -> &'static str {
        match self {
            Self::Shl => "bv32.shl",
            Self::Lshr => "bv32.lshr",
            Self::And => "bv32.and",
            Self::Or => "bv32.or",
            Self::Xor => "bv32.xor",
            Self::Add => "bv32.add",
            Self::Sub => "bv32.sub",
            Self::Mul => "bv32.mul",
        }
    }

    fn from_ctor_name(name: &str) -> Option<Self> {
        match name {
            "bv32.shl" => Some(Self::Shl),
            "bv32.lshr" => Some(Self::Lshr),
            "bv32.and" => Some(Self::And),
            "bv32.or" => Some(Self::Or),
            "bv32.xor" => Some(Self::Xor),
            "bv32.add" => Some(Self::Add),
            "bv32.sub" => Some(Self::Sub),
            "bv32.mul" => Some(Self::Mul),
            _ => None,
        }
    }
}

pub(crate) trait Bv32FloorVisitor {
    type Output;

    fn visit_bv32_const(self, term: &Rc<Term>, value: u32) -> Self::Output;
    fn visit_bv32_unary(self, term: &Rc<Term>, op: Bv32UnaryOp, arg: &Rc<Term>) -> Self::Output;
    fn visit_bv32_binary(
        self,
        term: &Rc<Term>,
        op: Bv32BinaryOp,
        left: &Rc<Term>,
        right: &Rc<Term>,
    ) -> Self::Output;
    fn visit_bv32_ite(
        self,
        term: &Rc<Term>,
        cond: &Rc<Term>,
        then_term: &Rc<Term>,
        else_term: &Rc<Term>,
    ) -> Self::Output;
    fn visit_non_bv32(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait Bv32FloorAccept {
    fn accept_bv32_floor<V: Bv32FloorVisitor>(&self, visitor: V) -> V::Output;
}

impl Bv32FloorAccept for Rc<Term> {
    fn accept_bv32_floor<V: Bv32FloorVisitor>(&self, visitor: V) -> V::Output {
        if let Some(value) = bv32_const_value(self) {
            return visitor.visit_bv32_const(self, value);
        }
        match self.as_ref() {
            Term::Ctor { name, args } if args.len() == 1 => {
                if let Some(op) = Bv32UnaryOp::from_ctor_name(name) {
                    visitor.visit_bv32_unary(self, op, &args[0])
                } else {
                    visitor.visit_non_bv32(self)
                }
            }
            Term::Ctor { name, args } if args.len() == 2 => {
                if let Some(op) = Bv32BinaryOp::from_ctor_name(name) {
                    visitor.visit_bv32_binary(self, op, &args[0], &args[1])
                } else {
                    visitor.visit_non_bv32(self)
                }
            }
            Term::Ctor { name, args } if name == "bv32.ite" && args.len() == 3 => {
                visitor.visit_bv32_ite(self, &args[0], &args[1], &args[2])
            }
            _ => visitor.visit_non_bv32(self),
        }
    }
}

fn bv32_const_value(term: &Rc<Term>) -> Option<u32> {
    match term.as_ref() {
        Term::Const {
            value: ConstValue::Int(value),
            sort,
        } if matches!(sort.name.as_str(), "u32" | "bv32") => u32::try_from(*value).ok(),
        _ => None,
    }
}

pub(crate) trait MonadicFloorVisitor {
    type Output;

    fn visit_some(self, inner: &Rc<Term>) -> Self::Output;
    fn visit_none(self) -> Self::Output;
    fn visit_ok(self, inner: &Rc<Term>) -> Self::Output;
    fn visit_err(self, inner: &Rc<Term>) -> Self::Output;
    fn visit_non_monadic(self, term: &Rc<Term>) -> Self::Output;
}

pub(crate) trait MonadicFloorAccept {
    fn accept_monadic_floor<V: MonadicFloorVisitor>(&self, visitor: V) -> V::Output;
}

impl MonadicFloorAccept for Rc<Term> {
    fn accept_monadic_floor<V: MonadicFloorVisitor>(&self, visitor: V) -> V::Output {
        match self.as_ref() {
            Term::Ctor { name, args } if name == OPT_SOME && args.len() == 1 => {
                visitor.visit_some(&args[0])
            }
            Term::Ctor { name, args } if name == OPT_NONE && args.is_empty() => {
                visitor.visit_none()
            }
            Term::Ctor { name, args } if name == RES_OK && args.len() == 1 => {
                visitor.visit_ok(&args[0])
            }
            Term::Ctor { name, args } if name == RES_ERR && args.len() == 1 => {
                visitor.visit_err(&args[0])
            }
            _ => visitor.visit_non_monadic(self),
        }
    }
}

pub(crate) trait DesugaredFloorVisitor {
    type Output;

    fn visit_term(self, term: Rc<Term>) -> Self::Output;
    fn visit_term_seq(self, terms: Vec<Rc<Term>>) -> Self::Output;
    fn visit_tuple_components(self, parts: Vec<Rc<Term>>) -> Self::Output;
    fn visit_passthrough(self, floor: Desugared) -> Self::Output;
}

pub(crate) trait DesugaredFloorAccept {
    fn accept_desugared_floor<V: DesugaredFloorVisitor>(self, visitor: V) -> V::Output;
}

impl DesugaredFloorAccept for Desugared {
    fn accept_desugared_floor<V: DesugaredFloorVisitor>(self, visitor: V) -> V::Output {
        match self {
            Desugared::Term(term) => visitor.visit_term(term),
            Desugared::TermSeq(terms) => visitor.visit_term_seq(terms),
            Desugared::TupleComponents(parts) => visitor.visit_tuple_components(parts),
            other => visitor.visit_passthrough(other),
        }
    }
}

pub(crate) struct RequiredTermVisitor<'a> {
    pub(crate) owner: &'a str,
}

impl DesugaredFloorVisitor for RequiredTermVisitor<'_> {
    type Output = Rc<Term>;

    fn visit_term(self, term: Rc<Term>) -> Self::Output {
        term
    }

    fn visit_term_seq(self, _terms: Vec<Rc<Term>>) -> Self::Output {
        panic!(
            "{} completed a sequence floor where a term floor was required",
            self.owner
        )
    }

    fn visit_tuple_components(self, _parts: Vec<Rc<Term>>) -> Self::Output {
        panic!(
            "{} completed a tuple-components floor where a term floor was required",
            self.owner
        )
    }

    fn visit_passthrough(self, floor: Desugared) -> Self::Output {
        let _ = floor;
        panic!(
            "{} completed a non-term floor where a term floor was required",
            self.owner
        )
    }
}

#[derive(Clone, Copy)]
pub(crate) struct CurryVisitor<'a> {
    pub(crate) param: &'a str,
    pub(crate) arg: &'a Rc<Term>,
    pub(crate) occurrence: CurryOccurrence<'a>,
}

impl TermFloorVisitor for CurryVisitor<'_> {
    type Output = Rc<Term>;

    fn visit_term(self, term: &Rc<Term>) -> Self::Output {
        curry_term(term, self.param, self.arg, &self.occurrence)
    }
}

impl DesugaredFloorVisitor for CurryVisitor<'_> {
    type Output = Desugared;

    fn visit_term(self, term: Rc<Term>) -> Self::Output {
        Desugared::Term(term.accept_term_floor(self))
    }

    fn visit_term_seq(self, terms: Vec<Rc<Term>>) -> Self::Output {
        Desugared::TermSeq(
            terms
                .into_iter()
                .map(|term| term.accept_term_floor(self))
                .collect(),
        )
    }

    fn visit_tuple_components(self, parts: Vec<Rc<Term>>) -> Self::Output {
        Desugared::TupleComponents(
            parts
                .into_iter()
                .map(|part| part.accept_term_floor(self))
                .collect(),
        )
    }

    fn visit_passthrough(self, floor: Desugared) -> Self::Output {
        floor
    }
}

fn curry_term(
    term: &Rc<Term>,
    param: &str,
    arg: &Rc<Term>,
    occurrence: &CurryOccurrence<'_>,
) -> Rc<Term> {
    match term.as_ref() {
        Term::Var { name } if name == param => Rc::clone(arg),
        Term::Ctor { name, args } if is_deferred_primitive_method_name(name) => {
            let curried_args = args
                .iter()
                .map(|child| curry_term(child, param, arg, occurrence))
                .collect::<Vec<_>>();
            try_eval_deferred_primitive_method(name, &curried_args).unwrap_or_else(|| {
                Rc::new(Term::Ctor {
                    name: name.clone(),
                    args: curried_args,
                })
            })
        }
        Term::Ctor { name, args } if runtime_occurrence_ctor(name) => {
            let curried = Rc::new(Term::Ctor {
                name: name.clone(),
                args: args
                    .iter()
                    .map(|child| curry_term(child, param, arg, occurrence))
                    .collect(),
            });
            if name == "method:to_string" && args.len() == 1 {
                let Term::Ctor { args, .. } = curried.as_ref() else {
                    unreachable!("curried to_string term stayed a ctor");
                };
                if let Some(value) = crate::sugar::format::display_literal_term_floor(&args[0]) {
                    return str_const(value);
                }
                return curried;
            }
            if literal_predicate_bool(&curried).is_some() {
                curried
            } else {
                Rc::new(Term::Ctor {
                    name: format!("{}{suffix}", name, suffix = occurrence.suffix()),
                    args: Vec::new(),
                })
            }
        }
        Term::Ctor { name, args } if name == VALUE_IF_TERM && args.len() == 3 => {
            let cond = curry_term(&args[0], param, arg, occurrence);
            let then_term = curry_term(&args[1], param, arg, occurrence);
            let else_term = curry_term(&args[2], param, arg, occurrence);
            value_if_term(cond, then_term, else_term)
        }
        Term::Ctor { name, args } => Rc::new(Term::Ctor {
            name: name.clone(),
            args: args
                .iter()
                .map(|child| curry_term(child, param, arg, occurrence))
                .collect(),
        }),
        Term::Let { bindings, body } => Rc::new(Term::Let {
            bindings: bindings
                .iter()
                .map(|binding| LetBinding {
                    name: binding.name.clone(),
                    bound_term: curry_term(&binding.bound_term, param, arg, occurrence),
                })
                .collect(),
            body: curry_term(body, param, arg, occurrence),
        }),
        Term::Lambda {
            param_name,
            param_sort,
            body,
        } if param_name != param => Rc::new(Term::Lambda {
            param_name: param_name.clone(),
            param_sort: param_sort.clone(),
            body: curry_term(body, param, arg, occurrence),
        }),
        _ => Rc::clone(term),
    }
}

fn runtime_occurrence_ctor(name: &str) -> bool {
    name.starts_with("call:") || name.starts_with("method:")
}

fn runtime_occurrence_boundary(term: &Rc<Term>) -> Option<String> {
    match term.as_ref() {
        Term::Ctor { name, .. } if runtime_occurrence_ctor(name) => Some(canonical_term_sig(term)),
        Term::Ctor { args, .. } => args.iter().find_map(runtime_occurrence_boundary),
        Term::Let { bindings, body } => bindings
            .iter()
            .find_map(|binding| runtime_occurrence_boundary(&binding.bound_term))
            .or_else(|| runtime_occurrence_boundary(body)),
        Term::Lambda { body, .. } => runtime_occurrence_boundary(body),
        _ => None,
    }
}

fn literal_predicate_bool(term: &Rc<Term>) -> Option<bool> {
    match term.as_ref() {
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } => Some(*value),
        Term::Ctor { name, args } if name == "bit-not" && args.len() == 1 => {
            literal_predicate_bool(&args[0]).map(|value| !value)
        }
        Term::Ctor { name, args } if name == "deref" && args.len() == 1 => {
            literal_predicate_bool(&args[0])
        }
        Term::Ctor { name, args } if name.starts_with("cmp:") && args.len() == 2 => {
            literal_cmp_bool(name, &args[0], &args[1])
        }
        Term::Ctor { name, args } if name.starts_with("method:") && args.len() == 1 => {
            literal_method_bool(name.strip_prefix("method:")?, &args[0])
        }
        _ => None,
    }
}

fn literal_cmp_bool(name: &str, left: &Rc<Term>, right: &Rc<Term>) -> Option<bool> {
    let left = peel_deref_term(left);
    let right = peel_deref_term(right);
    if let Some((left, right)) = literal_u128_pair(left, right) {
        return match name {
            "cmp:eq" => Some(left == right),
            "cmp:neq" => Some(left != right),
            "cmp:lt" => Some(left < right),
            "cmp:le" => Some(left <= right),
            "cmp:gt" => Some(left > right),
            "cmp:ge" => Some(left >= right),
            _ => None,
        };
    }
    let (left, right) = (const_fold_int_term(left)?, const_fold_int_term(right)?);
    match name {
        "cmp:eq" => Some(left == right),
        "cmp:neq" => Some(left != right),
        "cmp:lt" => Some(left < right),
        "cmp:le" => Some(left <= right),
        "cmp:gt" => Some(left > right),
        "cmp:ge" => Some(left >= right),
        _ => None,
    }
}

fn literal_u128_pair(left: &Rc<Term>, right: &Rc<Term>) -> Option<(u128, u128)> {
    let left_u = const_fold_u128_term(left);
    let right_u = const_fold_u128_term(right);
    if left_u.is_none() && right_u.is_none() {
        return None;
    }
    Some((
        left_u.or_else(|| const_fold_int_term(left).and_then(|n| u128::try_from(n).ok()))?,
        right_u.or_else(|| const_fold_int_term(right).and_then(|n| u128::try_from(n).ok()))?,
    ))
}

fn literal_method_bool(method: &str, receiver: &Rc<Term>) -> Option<bool> {
    let receiver = peel_deref_term(receiver);
    if let Some(ch) = literal_char(receiver) {
        return literal_char_method_bool(method, ch);
    }
    let byte = const_fold_int_term(receiver).and_then(|n| u8::try_from(n).ok())?;
    literal_byte_method_bool(method, byte)
}

fn peel_deref_term(term: &Rc<Term>) -> &Rc<Term> {
    match term.as_ref() {
        Term::Ctor { name, args } if name == "deref" && args.len() == 1 => {
            peel_deref_term(&args[0])
        }
        _ => term,
    }
}

fn literal_char(term: &Rc<Term>) -> Option<char> {
    let Term::Const {
        value: ConstValue::String(value),
        ..
    } = term.as_ref()
    else {
        return None;
    };
    let mut chars = value.chars();
    let ch = chars.next()?;
    chars.next().is_none().then_some(ch)
}

fn literal_char_method_bool(method: &str, ch: char) -> Option<bool> {
    match method {
        "is_alphabetic" => Some(ch.is_alphabetic()),
        "is_numeric" => Some(ch.is_numeric()),
        "is_ascii" => Some(ch.is_ascii()),
        "is_alphanumeric" => Some(ch.is_alphanumeric()),
        "is_whitespace" => Some(ch.is_whitespace()),
        "is_uppercase" => Some(ch.is_uppercase()),
        "is_lowercase" => Some(ch.is_lowercase()),
        "is_ascii_alphabetic" => Some(ch.is_ascii_alphabetic()),
        "is_ascii_digit" => Some(ch.is_ascii_digit()),
        "is_ascii_alphanumeric" => Some(ch.is_ascii_alphanumeric()),
        "is_ascii_octdigit" => Some(matches!(ch, '0'..='7')),
        "is_ascii_lowercase" => Some(ch.is_ascii_lowercase()),
        "is_ascii_uppercase" => Some(ch.is_ascii_uppercase()),
        "is_ascii_hexdigit" => Some(ch.is_ascii_hexdigit()),
        "is_ascii_punctuation" => Some(ch.is_ascii_punctuation()),
        "is_ascii_graphic" => Some(ch.is_ascii_graphic()),
        "is_ascii_whitespace" => Some(ch.is_ascii_whitespace()),
        "is_ascii_control" => Some(ch.is_ascii_control()),
        _ => None,
    }
}

fn literal_byte_method_bool(method: &str, byte: u8) -> Option<bool> {
    match method {
        "is_ascii" => Some(byte.is_ascii()),
        "is_ascii_alphabetic" => Some(byte.is_ascii_alphabetic()),
        "is_ascii_digit" => Some(byte.is_ascii_digit()),
        "is_ascii_alphanumeric" => Some(byte.is_ascii_alphanumeric()),
        "is_ascii_octdigit" => Some(matches!(byte, b'0'..=b'7')),
        "is_ascii_lowercase" => Some(byte.is_ascii_lowercase()),
        "is_ascii_uppercase" => Some(byte.is_ascii_uppercase()),
        "is_ascii_hexdigit" => Some(byte.is_ascii_hexdigit()),
        "is_ascii_punctuation" => Some(byte.is_ascii_punctuation()),
        "is_ascii_graphic" => Some(byte.is_ascii_graphic()),
        "is_ascii_whitespace" => Some(byte.is_ascii_whitespace()),
        "is_ascii_control" => Some(byte.is_ascii_control()),
        _ => None,
    }
}

pub(crate) fn literal_array_term_from_terms(terms: &[Rc<Term>]) -> Rc<Term> {
    let inner = terms
        .iter()
        .map(literal_array_elem_sig)
        .collect::<Vec<_>>()
        .join(",");
    make_var(format!("literal:Array({inner})"))
}

fn literal_array_elem_sig(term: &Rc<Term>) -> String {
    const_fold_int_term(term)
        .map(|value| canonical_term_sig(&num(value)))
        .unwrap_or_else(|| canonical_term_sig(term))
}

pub(crate) fn fold_int_terms(
    op: &str,
    identity: i128,
    terms: impl IntoIterator<Item = Rc<Term>>,
) -> Rc<Term> {
    terms.into_iter().fold(num(identity), |acc, term| {
        let combined = Rc::new(Term::Ctor {
            name: op.to_string(),
            args: vec![acc, term],
        });
        const_fold_int_term(&combined).map_or(combined, num)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sugar::temporal_floor::{CurryDoorway, TemporalFloor};
    use sugar_ir_symbolic::{and_, eq, num, Formula, Sort};

    fn var(name: &str) -> Rc<Term> {
        make_var(name)
    }

    fn occurrence(family: &'static str, ordinal: usize) -> CurryOccurrence<'static> {
        TemporalFloor::default()
            .alias(CurryDoorway::new(family, ordinal))
            .expect("test occurrence aliases through temporal floor")
    }

    struct PredicateKindProbe;

    impl PredicateValueFloorVisitor for PredicateKindProbe {
        type Output = String;

        fn visit_predicate_value(
            self,
            value: crate::sugar::predicate_value::PredicateValue,
        ) -> Self::Output {
            match value.formula().as_ref() {
                Formula::Atomic { name, .. } => format!("predicate:{name}"),
                Formula::Connective { kind, .. } => format!("predicate:{kind}"),
                other => panic!("unexpected predicate formula floor: {other:?}"),
            }
        }

        fn visit_non_predicate(self, floor: Desugared) -> Self::Output {
            match floor {
                Desugared::Term(_) => "non:Term".to_string(),
                Desugared::Constraints { .. } => "non:Constraints".to_string(),
                _ => "non:Other".to_string(),
            }
        }
    }

    struct BoolLiteralProbe;

    impl BoolFloorVisitor for BoolLiteralProbe {
        type Output = Option<bool>;

        fn visit_bool(self, value: bool) -> Self::Output {
            Some(value)
        }

        fn visit_non_bool(self, _term: &Rc<Term>) -> Self::Output {
            None
        }
    }

    #[test]
    fn predicate_value_floor_distinguishes_predicate_position_from_data_bool() {
        let predicate = Desugared::PredicateValue(
            crate::sugar::predicate_value::PredicateValue::new(eq(var("flag"), bool_const(true))),
        );

        assert_eq!(
            predicate.accept_predicate_value_floor(PredicateKindProbe),
            "predicate:="
        );
        assert_eq!(
            Desugared::Term(bool_const(true)).accept_predicate_value_floor(PredicateKindProbe),
            "non:Term"
        );
        assert_eq!(
            bool_const(true).accept_bool_floor(BoolLiteralProbe),
            Some(true)
        );
    }

    #[test]
    #[should_panic(
        expected = "predicate consumer completed Term floor where a PredicateValue floor was required"
    )]
    fn required_predicate_value_rejects_data_bool_term() {
        Desugared::Term(bool_const(true)).accept_predicate_value_floor(
            RequiredPredicateValueVisitor {
                owner: "predicate consumer",
            },
        );
    }

    #[test]
    fn predicate_value_floor_composes_nested_predicates_without_resniffing_terms() {
        let predicate = Desugared::PredicateValue(
            crate::sugar::predicate_value::PredicateValue::new(and_(vec![
                eq(var("p"), bool_const(true)),
                eq(var("q"), bool_const(false)),
            ])),
        );

        let value = predicate.accept_predicate_value_floor(RequiredPredicateValueVisitor {
            owner: "nested predicate",
        });
        let Formula::Connective { kind, operands } = value.formula().as_ref() else {
            panic!("expected nested predicate connective");
        };
        assert_eq!(kind, "and");
        assert_eq!(operands.len(), 2);
    }

    struct SymbolicProbe;

    impl SymbolicValueFloorVisitor for SymbolicProbe {
        type Output = Option<String>;

        fn visit_symbolic_value(self, value: SymbolicValue) -> Self::Output {
            match value.term().as_ref() {
                Term::Var { name } => Some(name.clone()),
                other => panic!("SymbolicValue committed a non-var carrier: {other:?}"),
            }
        }

        fn visit_non_symbolic(self, _term: &Rc<Term>) -> Self::Output {
            None
        }
    }

    #[test]
    fn symbolic_value_floor_dispatches_var_without_sort_commitment() {
        assert_eq!(
            var("runtime_value").accept_symbolic_value_floor(SymbolicProbe),
            Some("runtime_value".to_string())
        );
    }

    #[test]
    fn symbolic_value_floor_does_not_claim_carrier_committed_const() {
        assert_eq!(num(1).accept_symbolic_value_floor(SymbolicProbe), None);
    }

    #[test]
    fn synthetic_open_edge_floor_dispatches_to_coverage_gap() {
        let floor = Desugared::ObjectValue(crate::sugar::object_value::ObjectValue::new(
            "PluginFloor",
            Vec::new(),
            Vec::new(),
        ));

        let FloorDispatch::Gap(gap) =
            term_floor_dispatch(floor, "synthetic.plugin", "synthetic PluginFloor")
        else {
            panic!("synthetic open-edge floor should dispatch to a coverage gap");
        };

        assert_eq!(gap.gap_kind, "FloorDispatch");
        assert_eq!(gap.gap_locus, "TermFloor");
        assert_eq!(gap.owner, "synthetic.plugin");
        assert_eq!(gap.blame, "synthetic PluginFloor");
        assert_eq!(gap.observed, "ObjectValue");
        assert_eq!(gap.requested, "TermFloor");
        assert_eq!(gap.fix, "sugar::term_dispatch");

        let effect = FloorDispatch::<Rc<Term>>::Gap(gap).into_result();
        let Err(Effect::CoverageGap { boundary, reason }) = effect else {
            panic!("FloorDispatch::Gap must lower to Effect::CoverageGap");
        };
        assert_eq!(boundary, "ObjectValue");
        assert!(reason.contains("write more FloorDispatch for this TermFloor"));
        assert!(reason.contains("observed=ObjectValue"));
        assert!(reason.contains("requested=TermFloor"));
    }

    #[test]
    fn closed_term_floors_dispatch_without_gap() {
        let FloorDispatch::Dispatched(term) =
            term_floor_dispatch(Desugared::Term(var("x")), "closed.term", "x")
        else {
            panic!("Term floor is closed and must not enter the gap path");
        };
        assert!(matches!(term.as_ref(), Term::Var { name } if name == "x"));

        let FloorDispatch::Dispatched(array_term) = term_floor_dispatch(
            Desugared::TermSeq(vec![num(1), num(2)]),
            "closed.seq",
            "[1,2]",
        ) else {
            panic!("TermSeq floor is closed and must not enter the gap path");
        };
        assert!(matches!(
            array_term.as_ref(),
            Term::Var { name } if name == "literal:Array(i:1,i:2)"
        ));
    }

    #[test]
    fn curry_replaces_bound_param_inside_ground_arithmetic() {
        let term = Rc::new(Term::Ctor {
            name: "+".to_string(),
            args: vec![var("x"), num(1)],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "x",
            arg: &num(2),
            occurrence: occurrence("map", 0),
        });

        assert_eq!(const_fold_int_term(&curried), Some(3));
    }

    #[test]
    fn runtime_call_curries_to_orderless_occurrence_symbol() {
        let term = Rc::new(Term::Ctor {
            name: "call:f".to_string(),
            args: vec![var("x")],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "x",
            arg: &num(2),
            occurrence: occurrence("map", 1),
        });

        match curried.as_ref() {
            Term::Ctor { name, args } => {
                assert_eq!(name, "call:f#map2");
                assert!(args.is_empty());
            }
            other => panic!("expected curried call occurrence, got {other:?}"),
        }
    }

    #[test]
    fn curry_dispatches_literal_method_predicate_to_bool_floor() {
        let term = Rc::new(Term::Ctor {
            name: "method:is_ascii_uppercase".to_string(),
            args: vec![var("ch")],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "ch",
            arg: &num(i128::from(b'A')),
            occurrence: occurrence("quant", 0),
        });

        assert_eq!(
            curried.accept_term_floor(LiteralPredicateBoolVisitor),
            Some(true)
        );
    }

    #[test]
    fn curry_dispatches_literal_to_string_to_format_floor() {
        let term = Rc::new(Term::Ctor {
            name: "method:to_string".to_string(),
            args: vec![var("id")],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "id",
            arg: &num(42),
            occurrence: occurrence("map", 0),
        });

        match curried.as_ref() {
            Term::Const {
                value: ConstValue::String(value),
                ..
            } => assert_eq!(value, "42"),
            other => panic!("expected curried to_string literal, got {other:?}"),
        }
    }

    #[test]
    fn curry_keeps_opaque_method_as_orderless_occurrence_symbol() {
        let term = Rc::new(Term::Ctor {
            name: "method:opaque_predicate".to_string(),
            args: vec![var("x")],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "x",
            arg: &num(7),
            occurrence: occurrence("quant", 2),
        });

        match curried.as_ref() {
            Term::Ctor { name, args } => {
                assert_eq!(name, "method:opaque_predicate#quant3");
                assert!(args.is_empty());
            }
            other => panic!("expected opaque method occurrence, got {other:?}"),
        }
    }

    #[test]
    fn predicate_visitor_folds_curried_comparison_floor() {
        let term = Rc::new(Term::Ctor {
            name: "cmp:gt".to_string(),
            args: vec![
                Rc::new(Term::Ctor {
                    name: "deref".to_string(),
                    args: vec![var("n")],
                }),
                num(3),
            ],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "n",
            arg: &num(4),
            occurrence: occurrence("quant", 0),
        });

        assert_eq!(
            curried.accept_term_floor(LiteralPredicateBoolVisitor),
            Some(true)
        );
    }

    #[test]
    fn predicate_visitor_folds_nested_deref_bitand_comparison_floor() {
        let term = Rc::new(Term::Ctor {
            name: "cmp:eq".to_string(),
            args: vec![
                Rc::new(Term::Ctor {
                    name: "bv32.and".to_string(),
                    args: vec![
                        Rc::new(Term::Ctor {
                            name: "deref".to_string(),
                            args: vec![var("n")],
                        }),
                        num(1),
                    ],
                }),
                num(0),
            ],
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "n",
            arg: &num(2),
            occurrence: occurrence("filter", 0),
        });

        assert_eq!(
            curried.accept_term_floor(LiteralPredicateBoolVisitor),
            Some(true)
        );
    }

    #[test]
    fn nested_curry_appends_occurrence_context_to_materialized_calls() {
        let inner = Rc::new(Term::Ctor {
            name: "call:f#map1".to_string(),
            args: Vec::new(),
        });

        let outer = inner.accept_term_floor(CurryVisitor {
            param: "n",
            arg: &num(2),
            occurrence: occurrence("map", 1),
        });

        match outer.as_ref() {
            Term::Ctor { name, args } => {
                assert_eq!(name, "call:f#map1#map2");
                assert!(args.is_empty());
            }
            other => panic!("expected nested curried occurrence, got {other:?}"),
        }
    }

    #[test]
    fn desugared_term_sequence_accepts_curry_without_materializing_array() {
        let floor = Desugared::TermSeq(vec![
            Rc::new(Term::Ctor {
                name: "+".to_string(),
                args: vec![var("n"), num(1)],
            }),
            Rc::new(Term::Ctor {
                name: "+".to_string(),
                args: vec![var("n"), num(2)],
            }),
        ]);

        let curried = floor.accept_desugared_floor(CurryVisitor {
            param: "n",
            arg: &num(10),
            occurrence: occurrence("map", 0),
        });

        let Desugared::TermSeq(terms) = curried else {
            panic!("expected term sequence floor");
        };
        assert_eq!(
            terms.iter().map(const_fold_int_term).collect::<Vec<_>>(),
            vec![Some(11), Some(12),]
        );
    }

    #[test]
    fn literal_array_term_canonicalizes_const_foldable_elements() {
        let add = Rc::new(Term::Ctor {
            name: "+".to_string(),
            args: vec![num(1), num(1)],
        });
        let cast = Rc::new(Term::Ctor {
            name: "cast:u64".to_string(),
            args: vec![num(3)],
        });

        let array = literal_array_term_from_terms(&[add, cast]);

        match array.as_ref() {
            Term::Var { name } => assert_eq!(name, "literal:Array(i:2,i:3)"),
            other => panic!("expected literal array term var, got {other:?}"),
        }
    }

    #[test]
    fn curry_walks_let_body_floor_before_materializing_calls() {
        let term = Rc::new(Term::Let {
            bindings: vec![LetBinding {
                name: "y".to_string(),
                bound_term: var("x"),
            }],
            body: Rc::new(Term::Ctor {
                name: "call:g".to_string(),
                args: vec![var("y")],
            }),
        });

        let curried = term.accept_term_floor(CurryVisitor {
            param: "x",
            arg: &num(9),
            occurrence: occurrence("map", 0),
        });

        match curried.as_ref() {
            Term::Let { bindings, body } => {
                assert!(matches!(
                    bindings[0].bound_term.as_ref(),
                    Term::Const {
                        value: sugar_ir_symbolic::ConstValue::Int(9),
                        sort
                    } if sort.name == "Int"
                ));
                assert!(matches!(
                    body.as_ref(),
                    Term::Ctor { name, args } if name == "call:g#map1" && args.is_empty()
                ));
            }
            other => panic!("expected let body floor, got {other:?}"),
        }
    }

    fn bv32_const(value: u32) -> Rc<Term> {
        Rc::new(Term::Const {
            value: ConstValue::Int(i128::from(value)),
            sort: Sort {
                name: "u32".to_string(),
            },
        })
    }

    fn bv32_ctor(name: &str, args: Vec<Rc<Term>>) -> Rc<Term> {
        Rc::new(Term::Ctor {
            name: name.to_string(),
            args,
        })
    }

    struct Bv32KindProbe;

    impl Bv32FloorVisitor for Bv32KindProbe {
        type Output = String;

        fn visit_bv32_const(self, _term: &Rc<Term>, value: u32) -> Self::Output {
            format!("const:{value}")
        }

        fn visit_bv32_unary(
            self,
            _term: &Rc<Term>,
            op: Bv32UnaryOp,
            _arg: &Rc<Term>,
        ) -> Self::Output {
            format!("unary:{}", op.ctor_name())
        }

        fn visit_bv32_binary(
            self,
            _term: &Rc<Term>,
            op: Bv32BinaryOp,
            _left: &Rc<Term>,
            _right: &Rc<Term>,
        ) -> Self::Output {
            format!("binary:{}", op.ctor_name())
        }

        fn visit_bv32_ite(
            self,
            _term: &Rc<Term>,
            _cond: &Rc<Term>,
            _then_term: &Rc<Term>,
            _else_term: &Rc<Term>,
        ) -> Self::Output {
            "ite".to_string()
        }

        fn visit_non_bv32(self, term: &Rc<Term>) -> Self::Output {
            format!("non:{}", canonical_term_sig(term))
        }
    }

    fn bv32_leaf_sig(term: &Rc<Term>) -> String {
        match term.as_ref() {
            Term::Var { name } => format!("var:{name}"),
            _ => canonical_term_sig(term),
        }
    }

    struct Bv32TreeProbe;

    impl Bv32FloorVisitor for Bv32TreeProbe {
        type Output = String;

        fn visit_bv32_const(self, _term: &Rc<Term>, value: u32) -> Self::Output {
            format!("const:{value}")
        }

        fn visit_bv32_unary(
            self,
            _term: &Rc<Term>,
            op: Bv32UnaryOp,
            arg: &Rc<Term>,
        ) -> Self::Output {
            format!(
                "{}({})",
                op.ctor_name(),
                arg.accept_bv32_floor(Bv32TreeProbe)
            )
        }

        fn visit_bv32_binary(
            self,
            _term: &Rc<Term>,
            op: Bv32BinaryOp,
            left: &Rc<Term>,
            right: &Rc<Term>,
        ) -> Self::Output {
            format!(
                "{}({},{})",
                op.ctor_name(),
                left.accept_bv32_floor(Bv32TreeProbe),
                right.accept_bv32_floor(Bv32TreeProbe)
            )
        }

        fn visit_bv32_ite(
            self,
            _term: &Rc<Term>,
            cond: &Rc<Term>,
            then_term: &Rc<Term>,
            else_term: &Rc<Term>,
        ) -> Self::Output {
            format!(
                "bv32.ite({},{},{})",
                bv32_leaf_sig(cond),
                then_term.accept_bv32_floor(Bv32TreeProbe),
                else_term.accept_bv32_floor(Bv32TreeProbe)
            )
        }

        fn visit_non_bv32(self, term: &Rc<Term>) -> Self::Output {
            bv32_leaf_sig(term)
        }
    }

    #[test]
    fn bv32_floor_dispatches_value_forms_to_typed_arms() {
        assert_eq!(bv32_const(7).accept_bv32_floor(Bv32KindProbe), "const:7");

        assert_eq!(
            bv32_ctor("bv32.neg", vec![var("x")]).accept_bv32_floor(Bv32KindProbe),
            "unary:bv32.neg"
        );

        assert_eq!(
            bv32_ctor("bv32.and", vec![var("a"), var("b")]).accept_bv32_floor(Bv32KindProbe),
            "binary:bv32.and"
        );

        assert_eq!(
            bv32_ctor(
                "bv32.ite",
                vec![bool_const(true), bv32_const(1), bv32_const(0)]
            )
            .accept_bv32_floor(Bv32KindProbe),
            "ite"
        );
    }

    #[test]
    fn bv32_floor_routes_non_bv32_and_predicates_to_escape() {
        assert!(num(7).accept_bv32_floor(Bv32KindProbe).starts_with("non:"));

        assert!(bv32_ctor("bv32.eq", vec![var("a"), var("b")])
            .accept_bv32_floor(Bv32KindProbe)
            .starts_with("non:"));

        assert!(Rc::new(Term::Ctor {
            name: "+".to_string(),
            args: vec![
                bv32_ctor("bv32.and", vec![var("a"), var("b")]),
                bv32_const(1)
            ],
        })
        .accept_bv32_floor(Bv32KindProbe)
        .starts_with("non:"));
    }

    #[test]
    fn bv32_floor_dispatches_nested_value_terms_consistently() {
        let nested = bv32_ctor(
            "bv32.or",
            vec![bv32_ctor("bv32.and", vec![var("a"), var("b")]), var("c")],
        );

        assert_eq!(
            nested.accept_bv32_floor(Bv32TreeProbe),
            "bv32.or(bv32.and(var:a,var:b),var:c)"
        );
    }
}
