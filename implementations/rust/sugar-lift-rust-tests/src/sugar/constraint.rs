// SPDX-License-Identifier: Apache-2.0
//
// ConstraintSugar family: source shapes whose semantic output is a ProofIR
// constraint. The collector asks for the `Constraint` role; these claims own
// syntax entry points that expose an assertion-shaped expression. The proof
// meaning is the expression shape underneath (`lhs cmp rhs`, boolean
// connective, panic locus), not a human method name.

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::configuration;
use crate::sugar::method_family;
use std::collections::BTreeMap;
use std::rc::Rc;

use crate::sugar::factory::{ConstraintFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::{
    ascii_byte_class_atom, ascii_char_class_atom, assertion_entry_from_relation, bool_const,
    callsite_assertion_name, const_fold_int_term, const_fold_u128_term,
    literal_char_predicate_atom, literal_string_value, parse_macro_args, token_key,
    AssertionFactKind, CfgDisposition, CfgPredicate, Desugared, Outcome, RelationOp, Sugar,
    SugarCtx, Warrant,
};
use sugar_ir_symbolic::{and_, atomic_, eq, not_, num, str_const, ConstValue, Formula, Term};
use syn::parse::{Parse, ParseStream};
use syn::{BinOp, Expr, ExprIf, ExprLit, ExprMacro, Lit, Token, Type, UnOp};
use tracing::debug;

pub(crate) const RELATION_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::fallback_with_ordering(
    "constraint_relation_macro",
    SugarRole::Constraint,
    &["constraint_bool_expr"],
    recognize_relation_macro,
);

pub(crate) const RELATION_MACRO_ASSERTION_SURFACE: ExprSugarClaim =
    ExprSugarClaim::fallback_with_ordering(
        "assertion_surface_relation_macro",
        SugarRole::AssertionSurface,
        &["assertion_surface_assert_macro"],
        recognize_relation_macro,
    );

pub(crate) const BOUNDED_LITERAL_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::constraint_before(
    "constraint_bounded_literal_macro",
    &[
        "constraint_relation_macro",
        "constraint_assert_macro",
        "constraint_bool_expr",
    ],
    recognize_bounded_literal_macro,
);

pub(crate) const BOUNDED_LITERAL_MACRO_ASSERTION_SURFACE: ExprSugarClaim =
    ExprSugarClaim::with_ordering(
        "assertion_surface_bounded_literal_macro",
        SugarRole::AssertionSurface,
        &[
            "assertion_surface_relation_macro",
            "assertion_surface_assert_macro",
        ],
        recognize_bounded_literal_macro,
    );

pub(crate) const ASSERT_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::constraint_before(
    "constraint_assert_macro",
    &["constraint_bool_expr"],
    recognize_assert_macro,
);

pub(crate) const ASSERT_MACRO_ASSERTION_SURFACE: ExprSugarClaim =
    ExprSugarClaim::fallback_assertion_surface(
        "assertion_surface_assert_macro",
        recognize_assert_macro,
    );

pub(crate) const CFG_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::constraint_before(
    "constraint_cfg_macro",
    &["constraint_bool_expr"],
    recognize_cfg_macro,
);

pub(crate) const BOOL_EXPR_SUGAR: ExprSugarClaim =
    ExprSugarClaim::fallback_constraint("constraint_bool_expr", recognize_bool_expr);

pub(crate) const IF_PANIC_SUGAR: ExprSugarClaim = ExprSugarClaim::constraint_before(
    "constraint_if_panic",
    &["constraint_bool_expr"],
    recognize_if_panic,
);

pub(crate) const NO_PANIC_CALL_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_no_panic_call",
    SugarRole::SupportConstraint,
    recognize_no_panic_call,
);

struct RelationMacroSugar {
    name: String,
    lhs: SugarBody<TermFloor>,
    rhs: SugarBody<TermFloor>,
    op: RelationOp,
    debug_gated: bool,
}

struct BoundedLiteralMacroSugar {
    negate: bool,
    predicate: String,
    sources: Vec<String>,
}

fn recognize_bounded_literal_macro(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    let name = mac.path.segments.last()?.ident.to_string();
    let negate = match name.as_str() {
        "assert_all" => false,
        "assert_none" => true,
        _ => return None,
    };
    let args = parse_macro_args(mac.tokens.clone()).ok()?;
    let predicate = bounded_literal_predicate_name(args.exprs.first()?)?;
    let sources: Vec<String> = args.exprs[1..]
        .iter()
        .map(literal_string_value)
        .collect::<Option<_>>()?;
    if sources.is_empty() {
        return None;
    }
    Some(Box::new(BoundedLiteralMacroSugar {
        negate,
        predicate,
        sources,
    }))
}

