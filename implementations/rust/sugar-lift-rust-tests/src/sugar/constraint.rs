// SPDX-License-Identifier: Apache-2.0
//
// ConstraintSugar family: source shapes whose semantic output is a ProofIR
// constraint. The collector asks for the `Constraint` role; these claims own
// syntax entry points that expose an assertion-shaped expression. The proof
// meaning is the expression shape underneath (`lhs cmp rhs`, boolean
// connective, panic locus), not a human method name.

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::configuration;
use crate::sugar::constraint_runtime_boundary;
use std::rc::Rc;

use crate::sugar::factory::{build_constraint, build_term, SugarBuildCtx};
use crate::{
    ascii_byte_class_atom, ascii_char_class_atom, assertion_entry_from_relation, bool_const,
    callsite_assertion_name, const_fold_int_term, const_fold_u128_term,
    literal_char_predicate_atom, literal_string_value, parse_macro_args, token_key,
    AssertionFactKind, CfgDisposition, CfgPredicate, Desugared, Effect, Outcome, RelationOp, Sugar,
    SugarCtx, Warrant, STRUCTURAL_BACKSTOP_REASON,
};
use sugar_ir_symbolic::{and_, atomic_, eq, not_, num, str_const, ConstValue, Formula, Term};
use syn::{BinOp, Expr, ExprIf, ExprLit, ExprMacro, Lit, UnOp};
use tracing::debug;

pub(crate) const RELATION_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_relation_macro",
    SugarRole::Constraint,
    SugarPriority::Secondary,
    recognize_relation_macro,
);

pub(crate) const RELATION_MACRO_ASSERTION_SURFACE: ExprSugarClaim = ExprSugarClaim::new(
    "assertion_surface_relation_macro",
    SugarRole::AssertionSurface,
    SugarPriority::Secondary,
    recognize_relation_macro,
);

pub(crate) const BOUNDED_LITERAL_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_bounded_literal_macro",
    SugarRole::Constraint,
    SugarPriority::Primary,
    recognize_bounded_literal_macro,
);

pub(crate) const BOUNDED_LITERAL_MACRO_ASSERTION_SURFACE: ExprSugarClaim = ExprSugarClaim::new(
    "assertion_surface_bounded_literal_macro",
    SugarRole::AssertionSurface,
    SugarPriority::Primary,
    recognize_bounded_literal_macro,
);

pub(crate) const ASSERT_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_assert_macro",
    SugarRole::Constraint,
    SugarPriority::Secondary,
    recognize_assert_macro,
);

pub(crate) const ASSERT_MACRO_ASSERTION_SURFACE: ExprSugarClaim = ExprSugarClaim::new(
    "assertion_surface_assert_macro",
    SugarRole::AssertionSurface,
    SugarPriority::Secondary,
    recognize_assert_macro,
);

pub(crate) const BOOL_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_bool_expr",
    SugarRole::Constraint,
    SugarPriority::Tertiary,
    recognize_bool_expr,
);

pub(crate) const IF_PANIC_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_if_panic",
    SugarRole::Constraint,
    SugarPriority::Primary,
    recognize_if_panic,
);

pub(crate) const NO_PANIC_CALL_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_no_panic_call",
    SugarRole::SupportConstraint,
    SugarPriority::Primary,
    recognize_no_panic_call,
);

struct RelationMacroSugar {
    name: String,
    lhs: Box<dyn Sugar>,
    rhs: Box<dyn Sugar>,
    lhs_expr: Expr,
    rhs_expr: Expr,
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
                    return unsupported(format!(
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
                        return unsupported(format!(
                            "unsupported bounded literal macro predicate `{}`",
                            self.predicate
                        ));
                    };
                    atoms.push(if self.negate { not_(atom) } else { atom });
                }
            }
        }
        if atoms.is_empty() {
            return unsupported("bounded literal macro emitted no predicate atoms".to_string());
        }
        Outcome::Dug(Desugared::Constraints {
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
        lhs: build_term(&args.exprs[0], fcx),
        rhs: build_term(&args.exprs[1], fcx),
        lhs_expr: args.exprs[0].clone(),
        rhs_expr: args.exprs[1].clone(),
        op,
        debug_gated,
    }))
}

