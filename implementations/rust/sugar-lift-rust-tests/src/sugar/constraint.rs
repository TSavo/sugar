// SPDX-License-Identifier: Apache-2.0
//
// ConstraintSugar family: source shapes whose semantic output is a ProofIR
// constraint. The collector asks for the `Constraint` role; these claims own
// syntax entry points that expose an assertion-shaped expression. The proof
// meaning is the expression shape underneath (`lhs cmp rhs`, boolean
// connective, panic locus), not a human method name.

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::configuration;
use crate::sugar::factory::{build_constraint, SugarBuildCtx};
use crate::{
    callsite_assertion_name, lower_assert_condition, lower_assert_eq, lower_assert_ne,
    parse_macro_args, token_key, AssertionFactKind, CfgDisposition, CfgPredicate, Desugared,
    Effect, Outcome, RelationOp, Sugar, SugarCtx, Warrant, STRUCTURAL_BACKSTOP_REASON,
};
use sugar_ir_symbolic::{and_, atomic_, not_, str_const};
use syn::{Expr, ExprIf, ExprLit, ExprMacro, Lit, UnOp};

pub(crate) const RELATION_MACRO_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_relation_macro",
    SugarRole::Constraint,
    SugarPriority::Primary,
    recognize_relation_macro,
);

pub(crate) const ASSERT_MACRO_SUGAR: ExprSugarClaim =
    ExprSugarClaim::constraint("constraint_assert_macro", recognize_assert_macro);

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
    SugarRole::Constraint,
    SugarPriority::Primary,
    recognize_no_panic_call,
);

struct RelationMacroSugar {
    name: String,
    lhs: Expr,
    rhs: Expr,
    op: RelationOp,
    debug_gated: bool,
}

fn recognize_relation_macro(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
        lhs: args.exprs[0].clone(),
        rhs: args.exprs[1].clone(),
        op,
        debug_gated,
    }))
}

impl Sugar for RelationMacroSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Err(reason) = ensure_debug_assertions_active(&self.name, self.debug_gated, ctx) {
            return unsupported(reason);
        }
        let result = match self.op {
            RelationOp::Eq => lower_assert_eq(
                &self.lhs,
                &self.rhs,
                ctx.scope,
                &ctx.float_widths.borrow(),
                ctx.factory_audits,
            ),
            RelationOp::Ne => lower_assert_ne(&self.lhs, &self.rhs, ctx.scope, ctx.factory_audits),
            _ => unreachable!("relation macro sugar only owns equality and inequality macros"),
        };
        constraint_from_entry_result(&self.name, result)
    }
}

struct AssertSugar {
    name: String,
    expr: Expr,
    debug_gated: bool,
}

fn recognize_assert_macro(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
        expr,
        debug_gated,
    }))
}

impl Sugar for AssertSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        if let Err(reason) = ensure_debug_assertions_active(&self.name, self.debug_gated, ctx) {
            return unsupported(reason);
        }
        if let Some(outcome) = desugar_assert_payload_constraint(&self.expr, ctx) {
            return outcome;
        }
        constraint_from_entry_result(
            &self.name,
            lower_assert_condition(
                &self.expr,
                ctx.scope,
                &ctx.float_widths.borrow(),
                ctx.factory_audits,
            ),
        )
    }
}

struct BoolExprSugar {
    expr: Expr,
}

fn recognize_bool_expr(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Binary(_) => Some(Box::new(BoolExprSugar { expr: expr.clone() })),
        Expr::Unary(unary) if matches!(unary.op, UnOp::Not(_)) => {
            Some(Box::new(BoolExprSugar { expr: expr.clone() }))
        }
        Expr::Lit(ExprLit {
            lit: Lit::Bool(_), ..
        }) => Some(Box::new(BoolExprSugar { expr: expr.clone() })),
        Expr::Paren(_) | Expr::Group(_) => Some(Box::new(BoolExprSugar { expr: expr.clone() })),
        _ => None,
    }
}