impl Sugar for BoundedLiteralMacroSugar {
    fn desugar(&self, _ctx: &SugarCtx) -> Outcome {
        let mut atoms = Vec::new();
        for source in &self.sources {
            for ch in source.chars() {
                let atom = ascii_char_class_atom(&self.predicate, str_const(ch.to_string()))
                    .or_else(|| literal_char_predicate_atom(&self.predicate, ch));
                let Some(atom) = atom else {
                    constraint_gap(format!(
                        "unsupported bounded literal macro predicate `{}`",
                        self.predicate
                    ));
                };
                atoms.push(if self.negate { not_(atom) } else { atom });
            }
            if !bounded_literal_char_only_predicate(&self.predicate) {
                for byte in source.as_bytes() {
                    let Some(atom) = ascii_byte_class_atom(&self.predicate, num(i128::from(*byte)))
                    else {
                        constraint_gap(format!(
                            "unsupported bounded literal macro predicate `{}`",
                            self.predicate
                        ));
                    };
                    atoms.push(if self.negate { not_(atom) } else { atom });
                }
            }
        }
        if atoms.is_empty() {
            constraint_gap("bounded literal macro emitted no predicate atoms");
        }
        Outcome::Complete(Desugared::Constraints {
            atom: and_(atoms),
            n: 1,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant { name: None },
        })
    }
}

fn bounded_literal_predicate_name(expr: &Expr) -> Option<String> {
    match expr {
        Expr::Path(path) => path.path.get_ident().map(|ident| ident.to_string()),
        Expr::Paren(paren) => bounded_literal_predicate_name(&paren.expr),
        Expr::Group(group) => bounded_literal_predicate_name(&group.expr),
        _ => None,
    }
}

fn bounded_literal_char_only_predicate(method: &str) -> bool {
    matches!(method, "is_alphabetic")
}

fn recognize_relation_macro(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    let name = mac.path.segments.last()?.ident.to_string();
    if name == "assert_eq_const_safe" {
        return recognize_assert_eq_const_safe_macro(mac, fcx);
    }
    let (op, debug_gated) = match name.as_str() {
        "assert_eq" => (RelationOp::Eq, false),
        "assert_ne" => (RelationOp::Ne, false),
        "debug_assert_eq" => (RelationOp::Eq, true),
        "debug_assert_ne" => (RelationOp::Ne, true),
        _ => return None,
    };
    let args = parse_macro_args(mac.tokens.clone()).ok()?;
    if args.exprs.len() < 2 {
        return None;
    }
    Some(Box::new(RelationMacroSugar {
        name,
        lhs: SugarBody::term(&args.exprs[0], fcx),
        rhs: SugarBody::term(&args.exprs[1], fcx),
        op,
        debug_gated,
    }))
}

fn recognize_assert_eq_const_safe_macro(
    mac: &syn::Macro,
    fcx: &SugarBuildCtx,
) -> Option<Box<dyn Sugar>> {
    if fcx
        .scope()
        .macro_registry()
        .lookup("assert_eq_const_safe")
        .is_none()
    {
        return None;
    }
    let (lhs_expr, rhs_expr) = parse_assert_eq_const_safe_operands(mac.tokens.clone())?;
    Some(Box::new(RelationMacroSugar {
        name: "assert_eq_const_safe".to_string(),
        lhs: SugarBody::term(&lhs_expr, fcx),
        rhs: SugarBody::term(&rhs_expr, fcx),
        op: RelationOp::Eq,
        debug_gated: false,
    }))
}

pub(crate) fn parse_assert_eq_const_safe_operands(
    tokens: proc_macro2::TokenStream,
) -> Option<(Expr, Expr)> {
    let args = syn::parse2::<AssertEqConstSafeArgs>(tokens).ok()?;
    Some((args.lhs, args.rhs))
}

struct AssertEqConstSafeArgs {
    lhs: Expr,
    rhs: Expr,
}

impl Parse for AssertEqConstSafeArgs {
    fn parse(input: ParseStream<'_>) -> syn::Result<Self> {
        let _ty = input.parse::<Type>()?;
        input.parse::<Token![:]>()?;
        let lhs = input.parse::<Expr>()?;
        input.parse::<Token![,]>()?;
        let rhs = input.parse::<Expr>()?;
        if input.peek(Token![,]) {
            input.parse::<Token![,]>()?;
            let _message = input.parse::<proc_macro2::TokenStream>()?;
        }
        Ok(Self { lhs, rhs })
    }
}

impl Sugar for RelationMacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = inactive_debug_assertion(&self.name, self.debug_gated, ctx) {
            return outcome;
        }
        relation_constraint_from_bodies(&self.name, &self.lhs, &self.rhs, self.op, ctx)
    }
}