impl Sugar for RelationMacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Err(reason) = ensure_debug_assertions_active(&self.name, self.debug_gated, ctx) {
            return unsupported(reason);
        }
        if let Some(reason) = constraint_runtime_boundary::relation_runtime_boundary_reason(
            &self.lhs_expr,
            &self.rhs_expr,
            ctx,
        ) {
            return unsupported(format!("{}!: {reason}", self.name));
        }
        relation_constraint(&self.name, &*self.lhs, &*self.rhs, self.op, ctx)
    }
}

struct AssertSugar {
    name: String,
    payload: Box<dyn Sugar>,
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
        payload: build_constraint(&expr, fcx),
        debug_gated,
    }))
}

impl Sugar for AssertSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Err(reason) = ensure_debug_assertions_active(&self.name, self.debug_gated, ctx) {
            return unsupported(reason);
        }
        self.payload.desugar(ctx)
    }
}

enum BoolExprKind {
    Connective {
        left: Box<dyn Sugar>,
        right: Box<dyn Sugar>,
        is_and: bool,
    },
    Relation {
        lhs: Box<dyn Sugar>,
        rhs: Box<dyn Sugar>,
        lhs_expr: Expr,
        rhs_expr: Expr,
        op: RelationOp,
    },
    Not(Box<dyn Sugar>),
    Literal(bool),
    PredicateTerm {
        term: Box<dyn Sugar>,
        asserted: bool,
    },
    Wrapper(Box<dyn Sugar>),
}

struct BoolExprSugar {
    kind: BoolExprKind,
}