impl Sugar for BoolExprSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        constraint_from_entry_result(
            "assert",
            lower_assert_condition(
                &self.expr,
                ctx.scope,
                &ctx.float_widths.borrow(),
                ctx.factory_audits,
            ),
        )
    }
}

fn desugar_assert_payload_constraint(expr: &Expr, ctx: &SugarCtx) -> Option<Outcome> {
    if assert_payload_should_use_bool_fallback(expr, ctx) {
        return None;
    }
    let empty = std::collections::BTreeMap::new();
    let fcx = SugarBuildCtx::new(ctx.scope, ctx.options, &empty);
    if !crate::sugar::factory::has_constraint(expr, &fcx) {
        return None;
    }
    match build_constraint(expr, &fcx).desugar(ctx) {
        Outcome::Dug(Desugared::Constraints {
            atom,
            kind,
            warrant,
            ..
        }) => Some(Outcome::Dug(Desugared::Constraints {
            atom,
            n: 1,
            kind,
            warrant,
        })),
        Outcome::Hit(Effect::Unsupported { reason }) if reason == STRUCTURAL_BACKSTOP_REASON => {
            None
        }
        Outcome::Hit(effect) => Some(Outcome::Hit(effect)),
        Outcome::Dug(_) => None,
    }
}

fn assert_payload_should_use_bool_fallback(expr: &Expr, ctx: &SugarCtx) -> bool {
    match expr {
        Expr::Call(_) | Expr::MethodCall(_) | Expr::Await(_) | Expr::Field(_) => true,
        Expr::Path(path) => path.path.get_ident().is_some_and(|ident| {
            ctx.scope
                .stable_let_binding_for_term(&ident.to_string())
                .is_some_and(bound_assert_payload_should_use_bool_fallback)
        }),
        Expr::Paren(paren) => assert_payload_should_use_bool_fallback(&paren.expr, ctx),
        Expr::Group(group) => assert_payload_should_use_bool_fallback(&group.expr, ctx),
        _ => false,
    }
}

fn bound_assert_payload_should_use_bool_fallback(expr: &Expr) -> bool {
    match expr {
        Expr::Call(_) | Expr::MethodCall(_) | Expr::Await(_) | Expr::Field(_) => true,
        Expr::Path(_) => true,
        Expr::Paren(paren) => bound_assert_payload_should_use_bool_fallback(&paren.expr),
        Expr::Group(group) => bound_assert_payload_should_use_bool_fallback(&group.expr),
        _ => false,
    }
}

struct IfPanicSugar {
    cond: Expr,
    negate: bool,
}

fn recognize_if_panic(expr: &Expr, _fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
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
            cond: (*if_expr.cond).clone(),
            negate: true,
        })),
        (false, true) => Some(Box::new(IfPanicSugar {
            cond: (*if_expr.cond).clone(),
            negate: false,
        })),
        _ => None,
    }
}

impl Sugar for IfPanicSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let entry = match lower_assert_condition(
            &self.cond,
            ctx.scope,
            &ctx.float_widths.borrow(),
            ctx.factory_audits,
        ) {
            Ok(entry) => entry,
            Err(reason) => return unsupported(format!("if-panic constraint: {reason}")),
        };
        let atom = if self.negate {
            not_(entry.atom)
        } else {
            entry.atom
        };
        Outcome::Dug(Desugared::Constraints {
            atom,
            n: 1,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant { name: entry.name },
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
            NoPanicKind::ReturnsNormally => (normal_universe, AssertionFactKind::Support),
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

fn constraint_from_entry_result(
    name: &str,
    result: Result<crate::AssertionEntry, String>,
) -> Outcome {
    match result {
        Ok(entry) => constraint_from_entry(entry),
        Err(reason) => unsupported(format!("{name}!: {reason}")),
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

fn unsupported(reason: String) -> Outcome {
    Outcome::Hit(Effect::Unsupported { reason })
}