struct AssertSugar {
    name: String,
    payload: SugarBody<ConstraintFloor>,
    debug_gated: bool,
}

fn recognize_assert_macro(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    let name = mac.path.segments.last()?.ident.to_string();
    let debug_gated = match name.as_str() {
        "assert" => false,
        "debug_assert" => true,
        _ => return None,
    };
    let args = parse_macro_args(mac.tokens.clone()).ok()?;
    let expr = args.exprs.first()?.clone();
    Some(Box::new(AssertSugar {
        name,
        payload: SugarBody::constraint(&expr, fcx),
        debug_gated,
    }))
}

impl Sugar for AssertSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Some(outcome) = inactive_debug_assertion(&self.name, self.debug_gated, ctx) {
            return outcome;
        }
        self.payload.reduce(ctx)
    }
}

struct CfgMacroSugar {
    mac: syn::Macro,
}

fn recognize_cfg_macro(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::Macro(ExprMacro { mac, .. }) = expr else {
        return None;
    };
    if !mac
        .path
        .segments
        .last()
        .is_some_and(|segment| segment.ident == "cfg")
    {
        return None;
    }
    Some(Box::new(CfgMacroSugar { mac: mac.clone() }))
}

impl Sugar for CfgMacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let predicate = match self.mac.parse_body::<CfgPredicate>() {
            Ok(predicate) => predicate,
            Err(e) => {
                constraint_gap(format!("cfg!: cannot parse cfg predicate: {e}"));
            }
        };
        let value = match configuration::resolve_predicate(&predicate, ctx.options) {
            CfgDisposition::Present => true,
            CfgDisposition::Absent(_) => false,
            CfgDisposition::Ambiguous(reason) => constraint_gap(format!(
                "cfg!: ambiguous cfg predicate `{predicate}`: {reason}"
            )),
        };
        Outcome::Complete(Desugared::Constraints {
            atom: eq(bool_const(value), bool_const(true)),
            n: 1,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant { name: None },
        })
    }
}

enum BoolExprKind {
    Connective {
        left: SugarBody<ConstraintFloor>,
        right: SugarBody<ConstraintFloor>,
        is_and: bool,
    },
    Relation {
        lhs: SugarBody<TermFloor>,
        rhs: SugarBody<TermFloor>,
        op: RelationOp,
    },
    Not(SugarBody<ConstraintFloor>),
    Literal(bool),
    PredicateTerm {
        term: SugarBody<TermFloor>,
        expr: Expr,
        asserted: bool,
    },
    Wrapper(SugarBody<ConstraintFloor>),
}

struct BoolExprSugar {
    kind: BoolExprKind,
}

fn recognize_bool_expr(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Binary(binary) if matches!(binary.op, BinOp::And(_) | BinOp::Or(_)) => {
            Some(Box::new(BoolExprSugar {
                kind: BoolExprKind::Connective {
                    left: SugarBody::constraint(&binary.left, fcx),
                    right: SugarBody::constraint(&binary.right, fcx),
                    is_and: matches!(binary.op, BinOp::And(_)),
                },
            }))
        }
        Expr::Binary(binary) => {
            let op = relation_from_binop(&binary.op)?;
            Some(Box::new(BoolExprSugar {
                kind: BoolExprKind::Relation {
                    lhs: SugarBody::term(&binary.left, fcx),
                    rhs: SugarBody::term(&binary.right, fcx),
                    op,
                },
            }))
        }
        Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Not(SugarBody::constraint(&unary.expr, fcx)),
        })),
        Expr::Lit(ExprLit {
            lit: Lit::Bool(value),
            ..
        }) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Literal(value.value),
        })),
        expr if is_predicate_term_expr(expr) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::PredicateTerm {
                term: SugarBody::term(expr, fcx),
                expr: expr.clone(),
                asserted: true,
            },
        })),
        Expr::Paren(paren) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Wrapper(SugarBody::constraint(&paren.expr, fcx)),
        })),
        Expr::Group(group) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Wrapper(SugarBody::constraint(&group.expr, fcx)),
        })),
        _ => None,
    }
}