fn recognize_bool_expr(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Binary(binary) if matches!(binary.op, BinOp::And(_) | BinOp::Or(_)) => {
            Some(Box::new(BoolExprSugar {
                kind: BoolExprKind::Connective {
                    left: build_constraint(&binary.left, fcx),
                    right: build_constraint(&binary.right, fcx),
                    is_and: matches!(binary.op, BinOp::And(_)),
                },
            }))
        }
        Expr::Binary(binary) => {
            let op = relation_from_binop(&binary.op)?;
            Some(Box::new(BoolExprSugar {
                kind: BoolExprKind::Relation {
                    lhs: build_term(&binary.left, fcx),
                    rhs: build_term(&binary.right, fcx),
                    lhs_expr: (*binary.left).clone(),
                    rhs_expr: (*binary.right).clone(),
                    op,
                },
            }))
        }
        Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Not(build_constraint(&unary.expr, fcx)),
        })),
        Expr::Lit(ExprLit {
            lit: Lit::Bool(value),
            ..
        }) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Literal(value.value),
        })),
        expr if is_predicate_term_expr(expr) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::PredicateTerm {
                term: build_term(expr, fcx),
                asserted: true,
            },
        })),
        Expr::Paren(paren) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Wrapper(build_constraint(&paren.expr, fcx)),
        })),
        Expr::Group(group) => Some(Box::new(BoolExprSugar {
            kind: BoolExprKind::Wrapper(build_constraint(&group.expr, fcx)),
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
                let left = match constraint_payload(&**left, ctx) {
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
                        let right = match constraint_payload(&**right, ctx) {
                            Ok(payload) => payload,
                            Err(outcome) => return outcome,
                        };
                        return constraints_from_payload(right);
                    }
                    _ => {}
                }
                let right = match constraint_payload(&**right, ctx) {
                    Ok(payload) => payload,
                    Err(outcome) => return outcome,
                };
                let atom = if *is_and {
                    and_(vec![left.atom, right.atom])
                } else {
                    sugar_ir_symbolic::or_(vec![left.atom, right.atom])
                };
                Outcome::Dug(Desugared::Constraints {
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
            BoolExprKind::Relation {
                lhs,
                rhs,
                lhs_expr,
                rhs_expr,
                op,
            } => {
                if let Some(reason) = constraint_runtime_boundary::relation_runtime_boundary_reason(
                    lhs_expr, rhs_expr, ctx,
                ) {
                    return unsupported(format!("assert!: {reason}"));
                }
                relation_constraint("assert", &**lhs, &**rhs, *op, ctx)
            }
            BoolExprKind::Not(inner) => {
                let inner = match constraint_payload(&**inner, ctx) {
                    Ok(payload) => payload,
                    Err(outcome) => return outcome,
                };
                if let Some(atom) = bool_true_assertion_as_false(inner.atom.as_ref()) {
                    return Outcome::Dug(Desugared::Constraints {
                        atom,
                        n: 1,
                        kind: inner.kind,
                        warrant: Warrant { name: inner.name },
                    });
                }
                Outcome::Dug(Desugared::Constraints {
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
            BoolExprKind::PredicateTerm { term, asserted } => {
                let term = match term_payload(&**term, ctx) {
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
            BoolExprKind::Wrapper(inner) => inner.desugar(ctx),
        }
    }
}

fn constraints_from_payload(payload: ConstraintPayload) -> Outcome {
    Outcome::Dug(Desugared::Constraints {
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
    cond: Box<dyn Sugar>,
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
            cond: build_constraint(&if_expr.cond, fcx),
            negate: true,
        })),
        (false, true) => Some(Box::new(IfPanicSugar {
            cond: build_constraint(&if_expr.cond, fcx),
            negate: false,
        })),
        _ => None,
    }
}

impl Sugar for IfPanicSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let payload = match constraint_payload(&*self.cond, ctx) {
            Ok(payload) => payload,
            Err(outcome) => return outcome,
        };
        let atom = if self.negate {
            not_(payload.atom)
        } else {
            payload.atom
        };
        Outcome::Dug(Desugared::Constraints {
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
                let Some(subject) = ctx.opaque_callsite_term(expr) else {
                    return Outcome::from_opt(None);
                };
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
        Outcome::Dug(Desugared::Constraints {
            atom,
            n: 0,
            kind,
            warrant: Warrant { name },
        })
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

fn ensure_debug_assertions_active(
    name: &str,
    debug_gated: bool,
    ctx: &SugarCtx,
) -> Result<(), String> {
    if !debug_gated {
        return Ok(());
    }
    match configuration::resolve_predicate(
        &CfgPredicate::Name("debug_assertions".to_string()),
        ctx.options,
    ) {
        CfgDisposition::Present => Ok(()),
        CfgDisposition::Absent(reason) => Err(format!(
            "{name}!: cfg(debug_assertions) not active; skipped: {reason}"
        )),
        CfgDisposition::Ambiguous(reason) => Err(format!(
            "{name}!: cfg(debug_assertions) ambiguous; skipped: {reason}"
        )),
    }
}

fn constraint_from_entry(entry: crate::AssertionEntry) -> Outcome {
    Outcome::Dug(Desugared::Constraints {
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

fn constraint_payload(node: &dyn Sugar, ctx: &SugarCtx) -> Result<ConstraintPayload, Outcome> {
    match node.desugar(ctx) {
        Outcome::Dug(Desugared::Constraints {
            atom,
            kind,
            warrant,
            ..
        }) => Ok(ConstraintPayload {
            atom,
            kind,
            name: warrant.name,
        }),
        Outcome::Dug(_) => Err(Outcome::Hit(Effect::Unsupported {
            reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
        })),
        Outcome::Hit(effect) => Err(Outcome::Hit(effect)),
    }
}

fn relation_constraint(
    name: &str,
    lhs: &dyn Sugar,
    rhs: &dyn Sugar,
    op: RelationOp,
    ctx: &SugarCtx,
) -> Outcome {
    let lhs = match term_payload(lhs, ctx) {
        Ok(term) => term,
        Err(outcome) => return prefixed_backstop(name, outcome),
    };
    let rhs = match term_payload(rhs, ctx) {
        Ok(term) => term,
        Err(outcome) => return prefixed_backstop(name, outcome),
    };
    constraint_from_entry(assertion_entry_from_relation(lhs, rhs, op, ctx.scope))
}

fn term_payload(node: &dyn Sugar, ctx: &SugarCtx) -> Result<Rc<Term>, Outcome> {
    match node.desugar(ctx) {
        Outcome::Dug(desugared) => desugared.into_term().ok_or_else(|| {
            Outcome::Hit(Effect::Unsupported {
                reason: STRUCTURAL_BACKSTOP_REASON.to_string(),
            })
        }),
        Outcome::Hit(effect) => Err(Outcome::Hit(effect)),
    }
}

fn prefixed_backstop(name: &str, outcome: Outcome) -> Outcome {
    match outcome {
        Outcome::Hit(Effect::Unsupported { reason }) if reason != STRUCTURAL_BACKSTOP_REASON => {
            unsupported(format!("{name}!: {reason}"))
        }
        other => other,
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

fn unsupported(reason: String) -> Outcome {
    Outcome::Hit(Effect::Unsupported { reason })
}
