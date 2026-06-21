// SPDX-License-Identifier: Apache-2.0
//
// `tuple_decomp` — the SHARED assertion-surface decomposition for tuple-valued warrants.
//
// `assert_eq!(L, (a, b, c))` / `L == (a, b, c)` where one side is a tuple-valued PRODUCER
// (e.g. `f.integer_decode()`) and the other a literal N-tuple decomposes into per-component
// SCALAR equalities: `(and (= L0 a) (= L1 b) (= L2 c))`. Tuple `PartialEq` IS componentwise,
// so this rewrite is semantically EXACT. Each component is a grounded scalar, which has REAL
// z3 teeth via the integer total order -- a wrong component (`a != a'`) is z3-UNSAT.
//
// WHY: a tuple VALUE otherwise lowers to a single uninterpreted `literal:Tuple(..)` constant
// (a `Term::Ctor`/`Var` with no injectivity axiom), so a whole-tuple comparison is
// CONGRUENCE-ONLY -- a wrong tuple is z3-SAT (two free constants can be equal) = NO TEETH,
// landing UNDECIDED rather than REFUTED. That is a fake light. Decomposing to scalar
// component equalities is the teethed answer.
//
// SHARED MECHANISM: any tuple-valued producer registers its component source-exprs in
// `producer_components`. integer_decode is the first consumer; size_hint, enumerate's
// idx/val split, and partition_point reuse the SAME arm (do NOT each build a local split).
//
// SOUNDNESS / EXACT-OR-NONE: we only fire when one side is a recognized producer (whose
// components we derive by RUNNING the real host op) AND the other is a literal tuple of the
// SAME arity. A plain literal-tuple-vs-literal-tuple is left to its existing `literal:Tuple`
// lowering (unchanged). If a producer cannot derive its components (declined), or the arities
// differ, we decline -> the ordinary equality path applies (no regression, never a false
// discharge).

use std::rc::Rc;

use crate::sugar::claim::{ExprSugarClaim, SugarPriority, SugarRole};
use crate::sugar::factory::{build_term, SugarBuildCtx};
use crate::sugar::integer_decode;
use crate::{
    callsite_assertion_name, parse_macro_args, AssertionFactKind, Desugared, Effect, Outcome,
    Sugar, SugarCtx, Warrant, STRUCTURAL_BACKSTOP_REASON,
};
use sugar_ir_symbolic::{and_, atomic_, Term};
use syn::{BinOp, Expr, ExprBinary, ExprMacro};

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "constraint_tuple_decomp",
    SugarRole::Constraint,
    SugarPriority::Primary,
    recognize,
);

pub(crate) const ASSERTION_SURFACE_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::new(
    "assertion_surface_tuple_decomp",
    SugarRole::AssertionSurface,
    SugarPriority::Primary,
    recognize,
);

fn recognize(expr: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    match expr {
        Expr::Paren(paren) => recognize(&paren.expr, fcx),
        Expr::Group(group) => recognize(&group.expr, fcx),
        Expr::Binary(binary) => recognize_binary(binary, fcx),
        Expr::Macro(expr_macro) => recognize_macro(expr_macro, fcx),
        _ => None,
    }
}

fn recognize_binary(binary: &ExprBinary, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    if !matches!(binary.op, BinOp::Eq(_)) {
        return None;
    }
    build(&binary.left, &binary.right, fcx)
}

fn recognize_macro(expr_macro: &ExprMacro, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let name = expr_macro.mac.path.segments.last()?.ident.to_string();
    if !matches!(name.as_str(), "assert_eq" | "debug_assert_eq") {
        return None;
    }
    let args = parse_macro_args(expr_macro.mac.tokens.clone()).ok()?;
    if args.exprs.len() < 2 {
        return None;
    }
    build(&args.exprs[0], &args.exprs[1], fcx)
}

fn build(lhs: &Expr, rhs: &Expr, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let (producer_comps, literal_comps) = match_producer_and_literal(lhs, rhs)?;
    if producer_comps.is_empty() || producer_comps.len() != literal_comps.len() {
        return None;
    }
    let pairs = producer_comps
        .iter()
        .zip(literal_comps.iter())
        .map(|(p, l)| (build_term(p, fcx), build_term(l, fcx)))
        .collect();
    Some(Box::new(TupleDecompSugar { pairs }))
}

/// Resolve `(producer_component_exprs, literal_tuple_element_exprs)` from the two sides,
/// in either order. A "producer" is a tuple-valued expr whose components we derive by
/// running the real host op; a plain literal tuple is NOT a producer here (it keeps its
/// existing `literal:Tuple` lowering -- we only decompose when a producer is involved).
fn match_producer_and_literal(lhs: &Expr, rhs: &Expr) -> Option<(Vec<Expr>, Vec<Expr>)> {
    if let (Some(p), Some(l)) = (producer_components(lhs), literal_tuple_elements(rhs)) {
        return Some((p, l));
    }
    if let (Some(p), Some(l)) = (producer_components(rhs), literal_tuple_elements(lhs)) {
        return Some((p, l));
    }
    None
}

/// The extensible producer registry: a tuple-valued expr -> its component source exprs.
/// Add new tuple-valued producers (size_hint, enumerate idx/val, partition_point, ...) here.
fn producer_components(expr: &Expr) -> Option<Vec<Expr>> {
    match strip_paren_group(expr) {
        Expr::MethodCall(call) => integer_decode::decomposed_component_exprs(call),
        _ => None,
    }
}

fn literal_tuple_elements(expr: &Expr) -> Option<Vec<Expr>> {
    match strip_paren_group(expr) {
        Expr::Tuple(tuple) if !tuple.elems.is_empty() => {
            Some(tuple.elems.iter().cloned().collect())
        }
        _ => None,
    }
}

fn strip_paren_group(expr: &Expr) -> &Expr {
    match expr {
        Expr::Paren(paren) => strip_paren_group(&paren.expr),
        Expr::Group(group) => strip_paren_group(&group.expr),
        _ => expr,
    }
}

struct TupleDecompSugar {
    pairs: Vec<(Box<dyn Sugar>, Box<dyn Sugar>)>,
}

impl Sugar for TupleDecompSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let mut atoms = Vec::with_capacity(self.pairs.len());
        let mut anchor: Option<Rc<Term>> = None;
        for (lhs, rhs) in &self.pairs {
            let lhs_term = match term_payload(lhs.as_ref(), ctx) {
                Ok(term) => term,
                Err(outcome) => return outcome,
            };
            let rhs_term = match term_payload(rhs.as_ref(), ctx) {
                Ok(term) => term,
                Err(outcome) => return outcome,
            };
            if anchor.is_none() {
                anchor = Some(Rc::clone(&lhs_term));
            }
            atoms.push(atomic_("=".to_string(), vec![lhs_term, rhs_term]));
        }
        let atom = and_(atoms);
        let name =
            anchor.and_then(|term| callsite_assertion_name(term.as_ref(), ctx.scope.local_scope()));
        Outcome::Dug(Desugared::Constraints {
            atom,
            n: 1,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant { name },
        })
    }
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