impl Sugar for BoolExprSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match &self.kind {
            BoolExprKind::Connective {
                left,
                right,
                is_and,
            } => {
                let left = match constraint_payload(left, ctx) {
                    Ok(payload) => payload,
                    Err(outcome) => return outcome,
                };
                match (*is_and, const_formula_bool(left.atom.as_ref())) {
                    (true, Some(false)) | (false, Some(true)) => {
                        debug!(
                            target: "sugar_lift_rust_tests::sugar::constraint",
                            connective = if *is_and { "&&" } else { "||" },
                            left_value = !*is_and,
                            "short-circuited boolean constraint on left literal-backed side"
                        );
                        return constraints_from_payload(left);
                    }
                    (true, Some(true)) | (false, Some(false)) => {
                        debug!(
                            target: "sugar_lift_rust_tests::sugar::constraint",
                            connective = if *is_and { "&&" } else { "||" },
                            left_value = *is_and,
                            "continued boolean constraint after non-deciding left literal-backed side"
                        );
                        let right = match constraint_payload(right, ctx) {
                            Ok(payload) => payload,
                            Err(outcome) => return outcome,
                        };
                        return constraints_from_payload(right);
                    }
                    _ => {}
                }
                let right = match constraint_payload(right, ctx) {
                    Ok(payload) => payload,
                    Err(outcome) => return outcome,
                };
                let atom = if *is_and {
                    and_(vec![left.atom, right.atom])
                } else {
                    sugar_ir_symbolic::or_(vec![left.atom, right.atom])
                };
                Outcome::Complete(Desugared::Constraints {
                    atom,
                    n: 1,
                    kind: if left.kind.is_warranted() || right.kind.is_warranted() {
                        AssertionFactKind::Warranted
                    } else {
                        AssertionFactKind::Support
                    },
                    warrant: Warrant {
                        name: common_constraint_name(&left.name, &right.name),
                    },
                })
            }
            BoolExprKind::Relation { lhs, rhs, op } => {
                relation_constraint_from_bodies("assert", lhs, rhs, *op, ctx)
            }
            BoolExprKind::Not(inner) => {
                let inner = match constraint_payload(inner, ctx) {
                    Ok(payload) => payload,
                    Err(outcome) => return outcome,
                };
                if let Some(atom) = bool_true_assertion_as_false(inner.atom.as_ref()) {
                    return Outcome::Complete(Desugared::Constraints {
                        atom,
                        n: 1,
                        kind: inner.kind,
                        warrant: Warrant { name: inner.name },
                    });
                }
                Outcome::Complete(Desugared::Constraints {
                    atom: not_(inner.atom),
                    n: 1,
                    kind: inner.kind,
                    warrant: Warrant { name: inner.name },
                })
            }
            BoolExprKind::Literal(value) => {
                let entry = assertion_entry_from_relation(
                    bool_const(*value),
                    bool_const(true),
                    RelationOp::Eq,
                    ctx.scope,
                );
                constraint_from_entry(entry)
            }
            BoolExprKind::PredicateTerm {
                term,
                expr: _,
                asserted,
            } => {
                let term = match term_payload(term, ctx) {
                    Ok(term) => term,
                    Err(outcome) => return outcome,
                };
                constraint_from_entry(assertion_entry_from_relation(
                    term,
                    bool_const(*asserted),
                    RelationOp::Eq,
                    ctx.scope,
                ))
            }
            BoolExprKind::Wrapper(inner) => inner.reduce(ctx),
        }
    }
}

fn constraints_from_payload(payload: ConstraintPayload) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom: payload.atom,
        n: 1,
        kind: payload.kind,
        warrant: Warrant { name: payload.name },
    })
}

fn is_predicate_term_expr(expr: &Expr) -> bool {
    matches!(
        expr,
        Expr::Path(_) | Expr::Call(_) | Expr::MethodCall(_) | Expr::Await(_) | Expr::Field(_)
    )
}

fn bool_true_assertion_as_false(atom: &Formula) -> Option<Rc<Formula>> {
    let Formula::Atomic { name, args } = atom else {
        return None;
    };
    if name != "=" || args.len() != 2 {
        return None;
    }
    if is_bool_const(args[1].as_ref(), true) {
        return Some(eq(args[0].clone(), bool_const(false)));
    }
    if is_bool_const(args[0].as_ref(), true) {
        return Some(eq(bool_const(false), args[1].clone()));
    }
    None
}

fn is_bool_const(term: &Term, expected: bool) -> bool {
    matches!(
        term,
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } if *value == expected
    )
}

fn const_formula_bool(formula: &Formula) -> Option<bool> {
    match formula {
        Formula::Atomic { name, args } if args.len() == 2 => {
            const_atomic_bool(name, &args[0], &args[1])
        }
        Formula::Connective { kind, operands } if kind == "not" && operands.len() == 1 => {
            const_formula_bool(operands[0].as_ref()).map(|value| !value)
        }
        Formula::Connective { kind, operands } if kind == "and" => {
            let mut saw_any = false;
            for operand in operands {
                saw_any = true;
                match const_formula_bool(operand.as_ref()) {
                    Some(false) => return Some(false),
                    Some(true) => {}
                    None => return None,
                }
            }
            saw_any.then_some(true)
        }
        Formula::Connective { kind, operands } if kind == "or" => {
            let mut saw_any = false;
            for operand in operands {
                saw_any = true;
                match const_formula_bool(operand.as_ref()) {
                    Some(true) => return Some(true),
                    Some(false) => {}
                    None => return None,
                }
            }
            saw_any.then_some(false)
        }
        _ => None,
    }
}

fn const_atomic_bool(name: &str, lhs: &Rc<Term>, rhs: &Rc<Term>) -> Option<bool> {
    if let Some((left, right)) = const_u128_pair(lhs, rhs) {
        return compare_u128(name, left, right);
    }
    if let Some((left, right)) = const_int_pair(lhs, rhs) {
        return compare_i128(name, left, right);
    }
    if let Some((left, right)) = const_bool_pair(lhs, rhs) {
        return match name {
            "=" => Some(left == right),
            "\u{2260}" => Some(left != right),
            _ => None,
        };
    }
    None
}

fn const_u128_pair(lhs: &Rc<Term>, rhs: &Rc<Term>) -> Option<(u128, u128)> {
    let left_u = const_fold_u128_term(lhs);
    let right_u = const_fold_u128_term(rhs);
    if left_u.is_none() && right_u.is_none() {
        return None;
    }
    Some((
        left_u.or_else(|| const_fold_int_term(lhs).and_then(|n| u128::try_from(n).ok()))?,
        right_u.or_else(|| const_fold_int_term(rhs).and_then(|n| u128::try_from(n).ok()))?,
    ))
}

fn const_int_pair(lhs: &Rc<Term>, rhs: &Rc<Term>) -> Option<(i128, i128)> {
    Some((const_fold_int_term(lhs)?, const_fold_int_term(rhs)?))
}

fn const_bool_pair(lhs: &Rc<Term>, rhs: &Rc<Term>) -> Option<(bool, bool)> {
    Some((term_bool(lhs.as_ref())?, term_bool(rhs.as_ref())?))
}

fn term_bool(term: &Term) -> Option<bool> {
    match term {
        Term::Const {
            value: ConstValue::Bool(value),
            ..
        } => Some(*value),
        _ => None,
    }
}

fn compare_u128(name: &str, left: u128, right: u128) -> Option<bool> {
    match name {
        "=" => Some(left == right),
        "\u{2260}" => Some(left != right),
        "<" => Some(left < right),
        "\u{2264}" => Some(left <= right),
        ">" => Some(left > right),
        "\u{2265}" => Some(left >= right),
        _ => None,
    }
}

fn compare_i128(name: &str, left: i128, right: i128) -> Option<bool> {
    match name {
        "=" => Some(left == right),
        "\u{2260}" => Some(left != right),
        "<" => Some(left < right),
        "\u{2264}" => Some(left <= right),
        ">" => Some(left > right),
        "\u{2265}" => Some(left >= right),
        _ => None,
    }
}

struct IfPanicSugar {
    cond: SugarBody<ConstraintFloor>,
    negate: bool,
}

fn recognize_if_panic(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let Expr::If(if_expr) = expr else {
        return None;
    };
    if matches!(&*if_expr.cond, Expr::Let(_)) {
        return None;
    }
    let then_diverges = block_diverges(if_expr);
    let else_diverges = else_branch_diverges(if_expr);
    match (then_diverges, else_diverges) {
        (true, false) => Some(Box::new(IfPanicSugar {
            cond: SugarBody::constraint(&if_expr.cond, fcx),
            negate: true,
        })),
        (false, true) => Some(Box::new(IfPanicSugar {
            cond: SugarBody::constraint(&if_expr.cond, fcx),
            negate: false,
        })),
        _ => None,
    }
}

impl Sugar for IfPanicSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let payload = match constraint_payload(&self.cond, ctx) {
            Ok(payload) => payload,
            Err(outcome) => return outcome,
        };
        let atom = if self.negate {
            not_(payload.atom)
        } else {
            payload.atom
        };
        Outcome::Complete(Desugared::Constraints {
            atom,
            n: 1,
            kind: payload.kind,
            warrant: Warrant { name: payload.name },
        })
    }
}

enum NoPanicKind {
    ReturnsNormally,
    UnconditionalPanic,
}

struct NoPanicCallSugar {
    site: String,
    kind: NoPanicKind,
    term_expr: Option<Expr>,
}

fn recognize_no_panic_call(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !fcx.options().panic_freedom_enabled() {
        return None;
    }
    let kind = match expr {
        Expr::Call(_) | Expr::MethodCall(_) => NoPanicKind::ReturnsNormally,
        Expr::Macro(m) if panic_macro(&m.mac) => NoPanicKind::UnconditionalPanic,
        _ => return None,
    };
    let term_expr = match expr {
        Expr::Call(_) | Expr::MethodCall(_) => Some(expr.clone()),
        _ => None,
    };
    Some(Box::new(NoPanicCallSugar {
        site: token_key(expr),
        kind,
        term_expr,
    }))
}

impl Sugar for NoPanicCallSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let (normal_universe, name) = match &self.term_expr {
            Some(expr) => {
                if is_no_panic_literal_empty_into_iter(expr)
                    || is_no_panic_empty_literal_sequence_callsite(expr, ctx)
                {
                    return no_panic_tautology_for_site(ctx, &self.site);
                }
                let Some(subject) = ctx.opaque_callsite_term(expr) else {
                    constraint_gap(format!(
                        "no-panic callsite `{}` had no opaque subject term",
                        self.site
                    ));
                };
                // Lane 5 concrete-fold: ASCII char-class predicates and
                // `eq_ignore_ascii_case` on literal receivers can NEVER panic.
                // Emit a concrete tautology so the no-panic support entry does
                // not introduce an opaque panic atom into the group `inv` that
                // would block z3 discharge.
                if is_lane5_no_panic_literal_call(expr) {
                    let name = callsite_assertion_name(subject.as_ref(), ctx.scope.local_scope());
                    return Outcome::Complete(Desugared::Constraints {
                        atom: eq(bool_const(true), bool_const(true)),
                        n: 0,
                        kind: AssertionFactKind::Warranted,
                        warrant: Warrant { name },
                    });
                }
                let normal_universe = ctx
                    .normal_return_universe_for_subject(expr, subject.clone())
                    .unwrap_or_else(|| not_(atomic_("panic", vec![subject.clone()])));
                let name = callsite_assertion_name(subject.as_ref(), ctx.scope.local_scope());
                (normal_universe, name)
            }
            None => {
                let subject = str_const(format!("{}::{}", ctx.scope.local_scope(), self.site));
                (not_(atomic_("panic", vec![subject])), None)
            }
        };
        let (atom, kind) = match self.kind {
            NoPanicKind::ReturnsNormally => (normal_universe, AssertionFactKind::Warranted),
            NoPanicKind::UnconditionalPanic => (
                and_(vec![normal_universe.clone(), not_(normal_universe)]),
                AssertionFactKind::Warranted,
            ),
        };
        let name = name.or_else(|| {
            Some(format!(
                "{}::panic-path::{}",
                ctx.scope.local_scope(),
                compact_warrant_fragment(&self.site)
            ))
        });
        Outcome::Complete(Desugared::Constraints {
            atom,
            n: 0,
            kind,
            warrant: Warrant { name },
        })
    }
}

fn no_panic_tautology_for_site(ctx: &SugarCtx, site: &str) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom: eq(bool_const(true), bool_const(true)),
        n: 0,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant {
            name: Some(format!(
                "{}::panic-path::{}",
                ctx.scope.local_scope(),
                compact_warrant_fragment(site)
            )),
        },
    })
}

fn call_path_name(call: &syn::ExprCall) -> Option<String> {
    let Expr::Path(path) = call.func.as_ref() else {
        return None;
    };
    Some(
        path.path
            .segments
            .iter()
            .map(|segment| segment.ident.to_string())
            .collect::<Vec<_>>()
            .join("::"),
    )
}

fn is_no_panic_literal_empty_into_iter(expr: &Expr) -> bool {
    match strip_groups_parens(expr) {
        Expr::Call(call) => {
            let Some(path) = call_path_name(call) else {
                return false;
            };
            path.ends_with("IntoIterator::into_iter")
                && call.args.len() == 1
                && call
                    .args
                    .first()
                    .is_some_and(expr_is_empty_literal_array_expr)
        }
        Expr::MethodCall(call) => {
            call.method == "into_iter" && expr_is_empty_literal_array_expr(&call.receiver)
        }
        _ => false,
    }
}

fn is_no_panic_empty_literal_sequence_callsite(expr: &Expr, ctx: &SugarCtx) -> bool {
    let Expr::MethodCall(call) = strip_groups_parens(expr) else {
        return false;
    };
    let method = call.method.to_string();
    if !matches!(
        method.as_str(),
        "iter"
            | "into_iter"
            | "cloned"
            | "copied"
            | "fuse"
            | "rev"
            | "enumerate"
            | "skip"
            | "take"
            | "step_by"
    ) {
        return false;
    }
    let let_inits: BTreeMap<String, &Expr> = BTreeMap::new();
    method_family::literal_sequence_static_len_in_scope(expr, &let_inits, ctx.scope) == Some(0)
}

fn expr_is_empty_literal_array_expr(expr: &Expr) -> bool {
    match strip_groups_parens(expr) {
        Expr::Array(array) => array.elems.is_empty(),
        Expr::Cast(cast) => expr_is_empty_literal_array_expr(&cast.expr),
        Expr::Reference(reference) if reference.mutability.is_none() => {
            expr_is_empty_literal_array_expr(&reference.expr)
        }
        _ => false,
    }
}

fn strip_groups_parens(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => strip_groups_parens(&paren.expr),
        Expr::Group(group) => strip_groups_parens(&group.expr),
        _ => expr,
    }
}

fn compact_warrant_fragment(site: &str) -> String {
    site.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '_' | ':' | '.') {
                ch
            } else {
                '_'
            }
        })
        .collect()
}

fn block_diverges(if_expr: &ExprIf) -> bool {
    if_expr
        .then_branch
        .stmts
        .last()
        .is_some_and(stmt_panics_or_aborts)
}

fn else_branch_diverges(if_expr: &ExprIf) -> bool {
    if_expr
        .else_branch
        .as_ref()
        .is_some_and(|(_, expr)| expr_panics_or_aborts(expr))
}

fn stmt_panics_or_aborts(stmt: &syn::Stmt) -> bool {
    match stmt {
        syn::Stmt::Expr(expr, _) => expr_panics_or_aborts(expr),
        syn::Stmt::Macro(m) => panic_macro(&m.mac),
        _ => false,
    }
}

fn expr_panics_or_aborts(expr: &Expr) -> bool {
    match expr {
        Expr::Macro(m) => panic_macro(&m.mac),
        Expr::Block(block) => block.block.stmts.last().is_some_and(stmt_panics_or_aborts),
        Expr::Unsafe(unsafe_expr) => unsafe_expr
            .block
            .stmts
            .last()
            .is_some_and(stmt_panics_or_aborts),
        Expr::Paren(paren) => expr_panics_or_aborts(&paren.expr),
        Expr::Group(group) => expr_panics_or_aborts(&group.expr),
        Expr::Call(call) => {
            let Expr::Path(path) = &*call.func else {
                return false;
            };
            let last = path
                .path
                .segments
                .last()
                .map(|segment| segment.ident.to_string());
            matches!(last.as_deref(), Some("exit") | Some("abort"))
                && path
                    .path
                    .segments
                    .iter()
                    .any(|segment| segment.ident == "process")
        }
        _ => false,
    }
}

fn panic_macro(mac: &syn::Macro) -> bool {
    mac.path.segments.last().is_some_and(|segment| {
        matches!(
            segment.ident.to_string().as_str(),
            "panic" | "unreachable" | "todo" | "unimplemented"
        )
    })
}

fn inactive_debug_assertion(name: &str, debug_gated: bool, ctx: &SugarCtx) -> Option<Outcome> {
    if !debug_gated {
        return None;
    }
    match configuration::resolve_predicate(
        &CfgPredicate::Name("debug_assertions".to_string()),
        ctx.options,
    ) {
        CfgDisposition::Present => None,
        CfgDisposition::Absent(reason) => Some(inert_support_constraint(
            ctx,
            format!("{name}!: cfg(debug_assertions) not active; skipped: {reason}"),
        )),
        CfgDisposition::Ambiguous(reason) => constraint_gap(format!(
            "{name}!: cfg(debug_assertions) ambiguous; skipped: {reason}"
        )),
    }
}

fn inert_support_constraint(ctx: &SugarCtx, reason: String) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom: eq(bool_const(true), bool_const(true)),
        n: 0,
        kind: AssertionFactKind::Support,
        warrant: Warrant {
            name: Some(format!(
                "{}::inactive::{}",
                ctx.scope.local_scope(),
                compact_warrant_fragment(&reason)
            )),
        },
    })
}

fn constraint_from_entry(entry: crate::AssertionEntry) -> Outcome {
    Outcome::Complete(Desugared::Constraints {
        atom: entry.atom,
        n: 1,
        kind: AssertionFactKind::Warranted,
        warrant: Warrant { name: entry.name },
    })
}

struct ConstraintPayload {
    atom: Rc<Formula>,
    kind: AssertionFactKind,
    name: Option<String>,
}

fn constraint_payload(
    body: &SugarBody<ConstraintFloor>,
    ctx: &SugarCtx,
) -> Result<ConstraintPayload, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(Desugared::Constraints {
            atom,
            kind,
            warrant,
            ..
        }) => Ok(ConstraintPayload {
            atom,
            kind,
            name: warrant.name,
        }),
        Outcome::Complete(_) => {
            constraint_gap("constraint body reduced to a non-constraint floor");
        }
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn relation_constraint_from_bodies(
    name: &str,
    lhs: &SugarBody<TermFloor>,
    rhs: &SugarBody<TermFloor>,
    op: RelationOp,
    ctx: &SugarCtx,
) -> Outcome {
    let lhs = match term_payload(lhs, ctx) {
        Ok(term) => term,
        Err(outcome) => return outcome,
    };
    let rhs = match term_payload(rhs, ctx) {
        Ok(term) => term,
        Err(outcome) => return outcome,
    };
    constraint_from_entry(assertion_entry_from_relation(lhs, rhs, op, ctx.scope))
}

fn term_payload(body: &SugarBody<TermFloor>, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match body.reduce(ctx) {
        Outcome::Complete(desugared) => Ok(desugared
            .into_term()
            .unwrap_or_else(|| constraint_gap("term body reduced to a non-term floor"))),
        Outcome::Incomplete(effect) => Err(Outcome::Incomplete(effect)),
    }
}

fn common_constraint_name(left: &Option<String>, right: &Option<String>) -> Option<String> {
    match (left, right) {
        (Some(left), Some(right)) if left == right => Some(left.clone()),
        _ => None,
    }
}

fn relation_from_binop(op: &BinOp) -> Option<RelationOp> {
    match op {
        BinOp::Eq(_) => Some(RelationOp::Eq),
        BinOp::Ne(_) => Some(RelationOp::Ne),
        BinOp::Lt(_) => Some(RelationOp::Lt),
        BinOp::Le(_) => Some(RelationOp::Le),
        BinOp::Gt(_) => Some(RelationOp::Gt),
        BinOp::Ge(_) => Some(RelationOp::Ge),
        _ => None,
    }
}

/// Returns `true` when `expr` is a method call that can NEVER panic and whose
/// result is fully determined by the literal receiver / arguments.  These are
/// the Lane 5 ASCII char-class predicates and `eq_ignore_ascii_case`.
///
/// For such calls the "no-panic support" entry emitted by [`NoPanicCallSugar`]
/// should be a concrete tautology (`eq(true, true)`) rather than the opaque
/// `not(panic(method:…(…)))` atom.  An opaque atom in the group `inv` makes
/// both the positive and negative z3 queries SAT, keeping the discharge status
/// at `Undecided` even after the primary `StringPredicateSugar` has lowered the
/// predicate to `eq(bool(result), bool(true))`.
fn is_lane5_no_panic_literal_call(expr: &Expr) -> bool {
    let Expr::MethodCall(call) = expr else {
        return false;
    };
    let method = call.method.to_string();
    match method.as_str() {
        // Zero-arg ASCII char-class predicates — receiver must be a char or byte literal.
        "is_ascii_alphabetic"
        | "is_ascii_alphanumeric"
        | "is_ascii_control"
        | "is_ascii_digit"
        | "is_ascii_graphic"
        | "is_ascii_hexdigit"
        | "is_ascii_lowercase"
        | "is_ascii_octdigit"
        | "is_ascii_punctuation"
        | "is_ascii_uppercase"
        | "is_ascii_whitespace" => call.args.is_empty() && is_char_or_byte_lit(&call.receiver),
        // Case-insensitive string comparison — one arg, both sides must be string/char literals.
        "eq_ignore_ascii_case" => {
            call.args.len() == 1
                && is_str_or_char_lit(&call.receiver)
                && is_str_or_char_lit(&call.args[0])
        }
        _ => false,
    }
}

/// `true` iff `expr` is a char literal or byte literal (recursing through
/// parentheses and groups).
fn is_char_or_byte_lit(expr: &Expr) -> bool {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Char(_), ..
        }) => true,
        Expr::Lit(ExprLit {
            lit: Lit::Byte(_), ..
        }) => true,
        Expr::Paren(p) => is_char_or_byte_lit(&p.expr),
        Expr::Group(g) => is_char_or_byte_lit(&g.expr),
        _ => false,
    }
}

/// `true` iff `expr` is a string literal or char literal (recursing through
/// parentheses and groups).
fn is_str_or_char_lit(expr: &Expr) -> bool {
    match expr {
        Expr::Lit(ExprLit {
            lit: Lit::Str(_) | Lit::Char(_),
            ..
        }) => true,
        Expr::Paren(p) => is_str_or_char_lit(&p.expr),
        Expr::Group(g) => is_str_or_char_lit(&g.expr),
        _ => false,
    }
}

fn constraint_gap(reason: impl Into<String>) -> ! {
    panic!(
        "constraint did not reach a lawful proof-universe floor: {}",
        reason.into()
    )
}
